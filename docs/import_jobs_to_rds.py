#!/usr/bin/env python3
"""
Import CoreSignal Job Data to RDS

Reads jobs_data.json (output from fetch_jobs_data.sh) and imports
the job counts to company_jobs_snapshot table.

Usage:
    python3 import_jobs_to_rds.py

Requires:
    - DB_HOST, DB_NAME, DB_USER, DB_PASSWORD environment variables
    - jobs_data.json in the same directory
"""

import os
import sys
import json
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


def main():
    print("=" * 60)
    print("CoreSignal Jobs Data to RDS Importer")
    print("=" * 60)

    # Load jobs data
    script_dir = Path(__file__).parent
    jobs_file = script_dir / 'jobs_data.json'

    if not jobs_file.exists():
        print(f"\nERROR: {jobs_file} not found.")
        print("Run fetch_jobs_data.sh first to fetch job data from CoreSignal.")
        return 1

    with open(jobs_file) as f:
        data = json.load(f)

    print(f"Loaded jobs data from {jobs_file}")
    print(f"Fetched at: {data.get('fetched_at', 'unknown')}")

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
    companies_data = data.get('companies', {})
    imported = 0

    for ticker, job_data in companies_data.items():
        jobs_by_function = job_data.get('jobs_by_function', {})
        jobs_by_seniority = job_data.get('jobs_by_seniority', {})
        employee_count = CACHED_EMPLOYEE_COUNTS.get(ticker)

        print(f"\n{ticker}:")
        print(f"  Jobs by function: {sum(jobs_by_function.values())} total")
        print(f"  Jobs by seniority: {sum(jobs_by_seniority.values())} total")
        print(f"  Employee count: {employee_count}")

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
    print(f"Successfully imported: {imported}/{len(companies_data)} companies")

    return 0


if __name__ == '__main__':
    sys.exit(main())
