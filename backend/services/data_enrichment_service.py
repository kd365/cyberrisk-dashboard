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
            from services.ocr_service import get_ocr_service

            artifacts = db_service.get_artifacts_by_ticker(ticker)
            # Sort by date descending to get most recent
            # Prefer OCR-extracted files (_ocr.txt), then regular .txt, then .pdf
            filings = [a for a in artifacts if filing_type in a.get("type", "")]

            def get_file_priority(s3_key: str) -> int:
                """Return priority: 0=ocr.txt (best), 1=regular.txt, 2=pdf"""
                if "_ocr.txt" in s3_key:
                    return 0
                elif s3_key.endswith(".txt"):
                    return 1
                return 2

            # Sort by priority first, then by date descending
            filings.sort(
                key=lambda x: (
                    get_file_priority(x.get("s3_key", "")),
                    x.get("date", "") or "",
                ),
                reverse=False,
            )
            # Also sort by date within each priority
            filings.sort(key=lambda x: x.get("date", ""), reverse=True)

            filing = filings[0] if filings else None

            if not filing:
                return None

            bucket = os.environ.get("S3_BUCKET", "cyberrisk-data")
            s3_key = filing["s3_key"]
            ocr = get_ocr_service()

            # If PDF, use OCR extraction
            if s3_key.endswith(".pdf"):
                logger.info(f"Using OCR extraction for {s3_key}")
                ocr.bucket = bucket
                text = ocr.extract_text_from_s3(s3_key, use_ocr=True)
            else:
                # Read TXT file
                response = self.s3.get_object(Bucket=bucket, Key=s3_key)
                text = response["Body"].read().decode("utf-8")
                # Clean XBRL/HTML artifacts from the text
                text = ocr.clean_text(text)

            if not text:
                return None

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
# 3. SEC 8-K Event Extraction (Executive Changes, M&A, Security Incidents)
# =============================================================================


class SEC8KEventExtractor:
    """
    Extract material events from SEC 8-K filings by parsing Item sections.

    Supported Items:
    - 1.01: Entry into Material Agreements (M&A, partnerships)
    - 1.02: Termination of Material Agreements
    - 2.01: Completion of Acquisition/Disposition
    - 2.05: Costs Associated with Exit/Restructuring
    - 5.02: Departure/Appointment of Directors/Officers
    - 8.01: Other Events (cybersecurity incidents, breaches)

    FREE - uses existing SEC filing data.
    """

    # Item section patterns for parsing (handles single-line and multi-line text)
    ITEM_PATTERNS = {
        "1.01": r"item\s*1\.01[^a-zA-Z0-9]*(.{100,}?)(?=item\s*\d+\.\d+|signature|$)",
        "1.02": r"item\s*1\.02[^a-zA-Z0-9]*(.{100,}?)(?=item\s*\d+\.\d+|signature|$)",
        "2.01": r"item\s*2\.01[^a-zA-Z0-9]*(.{100,}?)(?=item\s*\d+\.\d+|signature|$)",
        "2.05": r"item\s*2\.05[^a-zA-Z0-9]*(.{100,}?)(?=item\s*\d+\.\d+|signature|$)",
        "5.02": r"item\s*5\.02[^a-zA-Z0-9]*(.{100,}?)(?=item\s*\d+\.\d+|signature|$)",
        "8.01": r"item\s*8\.01[^a-zA-Z0-9]*(.{100,}?)(?=item\s*\d+\.\d+|signature|$)",
    }

    # Prompts for each Item type
    PROMPTS = {
        "5.02": """Analyze this SEC 8-K Item 5.02 section and extract executive change events.
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

If no executive changes found, return {{"events": []}}""",
        "1.01": """Analyze this SEC 8-K Item 1.01 section about material agreements.
Return ONLY valid JSON, no markdown:

{text}

Extract:
{{
    "events": [
        {{
            "event_type": "<acquisition|merger|partnership|licensing|credit_agreement|other>",
            "counterparty": "<other company/entity name>",
            "deal_value": "<dollar amount or null>",
            "effective_date": "<YYYY-MM-DD or null>",
            "summary": "<1-2 sentence description>"
        }}
    ]
}}

If no material agreements found, return {{"events": []}}""",
        "2.01": """Analyze this SEC 8-K Item 2.01 section about completed acquisitions/dispositions.
Return ONLY valid JSON, no markdown:

{text}

Extract:
{{
    "events": [
        {{
            "event_type": "<acquisition_completed|disposition_completed>",
            "target_company": "<acquired/disposed company name>",
            "deal_value": "<dollar amount or null>",
            "completion_date": "<YYYY-MM-DD or null>",
            "summary": "<1-2 sentence description>"
        }}
    ]
}}

If no completed deals found, return {{"events": []}}""",
        "8.01": """Analyze this SEC 8-K Item 8.01 section for cybersecurity or material events.
Return ONLY valid JSON, no markdown:

{text}

Extract:
{{
    "events": [
        {{
            "event_type": "<cybersecurity_incident|data_breach|vulnerability|ransomware|other_security|material_event>",
            "severity": "<critical|high|medium|low|unknown>",
            "discovery_date": "<YYYY-MM-DD or null>",
            "affected_systems": "<description or null>",
            "data_compromised": "<yes|no|unknown>",
            "summary": "<1-2 sentence description>"
        }}
    ]
}}

If no security/material events found, return {{"events": []}}""",
        "1.02": """Analyze this SEC 8-K Item 1.02 section about terminated agreements.
Return ONLY valid JSON, no markdown:

{text}

Extract:
{{
    "events": [
        {{
            "event_type": "<contract_termination|partnership_end|license_revoked>",
            "counterparty": "<other company/entity name>",
            "termination_date": "<YYYY-MM-DD or null>",
            "reason": "<reason if stated or null>",
            "summary": "<1-2 sentence description>"
        }}
    ]
}}

If no terminations found, return {{"events": []}}""",
        "2.05": """Analyze this SEC 8-K Item 2.05 section about restructuring/exit costs.
Return ONLY valid JSON, no markdown:

{text}

Extract:
{{
    "events": [
        {{
            "event_type": "<layoff|restructuring|facility_closure|cost_reduction>",
            "estimated_cost": "<dollar amount or null>",
            "employees_affected": "<number or null>",
            "expected_completion": "<YYYY-MM-DD or null>",
            "summary": "<1-2 sentence description>"
        }}
    ]
}}

If no restructuring events found, return {{"events": []}}""",
    }

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
        """Get all 8-K filings for a company."""
        try:
            from services.database_service import db_service

            artifacts = db_service.get_artifacts_by_ticker(ticker)
            return [a for a in artifacts if "8-K" in a.get("type", "")]
        except Exception as e:
            logger.error(f"Error getting 8-K filings for {ticker}: {e}")
            return []

    def parse_item_sections(self, text: str) -> Dict[str, str]:
        """Parse 8-K text into Item sections."""
        sections = {}
        text_lower = text.lower()

        for item_num, pattern in self.ITEM_PATTERNS.items():
            match = re.search(pattern, text_lower, re.IGNORECASE)
            if match:
                # Get the actual text (not lowercased) using the match positions
                start = match.start(1)
                end = match.end(1)
                section_text = text[start:end].strip()
                # Limit section to 6000 chars to stay within LLM context
                if len(section_text) > 6000:
                    section_text = section_text[:6000]
                if len(section_text) > 100:  # Only include if substantial
                    sections[item_num] = section_text

        return sections

    def extract_events_from_section(
        self,
        item_num: str,
        section_text: str,
        ticker: str,
        filing_date: str,
        s3_key: str,
    ) -> List[Dict]:
        """Extract events from a single Item section using LLM."""
        if item_num not in self.PROMPTS:
            return []

        try:
            prompt = self.PROMPTS[item_num].format(text=section_text)
            response_text = self.llm.extract_features(prompt, max_tokens=800)

            json_match = re.search(r"\{[\s\S]*\}", response_text)
            if json_match:
                data = json.loads(json_match.group())
                events = []
                for event in data.get("events", []):
                    event["ticker"] = ticker
                    event["filing_date"] = filing_date
                    event["s3_key"] = s3_key
                    event["item_number"] = item_num
                    events.append(event)
                return events
        except Exception as e:
            logger.warning(f"Error extracting from Item {item_num}: {e}")

        return []

    def extract_all_events(self, ticker: str) -> Dict[str, List[Dict]]:
        """Extract all event types from all 8-K filings for a company."""
        filings = self.get_8k_filings(ticker)
        bucket = os.environ.get("S3_BUCKET", "cyberrisk-data")

        all_events = {
            "executive_events": [],
            "ma_events": [],
            "security_events": [],
            "restructuring_events": [],
        }

        for filing in filings:  # Process ALL 8-Ks
            try:
                s3_key = filing["s3_key"]
                response = self.s3.get_object(Bucket=bucket, Key=s3_key)
                text = response["Body"].read().decode("utf-8")
                filing_date = filing.get("date")

                # Parse into sections
                sections = self.parse_item_sections(text)

                # Extract from each section
                for item_num, section_text in sections.items():
                    events = self.extract_events_from_section(
                        item_num, section_text, ticker, filing_date, s3_key
                    )

                    # Categorize events
                    for event in events:
                        if item_num == "5.02":
                            all_events["executive_events"].append(event)
                        elif item_num in ["1.01", "1.02", "2.01"]:
                            all_events["ma_events"].append(event)
                        elif item_num == "8.01":
                            all_events["security_events"].append(event)
                        elif item_num == "2.05":
                            all_events["restructuring_events"].append(event)

            except Exception as e:
                logger.warning(f"Error processing 8-K {filing.get('s3_key')}: {e}")

        logger.info(
            f"{ticker}: Found {len(all_events['executive_events'])} exec, "
            f"{len(all_events['ma_events'])} M&A, "
            f"{len(all_events['security_events'])} security, "
            f"{len(all_events['restructuring_events'])} restructuring events"
        )

        return all_events

    def extract_executive_events(self, ticker: str) -> List[Dict]:
        """Extract only executive events (backward compatible)."""
        all_events = self.extract_all_events(ticker)
        return all_events["executive_events"]

    def create_executive_events(self, ticker: str) -> Dict[str, Any]:
        """Create executive event nodes and relationships."""
        events = self.extract_executive_events(ticker)
        created = 0

        for event in events:
            try:
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

    def create_ma_events(self, ticker: str, events: List[Dict]) -> int:
        """Create M&A event nodes in Neo4j with relationships to other companies."""
        created = 0
        for event in events:
            try:
                # Get counterparty/target company name
                other_company = event.get("counterparty") or event.get("target_company")

                query = """
                    MATCH (o:Organization {ticker: $ticker})
                    CREATE (e:MAEvent {
                        event_type: $event_type,
                        counterparty: $counterparty,
                        target_company: $target_company,
                        deal_value: $deal_value,
                        effective_date: $effective_date,
                        summary: $summary,
                        filing_date: $filing_date,
                        item_number: $item_number,
                        created_at: $now
                    })
                    MERGE (o)-[:HAS_MA_EVENT]->(e)

                    // Create/link counterparty organization if named
                    WITH o, e
                    WHERE $other_company IS NOT NULL AND $other_company <> ''
                    MERGE (other:Organization {name: $other_company})
                    ON CREATE SET other.created_from = 'ma_event'
                    MERGE (e)-[:INVOLVES_COMPANY]->(other)
                    MERGE (o)-[:MA_RELATIONSHIP {type: $event_type, date: $effective_date}]->(other)

                    RETURN e.event_type as created
                """
                result = self.neo4j.execute_write(
                    query,
                    {
                        "ticker": ticker,
                        "event_type": event.get("event_type"),
                        "counterparty": event.get("counterparty"),
                        "target_company": event.get("target_company"),
                        "other_company": other_company,
                        "deal_value": event.get("deal_value"),
                        "effective_date": event.get("effective_date")
                        or event.get("completion_date")
                        or event.get("termination_date"),
                        "summary": event.get("summary"),
                        "filing_date": event.get("filing_date"),
                        "item_number": event.get("item_number"),
                        "now": datetime.utcnow().isoformat(),
                    },
                )
                if result:
                    created += 1
            except Exception as e:
                logger.warning(f"Failed to create M&A event: {e}")
        return created

    def create_security_events(self, ticker: str, events: List[Dict]) -> int:
        """Create security/cyber incident nodes in Neo4j with vulnerability links."""
        created = 0
        for event in events:
            try:
                query = """
                    MATCH (o:Organization {ticker: $ticker})
                    CREATE (e:SecurityEvent {
                        event_type: $event_type,
                        severity: $severity,
                        discovery_date: $discovery_date,
                        affected_systems: $affected_systems,
                        data_compromised: $data_compromised,
                        summary: $summary,
                        filing_date: $filing_date,
                        created_at: $now
                    })
                    MERGE (o)-[:HAS_SECURITY_EVENT]->(e)
                    MERGE (o)-[:EXPERIENCED_INCIDENT {
                        date: $discovery_date,
                        severity: $severity,
                        type: $event_type
                    }]->(e)

                    // Link to Vulnerability node if it's a vulnerability disclosure
                    WITH o, e
                    WHERE $event_type IN ['vulnerability', 'data_breach', 'cybersecurity_incident']
                    MERGE (v:Vulnerability {
                        name: $summary,
                        severity: $severity,
                        disclosed_date: $discovery_date
                    })
                    ON CREATE SET v.source = 'sec_8k', v.created_at = $now
                    MERGE (e)-[:RELATES_TO_VULNERABILITY]->(v)
                    MERGE (o)-[:DISCLOSED_VULNERABILITY]->(v)

                    RETURN e.event_type as created
                """
                result = self.neo4j.execute_write(
                    query,
                    {
                        "ticker": ticker,
                        "event_type": event.get("event_type"),
                        "severity": event.get("severity"),
                        "discovery_date": event.get("discovery_date"),
                        "affected_systems": event.get("affected_systems"),
                        "data_compromised": event.get("data_compromised"),
                        "summary": event.get("summary"),
                        "filing_date": event.get("filing_date"),
                        "now": datetime.utcnow().isoformat(),
                    },
                )
                if result:
                    created += 1
            except Exception as e:
                logger.warning(f"Failed to create security event: {e}")
        return created

    def create_restructuring_events(self, ticker: str, events: List[Dict]) -> int:
        """Create restructuring event nodes in Neo4j."""
        created = 0
        for event in events:
            try:
                query = """
                    MATCH (o:Organization {ticker: $ticker})
                    CREATE (e:RestructuringEvent {
                        event_type: $event_type,
                        estimated_cost: $estimated_cost,
                        employees_affected: $employees_affected,
                        expected_completion: $expected_completion,
                        summary: $summary,
                        filing_date: $filing_date,
                        created_at: $now
                    })
                    MERGE (o)-[:HAS_RESTRUCTURING_EVENT]->(e)
                    RETURN e.event_type as created
                """
                result = self.neo4j.execute_write(
                    query,
                    {
                        "ticker": ticker,
                        "event_type": event.get("event_type"),
                        "estimated_cost": event.get("estimated_cost"),
                        "employees_affected": event.get("employees_affected"),
                        "expected_completion": event.get("expected_completion"),
                        "summary": event.get("summary"),
                        "filing_date": event.get("filing_date"),
                        "now": datetime.utcnow().isoformat(),
                    },
                )
                if result:
                    created += 1
            except Exception as e:
                logger.warning(f"Failed to create restructuring event: {e}")
        return created

    def create_all_events(self, ticker: str) -> Dict[str, Any]:
        """Extract and create all event types for a company."""
        all_events = self.extract_all_events(ticker)

        results = {
            "ticker": ticker,
            "executive_events": 0,
            "ma_events": 0,
            "security_events": 0,
            "restructuring_events": 0,
        }

        # Create executive events
        for event in all_events["executive_events"]:
            try:
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
                    results["executive_events"] += 1
            except Exception as e:
                logger.warning(f"Failed to create executive event: {e}")

        # Create M&A events
        results["ma_events"] = self.create_ma_events(ticker, all_events["ma_events"])

        # Create security events
        results["security_events"] = self.create_security_events(
            ticker, all_events["security_events"]
        )

        # Create restructuring events
        results["restructuring_events"] = self.create_restructuring_events(
            ticker, all_events["restructuring_events"]
        )

        total = sum(
            [
                results["executive_events"],
                results["ma_events"],
                results["security_events"],
                results["restructuring_events"],
            ]
        )
        logger.info(f"{ticker}: Created {total} total events in graph")

        return results

    def enrich_all_companies(self) -> Dict[str, Any]:
        """Extract all 8-K events for all companies."""
        from services.database_service import db_service

        companies = db_service.get_all_companies()
        results = {
            "success": [],
            "totals": {
                "executive_events": 0,
                "ma_events": 0,
                "security_events": 0,
                "restructuring_events": 0,
            },
        }

        for company in companies:
            ticker = company["ticker"]
            logger.info(f"Extracting 8-K events for {ticker}...")
            result = self.create_all_events(ticker)
            results["success"].append(result)
            results["totals"]["executive_events"] += result["executive_events"]
            results["totals"]["ma_events"] += result["ma_events"]
            results["totals"]["security_events"] += result["security_events"]
            results["totals"]["restructuring_events"] += result["restructuring_events"]

        return results


# Backward compatibility alias
ExecutiveEventExtractor = SEC8KEventExtractor


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
