#!/usr/bin/env python3
"""
Import Job Data from Query Results

Reads functionsquery.txt and seniorityquery.txt and imports
the job counts to company_jobs_snapshot table.

Usage:
    python3 import_jobs_from_queries.py

Requires:
    - DB_HOST, DB_NAME, DB_USER, DB_PASSWORD environment variables
    - functionsquery.txt and seniorityquery.txt in the same directory
"""

import os
import sys
from pathlib import Path
from datetime import date

# Add backend to path for importing services
backend_path = Path(__file__).parent.parent / 'backend'
sys.path.insert(0, str(backend_path))

# Load .env if present
try:
    from dotenv import load_dotenv
    env_path = backend_path / '.env'
    if env_path.exists():
        load_dotenv(env_path)
        print(f"Loaded .env from {env_path}")
except ImportError:
    pass

from services.coresignal_service import CoreSignalService, CACHED_EMPLOYEE_COUNTS

# Map company names to tickers
COMPANY_TO_TICKER = {
    'Zscaler': 'ZS',
    'Cloudflare': 'NET',
    'Crowdstrike': 'CRWD',
    'CrowdStrike': 'CRWD',
    'Palo Alto Networks': 'PANW',
    'Fortinet': 'FTNT',
    'Okta': 'OKTA',
    'SentinelOne': 'S',
    'CyberArk': 'CYBR',
    'Tenable': 'TENB',
    'Splunk': 'SPLK',
}


def parse_functions_file(filepath: str) -> dict:
    """Parse functionsquery.txt into dict by ticker"""
    result = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(',')
            if len(parts) != 3:
                continue
            company, function, count = parts
            ticker = COMPANY_TO_TICKER.get(company)
            if not ticker:
                print(f"  Unknown company: {company}")
                continue
            if ticker not in result:
                result[ticker] = {}
            result[ticker][function] = int(count)
    return result


def parse_seniority_file(filepath: str) -> dict:
    """Parse seniorityquery.txt into dict by ticker"""
    result = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(',')
            if len(parts) != 3:
                continue
            company, seniority, count = parts
            ticker = COMPANY_TO_TICKER.get(company)
            if not ticker:
                continue
            if ticker not in result:
                result[ticker] = {}
            result[ticker][seniority] = int(count)
    return result


def main():
    print("=" * 60)
    print("CoreSignal Jobs Query Data Importer")
    print("=" * 60)

    script_dir = Path(__file__).parent
    functions_file = script_dir / 'functionsquery.txt'
    seniority_file = script_dir / 'seniorityquery.txt'

    if not functions_file.exists() or not seniority_file.exists():
        print("\nERROR: Query files not found.")
        print(f"  Expected: {functions_file}")
        print(f"  Expected: {seniority_file}")
        return 1

    # Parse files
    print("\nParsing query files...")
    functions_data = parse_functions_file(str(functions_file))
    seniority_data = parse_seniority_file(str(seniority_file))

    print(f"  Functions data for {len(functions_data)} companies")
    print(f"  Seniority data for {len(seniority_data)} companies")

    # Initialize service
    service = CoreSignalService()

    if not service.connected:
        print("\nERROR: Could not connect to RDS.")
        print("Make sure these environment variables are set:")
        print("  - DB_HOST")
        print("  - DB_NAME")
        print("  - DB_USER")
        print("  - DB_PASSWORD")
        return 1

    # Import each company's job data
    today = date.today().isoformat()
    imported = 0

    all_tickers = set(functions_data.keys()) | set(seniority_data.keys())

    for ticker in sorted(all_tickers):
        jobs_by_function = functions_data.get(ticker, {})
        jobs_by_seniority = seniority_data.get(ticker, {})
        employee_count = CACHED_EMPLOYEE_COUNTS.get(ticker)

        total_by_func = sum(jobs_by_function.values())
        total_by_sen = sum(jobs_by_seniority.values())

        print(f"\n{ticker}:")
        print(f"  Jobs by function: {total_by_func} total across {len(jobs_by_function)} categories")
        print(f"  Jobs by seniority: {total_by_sen} total across {len(jobs_by_seniority)} levels")
        print(f"  Employee count: {employee_count}")

        if employee_count:
            intensity = round((total_by_func / employee_count) * 100, 2)
            print(f"  Hiring intensity: {intensity}%")

        success = service.store_jobs_snapshot(
            ticker=ticker,
            snapshot_date=today,
            jobs_by_function=jobs_by_function,
            jobs_by_seniority=jobs_by_seniority,
            employee_count=employee_count
        )

        if success:
            imported += 1
            print(f"  ✅ Stored in RDS")
        else:
            print(f"  ⚠️  Failed to store")

    print("\n" + "=" * 60)
    print("IMPORT COMPLETE")
    print("=" * 60)
    print(f"Successfully imported: {imported}/{len(all_tickers)} companies")

    # Summary table
    print("\n" + "=" * 60)
    print("ACTIVE JOB POSTINGS SUMMARY")
    print("=" * 60)
    print(f"{'Ticker':<8} {'Total Jobs':<12} {'Employees':<12} {'Intensity':<10}")
    print("-" * 42)
    for ticker in sorted(all_tickers):
        total = sum(functions_data.get(ticker, {}).values())
        emp = CACHED_EMPLOYEE_COUNTS.get(ticker, 0)
        intensity = round((total / emp) * 100, 2) if emp else 0
        print(f"{ticker:<8} {total:<12} {emp:<12} {intensity}%")

    return 0


if __name__ == '__main__':
    sys.exit(main())
