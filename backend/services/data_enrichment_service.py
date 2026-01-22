"""
Data Enrichment Service - LLM-Powered Feature Engineering

Implements LLM-based feature extraction inspired by the paper:
"From Limited Data to Rare-event Prediction: LLM-powered Feature Engineering"

Features extracted:
1. Company Classification (cyber_sector_relevance, market_positioning, etc.)
2. Competitive Relationships (COMPETES_WITH, PARTNERS_WITH)
3. Executive Changes from 8-K filings
4. Cybersecurity Vulnerability Events from NVD/CVE

All data sources are FREE:
- Existing SEC filings (already in S3/artifacts)
- NVD API (free, no auth required)
- SEC EDGAR (free)
"""

import os
import json
import logging
import re
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple

import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)


# =============================================================================
# LLM Client for Feature Extraction
# =============================================================================


class LLMFeatureExtractor:
    """Uses Claude via Bedrock for feature extraction from documents."""

    MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"

    def __init__(self):
        self.region = os.environ.get("AWS_REGION", "us-west-2")
        config = Config(
            region_name=self.region, retries={"max_attempts": 3, "mode": "adaptive"}
        )
        self.bedrock = boto3.client("bedrock-runtime", config=config)

    def extract_features(self, prompt: str, max_tokens: int = 1000) -> str:
        """Call Claude to extract features from text."""
        try:
            response = self.bedrock.converse(
                modelId=self.MODEL_ID,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": max_tokens, "temperature": 0.1},
            )
            return response["output"]["message"]["content"][0]["text"]
        except Exception as e:
            logger.error(f"LLM extraction failed: {e}")
            return ""


# =============================================================================
# 1. Company Feature Extraction from SEC Filings
# =============================================================================


class CompanyFeatureExtractor:
    """
    Extract LLM-derived features from SEC filings for company nodes.

    Features extracted:
    - cyber_sector_relevance: 0-4 scale
    - market_positioning: leader/challenger/niche/emerging
    - threat_specialization: list of security domains
    - competitive_moat: technology/market_share/partnerships/data_scale
    - risk_summary: condensed key risks
    """

    EXTRACTION_PROMPT = """Analyze this SEC filing excerpt and extract the following features in JSON format:

{text}

Extract these features (respond ONLY with valid JSON, no markdown):
{{
    "cyber_sector_relevance": <0-4 scale: 0=not cybersecurity, 1=peripheral, 2=significant, 3=core business, 4=pure-play cybersecurity>,
    "market_positioning": "<leader|challenger|niche|emerging>",
    "threat_specialization": ["<list of security domains: endpoint, cloud, network, identity, email, data, vulnerability, etc.>"],
    "competitive_moat": "<technology|market_share|partnerships|data_scale|platform_breadth>",
    "risk_summary": "<2-3 sentence summary of key business risks>",
    "competitors_mentioned": ["<list of competitor company names mentioned>"],
    "partners_mentioned": ["<list of partner/customer company names mentioned>"]
}}"""

    def __init__(self):
        self.llm = LLMFeatureExtractor()
        self._neo4j = None
        self._s3 = None

    @property
    def neo4j(self):
        if self._neo4j is None:
            from services.neo4j_service import get_neo4j_service

            self._neo4j = get_neo4j_service()
        return self._neo4j

    @property
    def s3(self):
        if self._s3 is None:
            self._s3 = boto3.client("s3")
        return self._s3

    def get_filing_text(self, ticker: str, filing_type: str = "10-K") -> Optional[str]:
        """Get the most recent filing text for a company."""
        try:
            from services.database_service import db_service

            artifacts = db_service.get_artifacts_by_ticker(ticker)
            # Filter for txt files only (PDFs can't be read as text)
            # Sort by date descending to get most recent
            txt_filings = [
                a
                for a in artifacts
                if filing_type in a.get("type", "")
                and a.get("s3_key", "").endswith(".txt")
            ]
            txt_filings.sort(key=lambda x: x.get("date", ""), reverse=True)
            filing = txt_filings[0] if txt_filings else None

            if not filing:
                return None

            bucket = os.environ.get("S3_BUCKET", "cyberrisk-data")
            s3_key = filing["s3_key"]

            response = self.s3.get_object(Bucket=bucket, Key=s3_key)
            text = response["Body"].read().decode("utf-8")

            # Get first 15000 chars (business description + competition sections)
            return text[:15000]

        except Exception as e:
            logger.error(f"Error getting filing for {ticker}: {e}")
            return None

    def extract_company_features(self, ticker: str) -> Dict[str, Any]:
        """Extract LLM-derived features for a company."""
        text = self.get_filing_text(ticker)
        if not text:
            return {"error": f"No filing found for {ticker}"}

        prompt = self.EXTRACTION_PROMPT.format(text=text[:12000])
        response = self.llm.extract_features(prompt, max_tokens=800)

        try:
            # Parse JSON response
            # Handle potential markdown code blocks
            json_match = re.search(r"\{[\s\S]*\}", response)
            if json_match:
                features = json.loads(json_match.group())
                features["ticker"] = ticker
                features["extracted_at"] = datetime.utcnow().isoformat()
                return features
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error for {ticker}: {e}")

        return {"error": "Failed to parse LLM response", "raw": response}

    def update_company_node(self, ticker: str, features: Dict) -> bool:
        """Update Neo4j Organization node with extracted features."""
        if "error" in features:
            return False

        try:
            query = """
                MATCH (o:Organization {ticker: $ticker})
                SET o.cyber_sector_relevance = $cyber_sector_relevance,
                    o.market_positioning = $market_positioning,
                    o.threat_specialization = $threat_specialization,
                    o.competitive_moat = $competitive_moat,
                    o.risk_summary = $risk_summary,
                    o.features_extracted_at = $extracted_at
                RETURN o.name as name
            """
            result = self.neo4j.execute_write(
                query,
                {
                    "ticker": ticker,
                    "cyber_sector_relevance": features.get("cyber_sector_relevance", 0),
                    "market_positioning": features.get("market_positioning", "unknown"),
                    "threat_specialization": features.get("threat_specialization", []),
                    "competitive_moat": features.get("competitive_moat", "unknown"),
                    "risk_summary": features.get("risk_summary", ""),
                    "extracted_at": features.get("extracted_at"),
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to update {ticker}: {e}")
            return False

    def create_competitive_relationships(self, ticker: str, features: Dict) -> int:
        """Create COMPETES_WITH relationships from extracted competitors."""
        if "error" in features or not features.get("competitors_mentioned"):
            return 0

        count = 0
        for competitor in features["competitors_mentioned"]:
            try:
                # Try to find the competitor in our graph
                query = """
                    MATCH (source:Organization {ticker: $ticker})
                    MATCH (target:Organization)
                    WHERE toLower(target.name) CONTAINS toLower($competitor_name)
                       OR target.name =~ ('(?i).*' + $competitor_name + '.*')
                    MERGE (source)-[r:COMPETES_WITH]->(target)
                    SET r.extracted_at = $extracted_at,
                        r.source = 'sec_filing'
                    RETURN target.name as matched
                """
                result = self.neo4j.execute_write(
                    query,
                    {
                        "ticker": ticker,
                        "competitor_name": competitor,
                        "extracted_at": datetime.utcnow().isoformat(),
                    },
                )
                if result:
                    count += 1
            except Exception as e:
                logger.warning(f"Could not create relationship for {competitor}: {e}")

        return count

    def enrich_all_companies(self) -> Dict[str, Any]:
        """Enrich all tracked companies with LLM features."""
        from services.database_service import db_service

        companies = db_service.get_all_companies()
        results = {"success": [], "failed": [], "relationships_created": 0}

        for company in companies:
            ticker = company["ticker"]
            logger.info(f"Extracting features for {ticker}...")

            features = self.extract_company_features(ticker)

            if "error" not in features:
                self.update_company_node(ticker, features)
                rel_count = self.create_competitive_relationships(ticker, features)
                results["success"].append(ticker)
                results["relationships_created"] += rel_count
            else:
                results["failed"].append({"ticker": ticker, "error": features["error"]})

        return results


# =============================================================================
# 2. NVD/CVE Vulnerability Events
# =============================================================================


class VulnerabilityEventService:
    """
    Fetch cybersecurity vulnerabilities from NVD (National Vulnerability Database).
    FREE API - no authentication required.

    Creates Vulnerability nodes linked to affected vendors/products.
    """

    NVD_API_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"

    # Map cybersecurity vendors to their NVD CPE names
    VENDOR_CPE_MAP = {
        "CRWD": ["crowdstrike"],
        "PANW": ["palo_alto_networks", "paloaltonetworks"],
        "FTNT": ["fortinet"],
        "CSCO": ["cisco"],
        "ZS": ["zscaler"],
        "OKTA": ["okta"],
        "CYBR": ["cyberark"],
        "S": ["sentinelone"],
        "NET": ["cloudflare"],
        "SPLK": ["splunk"],
        "TENB": ["tenable"],
    }

    def __init__(self):
        self._neo4j = None

    @property
    def neo4j(self):
        if self._neo4j is None:
            from services.neo4j_service import get_neo4j_service

            self._neo4j = get_neo4j_service()
        return self._neo4j

    def fetch_vulnerabilities(
        self, vendor_keyword: str, days_back: int = 90
    ) -> List[Dict]:
        """Fetch vulnerabilities for a vendor from NVD."""
        try:
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=days_back)

            params = {
                "keywordSearch": vendor_keyword,
                "pubStartDate": start_date.strftime("%Y-%m-%dT00:00:00.000"),
                "pubEndDate": end_date.strftime("%Y-%m-%dT23:59:59.999"),
                "resultsPerPage": 50,
            }

            response = requests.get(self.NVD_API_URL, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()
            vulnerabilities = []

            for item in data.get("vulnerabilities", []):
                cve = item.get("cve", {})
                vuln = {
                    "cve_id": cve.get("id"),
                    "description": cve.get("descriptions", [{}])[0].get("value", ""),
                    "published": cve.get("published"),
                    "severity": self._get_severity(cve),
                    "vendor": vendor_keyword,
                }
                vulnerabilities.append(vuln)

            return vulnerabilities

        except Exception as e:
            logger.error(f"NVD fetch failed for {vendor_keyword}: {e}")
            return []

    def _get_severity(self, cve: Dict) -> str:
        """Extract severity from CVE metrics."""
        metrics = cve.get("metrics", {})

        # Try CVSS 3.1 first, then 3.0, then 2.0
        for version in ["cvssMetricV31", "cvssMetricV30", "cvssMetricV2"]:
            if version in metrics and metrics[version]:
                return (
                    metrics[version][0]
                    .get("cvssData", {})
                    .get("baseSeverity", "UNKNOWN")
                )

        return "UNKNOWN"

    def create_vulnerability_nodes(self, ticker: str) -> Dict[str, Any]:
        """Create Vulnerability nodes for a company's products."""
        cpe_names = self.VENDOR_CPE_MAP.get(ticker, [])
        if not cpe_names:
            return {"ticker": ticker, "vulnerabilities": 0, "error": "No CPE mapping"}

        total_created = 0

        for vendor_name in cpe_names:
            vulns = self.fetch_vulnerabilities(vendor_name)

            for vuln in vulns:
                try:
                    query = """
                        MERGE (v:Vulnerability {cve_id: $cve_id})
                        SET v.description = $description,
                            v.published = $published,
                            v.severity = $severity,
                            v.vendor = $vendor
                        WITH v
                        MATCH (o:Organization {ticker: $ticker})
                        MERGE (o)-[r:HAS_VULNERABILITY]->(v)
                        SET r.detected_at = $now
                        RETURN v.cve_id as created
                    """
                    result = self.neo4j.execute_write(
                        query,
                        {
                            "ticker": ticker,
                            "cve_id": vuln["cve_id"],
                            "description": vuln["description"][:500],
                            "published": vuln["published"],
                            "severity": vuln["severity"],
                            "vendor": vuln["vendor"],
                            "now": datetime.utcnow().isoformat(),
                        },
                    )
                    if result:
                        total_created += 1
                except Exception as e:
                    logger.warning(
                        f"Failed to create vulnerability {vuln['cve_id']}: {e}"
                    )

        return {"ticker": ticker, "vulnerabilities_created": total_created}

    def fetch_vulnerabilities_for_company(
        self, ticker: str, company_name: str, days_back: int = 90
    ) -> List[Dict]:
        """Fetch vulnerabilities for a company from NVD.

        Tries multiple search strategies:
        1. Known CPE mapping
        2. Company name search
        3. Ticker-based product search

        Returns list of vulnerabilities found (does not create nodes).
        """
        all_vulns = []

        # Try CPE mapping first
        cpe_names = self.VENDOR_CPE_MAP.get(ticker.upper(), [])
        for vendor_name in cpe_names:
            vulns = self.fetch_vulnerabilities(vendor_name, days_back)
            all_vulns.extend(vulns)

        # Also try company name if different from CPE names
        if company_name:
            # Simplify company name for search
            simple_name = (
                company_name.lower().replace(" inc.", "").replace(" corp.", "").strip()
            )
            if simple_name not in [n.lower() for n in cpe_names]:
                vulns = self.fetch_vulnerabilities(simple_name, days_back)
                # Dedupe by CVE ID
                existing_ids = {v["cve_id"] for v in all_vulns}
                for v in vulns:
                    if v["cve_id"] not in existing_ids:
                        all_vulns.append(v)

        return all_vulns

    def enrich_all_companies(self, days_back: int = 90) -> Dict[str, Any]:
        """Fetch vulnerabilities for all mapped companies."""
        results = {"success": [], "total_vulnerabilities": 0}

        for ticker in self.VENDOR_CPE_MAP.keys():
            logger.info(f"Fetching vulnerabilities for {ticker}...")
            result = self.create_vulnerability_nodes(ticker)
            results["success"].append(result)
            results["total_vulnerabilities"] += result.get("vulnerabilities_created", 0)

        return results


# =============================================================================
# 3. SEC 8-K Executive Event Extraction
# =============================================================================


class ExecutiveEventExtractor:
    """
    Extract executive change events from SEC 8-K filings.
    Item 5.02 reports departures/appointments of directors and executives.

    FREE - uses existing SEC filing data.
    """

    EXECUTIVE_PROMPT = """Analyze this SEC 8-K filing and extract executive change events.
Return ONLY valid JSON, no markdown:

{text}

Extract:
{{
    "events": [
        {{
            "event_type": "<appointment|departure|retirement|resignation>",
            "person_name": "<full name>",
            "title": "<job title>",
            "effective_date": "<YYYY-MM-DD or null>",
            "reason": "<brief reason if stated, or null>"
        }}
    ]
}}

If no executive changes, return {{"events": []}}"""

    def __init__(self):
        self.llm = LLMFeatureExtractor()
        self._neo4j = None
        self._s3 = None

    @property
    def neo4j(self):
        if self._neo4j is None:
            from services.neo4j_service import get_neo4j_service

            self._neo4j = get_neo4j_service()
        return self._neo4j

    @property
    def s3(self):
        if self._s3 is None:
            self._s3 = boto3.client("s3")
        return self._s3

    def get_8k_filings(self, ticker: str) -> List[Dict]:
        """Get 8-K filings for a company."""
        try:
            from services.database_service import db_service

            artifacts = db_service.get_artifacts_by_ticker(ticker)
            return [a for a in artifacts if "8-K" in a.get("type", "")]
        except Exception as e:
            logger.error(f"Error getting 8-K filings for {ticker}: {e}")
            return []

    def extract_executive_events(self, ticker: str) -> List[Dict]:
        """Extract executive events from 8-K filings."""
        filings = self.get_8k_filings(ticker)
        all_events = []

        bucket = os.environ.get("S3_BUCKET", "cyberrisk-data")

        for filing in filings[:5]:  # Process recent 5 8-Ks
            try:
                s3_key = filing["s3_key"]
                response = self.s3.get_object(Bucket=bucket, Key=s3_key)
                text = response["Body"].read().decode("utf-8")[:8000]

                # Check if this 8-K might have executive changes
                if not any(
                    kw in text.lower()
                    for kw in [
                        "item 5.02",
                        "departure",
                        "appointment",
                        "officer",
                        "director",
                    ]
                ):
                    continue

                prompt = self.EXECUTIVE_PROMPT.format(text=text)
                response_text = self.llm.extract_features(prompt, max_tokens=500)

                json_match = re.search(r"\{[\s\S]*\}", response_text)
                if json_match:
                    data = json.loads(json_match.group())
                    for event in data.get("events", []):
                        event["ticker"] = ticker
                        event["filing_date"] = filing.get("date")
                        event["s3_key"] = s3_key
                        all_events.append(event)

            except Exception as e:
                logger.warning(f"Error processing 8-K {filing.get('s3_key')}: {e}")

        return all_events

    def create_executive_events(self, ticker: str) -> Dict[str, Any]:
        """Create executive event nodes and relationships."""
        events = self.extract_executive_events(ticker)
        created = 0

        for event in events:
            try:
                # Create Person node if doesn't exist
                # Create ExecutiveChange event
                # Link to Organization
                query = """
                    MATCH (o:Organization {ticker: $ticker})
                    MERGE (p:Person {name: $person_name})
                    SET p.last_title = $title

                    CREATE (e:ExecutiveEvent {
                        event_type: $event_type,
                        person_name: $person_name,
                        title: $title,
                        effective_date: $effective_date,
                        reason: $reason,
                        filing_date: $filing_date,
                        created_at: $now
                    })

                    MERGE (o)-[:HAS_EXECUTIVE_EVENT]->(e)
                    MERGE (p)-[:INVOLVED_IN]->(e)

                    RETURN e.event_type as created
                """
                result = self.neo4j.execute_write(
                    query,
                    {
                        "ticker": ticker,
                        "event_type": event.get("event_type"),
                        "person_name": event.get("person_name"),
                        "title": event.get("title"),
                        "effective_date": event.get("effective_date"),
                        "reason": event.get("reason"),
                        "filing_date": event.get("filing_date"),
                        "now": datetime.utcnow().isoformat(),
                    },
                )
                if result:
                    created += 1
            except Exception as e:
                logger.warning(f"Failed to create executive event: {e}")

        return {"ticker": ticker, "events_created": created, "events": events}

    def enrich_all_companies(self) -> Dict[str, Any]:
        """Extract executive events for all companies."""
        from services.database_service import db_service

        companies = db_service.get_all_companies()
        results = {"success": [], "total_events": 0}

        for company in companies:
            ticker = company["ticker"]
            logger.info(f"Extracting executive events for {ticker}...")
            result = self.create_executive_events(ticker)
            results["success"].append(
                {"ticker": ticker, "events": result["events_created"]}
            )
            results["total_events"] += result["events_created"]

        return results


# =============================================================================
# 4. Analyst Sentiment Extraction from Earnings Calls
# =============================================================================


class AnalystSentimentExtractor:
    """
    Extract analyst sentiment features from earnings call transcripts.

    Features:
    - analyst_sentiment: overall tone of analyst questions
    - management_tone: confidence level of management responses
    - guidance_direction: raised/maintained/lowered
    """

    SENTIMENT_PROMPT = """Analyze this earnings call transcript Q&A section and extract sentiment features.
Return ONLY valid JSON:

{text}

Extract:
{{
    "analyst_sentiment": "<bullish|neutral|bearish|mixed>",
    "analyst_concerns": ["<list of main concerns raised by analysts>"],
    "management_tone": "<confident|cautious|defensive|neutral>",
    "guidance_direction": "<raised|maintained|lowered|not_mentioned>",
    "key_topics": ["<main topics discussed>"],
    "notable_quotes": ["<1-2 important quotes from Q&A>"]
}}"""

    def __init__(self):
        self.llm = LLMFeatureExtractor()
        self._neo4j = None
        self._s3 = None

    @property
    def neo4j(self):
        if self._neo4j is None:
            from services.neo4j_service import get_neo4j_service

            self._neo4j = get_neo4j_service()
        return self._neo4j

    @property
    def s3(self):
        if self._s3 is None:
            self._s3 = boto3.client("s3")
        return self._s3

    def extract_transcript_sentiment(self, ticker: str) -> Dict[str, Any]:
        """Extract sentiment from most recent earnings transcript."""
        try:
            from services.database_service import db_service

            artifacts = db_service.get_artifacts_by_ticker(ticker)
            transcript = next(
                (a for a in artifacts if "transcript" in a.get("type", "").lower()),
                None,
            )

            if not transcript:
                return {"error": f"No transcript found for {ticker}"}

            bucket = os.environ.get("S3_BUCKET", "cyberrisk-data")
            response = self.s3.get_object(Bucket=bucket, Key=transcript["s3_key"])
            text = response["Body"].read().decode("utf-8")

            # Try to find Q&A section
            qa_start = text.lower().find("question")
            if qa_start > 0:
                text = text[qa_start : qa_start + 10000]
            else:
                text = text[-10000:]  # Use last part which usually has Q&A

            prompt = self.SENTIMENT_PROMPT.format(text=text[:8000])
            response_text = self.llm.extract_features(prompt, max_tokens=600)

            json_match = re.search(r"\{[\s\S]*\}", response_text)
            if json_match:
                features = json.loads(json_match.group())
                features["ticker"] = ticker
                features["transcript_date"] = transcript.get("date")
                features["extracted_at"] = datetime.utcnow().isoformat()
                return features

        except Exception as e:
            logger.error(f"Sentiment extraction failed for {ticker}: {e}")

        return {"error": "Failed to extract sentiment"}

    def update_company_sentiment(self, ticker: str) -> Dict[str, Any]:
        """Extract and store analyst sentiment for a company."""
        sentiment = self.extract_transcript_sentiment(ticker)

        if "error" in sentiment:
            return sentiment

        try:
            query = """
                MATCH (o:Organization {ticker: $ticker})
                SET o.analyst_sentiment = $analyst_sentiment,
                    o.analyst_concerns = $analyst_concerns,
                    o.management_tone = $management_tone,
                    o.guidance_direction = $guidance_direction,
                    o.sentiment_extracted_at = $extracted_at
                RETURN o.name as updated
            """
            self.neo4j.execute_write(
                query,
                {
                    "ticker": ticker,
                    "analyst_sentiment": sentiment.get("analyst_sentiment"),
                    "analyst_concerns": sentiment.get("analyst_concerns", []),
                    "management_tone": sentiment.get("management_tone"),
                    "guidance_direction": sentiment.get("guidance_direction"),
                    "extracted_at": sentiment.get("extracted_at"),
                },
            )
            return {"ticker": ticker, "sentiment": sentiment}
        except Exception as e:
            return {"error": str(e)}

    def enrich_all_companies(self) -> Dict[str, Any]:
        """Extract analyst sentiment for all companies."""
        from services.database_service import db_service

        companies = db_service.get_all_companies()
        results = {"success": [], "failed": []}

        for company in companies:
            ticker = company["ticker"]
            logger.info(f"Extracting analyst sentiment for {ticker}...")
            result = self.update_company_sentiment(ticker)

            if "error" not in result:
                results["success"].append(ticker)
            else:
                results["failed"].append({"ticker": ticker, "error": result["error"]})

        return results


# =============================================================================
# Main Enrichment Orchestrator
# =============================================================================


class DataEnrichmentService:
    """
    Orchestrates all data enrichment operations.
    """

    def __init__(self):
        self.company_extractor = CompanyFeatureExtractor()
        self.vulnerability_service = VulnerabilityEventService()
        self.executive_extractor = ExecutiveEventExtractor()
        self.sentiment_extractor = AnalystSentimentExtractor()

    def run_full_enrichment(
        self,
        skip_llm_features: bool = False,
        skip_vulnerabilities: bool = False,
        skip_executive_events: bool = False,
        skip_analyst_sentiment: bool = False,
    ) -> Dict[str, Any]:
        """Run all enrichment pipelines.

        Args:
            skip_llm_features: Skip LLM feature extraction
            skip_vulnerabilities: Skip NVD vulnerability fetching
            skip_executive_events: Skip 8-K executive event extraction
            skip_analyst_sentiment: Skip analyst sentiment extraction
        """
        results = {}

        logger.info("=" * 60)
        logger.info("Starting Full Data Enrichment")
        logger.info("=" * 60)

        # 1. Company Features & Competitive Relationships
        if not skip_llm_features:
            logger.info("\n[1/4] Extracting company features...")
            results["company_features"] = self.company_extractor.enrich_all_companies()
        else:
            logger.info("\n[1/4] Skipping company features (skip_llm_features=True)")
            results["company_features"] = {"skipped": True}

        # 2. Vulnerability Events
        if not skip_vulnerabilities:
            logger.info("\n[2/4] Fetching vulnerability events...")
            results["vulnerabilities"] = (
                self.vulnerability_service.enrich_all_companies()
            )
        else:
            logger.info("\n[2/4] Skipping vulnerabilities (skip_vulnerabilities=True)")
            results["vulnerabilities"] = {"skipped": True}

        # 3. Executive Events
        if not skip_executive_events:
            logger.info("\n[3/4] Extracting executive events...")
            results["executive_events"] = (
                self.executive_extractor.enrich_all_companies()
            )
        else:
            logger.info(
                "\n[3/4] Skipping executive events (skip_executive_events=True)"
            )
            results["executive_events"] = {"skipped": True}

        # 4. Analyst Sentiment
        if not skip_analyst_sentiment:
            logger.info("\n[4/4] Extracting analyst sentiment...")
            results["analyst_sentiment"] = (
                self.sentiment_extractor.enrich_all_companies()
            )
        else:
            logger.info(
                "\n[4/4] Skipping analyst sentiment (skip_analyst_sentiment=True)"
            )
            results["analyst_sentiment"] = {"skipped": True}

        logger.info("\n" + "=" * 60)
        logger.info("Enrichment Complete")
        logger.info("=" * 60)

        return results

    def enrich_single_company(
        self,
        ticker: str,
        skip_llm_features: bool = False,
        skip_vulnerabilities: bool = False,
        skip_executive_events: bool = False,
        skip_analyst_sentiment: bool = False,
    ) -> Dict[str, Any]:
        """Run all enrichments for a single company.

        Args:
            ticker: Stock ticker symbol
            skip_llm_features: Skip LLM feature extraction
            skip_vulnerabilities: Skip NVD vulnerability fetching
            skip_executive_events: Skip 8-K executive event extraction
            skip_analyst_sentiment: Skip analyst sentiment extraction
        """
        ticker = ticker.upper()
        results = {"ticker": ticker}

        # Company features
        if not skip_llm_features:
            features = self.company_extractor.extract_company_features(ticker)
            if features and "error" not in features:
                self.company_extractor.update_company_node(ticker, features)
                self.company_extractor.create_competitive_relationships(
                    ticker, features
                )
            results["features"] = features
        else:
            results["features"] = {"skipped": True}

        # Vulnerabilities
        if not skip_vulnerabilities:
            results["vulnerabilities"] = (
                self.vulnerability_service.create_vulnerability_nodes(ticker)
            )
        else:
            results["vulnerabilities"] = {"skipped": True}

        # Executive events
        if not skip_executive_events:
            results["executive_events"] = (
                self.executive_extractor.create_executive_events(ticker)
            )
        else:
            results["executive_events"] = {"skipped": True}

        # Analyst sentiment
        if not skip_analyst_sentiment:
            results["sentiment"] = self.sentiment_extractor.update_company_sentiment(
                ticker
            )
        else:
            results["sentiment"] = {"skipped": True}

        return results


# Singleton instance
_enrichment_service = None


def get_enrichment_service() -> DataEnrichmentService:
    """Get singleton enrichment service instance."""
    global _enrichment_service
    if _enrichment_service is None:
        _enrichment_service = DataEnrichmentService()
    return _enrichment_service
