#!/usr/bin/env python3
"""
Test script for the new 8-K event extraction
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.data_enrichment_service import SEC8KEventExtractor


def test_single_company(ticker: str):
    """Test extraction for a single company."""
    print(f"\n{'='*60}")
    print(f"Testing 8-K extraction for {ticker}")
    print(f"{'='*60}")

    extractor = SEC8KEventExtractor()
    result = extractor.extract_all_events(ticker)

    print(f"\nResults for {ticker}:")
    print(f"  Executive Events: {len(result['executive_events'])}")
    print(f"  M&A Events:       {len(result['ma_events'])}")
    print(f"  Security Events:  {len(result['security_events'])}")
    print(f"  Restructuring:    {len(result['restructuring_events'])}")

    # Print sample events
    if result['executive_events']:
        print(f"\n  Sample Executive Event:")
        evt = result['executive_events'][0]
        print(f"    - {evt.get('event_type')}: {evt.get('person_name')} as {evt.get('title')}")

    if result['ma_events']:
        print(f"\n  Sample M&A Event:")
        evt = result['ma_events'][0]
        print(f"    - {evt.get('event_type')}: {evt.get('summary', 'N/A')[:80]}")

    if result['security_events']:
        print(f"\n  Sample Security Event:")
        evt = result['security_events'][0]
        print(f"    - {evt.get('event_type')} ({evt.get('severity')}): {evt.get('summary', 'N/A')[:80]}")

    return result


def run_all_companies():
    """Run extraction for all companies."""
    extractor = SEC8KEventExtractor()
    results = extractor.enrich_all_companies()

    print(f"\n{'='*60}")
    print("EXTRACTION COMPLETE")
    print(f"{'='*60}")
    print(f"Total Executive Events: {results['totals']['executive_events']}")
    print(f"Total M&A Events:       {results['totals']['ma_events']}")
    print(f"Total Security Events:  {results['totals']['security_events']}")
    print(f"Total Restructuring:    {results['totals']['restructuring_events']}")

    return results


if __name__ == "__main__":
    if len(sys.argv) > 1:
        ticker = sys.argv[1].upper()
        if ticker == "ALL":
            run_all_companies()
        else:
            test_single_company(ticker)
    else:
        # Default: test FTNT
        test_single_company("FTNT")
