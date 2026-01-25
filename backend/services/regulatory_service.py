"""
Regulatory Service
Provides regulatory tracking and compliance monitoring for CyberRisk Dashboard

Integrates with Federal Register API to fetch cybersecurity-related regulations
and calculate relevance scores for tracked companies using TF-IDF style scoring.
"""

import os
import math
import requests
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

from services.database_service import db_service


class RegulatoryService:
    """
    Service for tracking regulatory changes and generating company alerts
    """

    # Federal Register API configuration
    FEDERAL_REGISTER_BASE_URL = "https://www.federalregister.gov/api/v1"

    # Agencies to track for cybersecurity regulations
    TRACKED_AGENCIES = [
        "securities-and-exchange-commission",  # SEC
        "cybersecurity-and-infrastructure-security-agency",  # CISA
        "federal-trade-commission",  # FTC
        "national-institute-of-standards-and-technology",  # NIST
        "department-of-justice",  # DOJ
        "department-of-commerce",  # Commerce
        "office-of-the-comptroller-of-the-currency",  # OCC (banking)
    ]

    # Agency slug to display name mapping
    AGENCY_NAMES = {
        "securities-and-exchange-commission": "SEC",
        "cybersecurity-and-infrastructure-security-agency": "CISA",
        "federal-trade-commission": "FTC",
        "national-institute-of-standards-and-technology": "NIST",
        "department-of-justice": "DOJ",
        "department-of-commerce": "Commerce",
        "office-of-the-comptroller-of-the-currency": "OCC",
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
        """Initialize the regulatory service"""
        self.db = db_service

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
            start_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")

        all_articles = []

        # Search for each keyword to maximize coverage
        search_terms = (
            [search_term] if search_term != "cybersecurity" else self.CYBER_KEYWORDS[:5]
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
        Ingest regulations from Federal Register and create alerts for tracked companies

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
        alerts_created = 0

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

        result = {
            "regulations_created": regulations_created,
            "alerts_created": alerts_created,
            "articles_processed": len(articles),
            "companies_checked": len(companies),
        }

        print(f"\n=== Ingestion Complete ===")
        print(f"  Regulations created: {regulations_created}")
        print(f"  Alerts created: {alerts_created}")

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
