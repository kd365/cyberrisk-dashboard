import boto3
import pandas as pd
import io
import os
from botocore.exceptions import ClientError, ProfileNotFound
try:
    from PyPDF2 import PdfReader
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
    print("Warning: PyPDF2 not installed. PDF text extraction will be limited.")

class S3ArtifactService:
    def __init__(self):
        # Use profile locally, instance role on EC2
        profile = os.environ.get('AWS_PROFILE', 'cyber-risk')
        try:
            session = boto3.Session(profile_name=profile)
            # Test if profile exists
            session.get_credentials()
            self.s3 = session.client('s3')
        except (ProfileNotFound, Exception):
            # On EC2, use instance role (no profile)
            self.s3 = boto3.client('s3')
        # Use ARTIFACTS_BUCKET env var, fallback to old bucket for local dev
        self.bucket = os.environ.get('ARTIFACTS_BUCKET', 'cyber-risk-artifacts')
    
    def get_artifacts_table(self):
        """Read artifacts.csv from S3"""
        try:
            response = self.s3.get_object(
                Bucket=self.bucket,
                Key='data/processed/artifacts.csv'
            )
            df = pd.read_csv(io.BytesIO(response['Body'].read()))

            # The CSV already has s3_key and document_link columns from the scraper
            # Just ensure document_link exists for backwards compatibility
            if 's3_key' in df.columns and 'document_link' not in df.columns:
                df['document_link'] = df['s3_key']

            # Convert to list of dicts
            artifacts = df.to_dict('records')

            print(f"✅ Loaded {len(artifacts)} artifacts from S3")
            return artifacts

        except ClientError as e:
            print(f"❌ Error reading artifacts: {e}")
            return []
    
    def get_companies(self):
        """Read cybersecurity_tickers.csv"""
        try:
            response = self.s3.get_object(
                Bucket=self.bucket,
                Key='data/reference/cybersecurity_tickers.csv'
            )
            df = pd.read_csv(io.BytesIO(response['Body'].read()))
            
            # Convert to list of dicts
            companies = df.to_dict('records')
            
            print(f"✅ Loaded {len(companies)} companies from S3")
            return companies
        
        except ClientError as e:
            print(f"❌ Error reading companies: {e}")
            return []
    
    def get_document_text(self, s3_key):
        """Get text from PDF in S3"""
        try:
            response = self.s3.get_object(
                Bucket=self.bucket,
                Key=s3_key
            )

            # Extract text from PDF
            if PDF_AVAILABLE and s3_key.endswith('.pdf'):
                pdf_content = response['Body'].read()
                pdf_file = io.BytesIO(pdf_content)

                try:
                    reader = PdfReader(pdf_file)
                    text = ""
                    for page in reader.pages:
                        text += page.extract_text() + "\n"

                    return text.strip()
                except Exception as pdf_error:
                    print(f"Error extracting text from PDF {s3_key}: {pdf_error}")
                    return f"[PDF extraction failed for {s3_key}]"
            else:
                # For non-PDF files, try reading as text
                content = response['Body'].read()
                try:
                    return content.decode('utf-8')
                except:
                    return content.decode('latin-1', errors='ignore')

        except ClientError as e:
            print(f"❌ Error reading document from S3: {e}")
            return None
        except Exception as e:
            print(f"❌ Unexpected error reading {s3_key}: {e}")
            return None
    
    def get_presigned_url(self, s3_key, expiration=3600):
        """Generate presigned URL for document"""
        try:
            url = self.s3.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.bucket,
                    'Key': s3_key
                },
                ExpiresIn=expiration
            )
            return url
        
        except ClientError as e:
            print(f"❌ Error generating presigned URL: {e}")
            return None
    
    def get_artifacts_by_ticker(self, ticker):
        """Get all artifacts for a specific ticker"""
        all_artifacts = self.get_artifacts_table()
        return [a for a in all_artifacts if a['ticker'] == ticker]
    
    def get_artifacts_by_type(self, artifact_type):
        """Get all artifacts of a specific type (SEC or transcript)"""
        all_artifacts = self.get_artifacts_table()
        return [a for a in all_artifacts if a['type'] == artifact_type]
    
    def check_existing_documents(self, ticker, doc_types=None):
        """
        Check what documents already exist for a ticker
        
        Args:
            ticker: Stock ticker symbol
            doc_types: List of types to check ('10-K', '10-Q', 'transcript')
                      If None, checks all types
        
        Returns:
            Dict with count of existing documents by type
        """
        artifacts = self.get_artifacts_by_ticker(ticker.upper())
        
        if doc_types is None:
            doc_types = ['10-K', '10-Q', 'transcript']
        
        existing = {}
        for doc_type in doc_types:
            count = sum(1 for a in artifacts if a.get('type') == doc_type)
            existing[doc_type] = count
        
        return {
            'ticker': ticker.upper(),
            'total': len(artifacts),
            'by_type': existing,
            'artifacts': artifacts
        }
    
    def check_if_document_exists(self, ticker, doc_type, date=None):
        """
        Check if a specific document already exists
        
        Args:
            ticker: Stock ticker
            doc_type: Document type ('10-K', '10-Q', 'transcript')
            date: Specific date to check for (optional)
        
        Returns:
            True if exists, False otherwise
        """
        artifacts = self.get_artifacts_by_ticker(ticker.upper())
        
        for artifact in artifacts:
            if artifact.get('type') != doc_type:
                continue
            
            if date and artifact.get('date') != date:
                continue
            
            # If we get here, the document exists
            return True
        
        return False
    
    def get_documents_to_fetch(self, ticker, doc_types=None):
        """
        Get list of documents that need to be fetched for a ticker
        (essentially the inverse of what exists)
        
        Returns:
            Dict with what should be fetched
        """
        existing = self.check_existing_documents(ticker, doc_types)
        
        # All possible document types
        all_types = {
            '10-K': 'Annual Report',
            '10-Q': 'Quarterly Report',
            'transcript': 'Earnings Transcript'
        }
        
        needed = {}
        for doc_type, description in all_types.items():
            count = existing['by_type'].get(doc_type, 0)
            needed[doc_type] = {
                'description': description,
                'existing': count,
                'needed': max(0, 5 - count)  # Target 5 per type
            }
        
        return {
            'ticker': ticker.upper(),
            'existing': existing['total'],
            'to_fetch': sum(v['needed'] for v in needed.values()),
            'breakdown': needed
        }