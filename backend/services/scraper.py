"""
SEC Filings and Transcript Scraper

Fetches SEC 10-K and 10-Q filings, plus Motley Fool earnings transcripts
Saves raw files to S3 and processes them for artifact table
"""

import boto3
import os
import requests
import pandas as pd
import io
from datetime import datetime, timedelta
from botocore.exceptions import ClientError, ProfileNotFound
import re
import json


class SecTranscriptScraper:
    def __init__(self):
        # Use profile locally, instance role on EC2
        profile = os.environ.get("AWS_PROFILE", "cyber-risk")
        try:
            session = boto3.Session(profile_name=profile)
            session.get_credentials()
            self.s3 = session.client("s3")
        except (ProfileNotFound, Exception):
            self.s3 = boto3.client("s3")
        # Use ARTIFACTS_BUCKET env var, fallback to old bucket for local dev
        self.bucket = os.environ.get("ARTIFACTS_BUCKET", "cyber-risk-artifacts")
        self.artifacts = []

    def scrape_sec_filings(self, ticker, num_filings=20, include_8k=False, num_8k=10):
        """
        Fetch SEC 10-K, 10-Q, and optionally 8-K filings for a ticker

        Uses SEC EDGAR API - fetches up to num_filings of each type (10-K and 10-Q)

        Args:
            ticker: Stock ticker symbol
            num_filings: Number of 10-K and 10-Q filings to fetch (default: 20 each)
            include_8k: Whether to include 8-K current reports (default: False)
            num_8k: Number of 8-K filings to fetch if include_8k is True (default: 10)

        8-K filings are "Current Reports" filed for material events like:
        - Cybersecurity incidents (Item 1.05 - required since Dec 2023)
        - Leadership changes (Item 5.02)
        - Material agreements (Item 1.01)
        - Financial results (Item 2.02)
        """
        print(f"🔍 Fetching SEC filings for {ticker}...")

        try:
            # SEC EDGAR API endpoint
            cik = self._get_cik_from_ticker(ticker)
            if not cik:
                print(f"  ❌ Could not find CIK for {ticker}")
                return []

            url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
            headers = {"User-Agent": "Kathleen Hill krande322@gmail.com"}

            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            data = response.json()
            filings = []

            # Extract filings separately to ensure we get enough of each type
            recent = data.get("filings", {}).get("recent", {})
            forms = recent.get("form", [])
            dates = recent.get("filingDate", [])
            accessions = recent.get("accessionNumber", [])

            tenk_count = 0
            tenq_count = 0
            eightk_count = 0

            for form, date, accession in zip(forms, dates, accessions):
                if form == "10-K" and tenk_count < num_filings:
                    filings.append(
                        {
                            "ticker": ticker,
                            "form": form,
                            "date": date,
                            "accession": accession,
                        }
                    )
                    tenk_count += 1
                elif form == "10-Q" and tenq_count < num_filings:
                    filings.append(
                        {
                            "ticker": ticker,
                            "form": form,
                            "date": date,
                            "accession": accession,
                        }
                    )
                    tenq_count += 1
                elif include_8k and form == "8-K" and eightk_count < num_8k:
                    filings.append(
                        {
                            "ticker": ticker,
                            "form": form,
                            "date": date,
                            "accession": accession,
                        }
                    )
                    eightk_count += 1

                # Stop if we have enough of all types
                max_8k = num_8k if include_8k else 0
                if (
                    tenk_count >= num_filings
                    and tenq_count >= num_filings
                    and eightk_count >= max_8k
                ):
                    break

            filing_summary = f"{tenk_count} 10-K, {tenq_count} 10-Q"
            if include_8k:
                filing_summary += f", {eightk_count} 8-K"
            print(f"  ✅ Found {len(filings)} SEC filings ({filing_summary})")
            return filings

        except Exception as e:
            print(f"  ❌ Error fetching SEC filings: {e}")
            return []

    def scrape_earnings_transcripts(self, ticker, num_quarters=8):
        """
        Fetch earnings call transcripts using Alpha Vantage API

        Alpha Vantage requires a specific quarter parameter (e.g., 2024Q1)
        This method fetches the most recent quarters

        Args:
            ticker: Stock ticker symbol
            num_quarters: Number of recent quarters to fetch (default: 8 = 2 years)
        """
        print(f"📞 Fetching earnings call transcripts for {ticker}...")

        try:
            import os
            import time
            from datetime import datetime

            # Get Alpha Vantage API key from environment
            api_key = os.environ.get("ALPHAVANTAGE_API_KEY")

            if not api_key:
                print(f"  ⚠️  ALPHAVANTAGE_API_KEY not set in environment")
                print(f"  💡 Set it with: export ALPHAVANTAGE_API_KEY='your-key-here'")
                print(
                    f"  📝 Get a free key at: https://www.alphavantage.co/support/#api-key"
                )
                return []

            transcripts = []

            # Generate list of recent quarters to fetch
            # Format: YYYYQM (e.g., 2024Q1, 2024Q2, etc.)
            current_year = datetime.now().year
            current_month = datetime.now().month
            current_quarter = (current_month - 1) // 3 + 1  # 1-4

            quarters_to_fetch = []
            year = current_year
            quarter = current_quarter

            for _ in range(num_quarters):
                quarters_to_fetch.append(f"{year}Q{quarter}")

                # Move to previous quarter
                quarter -= 1
                if quarter < 1:
                    quarter = 4
                    year -= 1

            print(f"  🔍 Fetching {len(quarters_to_fetch)} recent quarters...")

            # Alpha Vantage endpoint
            base_url = "https://www.alphavantage.co/query"

            for quarter_str in quarters_to_fetch:
                try:
                    # Fetch transcript for specific quarter
                    params = {
                        "function": "EARNINGS_CALL_TRANSCRIPT",
                        "symbol": ticker,
                        "quarter": quarter_str,
                        "apikey": api_key,
                    }

                    response = requests.get(base_url, params=params, timeout=15)
                    response.raise_for_status()

                    data = response.json()

                    # Check for API errors
                    if "Error Message" in data:
                        print(f"    ⚠️  {quarter_str}: {data['Error Message']}")
                        continue

                    if "Note" in data:
                        print(f"  ⚠️  API Rate Limit: {data['Note']}")
                        print(f"  💡 Free tier: 25 requests/day")
                        break  # Stop if rate limited

                    if "Information" in data:
                        print(f"    ⚠️  {quarter_str}: {data['Information']}")
                        continue

                    # Extract transcript (it's an array of speaker objects)
                    transcript_array = data.get("transcript", [])

                    if not transcript_array or len(transcript_array) == 0:
                        print(f"    ⏭️  {quarter_str}: No transcript")
                        continue

                    # Convert transcript array to formatted text
                    # Each item has: speaker, title, content, sentiment
                    transcript_lines = []
                    for item in transcript_array:
                        speaker = item.get("speaker", "Unknown")
                        title = item.get("title", "")
                        content = item.get("content", "")
                        sentiment = item.get("sentiment", "")

                        transcript_lines.append(f"Speaker: {speaker}")
                        if title:
                            transcript_lines.append(f"Title: {title}")
                        if sentiment:
                            transcript_lines.append(f"Sentiment: {sentiment}")
                        transcript_lines.append(f"\n{content}\n")
                        transcript_lines.append("-" * 80)

                    transcript_text = "\n".join(transcript_lines)

                    # Generate filename
                    filename = f"{ticker}_{quarter_str}_transcript.txt"
                    s3_key = f"raw/transcripts/{filename}"

                    # Check if already exists
                    try:
                        self.s3.head_object(Bucket=self.bucket, Key=s3_key)
                        print(f"    ⏭️  {quarter_str}: Already exists")
                        continue
                    except:
                        pass

                    # Save to S3
                    self.s3.put_object(
                        Bucket=self.bucket,
                        Key=s3_key,
                        Body=transcript_text.encode("utf-8"),
                    )

                    # Parse quarter for date metadata
                    year = quarter_str[:4]
                    q = quarter_str[-1]
                    # Approximate date: Q1=03-31, Q2=06-30, Q3=09-30, Q4=12-31
                    month_map = {"1": "03", "2": "06", "3": "09", "4": "12"}
                    day_map = {"1": "31", "2": "30", "3": "30", "4": "31"}
                    metadata_date = f"{year}-{month_map[q]}-{day_map[q]}"

                    transcripts.append(
                        {
                            "ticker": ticker,
                            "type": "transcript",
                            "date": metadata_date,
                            "source": "Alpha Vantage",
                            "s3_key": s3_key,
                            "filename": filename,
                        }
                    )

                    print(
                        f"    ✅ {quarter_str}: Downloaded ({len(transcript_text)} chars)"
                    )

                except Exception as e:
                    print(f"    ❌ {quarter_str}: {e}")

                finally:
                    # Rate limiting - free tier: 1 request per second
                    time.sleep(1.5)

            if transcripts:
                print(
                    f"  ✅ Successfully fetched {len(transcripts)} transcripts for {ticker}"
                )
            else:
                print(f"  ⚠️  No new transcripts downloaded for {ticker}")

            return transcripts

        except Exception as e:
            print(f"  ❌ Error fetching transcripts: {e}")
            return []

    def _get_cik_from_ticker(self, ticker):
        """
        Get CIK number from ticker symbol using SEC EDGAR company tickers JSON
        """
        try:
            # Use SEC's official company tickers mapping
            url = "https://www.sec.gov/files/company_tickers.json"
            headers = {"User-Agent": "Kathleen Hill krande322@gmail.com"}
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            data = response.json()

            # Search for ticker in the mapping
            ticker_upper = ticker.upper()
            for entry in data.values():
                if entry.get("ticker", "").upper() == ticker_upper:
                    return entry.get("cik_str")

        except Exception as e:
            print(f"  ⚠️  Error looking up CIK: {e}")

        return None

    def save_raw_files(self, artifacts_list):
        """
        Save raw documents to S3

        Structure: raw/{type}/{ticker}_{date}_{type}.txt
        """
        saved = []

        for artifact in artifacts_list:
            try:
                ticker = artifact["ticker"]
                date = artifact["date"].replace("-", "")
                artifact_type = artifact.get("type", "sec")
                form = artifact.get("form", "").replace("-", "")

                if artifact_type == "sec":
                    key = f"raw/sec/{ticker}_{date}_{form}.txt"
                else:
                    key = f"raw/transcripts/{ticker}_{date}_transcript.txt"

                # Check if already exists
                try:
                    self.s3.head_object(Bucket=self.bucket, Key=key)
                    print(f"  ⏭️  Skip (already exists): {key}")
                    saved.append(key)
                    continue
                except:
                    pass

                # Fetch actual SEC filing content
                if artifact_type == "sec":
                    content = self._fetch_sec_filing_text(artifact)
                    if not content:
                        print(f"  ⚠️  Could not fetch content for {key}, skipping")
                        continue
                else:
                    # Mock content for transcripts (handled separately in scrape_earnings_transcripts)
                    content = f"DOCUMENT: Earnings Transcript\n"
                    content += f"Ticker: {ticker}\n"
                    content += f"Date: {artifact['date']}\n"
                    content += "Mock content - replace with actual document text\n"

                self.s3.put_object(
                    Bucket=self.bucket, Key=key, Body=content.encode("utf-8")
                )

                print(f"  ✅ Saved: {key}")
                saved.append(key)

            except Exception as e:
                print(f"  ❌ Error saving {key}: {e}")

        return saved

    def _fetch_sec_filing_pdf(self, artifact):
        """
        Download SEC filing as PDF

        SEC provides PDFs in: https://www.sec.gov/cgi-bin/viewer?action=view&cik=CIK&accession_number=ACCESSION&xbrl_type=v
        """
        import time

        try:
            ticker = artifact.get("ticker")
            accession = artifact.get("accession")

            # Get CIK
            cik = self._get_cik_from_ticker(ticker)
            if not cik:
                return None

            # Remove dashes from accession
            accession_no_dash = accession.replace("-", "")

            # SEC PDF URL pattern
            url = f"https://www.sec.gov/cgi-bin/viewer?action=view&cik={cik}&accession_number={accession_no_dash}&xbrl_type=v"

            headers = {"User-Agent": "Kathleen Hill krande322@gmail.com"}
            response = requests.get(url, headers=headers, timeout=30, stream=True)
            response.raise_for_status()

            # Rate limiting - SEC allows 10 requests per second
            time.sleep(0.15)

            # Return PDF bytes
            return response.content

        except Exception as e:
            print(f"  ❌ Error fetching PDF: {e}")

            # Fallback: Try alternative PDF URL
            try:
                # Alternative: Direct document URL
                accession_dash = artifact.get("accession")
                accession_no_dash = accession_dash.replace("-", "")
                url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dash}/{accession_dash}.pdf"

                response = requests.get(url, headers=headers, timeout=30, stream=True)
                response.raise_for_status()

                time.sleep(0.15)
                return response.content
            except Exception as e2:
                print(f"  ❌ PDF fallback also failed: {e2}")
                return None

    def save_raw_pdf_files(self, artifacts):
        """
        Save SEC filings as PDFs to S3

        Args:
            artifacts: List of SEC filing metadata dicts

        Returns:
            List of S3 keys for saved files
        """
        saved = []

        for artifact in artifacts:
            ticker = artifact.get("ticker")
            date = artifact.get("date")
            form = artifact.get("form")

            # Generate S3 key: raw/sec/TICKER_10-K_YYYY-MM-DD.pdf
            filename = f"{ticker}_{form}_{date}.pdf"
            key = f"raw/sec/{filename}"

            try:
                # Check if already exists
                try:
                    self.s3.head_object(Bucket=self.bucket, Key=key)
                    print(f"  ⏭️  Skipping {filename} (already exists)")
                    saved.append(key)
                    continue
                except ClientError:
                    pass

                # Fetch PDF content
                print(f"  📥 Downloading PDF for {ticker} {form} {date}...")
                content = self._fetch_sec_filing_pdf(artifact)

                if content:
                    # Save to S3
                    self.s3.put_object(
                        Bucket=self.bucket,
                        Key=key,
                        Body=content,
                        ContentType="application/pdf",
                    )
                    print(f"  ✅ Saved {key}")
                    saved.append(key)
                else:
                    print(f"  ⚠️  Could not fetch PDF for {key}, skipping")

            except Exception as e:
                print(f"  ❌ Error saving {key}: {e}")

        return saved

    def _fetch_sec_filing_text(self, artifact):
        """
        Fetch actual SEC filing content from EDGAR

        Returns plain text extracted from the filing
        """
        try:
            import time
            from bs4 import BeautifulSoup
            import re

            accession = artifact.get("accession", "").replace("-", "")
            form = artifact.get("form", "")
            ticker = artifact.get("ticker", "")

            if not accession:
                return None

            # Get CIK
            cik = self._get_cik_from_ticker(ticker)
            if not cik:
                return None

            # Format: https://www.sec.gov/Archives/edgar/data/CIK/ACCESSIONNODASHES/ACCESSIONWITHDASHES.txt
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{artifact.get('accession')}.txt"

            headers = {"User-Agent": "Kathleen Hill krande322@gmail.com"}
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            # Rate limiting - SEC allows 10 requests per second
            time.sleep(0.15)

            # Extract text from the filing using BeautifulSoup
            full_text = response.text

            # SEC filings have SGML headers followed by HTML documents
            # Extract just the HTML portion(s)
            # Pattern: <DOCUMENT> ... </DOCUMENT> contains the actual filing
            documents = re.findall(r"<DOCUMENT>(.*?)</DOCUMENT>", full_text, re.DOTALL)

            if not documents:
                # Fallback: treat entire response as HTML
                documents = [full_text]

            # Extract text from all documents
            all_text = []
            for doc in documents:
                # Use BeautifulSoup to extract text from HTML
                soup = BeautifulSoup(doc, "lxml")

                # Remove script and style tags
                for script in soup(["script", "style", "noscript"]):
                    script.decompose()

                # Get text
                text = soup.get_text(separator=" ", strip=True)

                # Clean up whitespace
                text = re.sub(r"\s+", " ", text)
                text = text.strip()

                if len(text) > 100:  # Only include substantial text blocks
                    all_text.append(text)

            combined_text = " ".join(all_text)

            # Add header
            header = f"SEC FILING: {form}\n"
            header += f"Ticker: {ticker}\n"
            header += f"Date: {artifact.get('date')}\n"
            header += f"Accession: {artifact.get('accession')}\n"
            header += f"Source: SEC EDGAR\n"
            header += "-" * 80 + "\n\n"

            return header + combined_text

        except Exception as e:
            print(f"  ❌ Error fetching SEC filing: {e}")
            import traceback

            traceback.print_exc()
            return None

    def generate_artifacts_csv(self, companies_df):
        """
        Generate processed artifacts CSV by scanning S3 raw folder
        and organizing artifacts
        """
        print("📊 Generating artifacts CSV...")

        artifacts = []

        try:
            # List all raw files
            paginator = self.s3.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=self.bucket, Prefix="raw/")

            for page in pages:
                if "Contents" not in page:
                    continue

                for obj in page["Contents"]:
                    key = obj["Key"]
                    filename = key.split("/")[-1]

                    # Parse filename: TICKER_DATE_TYPE.txt or TICKER_TYPE_DATE.pdf
                    # Remove extension
                    name_without_ext = filename.replace(".txt", "").replace(".pdf", "")
                    parts = name_without_ext.split("_")

                    if len(parts) < 3:
                        continue

                    ticker = parts[0].upper()

                    # Handle different filename patterns
                    if parts[1] in ["10-K", "10-Q", "10K", "10Q", "8-K", "8K"]:
                        # Pattern: TICKER_10-K_DATE.pdf or TICKER_8-K_DATE.pdf
                        doc_type = parts[1]
                        date = parts[2] if len(parts) > 2 else ""
                    else:
                        # Pattern: TICKER_DATE_TYPE.txt
                        date = parts[1]
                        doc_type = "_".join(parts[2:])

                    # Determine artifact type
                    if "10K" in doc_type or "10-K" in doc_type:
                        artifact_type = "10-K"
                    elif "10Q" in doc_type or "10-Q" in doc_type:
                        artifact_type = "10-Q"
                    elif "8K" in doc_type or "8-K" in doc_type:
                        artifact_type = "8-K"
                    elif "transcript" in doc_type.lower():
                        artifact_type = "Earnings Transcript"
                    else:
                        artifact_type = "Other"

                    # Get company name
                    company = companies_df[companies_df["ticker"] == ticker]
                    company_name = (
                        company["name"].values[0] if len(company) > 0 else ticker
                    )

                    artifacts.append(
                        {
                            "ticker": ticker,
                            "company_name": company_name,
                            "type": artifact_type,
                            "date": self._format_date(date),
                            "s3_key": key,
                            "document_link": key,
                        }
                    )

            print(f"✅ Found {len(artifacts)} artifacts in S3")

            # Save to CSV
            if artifacts:
                df = pd.DataFrame(artifacts)
                csv_buffer = io.StringIO()
                df.to_csv(csv_buffer, index=False)

                self.s3.put_object(
                    Bucket=self.bucket,
                    Key="data/processed/artifacts.csv",
                    Body=csv_buffer.getvalue().encode("utf-8"),
                )
                print(f"✅ Saved artifacts.csv to S3")

            return artifacts

        except Exception as e:
            print(f"❌ Error generating artifacts CSV: {e}")
            return []

    def _format_date(self, date_str):
        """
        Convert date strings to YYYY-MM-DD format

        Handles:
        - YYYYMMDD (e.g., 20240315) -> 2024-03-15
        - YYYYQX (e.g., 2024Q1) -> 2024-03-31 (quarter end date)
        """
        try:
            # Handle quarter format (e.g., 2024Q1)
            if "Q" in date_str and len(date_str) == 6:
                year = date_str[:4]
                quarter = date_str[-1]
                # Quarter end dates: Q1=03-31, Q2=06-30, Q3=09-30, Q4=12-31
                quarter_map = {"1": "03-31", "2": "06-30", "3": "09-30", "4": "12-31"}
                return f"{year}-{quarter_map.get(quarter, '12-31')}"

            # Handle YYYYMMDD format
            if len(date_str) == 8 and date_str.isdigit():
                return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        except:
            pass
        return date_str


def main():
    """
    Main scraping workflow - processes ALL companies
    """
    print("=" * 70)
    print("🔄 SEC FILINGS & TRANSCRIPT SCRAPER")
    print("=" * 70)

    scraper = SecTranscriptScraper()

    # Load companies list
    from s3_service import S3ArtifactService

    s3_service = S3ArtifactService()
    companies = s3_service.get_companies()
    companies_df = pd.DataFrame(companies)

    print(f"\n📋 Loaded {len(companies)} companies")
    print(f"📊 Fetching up to 20 historical SEC filings per company (10-K and 10-Q)")
    print(f"📞 Checking for existing transcripts in S3")

    all_artifacts = []

    for idx, ticker in enumerate(companies_df["ticker"].tolist(), 1):
        print(f"\n{'='*70}")
        print(f"[{idx}/{len(companies_df)}] Processing {ticker}")
        print(f"{'='*70}")

        # Scrape SEC filings (up to 20 of each type)
        sec_filings = scraper.scrape_sec_filings(ticker, num_filings=20)

        # Fetch earnings call transcripts from Alpha Vantage
        transcripts = scraper.scrape_earnings_transcripts(ticker)

        # Save raw files (SEC filings only - transcripts already in S3)
        if sec_filings:
            scraper.save_raw_files(sec_filings)

        all_artifacts.extend(sec_filings)
        all_artifacts.extend(transcripts)

    # Generate artifacts CSV from all files in S3
    print(f"\n{'='*70}")
    scraper.generate_artifacts_csv(companies_df)

    print("\n" + "=" * 70)
    print(f"✅ SCRAPING COMPLETE - Processed {len(companies_df)} companies")
    print(f"📄 Total artifacts collected: {len(all_artifacts)}")
    print("=" * 70)


if __name__ == "__main__":
    main()
