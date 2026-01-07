# =============================================================================
# Person Extraction Service - Extract Executives and Key People
# =============================================================================
#
# This service extracts Person nodes from multiple sources:
# 1. SEC Filings - Executive officers, board members
# 2. Earnings Transcripts - Speakers and mentioned individuals
# 3. CoreSignal Data - Employee records with titles (if available)
#
# =============================================================================

import os
import re
import logging
from typing import Dict, List, Any, Optional

import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)


class PersonExtractionService:
    """
    Extracts and normalizes person data for knowledge graph.

    Identifies executives, board members, and key individuals from
    company documents and creates Person nodes with relationships.
    """

    # Executive title patterns for role classification
    EXECUTIVE_PATTERNS = {
        'FOUNDER': ['founder', 'co-founder', 'cofounder'],
        'CEO': ['chief executive', 'ceo', 'president and ceo'],
        'CFO': ['chief financial', 'cfo', 'finance officer'],
        'CTO': ['chief technology', 'cto', 'technology officer'],
        'COO': ['chief operating', 'coo', 'operations officer'],
        'CISO': ['chief information security', 'ciso', 'security officer'],
        'CMO': ['chief marketing', 'cmo', 'marketing officer'],
        'CRO': ['chief revenue', 'cro', 'revenue officer'],
        'BOARD': ['director', 'board member', 'chairman', 'board of directors'],
        'VP': ['vice president', 'vp of', 'senior vice president', 'svp'],
        'EVP': ['executive vice president', 'evp']
    }

    # Title patterns for speaker extraction from transcripts
    SPEAKER_TITLES = [
        'CEO', 'CFO', 'CTO', 'COO', 'CISO', 'CMO', 'CRO',
        'President', 'Chairman', 'Director',
        'Vice President', 'VP', 'SVP', 'EVP',
        'Chief', 'Officer', 'Analyst'
    ]

    def __init__(self):
        """Initialize the person extraction service."""
        self.region = os.environ.get('AWS_REGION', 'us-west-2')

        # Initialize AWS Comprehend
        config = Config(
            region_name=self.region,
            retries={'max_attempts': 3, 'mode': 'adaptive'}
        )
        self.comprehend = boto3.client('comprehend', config=config)
        self.s3 = boto3.client('s3', config=config)

        # Service dependencies (lazy loaded)
        self._neo4j_service = None
        self._db_service = None

    @property
    def neo4j(self):
        """Lazy load Neo4j service."""
        if self._neo4j_service is None:
            from services.neo4j_service import get_neo4j_service
            self._neo4j_service = get_neo4j_service()
        return self._neo4j_service

    @property
    def db(self):
        """Lazy load database service."""
        if self._db_service is None:
            from services.database_service import db_service
            self._db_service = db_service
        return self._db_service

    # =========================================================================
    # Main Extraction Pipeline
    # =========================================================================

    def extract_persons_for_ticker(self, ticker: str) -> Dict:
        """
        Extract all persons for a company from documents.

        Args:
            ticker: Company ticker symbol

        Returns:
            Summary of extraction results
        """
        ticker = ticker.upper()
        logger.info(f"Extracting persons for {ticker}")

        results = {
            'ticker': ticker,
            'persons_extracted': 0,
            'executives': 0,
            'from_sec': 0,
            'from_transcripts': 0,
            'errors': []
        }

        try:
            # 1. Ensure company node exists
            self._ensure_company_node(ticker)

            # 2. Get artifacts for this ticker
            artifacts = self.db.get_artifacts_by_ticker(ticker)

            if not artifacts:
                logger.warning(f"No artifacts found for {ticker}")
                results['errors'].append('No documents found')
                return results

            # 3. Process SEC filings
            sec_artifacts = [a for a in artifacts if '10-K' in a.get('artifact_type', '') or '10-Q' in a.get('artifact_type', '')]
            for artifact in sec_artifacts:
                try:
                    persons = self._extract_from_sec_filing(artifact, ticker)
                    results['from_sec'] += len(persons)
                    results['persons_extracted'] += len(persons)
                except Exception as e:
                    logger.error(f"Error extracting from SEC: {e}")
                    results['errors'].append(str(e))

            # 4. Process transcripts
            transcript_artifacts = [a for a in artifacts if 'transcript' in a.get('artifact_type', '').lower()]
            for artifact in transcript_artifacts:
                try:
                    persons = self._extract_from_transcript(artifact, ticker)
                    results['from_transcripts'] += len(persons)
                    results['persons_extracted'] += len(persons)
                except Exception as e:
                    logger.error(f"Error extracting from transcript: {e}")
                    results['errors'].append(str(e))

            # 5. Count executives
            results['executives'] = self._count_executives(ticker)

            logger.info(f"Person extraction complete for {ticker}: {results}")
            return results

        except Exception as e:
            logger.error(f"Error extracting persons for {ticker}: {e}")
            results['errors'].append(str(e))
            return results

    # =========================================================================
    # SEC Filing Extraction
    # =========================================================================

    def _extract_from_sec_filing(self, artifact: Dict, ticker: str) -> List[Dict]:
        """
        Extract executives from SEC 10-K/10-Q filings.

        SEC filings have structured sections:
        - "Executive Officers" section
        - "Directors" section
        - Signature blocks
        """
        s3_key = artifact.get('s3_key')
        doc_id = s3_key.split('/')[-1].replace('.txt', '').replace('.pdf', '') if s3_key else None

        if not s3_key or not doc_id:
            return []

        # Get document text
        text = self._get_document_text(s3_key)
        if not text or len(text) < 100:
            return []

        persons = []

        # Use Comprehend to detect PERSON entities
        comprehend_persons = self._detect_persons(text[:10000])

        for person_data in comprehend_persons:
            name = person_data.get('Text', '').strip()
            score = person_data.get('Score', 0)

            if score < 0.8 or len(name) < 3:
                continue

            # Get surrounding context for role detection
            context = self._get_surrounding_context(text, name, window=150)
            role = self._detect_role(context)
            title = self._extract_title(context)
            is_executive = role in ['CEO', 'CFO', 'CTO', 'COO', 'CISO', 'CMO', 'CRO', 'BOARD', 'FOUNDER', 'VP', 'EVP']

            person = {
                'name': name,
                'normalized_name': self._normalize_name(name),
                'title': title,
                'role_type': role,
                'is_executive': is_executive,
                'source': 'sec_filing',
                'source_doc': doc_id
            }

            persons.append(person)

            # Add to Neo4j
            self._add_person_to_graph(person, ticker, doc_id)

        return self._deduplicate(persons)

    # =========================================================================
    # Transcript Extraction
    # =========================================================================

    def _extract_from_transcript(self, artifact: Dict, ticker: str) -> List[Dict]:
        """
        Extract speakers from earnings call transcripts.

        Transcripts have patterns like:
        - "George Kurtz - CEO"
        - "Operator: Our next question comes from..."
        """
        s3_key = artifact.get('s3_key')
        doc_id = s3_key.split('/')[-1].replace('.txt', '') if s3_key else None

        if not s3_key or not doc_id:
            return []

        text = self._get_document_text(s3_key)
        if not text or len(text) < 100:
            return []

        persons = []

        # Pattern: "Name - Title" or "Name, Title"
        title_pattern = '|'.join(self.SPEAKER_TITLES)
        speaker_pattern = rf'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s*[-,]\s*([A-Za-z\s]*(?:{title_pattern})[A-Za-z\s]*)'

        for match in re.finditer(speaker_pattern, text, re.IGNORECASE):
            name = match.group(1).strip()
            title = match.group(2).strip()

            # Skip common false positives
            if name.lower() in ['the company', 'our company', 'the board']:
                continue

            role = self._detect_role(title)
            is_executive = role in ['CEO', 'CFO', 'CTO', 'COO', 'CISO', 'CMO', 'CRO', 'BOARD', 'FOUNDER', 'VP', 'EVP']

            person = {
                'name': name,
                'normalized_name': self._normalize_name(name),
                'title': title,
                'role_type': role,
                'is_executive': is_executive,
                'source': 'transcript',
                'source_doc': doc_id
            }

            persons.append(person)

            # Add to Neo4j
            self._add_person_to_graph(person, ticker, doc_id)

        return self._deduplicate(persons)

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _ensure_company_node(self, ticker: str):
        """Ensure company node exists in Neo4j."""
        company = self.db.get_company(ticker)
        if company:
            self.neo4j.create_company(
                ticker=ticker,
                name=company.get('company_name', ticker),
                sector=company.get('sector', 'Cybersecurity')
            )

    def _get_document_text(self, s3_key: str) -> Optional[str]:
        """Get document text from S3."""
        try:
            bucket = os.environ.get('ARTIFACTS_BUCKET', 'cyber-risk-artifacts')
            response = self.s3.get_object(Bucket=bucket, Key=s3_key)
            content = response['Body'].read()

            try:
                return content.decode('utf-8')
            except UnicodeDecodeError:
                return None

        except Exception as e:
            logger.error(f"Error reading document {s3_key}: {e}")
            return None

    def _detect_persons(self, text: str) -> List[Dict]:
        """Use Comprehend to detect PERSON entities."""
        try:
            response = self.comprehend.detect_entities(
                Text=text,
                LanguageCode='en'
            )

            return [e for e in response.get('Entities', []) if e.get('Type') == 'PERSON']

        except Exception as e:
            logger.error(f"Comprehend error: {e}")
            return []

    def _get_surrounding_context(self, text: str, name: str, window: int = 100) -> str:
        """Get text surrounding a name mention."""
        try:
            idx = text.lower().find(name.lower())
            if idx == -1:
                return ""

            start = max(0, idx - window)
            end = min(len(text), idx + len(name) + window)

            return text[start:end]

        except Exception:
            return ""

    def _detect_role(self, context: str) -> str:
        """Detect executive role from context."""
        context_lower = context.lower()

        for role, patterns in self.EXECUTIVE_PATTERNS.items():
            if any(p in context_lower for p in patterns):
                return role

        return 'OTHER'

    def _extract_title(self, context: str) -> Optional[str]:
        """Extract job title from context."""
        # Common title patterns
        title_patterns = [
            r'(?:as|is|,)\s+(?:the\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:Officer|Director|President|VP|CEO|CFO|CTO|COO))',
            r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:of|for)\s+[A-Z][a-z]+)',
        ]

        for pattern in title_patterns:
            match = re.search(pattern, context)
            if match:
                return match.group(1).strip()

        return None

    def _normalize_name(self, name: str) -> str:
        """Normalize name for deduplication."""
        # Remove titles and suffixes
        name = re.sub(r'\b(Mr|Ms|Mrs|Dr|Jr|Sr|III|II|IV)\.?\b', '', name, flags=re.IGNORECASE)
        return name.lower().strip().replace(' ', '_').replace('.', '')

    def _deduplicate(self, persons: List[Dict]) -> List[Dict]:
        """Remove duplicate persons based on normalized name."""
        seen = set()
        unique = []

        for person in persons:
            norm = person.get('normalized_name', '')
            if norm and norm not in seen:
                seen.add(norm)
                unique.append(person)

        return unique

    def _add_person_to_graph(self, person: Dict, ticker: str, doc_id: str):
        """Add person to Neo4j graph."""
        # Create person node
        self.neo4j.create_person(
            name=person['name'],
            title=person.get('title'),
            normalized_name=person['normalized_name'],
            role_type=person.get('role_type'),
            is_executive=person.get('is_executive', False)
        )

        # Create relationship based on role
        if person.get('is_executive'):
            query = """
                MATCH (c:Company {ticker: $ticker})
                MATCH (p:Person {normalized_name: $person})
                MERGE (p)-[r:EXECUTIVE_OF]->(c)
                SET r.title = $title,
                    r.role_type = $role_type
            """
            self.neo4j.execute_write(query, {
                'ticker': ticker,
                'person': person['normalized_name'],
                'title': person.get('title'),
                'role_type': person.get('role_type')
            })

        # Link to document
        if doc_id:
            query = """
                MATCH (p:Person {normalized_name: $person})
                MATCH (d:Document {id: $doc_id})
                MERGE (p)-[r:MENTIONED_IN]->(d)
                SET r.context = $source
            """
            self.neo4j.execute_write(query, {
                'person': person['normalized_name'],
                'doc_id': doc_id,
                'source': person.get('source', 'document')
            })

    def _count_executives(self, ticker: str) -> int:
        """Count executives for a ticker."""
        query = """
            MATCH (p:Person)-[:EXECUTIVE_OF]->(c:Company {ticker: $ticker})
            RETURN count(DISTINCT p) as count
        """
        result = self.neo4j.execute_read(query, {'ticker': ticker})
        return result[0]['count'] if result else 0


# =============================================================================
# Singleton Instance
# =============================================================================

_person_extraction_service = None


def get_person_extraction_service() -> PersonExtractionService:
    """Get or create person extraction service singleton."""
    global _person_extraction_service
    if _person_extraction_service is None:
        _person_extraction_service = PersonExtractionService()
    return _person_extraction_service
