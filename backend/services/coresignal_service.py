"""
CoreSignal API Service

Provides access to:
- Employee headcount over time (historical data)
- Active jobs by function and seniority
- Hiring intensity metrics (jobs/employees ratio)

API Documentation: https://docs.coresignal.com/
Base URL: https://api.coresignal.com/cdapi/v2/
"""

import os
import json
import requests
from datetime import datetime, date
from typing import Optional, Dict, List, Any
from decimal import Decimal

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor, Json

    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False


# =============================================================================
# CURATED COMPANIES WITH CORESIGNAL IDS
# =============================================================================

CORESIGNAL_COMPANIES = {
    "CRWD": {"id": 10020216, "name": "CrowdStrike", "domain": "crowdstrike.com"},
    "ZS": {"id": 1114997, "name": "Zscaler", "domain": "zscaler.com"},
    "NET": {"id": 10826791, "name": "Cloudflare", "domain": "cloudflare.com"},
    "PANW": {
        "id": 7898996,
        "name": "Palo Alto Networks",
        "domain": "paloaltonetworks.com",
    },
    "FTNT": {"id": 9560844, "name": "Fortinet", "domain": "fortinet.com"},
    "OKTA": {"id": 5929958, "name": "Okta", "domain": "okta.com"},
    "S": {"id": 10842616, "name": "SentinelOne", "domain": "sentinelone.com"},
    "CYBR": {"id": 1904796, "name": "CyberArk", "domain": "cyberark.com"},
    "TENB": {"id": 11438875, "name": "Tenable", "domain": "tenable.com"},
    "SPLK": {"id": 4268152, "name": "Splunk", "domain": "splunk.com"},
}

# Pre-cached job data - Active job postings by function (Dec 2025)
CACHED_JOBS_BY_FUNCTION = {
    "CRWD": {
        "Engineering": 518,
        "Sales and Business Development": 213,
        "Information Technology": 768,
        "Marketing": 36,
        "Finance": 13,
        "Human Resources": 8,
        "Product Management": 21,
        "Research": 8,
        "Legal": 8,
        "Operations": 0,
        "Customer Success and Support": 0,
        "Administrative": 1,
        "Quality Assurance": 1,
    },
    "ZS": {
        "Engineering": 103,
        "Sales and Business Development": 104,
        "Information Technology": 157,
        "Marketing": 17,
        "Finance": 15,
        "Human Resources": 10,
        "Product Management": 9,
        "Research": 4,
        "Legal": 3,
        "Operations": 0,
        "Customer Success and Support": 0,
        "Administrative": 0,
        "Quality Assurance": 0,
    },
    "NET": {
        "Engineering": 336,
        "Sales and Business Development": 141,
        "Information Technology": 297,
        "Marketing": 88,
        "Finance": 16,
        "Human Resources": 8,
        "Product Management": 59,
        "Research": 0,
        "Legal": 14,
        "Operations": 0,
        "Customer Success and Support": 0,
        "Administrative": 3,
        "Quality Assurance": 0,
    },
    "PANW": {
        "Engineering": 253,
        "Sales and Business Development": 0,
        "Information Technology": 70,
        "Marketing": 25,
        "Finance": 15,
        "Human Resources": 9,
        "Product Management": 41,
        "Research": 1,
        "Legal": 0,
        "Operations": 0,
        "Customer Success and Support": 0,
        "Administrative": 3,
        "Quality Assurance": 0,
    },
    "FTNT": {
        "Engineering": 141,
        "Sales and Business Development": 351,
        "Information Technology": 376,
        "Marketing": 12,
        "Finance": 3,
        "Human Resources": 11,
        "Product Management": 2,
        "Research": 1,
        "Legal": 1,
        "Operations": 0,
        "Customer Success and Support": 0,
        "Administrative": 1,
        "Quality Assurance": 17,
    },
    "OKTA": {
        "Engineering": 112,
        "Sales and Business Development": 66,
        "Information Technology": 140,
        "Marketing": 30,
        "Finance": 17,
        "Human Resources": 2,
        "Product Management": 30,
        "Research": 1,
        "Legal": 3,
        "Operations": 0,
        "Customer Success and Support": 0,
        "Administrative": 3,
        "Quality Assurance": 0,
    },
    "S": {
        "Engineering": 111,
        "Sales and Business Development": 36,
        "Information Technology": 164,
        "Marketing": 17,
        "Finance": 1,
        "Human Resources": 1,
        "Product Management": 6,
        "Research": 0,
        "Legal": 1,
        "Operations": 0,
        "Customer Success and Support": 0,
        "Administrative": 1,
        "Quality Assurance": 0,
    },
    "CYBR": {
        "Engineering": 0,
        "Sales and Business Development": 0,
        "Information Technology": 149,
        "Marketing": 0,
        "Finance": 0,
        "Human Resources": 0,
        "Product Management": 0,
        "Research": 0,
        "Legal": 0,
        "Operations": 0,
        "Customer Success and Support": 0,
        "Administrative": 0,
        "Quality Assurance": 0,
    },
    "TENB": {
        "Engineering": 27,
        "Sales and Business Development": 23,
        "Information Technology": 37,
        "Marketing": 6,
        "Finance": 1,
        "Human Resources": 1,
        "Product Management": 2,
        "Research": 1,
        "Legal": 0,
        "Operations": 0,
        "Customer Success and Support": 0,
        "Administrative": 0,
        "Quality Assurance": 0,
    },
    "SPLK": {
        "Engineering": 49,
        "Sales and Business Development": 39,
        "Information Technology": 77,
        "Marketing": 15,
        "Finance": 0,
        "Human Resources": 0,
        "Product Management": 6,
        "Research": 4,
        "Legal": 0,
        "Operations": 0,
        "Customer Success and Support": 0,
        "Administrative": 4,
        "Quality Assurance": 0,
    },
}

# Pre-cached job data - Active job postings by seniority (Dec 2025)
CACHED_JOBS_BY_SENIORITY = {
    "CRWD": {
        "Entry level": 65,
        "Associate": 33,
        "Mid-Senior level": 932,
        "Director": 47,
        "Executive": 2,
        "Not Applicable": 5,
    },
    "ZS": {
        "Entry level": 11,
        "Associate": 0,
        "Mid-Senior level": 273,
        "Director": 28,
        "Executive": 1,
        "Not Applicable": 1,
    },
    "NET": {
        "Entry level": 28,
        "Associate": 232,
        "Mid-Senior level": 527,
        "Director": 24,
        "Executive": 10,
        "Not Applicable": 1,
    },
    "PANW": {
        "Entry level": 4,
        "Associate": 677,
        "Mid-Senior level": 312,
        "Director": 49,
        "Executive": 0,
        "Not Applicable": 31,
    },
    "FTNT": {
        "Entry level": 150,
        "Associate": 0,
        "Mid-Senior level": 657,
        "Director": 27,
        "Executive": 0,
        "Not Applicable": 5,
    },
    "OKTA": {
        "Entry level": 0,
        "Associate": 0,
        "Mid-Senior level": 4,
        "Director": 0,
        "Executive": 0,
        "Not Applicable": 337,
    },
    "S": {
        "Entry level": 0,
        "Associate": 0,
        "Mid-Senior level": 2,
        "Director": 1,
        "Executive": 0,
        "Not Applicable": 231,
    },
    "CYBR": {
        "Entry level": 1,
        "Associate": 0,
        "Mid-Senior level": 164,
        "Director": 0,
        "Executive": 0,
        "Not Applicable": 1,
    },
    "TENB": {
        "Entry level": 8,
        "Associate": 1,
        "Mid-Senior level": 58,
        "Director": 2,
        "Executive": 0,
        "Not Applicable": 0,
    },
    "SPLK": {
        "Entry level": 0,
        "Associate": 0,
        "Mid-Senior level": 0,
        "Director": 0,
        "Executive": 0,
        "Not Applicable": 161,
    },
}

# Current employee counts (Dec 2025 - from CoreSignal enriched data)
CACHED_EMPLOYEE_COUNTS = {
    "CRWD": 10833,
    "ZS": 8984,
    "NET": 6356,
    "PANW": 18400,
    "FTNT": 15737,
    "OKTA": 6686,
    "S": 3094,
    "CYBR": 4949,
    "TENB": 2343,
    "SPLK": 9760,
}


class CoreSignalService:
    """
    Service for interacting with CoreSignal APIs and managing growth data in RDS
    """

    BASE_URL = "https://api.coresignal.com/cdapi/v2"

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize CoreSignal service

        Args:
            api_key: CoreSignal API key. If not provided, reads from
                     CORESIGNAL_API_KEY environment variable
        """
        self.api_key = api_key or os.environ.get("CORESIGNAL_API_KEY")
        if not self.api_key:
            print("⚠️  CORESIGNAL_API_KEY not set. Some features will use cached data.")

        self.headers = {
            "Content-Type": "application/json",
            "apikey": self.api_key or "",
        }

        # Database connection
        self.connection = None
        self.connected = False
        self._connect_db()

    def _connect_db(self):
        """Establish database connection"""
        if not PSYCOPG2_AVAILABLE:
            print("📦 CoreSignalService: psycopg2 not available")
            return

        db_host = os.environ.get("DB_HOST")
        db_name = os.environ.get("DB_NAME", "cyberrisk")
        db_user = os.environ.get("DB_USER", "cyberrisk_admin")
        db_password = os.environ.get("DB_PASSWORD")

        if not db_host or not db_password:
            print("📦 CoreSignalService: DB credentials not configured")
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
            print(f"✅ CoreSignalService: Connected to RDS")
            self._ensure_tables_exist()
        except Exception as e:
            print(f"⚠️  CoreSignalService: DB connection failed - {e}")
            self.connected = False

    def _ensure_tables_exist(self):
        """Create growth data tables if they don't exist"""
        if not self.connected:
            return

        try:
            cursor = self.connection.cursor()

            # Headcount history table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS company_headcount_history (
                    id SERIAL PRIMARY KEY,
                    ticker VARCHAR(10) NOT NULL,
                    snapshot_date DATE NOT NULL,
                    employee_count INT NOT NULL,
                    by_department JSONB,
                    by_country JSONB,
                    by_seniority JSONB,
                    by_region JSONB,
                    data_source VARCHAR(50) DEFAULT 'coresignal',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(ticker, snapshot_date)
                );
                CREATE INDEX IF NOT EXISTS idx_headcount_ticker ON company_headcount_history(ticker);
                CREATE INDEX IF NOT EXISTS idx_headcount_date ON company_headcount_history(snapshot_date);
            """
            )

            # Jobs snapshot table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS company_jobs_snapshot (
                    id SERIAL PRIMARY KEY,
                    ticker VARCHAR(10) NOT NULL,
                    snapshot_date DATE NOT NULL,
                    jobs_by_function JSONB NOT NULL,
                    jobs_by_seniority JSONB NOT NULL,
                    total_jobs INT NOT NULL,
                    employee_count INT,
                    hiring_intensity DECIMAL(5,2),
                    data_source VARCHAR(50) DEFAULT 'coresignal',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(ticker, snapshot_date)
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_ticker ON company_jobs_snapshot(ticker);
                CREATE INDEX IF NOT EXISTS idx_jobs_date ON company_jobs_snapshot(snapshot_date);
            """
            )

            self.connection.commit()
            cursor.close()
            print("✅ CoreSignalService: Growth tables ready")
        except Exception as e:
            print(f"⚠️  Error creating growth tables: {e}")
            self.connection.rollback()

    def _get_connection(self):
        """Get or refresh connection"""
        if not self.connected:
            self._connect_db()
            return self.connection if self.connected else None

        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            return self.connection
        except:
            self._connect_db()
            return self.connection if self.connected else None

    # =========================================================================
    # HEADCOUNT DATA OPERATIONS
    # =========================================================================

    def store_headcount(
        self,
        ticker: str,
        snapshot_date: str,
        employee_count: int,
        by_department: Dict = None,
        by_country: Dict = None,
        by_seniority: Dict = None,
        by_region: Dict = None,
    ) -> bool:
        """
        Store a headcount snapshot

        Args:
            ticker: Stock ticker
            snapshot_date: Date string (YYYY-MM-DD)
            employee_count: Total employee count
            by_department: Optional breakdown by department
            by_country: Optional breakdown by country
            by_seniority: Optional breakdown by seniority
            by_region: Optional breakdown by region

        Returns:
            True if stored successfully
        """
        conn = self._get_connection()
        if not conn:
            return False

        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO company_headcount_history
                (ticker, snapshot_date, employee_count, by_department, by_country, by_seniority, by_region)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker, snapshot_date)
                DO UPDATE SET
                    employee_count = EXCLUDED.employee_count,
                    by_department = COALESCE(EXCLUDED.by_department, company_headcount_history.by_department),
                    by_country = COALESCE(EXCLUDED.by_country, company_headcount_history.by_country),
                    by_seniority = COALESCE(EXCLUDED.by_seniority, company_headcount_history.by_seniority),
                    by_region = COALESCE(EXCLUDED.by_region, company_headcount_history.by_region)
            """,
                (
                    ticker.upper(),
                    snapshot_date,
                    employee_count,
                    Json(by_department) if by_department else None,
                    Json(by_country) if by_country else None,
                    Json(by_seniority) if by_seniority else None,
                    Json(by_region) if by_region else None,
                ),
            )
            conn.commit()
            cursor.close()
            return True
        except Exception as e:
            conn.rollback()
            print(f"⚠️  Error storing headcount: {e}")
            return False

    def get_headcount_history(self, ticker: str, limit: int = 100) -> List[Dict]:
        """
        Get headcount history for a company

        Args:
            ticker: Stock ticker
            limit: Max records to return

        Returns:
            List of headcount records sorted by date
        """
        conn = self._get_connection()
        if not conn:
            return []

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                """
                SELECT ticker, snapshot_date, employee_count, by_department, by_country, by_seniority, by_region
                FROM company_headcount_history
                WHERE ticker = %s
                ORDER BY snapshot_date ASC
                LIMIT %s
            """,
                (ticker.upper(), limit),
            )

            rows = cursor.fetchall()
            cursor.close()

            result = []
            for row in rows:
                record = dict(row)
                record["snapshot_date"] = record["snapshot_date"].isoformat()
                result.append(record)

            return result
        except Exception as e:
            print(f"⚠️  Error getting headcount history: {e}")
            return []

    def get_multi_company_headcount(self, tickers: List[str]) -> Dict[str, List[Dict]]:
        """
        Get headcount history for multiple companies

        Args:
            tickers: List of stock tickers

        Returns:
            Dict mapping ticker to list of headcount records
        """
        result = {}
        for ticker in tickers:
            result[ticker.upper()] = self.get_headcount_history(ticker)
        return result

    # =========================================================================
    # JOBS DATA OPERATIONS
    # =========================================================================

    def store_jobs_snapshot(
        self,
        ticker: str,
        snapshot_date: str,
        jobs_by_function: Dict,
        jobs_by_seniority: Dict,
        employee_count: int = None,
    ) -> bool:
        """
        Store a jobs snapshot

        Args:
            ticker: Stock ticker
            snapshot_date: Date string (YYYY-MM-DD)
            jobs_by_function: Jobs count by function
            jobs_by_seniority: Jobs count by seniority
            employee_count: Optional current employee count

        Returns:
            True if stored successfully
        """
        conn = self._get_connection()
        if not conn:
            return False

        total_jobs = sum(jobs_by_function.values())
        hiring_intensity = None
        if employee_count and employee_count > 0:
            hiring_intensity = round((total_jobs / employee_count) * 100, 2)

        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO company_jobs_snapshot
                (ticker, snapshot_date, jobs_by_function, jobs_by_seniority, total_jobs, employee_count, hiring_intensity)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker, snapshot_date)
                DO UPDATE SET
                    jobs_by_function = EXCLUDED.jobs_by_function,
                    jobs_by_seniority = EXCLUDED.jobs_by_seniority,
                    total_jobs = EXCLUDED.total_jobs,
                    employee_count = EXCLUDED.employee_count,
                    hiring_intensity = EXCLUDED.hiring_intensity
            """,
                (
                    ticker.upper(),
                    snapshot_date,
                    Json(jobs_by_function),
                    Json(jobs_by_seniority),
                    total_jobs,
                    employee_count,
                    hiring_intensity,
                ),
            )
            conn.commit()
            cursor.close()
            return True
        except Exception as e:
            conn.rollback()
            print(f"⚠️  Error storing jobs snapshot: {e}")
            return False

    def get_latest_jobs(self, ticker: str) -> Optional[Dict]:
        """
        Get the latest jobs snapshot for a company

        Args:
            ticker: Stock ticker

        Returns:
            Latest jobs snapshot or None
        """
        conn = self._get_connection()
        if not conn:
            # Fall back to cached data
            ticker = ticker.upper()
            if ticker in CACHED_JOBS_BY_FUNCTION:
                jobs_func = CACHED_JOBS_BY_FUNCTION[ticker]
                jobs_sen = CACHED_JOBS_BY_SENIORITY.get(ticker, {})
                emp_count = CACHED_EMPLOYEE_COUNTS.get(ticker)
                total = sum(jobs_func.values())
                return {
                    "ticker": ticker,
                    "snapshot_date": "2024-12-28",
                    "jobs_by_function": jobs_func,
                    "jobs_by_seniority": jobs_sen,
                    "total_jobs": total,
                    "employee_count": emp_count,
                    "hiring_intensity": (
                        round((total / emp_count) * 100, 2) if emp_count else None
                    ),
                    "from_cache": True,
                }
            return None

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                """
                SELECT ticker, snapshot_date, jobs_by_function, jobs_by_seniority,
                       total_jobs, employee_count, hiring_intensity
                FROM company_jobs_snapshot
                WHERE ticker = %s
                ORDER BY snapshot_date DESC
                LIMIT 1
            """,
                (ticker.upper(),),
            )

            row = cursor.fetchone()
            cursor.close()

            if row:
                record = dict(row)
                record["snapshot_date"] = record["snapshot_date"].isoformat()
                record["from_cache"] = False
                # Convert Decimal to float for JSON serialization
                if record.get("hiring_intensity"):
                    record["hiring_intensity"] = float(record["hiring_intensity"])
                return record

            # Fall back to cached data if no DB record
            ticker = ticker.upper()
            if ticker in CACHED_JOBS_BY_FUNCTION:
                jobs_func = CACHED_JOBS_BY_FUNCTION[ticker]
                jobs_sen = CACHED_JOBS_BY_SENIORITY.get(ticker, {})
                emp_count = CACHED_EMPLOYEE_COUNTS.get(ticker)
                total = sum(jobs_func.values())
                return {
                    "ticker": ticker,
                    "snapshot_date": "2024-12-28",
                    "jobs_by_function": jobs_func,
                    "jobs_by_seniority": jobs_sen,
                    "total_jobs": total,
                    "employee_count": emp_count,
                    "hiring_intensity": (
                        round((total / emp_count) * 100, 2) if emp_count else None
                    ),
                    "from_cache": True,
                }

            return None
        except Exception as e:
            print(f"⚠️  Error getting jobs snapshot: {e}")
            return None

    # =========================================================================
    # COMPARISON DATA
    # =========================================================================

    def get_comparison_data(self, tickers: List[str]) -> Dict[str, Any]:
        """
        Get comparison data for multiple companies

        Args:
            tickers: List of stock tickers (max 3)

        Returns:
            Comprehensive comparison data for charts
        """
        tickers = [t.upper() for t in tickers[:3]]

        # Get company info
        companies = {}
        for ticker in tickers:
            info = CORESIGNAL_COMPANIES.get(ticker, {})
            jobs = self.get_latest_jobs(ticker)
            companies[ticker] = {
                "name": info.get("name", ticker),
                "employee_count": (
                    jobs.get("employee_count")
                    if jobs
                    else CACHED_EMPLOYEE_COUNTS.get(ticker)
                ),
                "total_jobs": jobs.get("total_jobs") if jobs else 0,
            }

        # Get jobs data
        jobs_by_function = {}
        jobs_by_seniority = {}
        hiring_intensity = {"overall": {}, "by_function": {}, "by_seniority": {}}

        for ticker in tickers:
            jobs = self.get_latest_jobs(ticker)
            if jobs:
                # Jobs by function
                for func, count in jobs.get("jobs_by_function", {}).items():
                    if func not in jobs_by_function:
                        jobs_by_function[func] = {}
                    jobs_by_function[func][ticker] = count

                # Jobs by seniority
                for sen, count in jobs.get("jobs_by_seniority", {}).items():
                    if sen not in jobs_by_seniority:
                        jobs_by_seniority[sen] = {}
                    jobs_by_seniority[sen][ticker] = count

                # Overall hiring intensity
                hiring_intensity["overall"][ticker] = jobs.get("hiring_intensity", 0)

                # Intensity by function
                emp_count = jobs.get("employee_count", 1)
                for func, count in jobs.get("jobs_by_function", {}).items():
                    if func not in hiring_intensity["by_function"]:
                        hiring_intensity["by_function"][func] = {}
                    intensity = round((count / emp_count) * 100, 2) if emp_count else 0
                    hiring_intensity["by_function"][func][ticker] = intensity

                # Intensity by seniority
                for sen, count in jobs.get("jobs_by_seniority", {}).items():
                    if sen not in hiring_intensity["by_seniority"]:
                        hiring_intensity["by_seniority"][sen] = {}
                    intensity = round((count / emp_count) * 100, 2) if emp_count else 0
                    hiring_intensity["by_seniority"][sen][ticker] = intensity

        # Get headcount history
        headcount_data = self.get_multi_company_headcount(tickers)

        # Build time series for charts
        headcount_history = []
        indexed_growth = []

        # Get all unique dates
        all_dates = set()
        for ticker, history in headcount_data.items():
            for record in history:
                # Convert to month for grouping
                date_str = record["snapshot_date"][:7]  # YYYY-MM
                all_dates.add(date_str)

        # Build history by date
        for date_str in sorted(all_dates):
            history_record = {"date": date_str}
            index_record = {"date": date_str}

            for ticker in tickers:
                # Find closest record for this month
                ticker_history = headcount_data.get(ticker, [])
                for record in ticker_history:
                    if record["snapshot_date"].startswith(date_str):
                        history_record[ticker] = record["employee_count"]
                        break

            headcount_history.append(history_record)

        # Calculate indexed growth (first date = 100)
        base_values = {}
        for record in headcount_history:
            for ticker in tickers:
                if ticker in record and ticker not in base_values:
                    base_values[ticker] = record[ticker]

        for record in headcount_history:
            index_record = {"date": record["date"]}
            for ticker in tickers:
                if (
                    ticker in record
                    and ticker in base_values
                    and base_values[ticker] > 0
                ):
                    index_record[ticker] = round(
                        (record[ticker] / base_values[ticker]) * 100, 1
                    )
            indexed_growth.append(index_record)

        # Generate insights
        insights = self._generate_insights(companies, hiring_intensity)

        return {
            "companies": companies,
            "jobs_by_function": jobs_by_function,
            "jobs_by_seniority": jobs_by_seniority,
            "hiring_intensity": hiring_intensity,
            "headcount_history": headcount_history,
            "indexed_growth": indexed_growth,
            "insights": insights,
        }

    def _generate_insights(self, companies: Dict, hiring_intensity: Dict) -> List[str]:
        """Generate key insights from comparison data"""
        insights = []

        # Find highest hiring intensity
        overall = hiring_intensity.get("overall", {})
        if overall:
            max_ticker = max(overall, key=overall.get)
            max_val = overall[max_ticker]
            insights.append(
                f"{companies[max_ticker]['name']}: Highest hiring intensity ({max_val}%)"
            )

        # Find most IT/Engineering focused
        by_func = hiring_intensity.get("by_function", {})
        it_eng = {}
        for ticker in companies:
            it_val = by_func.get("Information Technology", {}).get(ticker, 0)
            eng_val = by_func.get("Engineering", {}).get(ticker, 0)
            it_eng[ticker] = it_val + eng_val

        if it_eng:
            max_ticker = max(it_eng, key=it_eng.get)
            insights.append(
                f"{companies[max_ticker]['name']}: Heaviest IT/Engineering focus ({round(it_eng[max_ticker], 1)}%)"
            )

        # Find most sales-focused
        sales = by_func.get("Sales", {})
        if sales:
            max_ticker = max(sales, key=sales.get)
            max_val = sales[max_ticker]
            insights.append(
                f"{companies[max_ticker]['name']}: Highest sales hiring ({max_val}%)"
            )

        return insights

    # =========================================================================
    # API CALLS (for fetching new data)
    # =========================================================================

    def fetch_company_data(self, company_id: int) -> Optional[Dict]:
        """
        Fetch company data from CoreSignal API

        Args:
            company_id: CoreSignal/LinkedIn company ID

        Returns:
            Company data or None
        """
        if not self.api_key:
            print("⚠️  No API key configured")
            return None

        endpoint = f"{self.BASE_URL}/company_multi_source/collect/{company_id}"

        try:
            response = requests.get(endpoint, headers=self.headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"⚠️  CoreSignal API error: {e}")
            return None

    def search_jobs(
        self, company_id: int, filters: List[Dict] = None
    ) -> Optional[Dict]:
        """
        Search jobs using ES DSL query

        Args:
            company_id: CoreSignal/LinkedIn company ID
            filters: Additional ES DSL filters

        Returns:
            Search results or None
        """
        if not self.api_key:
            print("⚠️  No API key configured")
            return None

        endpoint = f"{self.BASE_URL}/job_multi_source/search/es_dsl"

        query = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"company_ids.li_company_id": str(company_id)}},
                        {"term": {"status": 1}},
                    ]
                }
            },
            "size": 1000,
        }

        if filters:
            query["query"]["bool"]["must"].extend(filters)

        try:
            response = requests.post(
                endpoint, headers=self.headers, json=query, timeout=30
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"⚠️  CoreSignal API error: {e}")
            return None

    # =========================================================================
    # JSON FILE IMPORT
    # =========================================================================

    def import_from_json_file(self, filepath: str, ticker: str) -> Dict[str, int]:
        """
        Import company data from CoreSignal enriched JSON file to RDS

        Args:
            filepath: Path to JSON file
            ticker: Stock ticker for the company

        Returns:
            Dict with counts of imported records
        """
        try:
            with open(filepath) as f:
                data = json.load(f)
        except Exception as e:
            return {"error": str(e)}

        ticker = ticker.upper()
        counts = {
            "headcount": 0,
            "by_department": 0,
            "by_country": 0,
            "by_seniority": 0,
        }

        # Import monthly headcount
        headcount_records = data.get("employees_count_by_month", [])
        for record in headcount_records:
            date_str = record.get("date", "")
            emp_count = record.get("employees_count", 0)

            # Handle date formats: YYYYMM or YYYY-MM-DD
            if len(date_str) == 6:
                snapshot_date = f"{date_str[:4]}-{date_str[4:]}-01"
            else:
                snapshot_date = date_str[:10]

            if self.store_headcount(ticker, snapshot_date, emp_count):
                counts["headcount"] += 1

        # Import department breakdown by month
        dept_records = data.get("employees_count_breakdown_by_department_by_month", [])
        for record in dept_records:
            date_str = record.get("date", "")
            breakdown = record.get("employees_count_breakdown_by_department", {})

            if len(date_str) == 6:
                snapshot_date = f"{date_str[:4]}-{date_str[4:]}-01"
            else:
                snapshot_date = date_str[:10]

            # Clean up department names (remove 'employees_count_' prefix)
            by_dept = {}
            for key, val in breakdown.items():
                if val is not None:
                    dept = key.replace("employees_count_", "")
                    by_dept[dept] = val

            if by_dept:
                self._update_headcount_breakdown(
                    ticker, snapshot_date, by_department=by_dept
                )
                counts["by_department"] += 1

        # Import country breakdown by month
        country_records = data.get("employees_count_by_country_by_month", [])
        for record in country_records:
            date_str = record.get("date", "")
            countries = record.get("employees_count_by_country", [])

            if len(date_str) == 6:
                snapshot_date = f"{date_str[:4]}-{date_str[4:]}-01"
            else:
                snapshot_date = date_str[:10]

            by_country = {}
            for item in countries:
                by_country[item.get("country", "Unknown")] = item.get(
                    "employee_count", 0
                )

            if by_country:
                self._update_headcount_breakdown(
                    ticker, snapshot_date, by_country=by_country
                )
                counts["by_country"] += 1

        # Import seniority breakdown by month
        seniority_records = data.get(
            "employees_count_breakdown_by_seniority_by_month", []
        )
        for record in seniority_records:
            date_str = record.get("date", "")
            breakdown = record.get("employees_count_breakdown_by_seniority", {})

            if len(date_str) == 6:
                snapshot_date = f"{date_str[:4]}-{date_str[4:]}-01"
            else:
                snapshot_date = date_str[:10]

            # Clean up seniority names
            by_seniority = {}
            for key, val in breakdown.items():
                if val is not None:
                    level = key.replace("employees_count_", "")
                    by_seniority[level] = val

            if by_seniority:
                self._update_headcount_breakdown(
                    ticker, snapshot_date, by_seniority=by_seniority
                )
                counts["by_seniority"] += 1

        print(f"✅ Imported {ticker} from {filepath}: {counts}")
        return counts

    def _update_headcount_breakdown(
        self,
        ticker: str,
        snapshot_date: str,
        by_department: Dict = None,
        by_country: Dict = None,
        by_seniority: Dict = None,
        by_region: Dict = None,
    ) -> bool:
        """Update breakdown data for existing headcount record"""
        conn = self._get_connection()
        if not conn:
            return False

        try:
            cursor = conn.cursor()
            updates = []
            values = []

            if by_department:
                updates.append(
                    "by_department = COALESCE(by_department, '{}'::jsonb) || %s"
                )
                values.append(Json(by_department))
            if by_country:
                updates.append("by_country = COALESCE(by_country, '{}'::jsonb) || %s")
                values.append(Json(by_country))
            if by_seniority:
                updates.append(
                    "by_seniority = COALESCE(by_seniority, '{}'::jsonb) || %s"
                )
                values.append(Json(by_seniority))
            if by_region:
                updates.append("by_region = COALESCE(by_region, '{}'::jsonb) || %s")
                values.append(Json(by_region))

            if not updates:
                return False

            values.extend([ticker.upper(), snapshot_date])
            sql = f"""
                UPDATE company_headcount_history
                SET {', '.join(updates)}
                WHERE ticker = %s AND snapshot_date = %s
            """
            cursor.execute(sql, values)
            conn.commit()
            cursor.close()
            return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            print(f"⚠️  Error updating breakdown: {e}")
            return False

    def import_basic_company_data(self, data: Dict, ticker: str) -> bool:
        """
        Import basic company data (from /company_multi_source/collect endpoint)
        This only has current employee count, not historical data.

        Args:
            data: JSON data from basic company endpoint
            ticker: Stock ticker

        Returns:
            True if stored successfully
        """
        ticker = ticker.upper()
        emp_count = data.get("employees_count")

        if not emp_count:
            return False

        # Store as today's snapshot
        today = date.today().isoformat()
        return self.store_headcount(ticker, today, emp_count)

    # =========================================================================
    # UTILITY METHODS
    # =========================================================================

    def get_available_companies(self) -> List[Dict]:
        """
        Get list of available companies for growth metrics

        Returns:
            List of company info dicts
        """
        companies = []
        for ticker, data in CORESIGNAL_COMPANIES.items():
            companies.append(
                {
                    "ticker": ticker,
                    "name": data["name"],
                    "domain": data["domain"],
                    "has_coresignal_id": data["id"] is not None,
                    "coresignal_id": data["id"],
                }
            )
        return companies

    def is_valid_ticker(self, ticker: str) -> bool:
        """Check if ticker is in our curated list"""
        return ticker.upper() in CORESIGNAL_COMPANIES


# Global service instance
coresignal_service = CoreSignalService()
