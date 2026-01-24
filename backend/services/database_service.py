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
            return artifact

        except Exception as e:
            conn.rollback()
            print(f"⚠️  Error creating artifact: {e}")
            return None


# Global database service instance
db_service = DatabaseService()
