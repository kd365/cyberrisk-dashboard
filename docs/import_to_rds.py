#!/usr/bin/env python3
"""
Import CoreSignal JSON data files to RDS

This script reads enriched company JSON files and imports the time-series
data into the company_headcount_history table.

Usage:
    python import_to_rds.py

Requires:
    - DB_HOST, DB_NAME, DB_USER, DB_PASSWORD environment variables
    - Or .env file with these variables
"""

import os
import sys
from pathlib import Path

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

from services.coresignal_service import CoreSignalService

# Company JSON files to ticker mapping
COMPANY_FILES = {
    'crowdstrike.json': 'CRWD',
    'zscaler.json': 'ZS',
    'cloudflare.json': 'NET',
    'paloaltonetworks.json': 'PANW',
    'fortinet.json': 'FTNT',
    'okta.json': 'OKTA',
    'sentinelone.json': 'S',
    'cyberark.json': 'CYBR',
    'tenable.json': 'TENB',
    'splunk.json': 'SPLK',
}


def main():
    print("=" * 60)
    print("CoreSignal JSON to RDS Importer")
    print("=" * 60)

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

    # Find JSON files
    docs_dir = Path(__file__).parent
    total_imported = {'headcount': 0, 'by_department': 0, 'by_country': 0, 'by_seniority': 0}

    for filename, ticker in COMPANY_FILES.items():
        filepath = docs_dir / filename
        if filepath.exists():
            print(f"\nProcessing {filename} -> {ticker}")
            result = service.import_from_json_file(str(filepath), ticker)

            if 'error' in result:
                print(f"  ERROR: {result['error']}")
            else:
                for key, count in result.items():
                    total_imported[key] = total_imported.get(key, 0) + count
                print(f"  Imported: {result}")
        else:
            print(f"\nSkipping {filename} (not found)")

    print("\n" + "=" * 60)
    print("IMPORT COMPLETE")
    print("=" * 60)
    print(f"Total headcount records: {total_imported['headcount']}")
    print(f"Department breakdowns:   {total_imported['by_department']}")
    print(f"Country breakdowns:      {total_imported['by_country']}")
    print(f"Seniority breakdowns:    {total_imported['by_seniority']}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
