#!/usr/bin/env python3
"""
Extract structured events from all 8-K filings for every tracked company.

Calls SEC8KEventExtractor.extract_all_events(ticker) to parse Items 1.01,
1.02, 2.01, 2.05, 5.02, and 8.01 from every 8-K in the artifacts table.
Writes the resulting events into Neo4j as MAEvent, ExecutiveEvent,
SecurityEvent, RestructuringEvent nodes (with relationships to the
filing organization and any counterparty organizations mentioned).

Idempotent at the LLM-extraction level (re-running re-parses the same
8-Ks and produces the same events), but Neo4j CREATE statements will
add duplicate event nodes if run twice. Recommended to delete prior
event nodes before re-running, or accept the duplicates.

Usage:
    docker exec cyberrisk-backend python /app/scripts/extract_8k_events_all.py
    docker exec cyberrisk-backend python /app/scripts/extract_8k_events_all.py --ticker CRWD

Cost: ~$0.50-1 in Bedrock Haiku calls for ~230 8-Ks.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.data_enrichment_service import SEC8KEventExtractor
from services.database_service import db_service


def extract_for_ticker(extractor: SEC8KEventExtractor, ticker: str) -> dict:
    """Run extraction + Neo4j writes for one ticker."""
    print(f"\n=== {ticker} ===")
    events = extractor.extract_all_events(ticker)

    counts = {
        "executive": len(events["executive_events"]),
        "ma": len(events["ma_events"]),
        "security": len(events["security_events"]),
        "restructuring": len(events["restructuring_events"]),
    }
    print(f"Extracted: {counts}")

    # Persist to Neo4j
    if events["ma_events"]:
        n = extractor.create_ma_events(ticker, events["ma_events"])
        print(f"  Stored {n} MAEvent nodes")
        counts["ma_stored"] = n

    if events["security_events"]:
        n = extractor.create_security_events(ticker, events["security_events"])
        print(f"  Stored {n} SecurityEvent nodes")
        counts["security_stored"] = n

    if events["restructuring_events"]:
        n = extractor.create_restructuring_events(
            ticker, events["restructuring_events"]
        )
        print(f"  Stored {n} RestructuringEvent nodes")
        counts["restructuring_stored"] = n

    # Executive events are already created by extract_executive_events()
    # via its own create_executive_events helper. Call separately.
    if events["executive_events"]:
        n = extractor.create_executive_events(ticker)
        if isinstance(n, dict):
            n = n.get("created", 0)
        print(f"  Stored {n} ExecutiveEvent nodes")
        counts["executive_stored"] = n

    return counts


def main(ticker_filter: str = None):
    extractor = SEC8KEventExtractor()

    # Find tickers that have 8-Ks
    conn = db_service._get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT c.ticker, COUNT(*) as cnt
        FROM artifacts a JOIN companies c ON a.company_id = c.id
        WHERE a.artifact_type = '8-K'
        GROUP BY c.ticker
        ORDER BY cnt DESC
        """
    )
    tickers_with_8k = [(r[0], r[1]) for r in cur.fetchall()]
    cur.close()

    if ticker_filter:
        tickers_with_8k = [
            (t, c) for t, c in tickers_with_8k if t == ticker_filter.upper()
        ]

    total_8ks = sum(c for _, c in tickers_with_8k)
    print(f"Processing {len(tickers_with_8k)} tickers with {total_8ks} total 8-Ks")
    print(f"Estimated time: ~{total_8ks // 4} minutes (~$0.50-1 Bedrock cost)")

    start = time.time()
    summary = {
        "tickers_processed": 0,
        "totals": {"ma": 0, "security": 0, "executive": 0, "restructuring": 0},
    }

    for i, (ticker, cnt) in enumerate(tickers_with_8k, 1):
        print(f"\n[{i}/{len(tickers_with_8k)}] {ticker} ({cnt} 8-Ks)")
        try:
            counts = extract_for_ticker(extractor, ticker)
            summary["tickers_processed"] += 1
            for k in ("ma", "security", "executive", "restructuring"):
                summary["totals"][k] += counts.get(k, 0)
        except Exception as e:
            print(f"  Failed: {e}")

    elapsed = time.time() - start
    print(f"\n{'='*60}")
    print(f"Done in {elapsed/60:.1f} min")
    print(f"Tickers processed: {summary['tickers_processed']}/{len(tickers_with_8k)}")
    print(f"Events extracted (across all tickers):")
    for k, v in summary["totals"].items():
        print(f"  {k}: {v}")
    print(f"{'='*60}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", help="Process only one ticker (e.g. CRWD)")
    args = parser.parse_args()
    main(ticker_filter=args.ticker)
