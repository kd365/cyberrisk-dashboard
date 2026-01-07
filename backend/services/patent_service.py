"""
Patent Service
Fetches patent data from USPTO Open Data Portal API and integrates with knowledge graph
"""

import os
import json
import requests
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from functools import lru_cache


class PatentService:
    """
    Service for fetching and managing patent data from USPTO Open Data Portal

    API Documentation: https://api.uspto.gov/swagger-ui/index.html
    Rate Limits:
      - Patent File Wrapper Documents: 1,200,000/week
      - Meta Data Retrievals: 5,000,000/week
    """

    # USPTO API base URL (the correct endpoint)
    BASE_URL = "https://api.uspto.gov/api/v1"

    # Patent applications search endpoint
    SEARCH_URL = "https://api.uspto.gov/api/v1/patent/applications/search"

    def __init__(self):
        """Initialize the patent service"""
        self.api_key = os.environ.get('USPTO_API_KEY', '')
        self.neo4j_service = None
        self.db_service = None

        if not self.api_key:
            print("⚠️  PatentService: USPTO_API_KEY not configured")
        else:
            print("✅ PatentService: Initialized with API key")

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with API key"""
        headers = {
            'Accept': 'application/json'
        }
        if self.api_key:
            headers['X-API-KEY'] = self.api_key
        return headers

    def search_patents_by_assignee(
        self,
        assignee_name: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Search for patents by assignee (company/organization) name

        Args:
            assignee_name: Name of the company/organization
            start_date: Start date in YYYYMMDD format (default: 1 year ago)
            end_date: End date in YYYYMMDD format (default: today)
            limit: Maximum number of results

        Returns:
            List of patent records
        """
        if not self.api_key:
            print("⚠️  USPTO API key not configured")
            return []

        try:
            # Search using the USPTO patent applications search API
            # The API uses simple query string search
            params = {
                'q': assignee_name,
                'offset': 0,
                'limit': min(limit, 100)  # API max is typically 100 per request
            }

            response = requests.get(
                self.SEARCH_URL,
                headers=self._get_headers(),
                params=params,
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                # Response structure: {"count": N, "patentFileWrapperDataBag": [...]}
                patents = data.get('patentFileWrapperDataBag', [])
                total_count = data.get('count', 0)
                print(f"✅ Found {len(patents)} patents (total: {total_count}) for {assignee_name}")
                return patents
            else:
                print(f"⚠️  USPTO API returned status {response.status_code}: {response.text[:200]}")
                return []

        except requests.exceptions.RequestException as e:
            print(f"⚠️  Error fetching patents for {assignee_name}: {e}")
            return []

    def search_patents_by_inventor(
        self,
        inventor_name: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Search for patents by inventor name

        Args:
            inventor_name: Name of the inventor (e.g., "John Smith")
            start_date: Start date in YYYYMMDD format
            end_date: End date in YYYYMMDD format
            limit: Maximum number of results

        Returns:
            List of patent records
        """
        if not self.api_key:
            return []

        try:
            # Search by inventor name using the applications search API
            params = {
                'q': inventor_name,
                'offset': 0,
                'limit': min(limit, 100)
            }

            response = requests.get(
                self.SEARCH_URL,
                headers=self._get_headers(),
                params=params,
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                patents = data.get('patentFileWrapperDataBag', [])
                total_count = data.get('count', 0)
                print(f"✅ Found {len(patents)} patents (total: {total_count}) for inventor {inventor_name}")
                return patents
            else:
                print(f"⚠️  USPTO API returned status {response.status_code}")
                return []

        except requests.exceptions.RequestException as e:
            print(f"⚠️  Error fetching patents for inventor {inventor_name}: {e}")
            return []

    def get_patent_details(self, patent_number: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a specific patent

        Args:
            patent_number: USPTO patent number (e.g., "US11234567B2")

        Returns:
            Patent details or None if not found
        """
        if not self.api_key:
            return None

        try:
            # Clean patent number
            clean_number = patent_number.replace('US', '').replace(',', '')

            response = requests.get(
                f"{self.BASE_URL}/patent/grants/{clean_number}",
                headers=self._get_headers(),
                timeout=30
            )

            if response.status_code == 200:
                return response.json()
            else:
                print(f"⚠️  Patent {patent_number} not found")
                return None

        except requests.exceptions.RequestException as e:
            print(f"⚠️  Error fetching patent {patent_number}: {e}")
            return None

    def transform_patent_for_neo4j(self, patent: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform USPTO patent data into Neo4j node format

        Args:
            patent: Raw patent data from USPTO API (patentFileWrapperDataBag item)

        Returns:
            Transformed patent data for Neo4j
        """
        # Extract application metadata
        app_meta = patent.get('applicationMetaData', {})

        # Extract key fields from new API structure
        application_number = patent.get('applicationNumberText', '')
        publication_number = app_meta.get('earliestPublicationNumber', '')
        patent_number = publication_number or application_number

        title = app_meta.get('inventionTitle', 'Unknown')

        # Parse dates
        filing_date = app_meta.get('filingDate', '')
        publication_date = app_meta.get('earliestPublicationDate', '')

        # Get assignees/applicants
        applicant_bag = app_meta.get('applicantBag', [])
        assignees = [a.get('applicantNameText', '') for a in applicant_bag if a.get('applicantNameText')]

        # Get inventors
        inventor_bag = app_meta.get('inventorBag', [])
        inventors = [i.get('inventorNameText', '') for i in inventor_bag if i.get('inventorNameText')]

        # Get classification codes
        cpc_codes = app_meta.get('cpcClassificationBag', [])

        # Build patent URL
        if publication_number:
            patent_url = f"https://patents.google.com/patent/{publication_number}"
        elif application_number:
            patent_url = f"https://assignment.uspto.gov/patent/index.html#/patent/search/resultAbstract?id={application_number}"
        else:
            patent_url = ''

        return {
            'patent_number': patent_number,
            'application_number': application_number,
            'title': title[:200] if title else '',
            'abstract': '',  # Abstract not in search results, would need separate API call
            'filing_date': filing_date,
            'publication_date': publication_date,
            'grant_date': publication_date,  # Use publication date as grant date
            'assignees': assignees,
            'inventors': inventors,
            'cpc_codes': cpc_codes[:10] if cpc_codes else [],
            'patent_url': patent_url,
            'status': app_meta.get('applicationStatusDescriptionText', ''),
            'source': 'USPTO'
        }

    def transform_patent_for_artifact(
        self,
        patent: Dict[str, Any],
        ticker: str
    ) -> Dict[str, Any]:
        """
        Transform USPTO patent data into artifact format for PostgreSQL

        Args:
            patent: Raw patent data from USPTO API
            ticker: Stock ticker of the associated company

        Returns:
            Artifact data for PostgreSQL
        """
        patent_data = self.transform_patent_for_neo4j(patent)

        return {
            'ticker': ticker,
            'artifact_type': 'Patent',
            'title': patent_data['title'],
            'description': patent_data.get('abstract', ''),
            'published_date': patent_data.get('publication_date') or patent_data.get('filing_date'),
            'external_url': patent_data['patent_url'],
            'metadata': {
                'patent_number': patent_data['patent_number'],
                'application_number': patent_data.get('application_number', ''),
                'filing_date': patent_data['filing_date'],
                'inventors': patent_data['inventors'],
                'cpc_codes': patent_data['cpc_codes'],
                'status': patent_data.get('status', '')
            }
        }

    def fetch_patents_for_organization(
        self,
        organization_name: str,
        ticker: Optional[str] = None,
        days_back: int = 365
    ) -> Dict[str, Any]:
        """
        Fetch all patents for an organization and prepare for storage

        Args:
            organization_name: Full name of the organization
            ticker: Optional stock ticker for artifact association
            days_back: Number of days to look back

        Returns:
            Dict with patents, neo4j_nodes, and artifacts
        """
        end_date = datetime.now().strftime('%Y%m%d')
        start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y%m%d')

        # Fetch patents from USPTO
        raw_patents = self.search_patents_by_assignee(
            organization_name,
            start_date=start_date,
            end_date=end_date,
            limit=100
        )

        # Transform for Neo4j and PostgreSQL
        neo4j_patents = []
        artifacts = []

        for patent in raw_patents:
            neo4j_data = self.transform_patent_for_neo4j(patent)
            neo4j_patents.append(neo4j_data)

            if ticker:
                artifact_data = self.transform_patent_for_artifact(patent, ticker)
                artifacts.append(artifact_data)

        return {
            'organization': organization_name,
            'ticker': ticker,
            'patent_count': len(raw_patents),
            'neo4j_patents': neo4j_patents,
            'artifacts': artifacts,
            'date_range': {
                'start': start_date,
                'end': end_date
            }
        }

    def create_patent_nodes_in_neo4j(
        self,
        patents: List[Dict[str, Any]],
        organization_name: str
    ) -> int:
        """
        Create Patent nodes in Neo4j and link to Organization

        Args:
            patents: List of transformed patent data
            organization_name: Name of the organization to link

        Returns:
            Number of patents created
        """
        if not self.neo4j_service:
            try:
                from services.neo4j_service import neo4j_service
                self.neo4j_service = neo4j_service
            except ImportError:
                print("⚠️  Neo4j service not available")
                return 0

        if not self.neo4j_service.connected:
            print("⚠️  Neo4j not connected")
            return 0

        created = 0

        for patent in patents:
            try:
                # Create Patent node
                query = """
                MERGE (p:Patent {patent_number: $patent_number})
                SET p.title = $title,
                    p.abstract = $abstract,
                    p.grant_date = $grant_date,
                    p.filing_date = $filing_date,
                    p.patent_url = $patent_url,
                    p.source = $source,
                    p.updated_at = datetime()

                WITH p

                // Link to Organization
                MATCH (o:Organization)
                WHERE toLower(o.name) CONTAINS toLower($org_name)
                   OR o.name = $org_name
                MERGE (o)-[:FILED]->(p)

                RETURN p.patent_number as patent_number
                """

                result = self.neo4j_service.run_query(query, {
                    'patent_number': patent['patent_number'],
                    'title': patent['title'],
                    'abstract': patent['abstract'],
                    'grant_date': patent['grant_date'],
                    'filing_date': patent['filing_date'],
                    'patent_url': patent['patent_url'],
                    'source': patent['source'],
                    'org_name': organization_name
                })

                if result:
                    created += 1

                # Link inventors
                for inventor_name in patent.get('inventors', []):
                    inventor_query = """
                    MATCH (p:Patent {patent_number: $patent_number})
                    MERGE (person:Person {name: $inventor_name})
                    MERGE (person)-[:INVENTED]->(p)
                    """
                    self.neo4j_service.run_query(inventor_query, {
                        'patent_number': patent['patent_number'],
                        'inventor_name': inventor_name
                    })

            except Exception as e:
                print(f"⚠️  Error creating patent node: {e}")
                continue

        print(f"✅ Created {created} patent nodes in Neo4j")
        return created

    def save_patents_as_artifacts(
        self,
        artifacts: List[Dict[str, Any]]
    ) -> int:
        """
        Save patents as artifacts in PostgreSQL

        Args:
            artifacts: List of artifact data

        Returns:
            Number of artifacts saved
        """
        if not self.db_service:
            try:
                from services.database_service import db_service
                self.db_service = db_service
            except ImportError:
                print("⚠️  Database service not available")
                return 0

        if not self.db_service.connected:
            print("⚠️  Database not connected")
            return 0

        saved = 0

        for artifact in artifacts:
            try:
                result = self.db_service.create_artifact(
                    ticker=artifact['ticker'],
                    artifact_type='Patent',
                    s3_key=artifact.get('external_url', ''),  # Use URL as reference
                    published_date=artifact.get('published_date')
                )

                if result:
                    saved += 1

            except Exception as e:
                print(f"⚠️  Error saving artifact: {e}")
                continue

        print(f"✅ Saved {saved} patent artifacts to PostgreSQL")
        return saved


# Global patent service instance
patent_service = PatentService()
