"""
Database Service
Provides CRUD operations for RDS PostgreSQL
"""

import os
import json
from typing import Optional, Dict, Any, List
from datetime import datetime

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor

    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False
    print("⚠️  psycopg2 not installed. Database operations unavailable.")


class DatabaseService:
    """
    Database service for CRUD operations on RDS PostgreSQL
    """

    def __init__(self):
        """Initialize database connection"""
        self.connection = None
        self.connected = False
        self._connect()

    def _connect(self):
        """Establish database connection"""
        if not PSYCOPG2_AVAILABLE:
            print("📦 DatabaseService: psycopg2 not available")
            return

        db_host = os.environ.get("DB_HOST")
        db_name = os.environ.get("DB_NAME", "cyberrisk")
        db_user = os.environ.get("DB_USER", "cyberrisk_admin")
        db_password = os.environ.get("DB_PASSWORD")

        if not db_host or not db_password:
            print("📦 DatabaseService: DB credentials not configured")
            return

        try:
            self.connection = psycopg2.connect(
                host=db_host,
                database=db_name,
                user=db_user,
                password=db_password,
                port=5432,
            )
            self.connected = True
            print(f"✅ DatabaseService: Connected to RDS at {db_host}")
            self._ensure_tables_exist()
        except Exception as e:
            print(f"⚠️  DatabaseService: Connection failed - {e}")
            self.connected = False

    def _ensure_tables_exist(self):
        """Create tables if they don't exist"""
        if not self.connected:
            return

        try:
            cursor = self.connection.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS companies (
                    id SERIAL PRIMARY KEY,
                    company_name VARCHAR(255) NOT NULL,
                    ticker VARCHAR(10) NOT NULL UNIQUE,
                    sector VARCHAR(100) DEFAULT 'Cybersecurity',
                    description TEXT,
                    exchange VARCHAR(50),
                    location VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_companies_ticker ON companies(ticker);

                -- Regulations table for regulatory tracking
                CREATE TABLE IF NOT EXISTS regulations (
                    id SERIAL PRIMARY KEY,
                    external_id VARCHAR(100) UNIQUE,
                    title VARCHAR(500) NOT NULL,
                    agency VARCHAR(50) NOT NULL,
                    summary TEXT,
                    effective_date DATE,
                    publication_date DATE,
                    source_url TEXT,
                    severity VARCHAR(20) DEFAULT 'MEDIUM',
                    keywords JSONB,
                    sectors_affected JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_regulations_agency ON regulations(agency);
                CREATE INDEX IF NOT EXISTS idx_regulations_severity ON regulations(severity);
                CREATE INDEX IF NOT EXISTS idx_regulations_effective_date ON regulations(effective_date);

                -- Regulatory alerts linking regulations to companies
                CREATE TABLE IF NOT EXISTS regulatory_alerts (
                    id SERIAL PRIMARY KEY,
                    regulation_id INT REFERENCES regulations(id) ON DELETE CASCADE,
                    company_id INT REFERENCES companies(id) ON DELETE CASCADE,
                    relevance_score FLOAT,
                    impact_level VARCHAR(20),
                    status VARCHAR(30) DEFAULT 'UNACKNOWLEDGED',
                    ai_impact_analysis TEXT,
                    matched_keywords JSONB,
                    acknowledged_by VARCHAR(255),
                    acknowledged_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(regulation_id, company_id)
                );
                CREATE INDEX IF NOT EXISTS idx_alerts_status ON regulatory_alerts(status);
                CREATE INDEX IF NOT EXISTS idx_alerts_impact ON regulatory_alerts(impact_level);

                -- Pre-extracted financials per SEC filing (populated at ingestion)
                CREATE TABLE IF NOT EXISTS filing_financials (
                    id SERIAL PRIMARY KEY,
                    ticker VARCHAR(10) NOT NULL,
                    s3_key VARCHAR(500) NOT NULL UNIQUE,
                    filing_type VARCHAR(20) NOT NULL,
                    filing_date DATE NOT NULL,
                    revenue BIGINT,
                    subscription_revenue BIGINT,
                    arr BIGINT,
                    net_income BIGINT,
                    operating_income BIGINT,
                    eps DECIMAL(10, 4),
                    raw_data JSONB,
                    extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_filing_financials_ticker_date
                    ON filing_financials(ticker, filing_date DESC);
            """
            )
            self.connection.commit()
            cursor.close()
        except Exception as e:
            print(f"⚠️  Error ensuring tables exist: {e}")

    def _get_connection(self):
        """Get or refresh connection"""
        if not self.connected:
            self._connect()
            return self.connection if self.connected else None

        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            return self.connection
        except:
            self._connect()
            return self.connection if self.connected else None

    # =========================================================================
    # COMPANY CRUD OPERATIONS
    # =========================================================================

    def create_company(
        self, company_name: str, ticker: str, sector: str = "Cybersecurity"
    ) -> Optional[Dict[str, Any]]:
        """
        Create a new company

        Args:
            company_name: Full company name (e.g., "CrowdStrike Holdings")
            ticker: Stock ticker symbol (e.g., "CRWD")
            sector: Industry sector (default: "Cybersecurity")

        Returns:
            Created company dict or None if failed
        """
        conn = self._get_connection()
        if not conn:
            return None

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                """
                INSERT INTO companies (company_name, ticker, sector)
                VALUES (%s, %s, %s)
                RETURNING id, company_name, ticker, sector, created_at
            """,
                (company_name, ticker.upper(), sector),
            )

            company = dict(cursor.fetchone())
            conn.commit()
            cursor.close()

            print(f"✅ Created company: {ticker} - {company_name}")
            return company

        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            print(f"⚠️  Company already exists: {ticker}")
            return None
        except Exception as e:
            conn.rollback()
            print(f"⚠️  Error creating company: {e}")
            return None

    def get_company(self, ticker: str) -> Optional[Dict[str, Any]]:
        """
        Get a company by ticker

        Args:
            ticker: Stock ticker symbol

        Returns:
            Company dict or None if not found
        """
        conn = self._get_connection()
        if not conn:
            return None

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                """
                SELECT id, company_name, ticker, sector, description, exchange, location, alternate_names, created_at
                FROM companies
                WHERE ticker = %s
            """,
                (ticker.upper(),),
            )

            row = cursor.fetchone()
            cursor.close()

            return dict(row) if row else None

        except Exception as e:
            print(f"⚠️  Error getting company: {e}")
            return None

    def get_all_companies(self) -> List[Dict[str, Any]]:
        """
        Get all companies

        Returns:
            List of company dicts
        """
        conn = self._get_connection()
        if not conn:
            return []

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                """
                SELECT id, company_name, ticker, sector, description, exchange, location, alternate_names, created_at
                FROM companies
                ORDER BY ticker
            """
            )

            rows = cursor.fetchall()
            cursor.close()

            return [dict(row) for row in rows]

        except Exception as e:
            print(f"⚠️  Error getting companies: {e}")
            return []

    def update_company(
        self, ticker: str, company_name: str = None, sector: str = None
    ) -> Optional[Dict[str, Any]]:
        """
        Update a company

        Args:
            ticker: Stock ticker symbol (used to identify the company)
            company_name: New company name (optional)
            sector: New sector (optional)

        Returns:
            Updated company dict or None if not found
        """
        conn = self._get_connection()
        if not conn:
            return None

        # Build dynamic update query
        updates = []
        params = []
        if company_name:
            updates.append("company_name = %s")
            params.append(company_name)
        if sector:
            updates.append("sector = %s")
            params.append(sector)

        if not updates:
            return self.get_company(ticker)

        # Add ticker as last param for WHERE clause
        params.append(ticker.upper())

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                f"""
                UPDATE companies
                SET {', '.join(updates)}
                WHERE ticker = %s
                RETURNING id, company_name, ticker, sector, description, exchange, location, created_at
            """,
                params,
            )

            row = cursor.fetchone()
            conn.commit()
            cursor.close()

            if row:
                print(f"✅ Updated company: {ticker}")
                return dict(row)
            return None

        except Exception as e:
            conn.rollback()
            print(f"⚠️  Error updating company: {e}")
            return None

    def delete_company(self, ticker: str) -> bool:
        """
        Delete a company

        Args:
            ticker: Stock ticker symbol

        Returns:
            True if deleted, False otherwise
        """
        conn = self._get_connection()
        if not conn:
            return False

        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                DELETE FROM companies
                WHERE ticker = %s
            """,
                (ticker.upper(),),
            )

            deleted = cursor.rowcount > 0
            conn.commit()
            cursor.close()

            if deleted:
                print(f"✅ Deleted company: {ticker}")
            else:
                print(f"⚠️  Company not found: {ticker}")

            return deleted

        except Exception as e:
            conn.rollback()
            print(f"⚠️  Error deleting company: {e}")
            return False

    def company_exists(self, ticker: str) -> bool:
        """Check if a company exists"""
        return self.get_company(ticker) is not None

    # =========================================================================
    # ARTIFACT CRUD OPERATIONS
    # =========================================================================

    def get_all_artifacts(self) -> List[Dict[str, Any]]:
        """
        Get all artifacts with company information

        Returns:
            List of artifact dicts matching the S3 CSV format
        """
        conn = self._get_connection()
        if not conn:
            return []

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                """
                SELECT
                    a.id,
                    c.ticker,
                    c.company_name as name,
                    a.artifact_type as type,
                    a.s3_key,
                    a.s3_key as document_link,
                    a.published_date as date,
                    a.created_at
                FROM artifacts a
                JOIN companies c ON a.company_id = c.id
                ORDER BY a.published_date DESC
            """
            )

            rows = cursor.fetchall()
            cursor.close()

            # Convert dates to string format for JSON serialization
            artifacts = []
            for row in rows:
                artifact = dict(row)
                if artifact.get("date"):
                    artifact["date"] = artifact["date"].isoformat()
                artifacts.append(artifact)

            return artifacts

        except Exception as e:
            print(f"⚠️  Error getting artifacts: {e}")
            return []

    def get_artifacts_by_ticker(self, ticker: str) -> List[Dict[str, Any]]:
        """
        Get all artifacts for a specific ticker

        Args:
            ticker: Stock ticker symbol

        Returns:
            List of artifact dicts
        """
        conn = self._get_connection()
        if not conn:
            return []

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                """
                SELECT
                    a.id,
                    c.ticker,
                    c.company_name as name,
                    a.artifact_type as type,
                    a.s3_key,
                    a.s3_key as document_link,
                    a.published_date as date,
                    a.created_at
                FROM artifacts a
                JOIN companies c ON a.company_id = c.id
                WHERE c.ticker = %s
                ORDER BY a.published_date DESC
            """,
                (ticker.upper(),),
            )

            rows = cursor.fetchall()
            cursor.close()

            # Convert dates to string format
            artifacts = []
            for row in rows:
                artifact = dict(row)
                if artifact.get("date"):
                    artifact["date"] = artifact["date"].isoformat()
                artifacts.append(artifact)

            return artifacts

        except Exception as e:
            print(f"⚠️  Error getting artifacts for {ticker}: {e}")
            return []

    def get_artifact_count_by_ticker(self, ticker: str) -> Dict[str, int]:
        """
        Get count of artifacts by type for a ticker

        Args:
            ticker: Stock ticker symbol

        Returns:
            Dict with type as key and count as value
        """
        conn = self._get_connection()
        if not conn:
            return {}

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                """
                SELECT
                    a.artifact_type as type,
                    COUNT(*) as count
                FROM artifacts a
                JOIN companies c ON a.company_id = c.id
                WHERE c.ticker = %s
                GROUP BY a.artifact_type
            """,
                (ticker.upper(),),
            )

            rows = cursor.fetchall()
            cursor.close()

            return {row["type"]: row["count"] for row in rows}

        except Exception as e:
            print(f"⚠️  Error getting artifact counts for {ticker}: {e}")
            return {}

    def create_artifact(
        self, ticker: str, artifact_type: str, s3_key: str, published_date: str = None
    ) -> Optional[Dict[str, Any]]:
        """
        Create a new artifact

        Args:
            ticker: Stock ticker of the company
            artifact_type: Type of artifact (10-K, 10-Q, transcript, etc.)
            s3_key: S3 key/path to the artifact
            published_date: Date the document was published

        Returns:
            Created artifact dict or None if failed
        """
        conn = self._get_connection()
        if not conn:
            return None

        # Get company ID
        company = self.get_company(ticker)
        if not company:
            print(f"⚠️  Company not found: {ticker}")
            return None

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                """
                INSERT INTO artifacts (company_id, artifact_type, s3_key, published_date)
                VALUES (%s, %s, %s, %s)
                RETURNING id, company_id, artifact_type as type, s3_key, published_date as date, created_at
            """,
                (company["id"], artifact_type, s3_key, published_date),
            )

            artifact = dict(cursor.fetchone())
            artifact["ticker"] = ticker
            conn.commit()
            cursor.close()

            print(f"✅ Created artifact: {artifact_type} for {ticker}")

            # Precompute financials for SEC filings so /api/financials/ stays fast.
            # Failures here are logged but don't fail the artifact insert —
            # the filing is still valuable for other features even if extraction fails.
            if artifact_type in ("10-K", "10-Q"):
                try:
                    self._extract_and_store_financials(
                        ticker, s3_key, artifact_type, published_date
                    )
                except Exception as e:
                    print(f"⚠️  Financials extraction failed for {s3_key}: {e}")

            return artifact

        except Exception as e:
            conn.rollback()
            print(f"⚠️  Error creating artifact: {e}")
            return None

    def _extract_and_store_financials(
        self, ticker: str, s3_key: str, filing_type: str, filing_date: str
    ):
        """
        Extract financial metrics from a single SEC filing and persist them.
        Called from create_artifact for 10-K/10-Q types, and from the backfill script.
        """
        # Local import avoids circular dependency (extractor depends on S3 service)
        from services.financial_html_extractor import FinancialHtmlExtractor

        extractor = FinancialHtmlExtractor()
        financials = extractor.extract_financials_from_html_filing(s3_key, filing_date)

        if not financials:
            print(f"  ⚠️  No financials extracted from {s3_key}")
            return

        # Skip if all key metrics are missing — nothing to store meaningfully
        has_data = any(
            financials.get(k)
            for k in (
                "revenue",
                "subscription_revenue",
                "net_income",
                "operating_income",
            )
        )
        if not has_data:
            print(f"  ⚠️  Extracted data is empty for {s3_key}, skipping store")
            return

        self.upsert_filing_financials(
            ticker, s3_key, filing_type, filing_date, financials
        )

    # =========================================================================
    # FILING FINANCIALS CRUD OPERATIONS
    # =========================================================================

    def upsert_filing_financials(
        self,
        ticker: str,
        s3_key: str,
        filing_type: str,
        filing_date: str,
        financials: Dict[str, Any],
    ) -> bool:
        """
        Store extracted financial metrics for a single filing.
        Idempotent: UNIQUE(s3_key) means re-running extraction updates in place.
        """
        conn = self._get_connection()
        if not conn:
            return False

        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO filing_financials (
                    ticker, s3_key, filing_type, filing_date,
                    revenue, subscription_revenue, arr, net_income,
                    operating_income, eps, raw_data, extracted_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (s3_key) DO UPDATE SET
                    revenue = EXCLUDED.revenue,
                    subscription_revenue = EXCLUDED.subscription_revenue,
                    arr = EXCLUDED.arr,
                    net_income = EXCLUDED.net_income,
                    operating_income = EXCLUDED.operating_income,
                    eps = EXCLUDED.eps,
                    raw_data = EXCLUDED.raw_data,
                    extracted_at = CURRENT_TIMESTAMP
                """,
                (
                    ticker.upper(),
                    s3_key,
                    filing_type,
                    filing_date,
                    financials.get("revenue"),
                    financials.get("subscription_revenue"),
                    financials.get("arr"),
                    financials.get("net_income"),
                    financials.get("operating_income"),
                    financials.get("eps"),
                    json.dumps(financials, default=str),
                ),
            )
            conn.commit()
            cursor.close()
            return True
        except Exception as e:
            conn.rollback()
            print(f"⚠️  Error upserting filing_financials for {s3_key}: {e}")
            return False

    def get_filing_financials(
        self, ticker: str, limit: int = 12
    ) -> List[Dict[str, Any]]:
        """
        Fetch pre-extracted financials for a ticker, newest first.
        Returns list of dicts ready for aggregation (rolling averages, summary).
        """
        conn = self._get_connection()
        if not conn:
            return []

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                """
                SELECT ticker, s3_key, filing_type, filing_date,
                       revenue, subscription_revenue, arr, net_income,
                       operating_income, eps, raw_data, extracted_at
                FROM filing_financials
                WHERE ticker = %s
                ORDER BY filing_date DESC
                LIMIT %s
                """,
                (ticker.upper(), limit),
            )
            rows = cursor.fetchall()
            cursor.close()

            result = []
            for row in rows:
                row_dict = dict(row)
                # Serialize date and numeric types for JSON response
                row_dict["date"] = (
                    row_dict["filing_date"].isoformat()
                    if row_dict.get("filing_date")
                    else None
                )
                row_dict["type"] = row_dict.get("filing_type")
                for numeric_key in (
                    "revenue",
                    "subscription_revenue",
                    "arr",
                    "net_income",
                    "operating_income",
                ):
                    if row_dict.get(numeric_key) is not None:
                        row_dict[numeric_key] = int(row_dict[numeric_key])
                if row_dict.get("eps") is not None:
                    row_dict["eps"] = float(row_dict["eps"])
                result.append(row_dict)
            return result
        except Exception as e:
            print(f"⚠️  Error fetching filing_financials for {ticker}: {e}")
            return []

    # =========================================================================
    # REGULATION CRUD OPERATIONS
    # =========================================================================

    def create_regulation(
        self,
        title: str,
        agency: str,
        external_id: str = None,
        summary: str = None,
        effective_date: str = None,
        publication_date: str = None,
        source_url: str = None,
        severity: str = "MEDIUM",
        keywords: List[str] = None,
        sectors_affected: List[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Create a new regulation

        Args:
            title: Regulation title
            agency: Regulatory agency (SEC, CISA, FTC, etc.)
            external_id: External ID (e.g., Federal Register doc number)
            summary: Regulation summary/abstract
            effective_date: When the regulation takes effect
            publication_date: When the regulation was published
            source_url: Link to the regulation
            severity: CRITICAL, HIGH, MEDIUM, or INFO
            keywords: List of relevant keywords
            sectors_affected: List of affected sectors

        Returns:
            Created regulation dict or None if failed
        """
        conn = self._get_connection()
        if not conn:
            return None

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                """
                INSERT INTO regulations (external_id, title, agency, summary, effective_date,
                    publication_date, source_url, severity, keywords, sectors_affected)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (external_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    summary = EXCLUDED.summary,
                    effective_date = EXCLUDED.effective_date,
                    severity = EXCLUDED.severity,
                    keywords = EXCLUDED.keywords,
                    sectors_affected = EXCLUDED.sectors_affected
                RETURNING id, external_id, title, agency, summary, effective_date,
                    publication_date, source_url, severity, keywords, sectors_affected, created_at
            """,
                (
                    external_id,
                    title,
                    agency,
                    summary,
                    effective_date,
                    publication_date,
                    source_url,
                    severity,
                    json.dumps(keywords) if keywords else None,
                    json.dumps(sectors_affected) if sectors_affected else None,
                ),
            )

            regulation = dict(cursor.fetchone())
            conn.commit()
            cursor.close()

            print(f"✅ Created/updated regulation: {title[:50]}...")
            return regulation

        except Exception as e:
            conn.rollback()
            print(f"⚠️  Error creating regulation: {e}")
            return None

    def get_regulation(self, regulation_id: int) -> Optional[Dict[str, Any]]:
        """Get a regulation by ID"""
        conn = self._get_connection()
        if not conn:
            return None

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                """
                SELECT id, external_id, title, agency, summary, effective_date,
                    publication_date, source_url, severity, keywords, sectors_affected, created_at
                FROM regulations
                WHERE id = %s
            """,
                (regulation_id,),
            )

            row = cursor.fetchone()
            cursor.close()

            return dict(row) if row else None

        except Exception as e:
            print(f"⚠️  Error getting regulation: {e}")
            return None

    def get_all_regulations(
        self, agency: str = None, severity: str = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get all regulations with optional filters

        Args:
            agency: Filter by agency (SEC, CISA, FTC, etc.)
            severity: Filter by severity (CRITICAL, HIGH, MEDIUM, INFO)
            limit: Maximum number of results

        Returns:
            List of regulation dicts
        """
        conn = self._get_connection()
        if not conn:
            return []

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            query = """
                SELECT id, external_id, title, agency, summary, effective_date,
                    publication_date, source_url, severity, keywords, sectors_affected, created_at
                FROM regulations
                WHERE 1=1
            """
            params = []

            if agency:
                query += " AND agency = %s"
                params.append(agency)
            if severity:
                query += " AND severity = %s"
                params.append(severity)

            query += (
                " ORDER BY effective_date DESC NULLS LAST, created_at DESC LIMIT %s"
            )
            params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()
            cursor.close()

            return [dict(row) for row in rows]

        except Exception as e:
            print(f"⚠️  Error getting regulations: {e}")
            return []

    def clear_regulations(self) -> bool:
        """
        Clear all regulations and alerts for fresh ingestion

        Returns:
            True if successful, False otherwise
        """
        conn = self._get_connection()
        if not conn:
            return False

        try:
            cursor = conn.cursor()
            # Delete alerts first (foreign key constraint)
            cursor.execute("DELETE FROM regulatory_alerts")
            alerts_deleted = cursor.rowcount
            # Then delete regulations
            cursor.execute("DELETE FROM regulations")
            regs_deleted = cursor.rowcount
            conn.commit()
            cursor.close()
            print(f"✅ Cleared {regs_deleted} regulations and {alerts_deleted} alerts")
            return True
        except Exception as e:
            conn.rollback()
            print(f"⚠️  Error clearing regulations: {e}")
            return False

    # =========================================================================
    # REGULATORY ALERT CRUD OPERATIONS
    # =========================================================================

    def create_regulatory_alert(
        self,
        regulation_id: int,
        company_id: int,
        relevance_score: float,
        impact_level: str = "MEDIUM",
        matched_keywords: List[str] = None,
        ai_impact_analysis: str = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Create a regulatory alert linking a regulation to a company

        Args:
            regulation_id: ID of the regulation
            company_id: ID of the company
            relevance_score: TF-IDF relevance score (0-1)
            impact_level: CRITICAL, HIGH, MEDIUM, or LOW
            matched_keywords: Keywords that matched
            ai_impact_analysis: AI-generated impact analysis

        Returns:
            Created alert dict or None if failed
        """
        conn = self._get_connection()
        if not conn:
            return None

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                """
                INSERT INTO regulatory_alerts (regulation_id, company_id, relevance_score,
                    impact_level, matched_keywords, ai_impact_analysis)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (regulation_id, company_id) DO UPDATE SET
                    relevance_score = EXCLUDED.relevance_score,
                    impact_level = EXCLUDED.impact_level,
                    matched_keywords = EXCLUDED.matched_keywords,
                    ai_impact_analysis = EXCLUDED.ai_impact_analysis
                RETURNING id, regulation_id, company_id, relevance_score, impact_level,
                    status, matched_keywords, ai_impact_analysis, created_at
            """,
                (
                    regulation_id,
                    company_id,
                    relevance_score,
                    impact_level,
                    json.dumps(matched_keywords) if matched_keywords else None,
                    ai_impact_analysis,
                ),
            )

            alert = dict(cursor.fetchone())
            conn.commit()
            cursor.close()

            print(
                f"✅ Created regulatory alert for regulation {regulation_id}, company {company_id}"
            )
            return alert

        except Exception as e:
            conn.rollback()
            print(f"⚠️  Error creating regulatory alert: {e}")
            return None

    def get_regulatory_alerts(
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
            status: Filter by status (UNACKNOWLEDGED, ACKNOWLEDGED, RESOLVED, etc.)
            impact_level: Filter by impact level (CRITICAL, HIGH, MEDIUM, LOW)
            limit: Maximum number of results

        Returns:
            List of alert dicts with regulation and company info
        """
        conn = self._get_connection()
        if not conn:
            return []

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            query = """
                SELECT
                    ra.id,
                    ra.regulation_id,
                    ra.company_id,
                    ra.relevance_score,
                    ra.impact_level,
                    ra.status,
                    ra.matched_keywords,
                    ra.ai_impact_analysis,
                    ra.acknowledged_by,
                    ra.acknowledged_at,
                    ra.created_at,
                    r.title as regulation_title,
                    r.agency,
                    r.severity as regulation_severity,
                    r.effective_date,
                    r.source_url,
                    c.ticker,
                    c.company_name
                FROM regulatory_alerts ra
                JOIN regulations r ON ra.regulation_id = r.id
                JOIN companies c ON ra.company_id = c.id
                WHERE 1=1
            """
            params = []

            if ticker:
                query += " AND c.ticker = %s"
                params.append(ticker.upper())
            if status:
                query += " AND ra.status = %s"
                params.append(status)
            if impact_level:
                query += " AND ra.impact_level = %s"
                params.append(impact_level)

            query += " ORDER BY ra.created_at DESC LIMIT %s"
            params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()
            cursor.close()

            return [dict(row) for row in rows]

        except Exception as e:
            print(f"⚠️  Error getting regulatory alerts: {e}")
            return []

    def update_alert_status(
        self, alert_id: int, status: str, acknowledged_by: str = None
    ) -> Optional[Dict[str, Any]]:
        """
        Update regulatory alert status

        Args:
            alert_id: ID of the alert
            status: New status (UNACKNOWLEDGED, ACKNOWLEDGED, RESOLVED, etc.)
            acknowledged_by: Username who acknowledged

        Returns:
            Updated alert dict or None if failed
        """
        conn = self._get_connection()
        if not conn:
            return None

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            if status == "ACKNOWLEDGED" and acknowledged_by:
                cursor.execute(
                    """
                    UPDATE regulatory_alerts
                    SET status = %s, acknowledged_by = %s, acknowledged_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    RETURNING id, regulation_id, company_id, status, acknowledged_by, acknowledged_at
                """,
                    (status, acknowledged_by, alert_id),
                )
            else:
                cursor.execute(
                    """
                    UPDATE regulatory_alerts
                    SET status = %s
                    WHERE id = %s
                    RETURNING id, regulation_id, company_id, status, acknowledged_by, acknowledged_at
                """,
                    (status, alert_id),
                )

            row = cursor.fetchone()
            conn.commit()
            cursor.close()

            if row:
                print(f"✅ Updated alert {alert_id} status to {status}")
                return dict(row)
            return None

        except Exception as e:
            conn.rollback()
            print(f"⚠️  Error updating alert status: {e}")
            return None

    def get_regulatory_dashboard_summary(self) -> Dict[str, Any]:
        """
        Get summary statistics for the regulatory dashboard

        Returns:
            Dict with alert counts by status, severity, agency, etc.
        """
        conn = self._get_connection()
        if not conn:
            return {}

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # Get alert counts by status
            cursor.execute(
                """
                SELECT status, COUNT(*) as count
                FROM regulatory_alerts
                GROUP BY status
            """
            )
            status_counts = {row["status"]: row["count"] for row in cursor.fetchall()}

            # Get alert counts by impact level
            cursor.execute(
                """
                SELECT impact_level, COUNT(*) as count
                FROM regulatory_alerts
                WHERE status != 'RESOLVED'
                GROUP BY impact_level
            """
            )
            impact_counts = {
                row["impact_level"]: row["count"] for row in cursor.fetchall()
            }

            # Get regulation counts by agency
            cursor.execute(
                """
                SELECT agency, COUNT(*) as count
                FROM regulations
                GROUP BY agency
            """
            )
            agency_counts = {row["agency"]: row["count"] for row in cursor.fetchall()}

            # Get upcoming effective dates
            cursor.execute(
                """
                SELECT id, title, agency, effective_date, severity
                FROM regulations
                WHERE effective_date >= CURRENT_DATE
                ORDER BY effective_date ASC
                LIMIT 5
            """
            )
            upcoming = [dict(row) for row in cursor.fetchall()]

            cursor.close()

            return {
                "alerts_by_status": status_counts,
                "alerts_by_impact": impact_counts,
                "regulations_by_agency": agency_counts,
                "upcoming_regulations": upcoming,
                "total_regulations": sum(agency_counts.values()),
                "total_active_alerts": sum(
                    count
                    for status, count in status_counts.items()
                    if status != "RESOLVED"
                ),
            }

        except Exception as e:
            print(f"⚠️  Error getting dashboard summary: {e}")
            return {}


# Global database service instance
db_service = DatabaseService()
