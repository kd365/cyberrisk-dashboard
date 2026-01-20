#!/usr/bin/env python3
"""
Load CoreSignal Growth Data into RDS

This script loads:
1. Historical headcount data from CSV (headcount_3companies.csv)
2. Jobs data from cached values
3. Additional data from JSON files if needed

Usage:
    python load_growth_data.py

Environment variables required:
    DB_HOST, DB_NAME, DB_USER, DB_PASSWORD
"""

import os
import sys
import json
import csv
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

try:
    import psycopg2
    from psycopg2.extras import Json
except ImportError:
    print("Error: psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)


# Pre-cached job data (Dec 2024)
CACHED_JOBS_BY_FUNCTION = {
    "CRWD": {
        "Engineering": 517,
        "Sales": 278,
        "Information Technology": 766,
        "Marketing": 35,
        "Finance": 13,
        "Human Resources": 8,
        "Product Management": 59,
        "Research": 8,
        "Legal": 8,
        "Operations": 0,
        "Customer Service": 0,
        "Administrative": 1,
    },
    "ZS": {
        "Engineering": 97,
        "Sales": 131,
        "Information Technology": 149,
        "Marketing": 18,
        "Finance": 15,
        "Human Resources": 10,
        "Product Management": 22,
        "Research": 4,
        "Legal": 2,
        "Operations": 0,
        "Customer Service": 0,
        "Administrative": 0,
    },
    "NET": {
        "Engineering": 331,
        "Sales": 217,
        "Information Technology": 293,
        "Marketing": 88,
        "Finance": 16,
        "Human Resources": 7,
        "Product Management": 74,
        "Research": 0,
        "Legal": 13,
        "Operations": 0,
        "Customer Service": 28,
        "Administrative": 3,
    },
}

CACHED_JOBS_BY_SENIORITY = {
    "CRWD": {
        "Entry level": 64,
        "Associate": 29,
        "Mid-Senior level": 926,
        "Director": 47,
        "Executive": 2,
    },
    "ZS": {
        "Entry level": 10,
        "Associate": 0,
        "Mid-Senior level": 267,
        "Director": 26,
        "Executive": 1,
    },
    "NET": {
        "Entry level": 27,
        "Associate": 229,
        "Mid-Senior level": 513,
        "Director": 24,
        "Executive": 10,
    },
}

# Latest employee counts (Nov 2025)
EMPLOYEE_COUNTS = {"CRWD": 10746, "ZS": 8984, "NET": 6246}


def get_db_connection():
    """Get database connection from environment variables"""
    db_host = os.environ.get("DB_HOST")
    db_name = os.environ.get("DB_NAME", "cyberrisk")
    db_user = os.environ.get("DB_USER", "cyberrisk_admin")
    db_password = os.environ.get("DB_PASSWORD")

    if not db_host or not db_password:
        print("Error: Database credentials not configured")
        print("Set DB_HOST, DB_NAME, DB_USER, DB_PASSWORD environment variables")
        sys.exit(1)

    try:
        conn = psycopg2.connect(
            host=db_host,
            database=db_name,
            user=db_user,
            password=db_password,
            port=5432,
        )
        print(f"Connected to RDS at {db_host}")
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}")
        sys.exit(1)


def ensure_tables_exist(conn):
    """Create growth data tables if they don't exist"""
    cursor = conn.cursor()

    # Headcount history table
    cursor.execute("""
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
    """)

    # Jobs snapshot table
    cursor.execute("""
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
    """)

    conn.commit()
    cursor.close()
    print("Tables created/verified")


def load_headcount_csv(conn, csv_path: str):
    """Load headcount data from CSV file"""
    if not os.path.exists(csv_path):
        print(f"CSV file not found: {csv_path}")
        return 0

    cursor = conn.cursor()
    count = 0

    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticker = row["ticker"]
            date_str = row["date"]
            employee_count = int(row["employees_count"])

            try:
                cursor.execute(
                    """
                    INSERT INTO company_headcount_history (ticker, snapshot_date, employee_count, data_source)
                    VALUES (%s, %s, %s, 'coresignal_csv')
                    ON CONFLICT (ticker, snapshot_date)
                    DO UPDATE SET employee_count = EXCLUDED.employee_count
                """,
                    (ticker, date_str, employee_count),
                )
                count += 1
            except Exception as e:
                print(f"Error inserting row: {e}")
                conn.rollback()

    conn.commit()
    cursor.close()
    print(f"Loaded {count} headcount records from CSV")
    return count


def load_jobs_data(conn):
    """Load cached jobs data"""
    cursor = conn.cursor()
    snapshot_date = "2024-12-28"
    count = 0

    for ticker in CACHED_JOBS_BY_FUNCTION:
        jobs_func = CACHED_JOBS_BY_FUNCTION[ticker]
        jobs_sen = CACHED_JOBS_BY_SENIORITY.get(ticker, {})
        emp_count = EMPLOYEE_COUNTS.get(ticker)

        total_jobs = sum(jobs_func.values())
        hiring_intensity = (
            round((total_jobs / emp_count) * 100, 2) if emp_count else None
        )

        try:
            cursor.execute(
                """
                INSERT INTO company_jobs_snapshot
                (ticker, snapshot_date, jobs_by_function, jobs_by_seniority, total_jobs, employee_count, hiring_intensity, data_source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'coresignal_cached')
                ON CONFLICT (ticker, snapshot_date)
                DO UPDATE SET
                    jobs_by_function = EXCLUDED.jobs_by_function,
                    jobs_by_seniority = EXCLUDED.jobs_by_seniority,
                    total_jobs = EXCLUDED.total_jobs,
                    employee_count = EXCLUDED.employee_count,
                    hiring_intensity = EXCLUDED.hiring_intensity
            """,
                (
                    ticker,
                    snapshot_date,
                    Json(jobs_func),
                    Json(jobs_sen),
                    total_jobs,
                    emp_count,
                    hiring_intensity,
                ),
            )
            count += 1
        except Exception as e:
            print(f"Error inserting jobs for {ticker}: {e}")
            conn.rollback()

    conn.commit()
    cursor.close()
    print(f"Loaded {count} jobs snapshots")
    return count


def load_json_data(conn, json_dir: str):
    """Load additional data from JSON files (department/country/seniority breakdowns)"""
    json_files = {
        "CRWD": "crowdstrike.json",
        "ZS": "zscaler.json",
        "NET": "cloudflare.json",
    }

    cursor = conn.cursor()
    count = 0

    for ticker, filename in json_files.items():
        filepath = os.path.join(json_dir, filename)
        if not os.path.exists(filepath):
            print(f"JSON file not found: {filepath}")
            continue

        print(f"Processing {filename}...")

        try:
            with open(filepath, "r") as f:
                data = json.load(f)

            # Extract monthly breakdowns and update existing headcount records
            dept_by_month = {}
            country_by_month = {}
            seniority_by_month = {}
            region_by_month = {}

            # Department breakdown
            for record in data.get(
                "employees_count_breakdown_by_department_by_month", []
            ):
                date_str = record.get("date")
                if date_str and len(date_str) == 6:
                    date_str = f"{date_str[:4]}-{date_str[4:6]}-01"
                breakdown = record.get("employees_count_breakdown_by_department", {})
                cleaned = {}
                for k, v in breakdown.items():
                    if v is not None:
                        dept = k.replace("employees_count_", "")
                        cleaned[dept] = v
                if cleaned:
                    dept_by_month[date_str] = cleaned

            # Country breakdown
            for record in data.get("employees_count_by_country_by_month", []):
                date_str = record.get("date")
                if date_str and len(date_str) == 6:
                    date_str = f"{date_str[:4]}-{date_str[4:6]}-01"
                countries = record.get("employees_count_by_country", [])
                country_data = {
                    item["country"]: item["employee_count"] for item in countries
                }
                if country_data:
                    country_by_month[date_str] = country_data

            # Seniority breakdown
            for record in data.get(
                "employees_count_breakdown_by_seniority_by_month", []
            ):
                date_str = record.get("date")
                if date_str and len(date_str) == 6:
                    date_str = f"{date_str[:4]}-{date_str[4:6]}-01"
                breakdown = record.get("employees_count_breakdown_by_seniority", {})
                cleaned = {}
                for k, v in breakdown.items():
                    if v is not None:
                        level = k.replace("employees_count_", "")
                        cleaned[level] = v
                if cleaned:
                    seniority_by_month[date_str] = cleaned

            # Region breakdown
            for record in data.get("employees_count_breakdown_by_region_by_month", []):
                date_str = record.get("date")
                if date_str and len(date_str) == 6:
                    date_str = f"{date_str[:4]}-{date_str[4:6]}-01"
                breakdown = record.get("employees_count_breakdown_by_region", {})
                cleaned = {}
                for k, v in breakdown.items():
                    if v is not None:
                        region = k.replace("employees_count_", "")
                        cleaned[region] = v
                if cleaned:
                    region_by_month[date_str] = cleaned

            # Update existing records with breakdown data
            all_dates = (
                set(dept_by_month.keys())
                | set(country_by_month.keys())
                | set(seniority_by_month.keys())
                | set(region_by_month.keys())
            )

            for date_str in all_dates:
                dept = dept_by_month.get(date_str)
                country = country_by_month.get(date_str)
                seniority = seniority_by_month.get(date_str)
                region = region_by_month.get(date_str)

                cursor.execute(
                    """
                    UPDATE company_headcount_history
                    SET by_department = COALESCE(%s, by_department),
                        by_country = COALESCE(%s, by_country),
                        by_seniority = COALESCE(%s, by_seniority),
                        by_region = COALESCE(%s, by_region)
                    WHERE ticker = %s AND snapshot_date = %s
                """,
                    (
                        Json(dept) if dept else None,
                        Json(country) if country else None,
                        Json(seniority) if seniority else None,
                        Json(region) if region else None,
                        ticker,
                        date_str,
                    ),
                )
                count += 1

            conn.commit()
            print(f"  Updated {len(all_dates)} records with breakdowns for {ticker}")

        except Exception as e:
            print(f"Error processing {filename}: {e}")
            conn.rollback()

    cursor.close()
    print(f"Processed JSON breakdown data")
    return count


def verify_data(conn):
    """Print summary of loaded data"""
    cursor = conn.cursor()

    print("\n" + "=" * 60)
    print("DATA VERIFICATION")
    print("=" * 60)

    # Headcount records
    cursor.execute("""
        SELECT ticker, COUNT(*) as records, MIN(snapshot_date) as earliest, MAX(snapshot_date) as latest
        FROM company_headcount_history
        GROUP BY ticker
        ORDER BY ticker
    """)
    print("\nHeadcount History:")
    for row in cursor.fetchall():
        print(f"  {row[0]}: {row[1]} records ({row[2]} to {row[3]})")

    # Jobs snapshots
    cursor.execute("""
        SELECT ticker, snapshot_date, total_jobs, hiring_intensity
        FROM company_jobs_snapshot
        ORDER BY ticker
    """)
    print("\nJobs Snapshots:")
    for row in cursor.fetchall():
        print(f"  {row[0]}: {row[2]} jobs, {row[3]}% intensity (as of {row[1]})")

    cursor.close()


def main():
    # Get script directory for relative paths
    script_dir = Path(__file__).parent.parent
    docs_dir = script_dir / "docs"

    csv_path = docs_dir / "headcount_3companies.csv"

    print("=" * 60)
    print("CoreSignal Growth Data Loader")
    print("=" * 60)

    # Connect to database
    conn = get_db_connection()

    # Create tables
    ensure_tables_exist(conn)

    # Load CSV headcount data
    print("\n--- Loading headcount CSV ---")
    load_headcount_csv(conn, str(csv_path))

    # Load cached jobs data
    print("\n--- Loading jobs data ---")
    load_jobs_data(conn)

    # Load JSON breakdown data
    print("\n--- Loading JSON breakdown data ---")
    load_json_data(conn, str(docs_dir))

    # Verify
    verify_data(conn)

    conn.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
