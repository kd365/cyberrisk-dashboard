#!/usr/bin/env python3
"""
Sync 8-K files from S3 to database

This script scans S3 for 8-K filings and registers them in the artifacts table.
"""

import boto3
import os
import re
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.database_service import db_service


def sync_8k_files():
    """Sync 8-K files from S3 to database."""
    bucket = os.environ.get("S3_BUCKET", "cyberrisk-dev-kh-artifacts-mslsw96u")
    s3 = boto3.client("s3", region_name="us-west-2")

    # List all 8-K files in S3
    paginator = s3.get_paginator("list_objects_v2")
    eightk_files = []
    for page in paginator.paginate(Bucket=bucket, Prefix="raw/sec/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if "8-K" in key:
                eightk_files.append(key)

    print(f"Found {len(eightk_files)} 8-K files in S3")

    # Parse and insert each one
    inserted = 0
    skipped = 0
    errors = 0

    for s3_key in eightk_files:
        # Parse: raw/sec/TICKER_8-K_YYYY-MM-DD.txt (or .pdf for legacy)
        filename = s3_key.split("/")[-1]
        match = re.match(r"([A-Z]+)_8-K_(\d{4}-\d{2}-\d{2})\.(txt|pdf)", filename)
        if match:
            ticker = match.group(1)
            date = match.group(2)

            # Check if company exists
            company = db_service.get_company(ticker)
            if not company:
                print(f"⚠️  Company not found: {ticker}, skipping")
                skipped += 1
                continue

            # Check if artifact already exists
            existing = db_service.get_artifacts_by_ticker(ticker)
            if any(a.get("s3_key") == s3_key for a in existing):
                skipped += 1
                continue

            result = db_service.create_artifact(ticker, "8-K", s3_key, date)
            if result:
                inserted += 1
                print(f"✅ Inserted: {ticker} 8-K {date}")
            else:
                errors += 1
        else:
            print(f"⚠️  Could not parse filename: {filename}")
            errors += 1

    print(f"\n{'='*50}")
    print(f"Sync complete:")
    print(f"  Inserted: {inserted}")
    print(f"  Skipped:  {skipped}")
    print(f"  Errors:   {errors}")
    print(f"  Total:    {len(eightk_files)}")

    return {"inserted": inserted, "skipped": skipped, "errors": errors}


if __name__ == "__main__":
    sync_8k_files()
