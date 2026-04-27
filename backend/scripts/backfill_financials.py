#!/usr/bin/env python3
"""
One-time backfill: parse every existing 10-K/10-Q in the artifacts table and
populate filing_financials so /api/financials/<ticker> no longer re-parses at
request time.

Idempotent — UNIQUE(s3_key) on filing_financials means re-running updates
existing rows rather than creating duplicates.

Usage (from backend/ as cwd, or inside the container):
    python scripts/backfill_financials.py              # all tickers
    python scripts/backfill_financials.py --ticker CRWD
    python scripts/backfill_financials.py --dry-run

In production (Docker), run via SSM:
    docker exec cyberrisk-backend python /app/scripts/backfill_financials.py
"""

import os
import sys
import argparse
import time

# Add the parent directory (backend/) to path so services.* imports resolve.
# Script lives at backend/scripts/backfill_financials.py — go up one level.
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from services.database_service import db_service
from services.s3_service import S3ArtifactService
from services.financial_html_extractor import FinancialHtmlExtractor


def backfill(ticker_filter: str = None, dry_run: bool = False) -> dict:
    s3_service = S3ArtifactService()
    extractor = FinancialHtmlExtractor()

    artifacts = s3_service.get_artifacts_table()
    filings = [
        a
        for a in artifacts
        if a.get("type") in ("10-K", "10-Q")
        and (ticker_filter is None or a.get("ticker") == ticker_filter.upper())
    ]

    print(f"Found {len(filings)} 10-K/10-Q filings to process")
    if dry_run:
        print("DRY RUN — not writing to DB")

    stats = {"processed": 0, "stored": 0, "empty": 0, "failed": 0}
    start = time.time()

    for i, filing in enumerate(filings, 1):
        ticker = filing.get("ticker")
        s3_key = filing.get("s3_key")
        filing_type = filing.get("type")
        filing_date = filing.get("date")

        if not all([ticker, s3_key, filing_type, filing_date]):
            stats["failed"] += 1
            continue

        print(f"[{i}/{len(filings)}] {ticker} {filing_type} {filing_date}")

        try:
            financials = extractor.extract_financials_from_html_filing(
                s3_key, filing_date
            )
            stats["processed"] += 1

            has_data = financials and any(
                financials.get(k)
                for k in (
                    "revenue",
                    "subscription_revenue",
                    "net_income",
                    "operating_income",
                )
            )
            if not has_data:
                stats["empty"] += 1
                continue

            if not dry_run:
                ok = db_service.upsert_filing_financials(
                    ticker, s3_key, filing_type, filing_date, financials
                )
                if ok:
                    stats["stored"] += 1
                else:
                    stats["failed"] += 1
            else:
                stats["stored"] += 1  # would-have-stored

        except Exception as e:
            print(f"  Failed: {e}")
            stats["failed"] += 1

    elapsed = time.time() - start
    print(
        f"\nDone in {elapsed:.1f}s — processed={stats['processed']}, "
        f"stored={stats['stored']}, empty={stats['empty']}, failed={stats['failed']}"
    )
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", help="Only process one ticker (e.g. CRWD)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    backfill(ticker_filter=args.ticker, dry_run=args.dry_run)
