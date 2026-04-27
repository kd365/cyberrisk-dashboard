#!/usr/bin/env python3
"""
Sync S3 SEC filings into the PostgreSQL artifacts table.

The scrape pipeline writes raw filings to s3://.../raw/sec/{TICKER}_{FORM}_{DATE}.{txt|pdf}
but historically did not register them in the artifacts table. This script closes
that gap by listing S3 and inserting any keys missing from the DB.

For 10-K and 10-Q filings, db_service.create_artifact() automatically triggers
financial extraction via the recently-added hook, populating filing_financials too.

Idempotent — safe to re-run. Existing rows are skipped, not duplicated.

Usage:
    docker exec cyberrisk-backend python /app/scripts/sync_s3_to_db.py
    docker exec cyberrisk-backend python /app/scripts/sync_s3_to_db.py --type 8-K
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
from services.database_service import db_service


# Match filenames like CRWD_10-K_2025-03-10.pdf, ZS_8-K_2026-02-26.txt, etc.
FILENAME_RE = re.compile(
    r"^(?P<ticker>[A-Z]+)_(?P<form>10-K|10-Q|8-K)_(?P<date>\d{4}-\d{2}-\d{2})\.(txt|pdf)$"
)


def list_sec_keys(bucket: str) -> list:
    """List all raw/sec/ keys from S3."""
    s3 = boto3.client("s3", region_name="us-west-2")
    paginator = s3.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=bucket, Prefix="raw/sec/"):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return keys


def sync(filing_type_filter: str = None) -> dict:
    bucket = os.environ.get(
        "ARTIFACTS_BUCKET",
        os.environ.get("S3_BUCKET", "cyberrisk-dev-kh-artifacts-mslsw96u"),
    )
    print(f"Listing S3 bucket: {bucket}")
    keys = list_sec_keys(bucket)
    print(f"Found {len(keys)} files in raw/sec/")

    # Pre-load all existing artifact s3_keys to skip in O(1)
    conn = db_service._get_connection()
    cur = conn.cursor()
    cur.execute("SELECT s3_key FROM artifacts")
    existing_keys = {row[0] for row in cur.fetchall()}
    cur.close()
    print(f"Existing artifact rows: {len(existing_keys)}")

    stats = {
        "inserted": 0,
        "skipped": 0,
        "unparseable": 0,
        "missing_company": 0,
        "extract_failed": 0,
        "by_type": {},
    }

    for key in keys:
        filename = key.split("/")[-1]
        m = FILENAME_RE.match(filename)
        if not m:
            stats["unparseable"] += 1
            continue

        ticker = m.group("ticker")
        form = m.group("form")
        date = m.group("date")

        if filing_type_filter and form != filing_type_filter:
            continue

        if key in existing_keys:
            stats["skipped"] += 1
            continue

        # create_artifact validates company exists and inserts row.
        # For 10-K/10-Q it also triggers financial extraction via the hook.
        try:
            result = db_service.create_artifact(ticker, form, key, date)
            if result:
                stats["inserted"] += 1
                stats["by_type"][form] = stats["by_type"].get(form, 0) + 1
            else:
                # create_artifact returns None if company missing or insert failed
                stats["missing_company"] += 1
        except Exception as e:
            print(f"  ❌ {key}: {e}")
            stats["extract_failed"] += 1

    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--type",
        choices=["10-K", "10-Q", "8-K"],
        help="Restrict sync to one filing type (default: all)",
    )
    args = parser.parse_args()

    stats = sync(filing_type_filter=args.type)
    print()
    print("=" * 60)
    print(f"  Inserted:        {stats['inserted']}")
    for form, n in sorted(stats["by_type"].items()):
        print(f"    {form}: {n}")
    print(f"  Already in DB:   {stats['skipped']}")
    print(f"  Unparseable:     {stats['unparseable']}")
    print(f"  Missing company: {stats['missing_company']}")
    print(f"  Extract failed:  {stats['extract_failed']}")
    print("=" * 60)
