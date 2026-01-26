"""
Regulatory Service
Provides regulatory tracking and compliance monitoring for CyberRisk Dashboard

Integrates with Federal Register API to fetch cybersecurity-related regulations
and calculate relevance scores for tracked companies using TF-IDF style scoring.

Uses AWS Bedrock LLM to validate regulation relevance and reduce false positives.
Syncs regulations to Neo4j knowledge graph for graph-based analysis.
"""

import os
import logging
import requests
import threading
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

import boto3
from botocore.config import Config

from services.database_service import db_service

logger = logging.getLogger(__name__)


class RegulatoryService:
    """
    Service for tracking regulatory changes and generating company alerts.

    Uses Bedrock LLM to validate regulation relevance (reduces false positives)
    and syncs regulations to Neo4j knowledge graph.
    """

    # Federal Register API configuration
    FEDERAL_REGISTER_BASE_URL = "https://www.federalregister.gov/api/v1"

    # Bedrock model for LLM validation
    MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"

    # Agencies to track for cybersecurity regulations
    # Note: CISA publishes through homeland-security-department, not its own slug
    TRACKED_AGENCIES = [
        "securities-and-exchange-commission",  # SEC - primary for disclosure rules
        "federal-trade-commission",  # FTC - privacy, consumer protection
        "homeland-security-department",  # DHS/CISA - critical infrastructure
        "department-of-commerce",  # Commerce/NIST - standards
        "federal-communications-commission",  # FCC - telecom/IoT security
        "department-of-justice",  # DOJ - enforcement
        "office-of-the-comptroller-of-the-currency",  # OCC - banking
        "federal-reserve-system",  # Fed - financial services
    ]

    # Agency slug to display name mapping
    AGENCY_NAMES = {
        "securities-and-exchange-commission": "SEC",
        "federal-trade-commission": "FTC",
        "homeland-security-department": "DHS/CISA",
        "department-of-commerce": "Commerce/NIST",
        "federal-communications-commission": "FCC",
        "department-of-justice": "DOJ",
        "office-of-the-comptroller-of-the-currency": "OCC",
        "federal-reserve-system": "Federal Reserve",
    }

    # Keywords for cybersecurity-related regulations
    CYBER_KEYWORDS = [
        "cybersecurity",
        "cyber security",
        "data breach",
        "data protection",
        "privacy",
        "disclosure",
        "incident reporting",
        "ransomware",
        "information security",
        "critical infrastructure",
        "encryption",
        "authentication",
        "vulnerability",
        "network security",
        "cloud security",
        "zero trust",
        "supply chain security",
    ]

    def __init__(self):
        """Initialize the regulatory service with Bedrock and Neo4j."""
        self.db = db_service

        # Initialize Bedrock client for LLM validation
        self.region = os.environ.get("AWS_REGION", "us-west-2")
        config = Config(
            region_name=self.region, retries={"max_attempts": 3, "mode": "adaptive"}
        )
        self.bedrock = boto3.client("bedrock-runtime", config=config)

        # Lazy-loaded Neo4j service
        self._neo4j = None

        # Async ingestion state tracking
        # In production with multiple workers, use Redis/DB instead
        self._ingestion_status = {
            "status": "idle",  # idle, running, completed, error
            "progress": 0,
            "message": "",
            "stats": {},
            "error": None,
            "start_time": None,
        }
        self._ingestion_lock = threading.Lock()

    @property
    def neo4j(self):
        """Lazy load Neo4j service."""
        if self._neo4j is None:
            try:
                from services.neo4j_service import get_neo4j_service

                self._neo4j = get_neo4j_service()
            except Exception as e:
                logger.warning(f"Neo4j service not available: {e}")
        return self._neo4j

    def get_ingestion_status(self) -> Dict[str, Any]:
        """
        Returns the current status of the background ingestion job.

        Returns:
            Dict with status, progress, message, stats, and error fields
        """
        with self._ingestion_lock:
            return dict(self._ingestion_status)

    def start_ingestion_async(
        self, start_date: str = None, end_date: str = None, clear_existing: bool = False
    ) -> Dict[str, Any]:
        """
        Starts the ingestion process in a background thread.

        Args:
            start_date: Start date for fetching regulations (YYYY-MM-DD)
            end_date: End date for fetching regulations (YYYY-MM-DD)
            clear_existing: If True, clear existing regulations before ingesting

        Returns:
            Dict with status indicating if ingestion was started
        """
        with self._ingestion_lock:
            if self._ingestion_status["status"] == "running":
                return {
                    "success": False,
                    "message": "Ingestion already in progress",
                    "status": self._ingestion_status,
                }

            # Reset status for new ingestion
            self._ingestion_status = {
                "status": "running",
                "progress": 0,
                "message": "Starting ingestion...",
                "stats": {},
                "error": None,
                "start_time": datetime.now().isoformat(),
            }

        # Start background thread
        thread = threading.Thread(
            target=self._ingestion_worker,
            args=(start_date, end_date, clear_existing),
            daemon=True,
        )
        thread.start()

        return {
            "success": True,
            "message": "Ingestion started in background",
            "status": self._ingestion_status,
        }

    def _ingestion_worker(
        self, start_date: str = None, end_date: str = None, clear_existing: bool = False
    ):
        """
        Background worker that performs the actual ingestion.

        Args:
            start_date: Start date for fetching regulations
            end_date: End date for fetching regulations
            clear_existing: If True, clear existing regulations first
        """
        try:
            # Clear existing if requested
            if clear_existing:
                with self._ingestion_lock:
                    self._ingestion_status["message"] = "Clearing existing regulations..."
                    self._ingestion_status["progress"] = 5
                self.db.clear_regulations()

            # Fetch articles
            with self._ingestion_lock:
                self._ingestion_status["message"] = "Fetching articles from Federal Register..."
                self._ingestion_status["progress"] = 10

            articles = self.fetch_federal_register_articles(start_date, end_date)

            with self._ingestion_lock:
                self._ingestion_status["message"] = f"Processing {len(articles)} articles..."
                self._ingestion_status["progress"] = 20

            # Get companies
            companies = self.db.get_all_companies()
            if not companies:
                with self._ingestion_lock:
                    self._ingestion_status["status"] = "error"
                    self._ingestion_status["error"] = "No companies found in database"
                    self._ingestion_status["message"] = "Failed: No companies found"
                return

            # Process articles
            regulations_created = 0
            regulations_skipped = 0
            alerts_created = 0
            graph_synced = 0

            total_articles = len(articles)
            for idx, article in enumerate(articles):
                # Update progress (20-90% range for processing)
                progress = 20 + int((idx / max(total_articles, 1)) * 70)
                with self._ingestion_lock:
                    self._ingestion_status["progress"] = progress
                    self._ingestion_status["message"] = f"Processing article {idx + 1}/{total_articles}: {article.get('title', '')[:50]}..."

                # LLM validation
                llm_validation = self._validate_with_llm(article)
                if not llm_validation["is_relevant"]:
                    regulations_skipped += 1
                    continue

                # Extract agency name
                agencies = article.get("agencies", [])
                agency_slug = agencies[0].get("slug", "") if agencies else "unknown"
                agency_name = self.AGENCY_NAMES.get(agency_slug, agency_slug.upper())

                severity = self._determine_severity(article)
                keywords = self._extract_keywords(article)

                # Create regulation
                regulation = self.db.create_regulation(
                    title=article.get("title", "Untitled"),
                    agency=agency_name,
                    external_id=article.get("document_number"),
                    summary=article.get("abstract"),
                    effective_date=article.get("effective_on"),
                    publication_date=article.get("publication_date"),
                    source_url=article.get("html_url"),
                    severity=severity,
                    keywords=keywords,
                    sectors_affected=["Cybersecurity", "Technology"],
                )

                if regulation:
                    regulations_created += 1
                    impacted_companies = []

                    # Generate alerts
                    for company in companies:
                        relevance = self._calculate_relevance_score(article, company)
                        if relevance["score"] >= 0.3:
                            impact_level = self._determine_impact_level(relevance["score"], severity)
                            alert = self.db.create_regulatory_alert(
                                regulation_id=regulation["id"],
                                company_id=company["id"],
                                relevance_score=relevance["score"],
                                impact_level=impact_level,
                                matched_keywords=relevance["matched_keywords"],
                            )
                            if alert:
                                alerts_created += 1
                                impacted_companies.append({
                                    "ticker": company.get("ticker"),
                                    "relevance_score": relevance["score"],
                                    "impact_level": impact_level,
                                })

                    # Sync to Neo4j
                    if impacted_companies:
                        sync_result = self._sync_to_knowledge_graph(regulation, impacted_companies)
                        if sync_result.get("nodes_created", 0) > 0:
                            graph_synced += 1

            # Complete
            with self._ingestion_lock:
                self._ingestion_status["status"] = "completed"
                self._ingestion_status["progress"] = 100
                self._ingestion_status["message"] = "Ingestion completed successfully"
                self._ingestion_status["stats"] = {
                    "regulations_created": regulations_created,
                    "regulations_skipped": regulations_skipped,
                    "alerts_created": alerts_created,
                    "articles_processed": total_articles,
                    "companies_checked": len(companies),
                    "graph_nodes_synced": graph_synced,
                }

            logger.info(f"Async ingestion completed: {regulations_created} regulations, {alerts_created} alerts")

        except Exception as e:
            logger.error(f"Async ingestion failed: {e}")
            with self._ingestion_lock:
                self._ingestion_status["status"] = "error"
                self._ingestion_status["error"] = str(e)
                self._ingestion_status["message"] = f"Failed: {str(e)}"

    def fetch_federal_register_articles(
        self,
        start_date: str = None,
        end_date: str = None,
        search_term: str = "cybersecurity",
    ) -> List[Dict[str, Any]]:
        """
        Fetch articles from the Federal Register API

        Args:
            start_date: Start date in YYYY-MM-DD format (default: 90 days ago)
            end_date: End date in YYYY-MM-DD format (default: today)
            search_term: Search term to filter articles

        Returns:
            List of article dicts from Federal Register
        """
        if not start_date:
            # Use 365 days for comprehensive coverage (async handles timeout)
            start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")

        all_articles = []

        # Search ALL keywords for comprehensive coverage (async handles timeout)
        search_terms = (
            [search_term] if search_term != "cybersecurity" else self.CYBER_KEYWORDS
        )

        for term in search_terms:
            try:
                url = f"{self.FEDERAL_REGISTER_BASE_URL}/documents.json"
                params = {
                    "conditions[term]": term,
                    "conditions[publication_date][gte]": start_date,
                    "conditions[publication_date][lte]": end_date,
                    "per_page": 100,
                    "fields[]": [
                        "document_number",
                        "title",
                        "agencies",
                        "abstract",
                        "publication_date",
                        "effective_on",
                        "html_url",
                        "type",
                        "action",
                    ],
                }

                response = requests.get(url, params=params, timeout=30)
                response.raise_for_status()

                data = response.json()
                articles = data.get("results", [])

                # Filter to tracked agencies and deduplicate
                for article in articles:
                    article_agencies = [
                        a.get("slug", "") for a in article.get("agencies", [])
                    ]
                    if any(
                        agency in self.TRACKED_AGENCIES for agency in article_agencies
                    ):
                        # Check if we already have this article
                        doc_num = article.get("document_number")
                        if not any(
                            a.get("document_number") == doc_num for a in all_articles
                        ):
                            all_articles.append(article)

                print(f"  Fetched {len(articles)} articles for term '{term}'")

            except requests.RequestException as e:
                print(f"  Error fetching Federal Register for '{term}': {e}")
                continue

        print(f"Total unique articles from Federal Register: {len(all_articles)}")
        return all_articles

    def ingest_regulations(
        self, start_date: str = None, end_date: str = None
    ) -> Dict[str, Any]:
        """
        Ingest regulations from Federal Register and create alerts for tracked companies.

        Uses LLM validation to filter out false positives (e.g., auto dealer regulations
        that match on keywords but aren't relevant to enterprise SaaS security).

        Args:
            start_date: Start date for fetching regulations
            end_date: End date for fetching regulations

        Returns:
            Dict with ingestion statistics
        """
        print("\n=== Starting Regulatory Ingestion ===")

        # Fetch articles from Federal Register
        articles = self.fetch_federal_register_articles(start_date, end_date)

        regulations_created = 0
        regulations_skipped = 0
        alerts_created = 0
        graph_synced = 0

        # Get all tracked companies
        companies = self.db.get_all_companies()
        if not companies:
            print("No companies found in database")
            return {
                "regulations_created": 0,
                "alerts_created": 0,
                "error": "No companies",
            }

        for article in articles:
            # LLM validation: Check if regulation is truly relevant to enterprise SaaS security
            llm_validation = self._validate_with_llm(article)
            if not llm_validation["is_relevant"]:
                print(
                    f"  Skipping irrelevant regulation: {article.get('title', '')[:60]}..."
                )
                print(f"    Reason: {llm_validation['reason']}")
                regulations_skipped += 1
                continue

            # Extract agency name
            agencies = article.get("agencies", [])
            agency_slug = agencies[0].get("slug", "") if agencies else "unknown"
            agency_name = self.AGENCY_NAMES.get(agency_slug, agency_slug.upper())

            # Determine severity based on document type and content
            severity = self._determine_severity(article)

            # Extract keywords from title and abstract
            keywords = self._extract_keywords(article)

            # Create regulation record
            regulation = self.db.create_regulation(
                title=article.get("title", "Untitled"),
                agency=agency_name,
                external_id=article.get("document_number"),
                summary=article.get("abstract"),
                effective_date=article.get("effective_on"),
                publication_date=article.get("publication_date"),
                source_url=article.get("html_url"),
                severity=severity,
                keywords=keywords,
                sectors_affected=["Cybersecurity", "Technology"],
            )

            if regulation:
                regulations_created += 1

                # Track companies with alerts for Neo4j sync
                impacted_companies = []

                # Generate alerts for relevant companies
                for company in companies:
                    relevance = self._calculate_relevance_score(article, company)

                    if relevance["score"] >= 0.3:  # Threshold for creating an alert
                        impact_level = self._determine_impact_level(
                            relevance["score"], severity
                        )

                        alert = self.db.create_regulatory_alert(
                            regulation_id=regulation["id"],
                            company_id=company["id"],
                            relevance_score=relevance["score"],
                            impact_level=impact_level,
                            matched_keywords=relevance["matched_keywords"],
                        )

                        if alert:
                            alerts_created += 1
                            # Track for Neo4j sync
                            impacted_companies.append(
                                {
                                    "ticker": company.get("ticker"),
                                    "relevance_score": relevance["score"],
                                    "impact_level": impact_level,
                                }
                            )

                # Sync regulation to Neo4j knowledge graph
                if impacted_companies:
                    sync_result = self._sync_to_knowledge_graph(
                        regulation, impacted_companies
                    )
                    if sync_result.get("nodes_created", 0) > 0:
                        graph_synced += 1

        result = {
            "regulations_created": regulations_created,
            "regulations_skipped": regulations_skipped,
            "alerts_created": alerts_created,
            "articles_processed": len(articles),
            "companies_checked": len(companies),
            "graph_nodes_synced": graph_synced,
        }

        print(f"\n=== Ingestion Complete ===")
        print(f"  Regulations created: {regulations_created}")
        print(f"  Regulations skipped (LLM filtered): {regulations_skipped}")
        print(f"  Alerts created: {alerts_created}")
        print(f"  Graph nodes synced: {graph_synced}")

        return result

    def _determine_severity(self, article: Dict) -> str:
        """
        Determine regulation severity based on document type and content

        Args:
            article: Federal Register article dict

        Returns:
            Severity level: CRITICAL, HIGH, MEDIUM, or INFO
        """
        title = (article.get("title") or "").lower()
        abstract = (article.get("abstract") or "").lower()
        doc_type = (article.get("type") or "").lower()
        text = f"{title} {abstract}"

        # Critical indicators
        critical_terms = [
            "final rule",
            "mandatory",
            "immediate",
            "enforcement action",
            "penalty",
        ]
        if any(term in text for term in critical_terms) or doc_type == "rule":
            return "CRITICAL"

        # High indicators
        high_terms = [
            "proposed rule",
            "requirement",
            "compliance",
            "deadline",
            "effective date",
        ]
        if any(term in text for term in high_terms):
            return "HIGH"

        # Medium indicators
        medium_terms = ["guidance", "advisory", "recommendation", "notice"]
        if any(term in text for term in medium_terms) or doc_type == "proposed rule":
            return "MEDIUM"

        return "INFO"

    def _extract_keywords(self, article: Dict) -> List[str]:
        """
        Extract relevant keywords from article

        Args:
            article: Federal Register article dict

        Returns:
            List of matched keywords
        """
        title = (article.get("title") or "").lower()
        abstract = (article.get("abstract") or "").lower()
        text = f"{title} {abstract}"

        matched = []
        for keyword in self.CYBER_KEYWORDS:
            if keyword.lower() in text:
                matched.append(keyword)

        return matched

    def _validate_with_llm(self, article: Dict) -> Dict[str, Any]:
        """
        Use Bedrock LLM to validate if a regulation is truly relevant to
        enterprise SaaS security companies. Reduces false positives from
        keyword-only matching.

        Args:
            article: Federal Register article dict

        Returns:
            Dict with 'is_relevant' (bool), 'reason' (str), and 'confidence' (float)
        """
        title = article.get("title") or "Untitled"
        abstract = article.get("abstract") or "No abstract available"
        agency = article.get("agencies", [{}])[0].get("name", "Unknown Agency")

        prompt = f"""Analyze this federal regulation and determine if it is DIRECTLY relevant to cybersecurity companies across all domains.

REGULATION:
Title: {title}
Agency: {agency}
Abstract: {abstract}

QUESTION: Is this regulation directly relevant to cybersecurity companies?

CYBERSECURITY COMPANY DOMAINS (if relevant to ANY of these, answer YES):
- Endpoint security (antivirus, EDR, XDR)
- Network security (firewalls, SASE, zero trust)
- Cloud security (CSPM, CWPP, container security)
- Identity and access management (IAM, PAM, SSO)
- Security operations (SIEM, SOAR, threat intelligence)
- Application security (DAST, SAST, API security)
- Data security (DLP, encryption, backup)
- Governance, risk, and compliance (GRC)
- Managed security services (MSSP, MDR)
- IoT/OT security
- Email and messaging security

Consider these factors:
1. Does it address cybersecurity, data protection, privacy, or information security?
2. Does it apply to technology companies, software providers, or IT services?
3. Would cybersecurity companies need to comply with or help customers comply?
4. Does it create market opportunities for security products/services?

IRRELEVANT examples (answer NO):
- Auto dealer regulations
- Physical product safety rules
- Agricultural standards
- Construction codes
- Industry-specific rules unrelated to technology or data

RELEVANT examples (answer YES):
- SEC cybersecurity disclosure rules
- FTC data protection requirements
- CISA incident reporting mandates
- Privacy regulations (HIPAA, CCPA impacts)
- Critical infrastructure protection rules
- Financial services security requirements

Respond in this exact format:
RELEVANT: YES or NO
CONFIDENCE: HIGH, MEDIUM, or LOW
REASON: One sentence explanation"""

        try:
            response = self.bedrock.converse(
                modelId=self.MODEL_ID,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": 256, "temperature": 0.1},
            )
            response_text = response["output"]["message"]["content"][0]["text"]

            # Parse the structured response
            is_relevant = "RELEVANT: YES" in response_text.upper()
            confidence = 0.5
            if "CONFIDENCE: HIGH" in response_text.upper():
                confidence = 0.9
            elif "CONFIDENCE: MEDIUM" in response_text.upper():
                confidence = 0.7
            elif "CONFIDENCE: LOW" in response_text.upper():
                confidence = 0.4

            # Extract reason
            reason = "LLM validation performed"
            if "REASON:" in response_text.upper():
                reason_start = response_text.upper().find("REASON:") + 7
                reason = response_text[reason_start:].strip().split("\n")[0]

            logger.info(
                f"LLM validation for '{title[:50]}...': relevant={is_relevant}, confidence={confidence}"
            )

            return {
                "is_relevant": is_relevant,
                "confidence": confidence,
                "reason": reason,
            }

        except Exception as e:
            logger.error(f"LLM validation failed: {e}")
            # On error, default to allowing the regulation through (fail open)
            return {
                "is_relevant": True,
                "confidence": 0.5,
                "reason": f"LLM validation failed: {str(e)}",
            }

    def _sync_to_knowledge_graph(self, regulation: Dict, companies: List[Dict]) -> Dict:
        """
        Sync regulation to Neo4j knowledge graph, creating Regulation nodes
        and IMPACTS relationships to relevant organizations.

        Args:
            regulation: Regulation dict from database
            companies: List of company dicts that are impacted

        Returns:
            Dict with sync statistics
        """
        if not self.neo4j:
            logger.warning("Neo4j not available, skipping graph sync")
            return {
                "nodes_created": 0,
                "relationships_created": 0,
                "error": "Neo4j unavailable",
            }

        try:
            # Determine timeline status based on effective date
            timeline_status = "unknown"
            effective_date = regulation.get("effective_date")
            if effective_date:
                try:
                    eff_date = datetime.strptime(effective_date, "%Y-%m-%d")
                    now = datetime.now()
                    if eff_date > now:
                        timeline_status = "upcoming"
                    elif (now - eff_date).days <= 90:
                        timeline_status = "recently_effective"
                    else:
                        timeline_status = "effective"
                except ValueError:
                    timeline_status = "unknown"

            # Create or update Regulation node with timeline and source attributes
            reg_query = """
                MERGE (r:Regulation {external_id: $external_id})
                SET r.name = $name,
                    r.agency = $agency,
                    r.severity = $severity,
                    r.summary = $summary,
                    r.effective_date = $effective_date,
                    r.publication_date = $publication_date,
                    r.timeline_status = $timeline_status,
                    r.source = $source,
                    r.source_url = $source_url,
                    r.keywords = $keywords,
                    r.sectors_affected = $sectors_affected,
                    r.updated_at = datetime()
                RETURN r
            """
            self.neo4j.execute_write(
                reg_query,
                {
                    "external_id": regulation.get("external_id")
                    or str(regulation["id"]),
                    "name": regulation.get("title", "Unknown Regulation"),
                    "agency": regulation.get("agency", "Unknown"),
                    "severity": regulation.get("severity", "MEDIUM"),
                    "summary": regulation.get("summary") or "",
                    "effective_date": regulation.get("effective_date"),
                    "publication_date": regulation.get("publication_date"),
                    "timeline_status": timeline_status,
                    "source": "Federal Register",
                    "source_url": regulation.get("source_url"),
                    "keywords": regulation.get("keywords", []),
                    "sectors_affected": regulation.get("sectors_affected", []),
                },
            )

            # Create IMPACTS relationships to affected organizations
            relationships_created = 0
            for company in companies:
                ticker = company.get("ticker")
                if not ticker:
                    continue

                rel_query = """
                    MATCH (r:Regulation {external_id: $external_id})
                    MATCH (o:Organization {ticker: $ticker})
                    MERGE (r)-[i:IMPACTS]->(o)
                    SET i.relevance_score = $relevance_score,
                        i.impact_level = $impact_level,
                        i.created_at = datetime()
                    RETURN i
                """
                result = self.neo4j.execute_write(
                    rel_query,
                    {
                        "external_id": regulation.get("external_id")
                        or str(regulation["id"]),
                        "ticker": ticker,
                        "relevance_score": company.get("relevance_score", 0.5),
                        "impact_level": company.get("impact_level", "MEDIUM"),
                    },
                )
                if result.get("relationships_created", 0) > 0:
                    relationships_created += 1

            logger.info(
                f"Synced regulation '{regulation.get('title', '')[:40]}...' to graph with {relationships_created} relationships"
            )

            return {
                "nodes_created": 1,
                "relationships_created": relationships_created,
            }

        except Exception as e:
            logger.error(f"Failed to sync regulation to graph: {e}")
            return {"nodes_created": 0, "relationships_created": 0, "error": str(e)}

    def _calculate_relevance_score(
        self, article: Dict, company: Dict
    ) -> Dict[str, Any]:
        """
        Calculate TF-IDF style relevance score between regulation and company

        Scoring breakdown:
        - Sector match (40%): Company sector vs regulation sectors_affected
        - Keyword overlap (40%): Company description vs regulation keywords
        - Base cybersecurity relevance (20%): All cyber companies have some relevance

        Args:
            article: Federal Register article dict
            company: Company dict from database

        Returns:
            Dict with score (0-1) and matched_keywords
        """
        title = (article.get("title") or "").lower()
        abstract = (article.get("abstract") or "").lower()
        reg_text = f"{title} {abstract}"

        company_name = (company.get("company_name") or "").lower()
        company_sector = (company.get("sector") or "").lower()
        company_desc = (company.get("description") or "").lower()
        company_text = f"{company_name} {company_sector} {company_desc}"

        # Sector match score (40%)
        sector_score = 0.0
        if "cybersecurity" in company_sector or "security" in company_sector:
            sector_score = 0.4
        elif "technology" in company_sector:
            sector_score = 0.2

        # Keyword overlap score (40%)
        matched_keywords = []
        keyword_score = 0.0

        # Check which cyber keywords appear in both regulation and company
        for keyword in self.CYBER_KEYWORDS:
            if keyword.lower() in reg_text and keyword.lower() in company_text:
                matched_keywords.append(keyword)

        if matched_keywords:
            # More matches = higher score, with diminishing returns
            keyword_score = min(0.4, 0.1 * len(matched_keywords))

        # Check for company name mentioned in regulation (strong signal)
        if company_name in reg_text or company.get("ticker", "").lower() in reg_text:
            keyword_score = 0.4
            matched_keywords.append(company.get("ticker", company_name))

        # Base cybersecurity relevance (20%)
        # All cybersecurity companies have baseline relevance to cyber regulations
        base_score = 0.2 if "cybersecurity" in company_sector.lower() else 0.1

        total_score = sector_score + keyword_score + base_score

        return {
            "score": min(1.0, total_score),
            "matched_keywords": matched_keywords,
            "breakdown": {
                "sector": sector_score,
                "keywords": keyword_score,
                "base": base_score,
            },
        }

    def _determine_impact_level(self, relevance_score: float, severity: str) -> str:
        """
        Determine impact level based on relevance score and regulation severity

        Args:
            relevance_score: Calculated relevance score (0-1)
            severity: Regulation severity

        Returns:
            Impact level: CRITICAL, HIGH, MEDIUM, or LOW
        """
        # Combine relevance and severity
        severity_weight = {"CRITICAL": 1.0, "HIGH": 0.75, "MEDIUM": 0.5, "INFO": 0.25}

        combined = relevance_score * severity_weight.get(severity, 0.5)

        if combined >= 0.6:
            return "CRITICAL"
        elif combined >= 0.4:
            return "HIGH"
        elif combined >= 0.2:
            return "MEDIUM"
        return "LOW"

    def get_alerts(
        self,
        ticker: str = None,
        status: str = None,
        impact_level: str = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Get regulatory alerts with optional filters

        Args:
            ticker: Filter by company ticker
            status: Filter by status
            impact_level: Filter by impact level
            limit: Maximum results

        Returns:
            List of alert dicts
        """
        return self.db.get_regulatory_alerts(ticker, status, impact_level, limit)

    def get_dashboard_summary(self) -> Dict[str, Any]:
        """
        Get regulatory dashboard summary statistics

        Returns:
            Dict with dashboard metrics
        """
        return self.db.get_regulatory_dashboard_summary()

    def acknowledge_alert(
        self, alert_id: int, username: str
    ) -> Optional[Dict[str, Any]]:
        """
        Acknowledge a regulatory alert

        Args:
            alert_id: ID of the alert
            username: Username acknowledging the alert

        Returns:
            Updated alert dict or None
        """
        return self.db.update_alert_status(alert_id, "ACKNOWLEDGED", username)

    def update_alert_status(
        self, alert_id: int, status: str
    ) -> Optional[Dict[str, Any]]:
        """
        Update alert status

        Args:
            alert_id: ID of the alert
            status: New status

        Returns:
            Updated alert dict or None
        """
        return self.db.update_alert_status(alert_id, status)

    def get_regulations(
        self, agency: str = None, severity: str = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get regulations with optional filters

        Args:
            agency: Filter by agency
            severity: Filter by severity
            limit: Maximum results

        Returns:
            List of regulation dicts
        """
        return self.db.get_all_regulations(agency, severity, limit)

    def get_regulation(self, regulation_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a single regulation by ID

        Args:
            regulation_id: ID of the regulation

        Returns:
            Regulation dict or None
        """
        return self.db.get_regulation(regulation_id)

    def create_manual_regulation(
        self,
        title: str,
        agency: str,
        summary: str = None,
        effective_date: str = None,
        source_url: str = None,
        severity: str = "MEDIUM",
        keywords: List[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Manually create a regulation entry

        Args:
            title: Regulation title
            agency: Regulatory agency
            summary: Regulation summary
            effective_date: Effective date
            source_url: Source URL
            severity: Severity level
            keywords: Relevant keywords

        Returns:
            Created regulation dict or None
        """
        return self.db.create_regulation(
            title=title,
            agency=agency,
            summary=summary,
            effective_date=effective_date,
            publication_date=datetime.now().strftime("%Y-%m-%d"),
            source_url=source_url,
            severity=severity,
            keywords=keywords,
            sectors_affected=["Cybersecurity"],
        )


# Global regulatory service instance
regulatory_service = RegulatoryService()
