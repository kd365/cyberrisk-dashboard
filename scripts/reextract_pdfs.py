#!/usr/bin/env python3
"""
Re-extract all PDF documents using the OCR service.

This script:
1. Finds all PDF artifacts in the database
2. Extracts text using the OCR service (Unstructured.io)
3. Saves clean TXT files to S3
4. Updates the artifacts table with new s3_keys

Usage:
    python scripts/reextract_pdfs.py [--ticker TICKER] [--dry-run]
"""

import os
import sys
import argparse
import logging
from datetime import datetime

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def reextract_pdfs(ticker: str = None, dry_run: bool = False):
    """Re-extract all PDFs using OCR service."""

    from services.database_service import db_service
    from services.ocr_service import get_ocr_service
    import boto3

    ocr = get_ocr_service()
    s3 = boto3.client("s3")
    bucket = os.environ.get("S3_BUCKET", "cyberrisk-dev-kh-artifacts-mslsw96u")

    # Get all PDF artifacts
    if ticker:
        query = """
            SELECT id, ticker, type, s3_key, date
            FROM artifacts
            WHERE s3_key LIKE '%.pdf' AND ticker = %s
            ORDER BY ticker, type, date DESC
        """
        artifacts = db_service.execute_query(query, (ticker,))
    else:
        query = """
            SELECT id, ticker, type, s3_key, date
            FROM artifacts
            WHERE s3_key LIKE '%.pdf'
            ORDER BY ticker, type, date DESC
        """
        artifacts = db_service.execute_query(query)

    logger.info(f"Found {len(artifacts)} PDF artifacts to process")

    results = {"success": [], "failed": [], "skipped": []}

    for artifact in artifacts:
        art_id, art_ticker, art_type, s3_key, art_date = artifact

        # Generate new TXT key
        txt_key = s3_key.replace(".pdf", "_ocr.txt")

        # Check if TXT already exists
        try:
            s3.head_object(Bucket=bucket, Key=txt_key)
            logger.info(f"  Skipping {s3_key} - TXT already exists")
            results["skipped"].append({"ticker": art_ticker, "s3_key": s3_key})
            continue
        except:
            pass  # File doesn't exist, proceed

        logger.info(f"Processing: {art_ticker} {art_type} ({s3_key})")

        if dry_run:
            logger.info(f"  [DRY RUN] Would extract to {txt_key}")
            results["success"].append({"ticker": art_ticker, "s3_key": s3_key})
            continue

        try:
            # Set bucket for OCR service
            ocr.bucket = bucket

            # Extract text
            text = ocr.extract_text_from_s3(s3_key, use_ocr=True, use_cache=False)

            if not text or len(text) < 100:
                logger.warning(f"  Extraction failed or too short for {s3_key}")
                results["failed"].append({
                    "ticker": art_ticker,
                    "s3_key": s3_key,
                    "error": "Extraction returned insufficient text"
                })
                continue

            # Check quality
            is_ok, reason = ocr.is_text_quality_acceptable(text)
            if not is_ok:
                logger.warning(f"  Quality check failed: {reason}")

            # Add header with metadata
            header = f"""SEC FILING (OCR Extracted): {art_type}
Ticker: {art_ticker}
Date: {art_date}
Source: OCR extraction from PDF
Extracted: {datetime.now().isoformat()}
--------------------------------------------------------------------------------

"""
            text = header + text

            # Upload to S3
            s3.put_object(
                Bucket=bucket,
                Key=txt_key,
                Body=text.encode("utf-8"),
                ContentType="text/plain"
            )

            logger.info(f"  Saved {len(text):,} chars to {txt_key}")

            # Create new artifact record for the TXT version
            insert_query = """
                INSERT INTO artifacts (ticker, name, type, s3_key, document_link, date, created_at)
                SELECT ticker, name, type, %s, %s, date, NOW()
                FROM artifacts WHERE id = %s
                ON CONFLICT DO NOTHING
            """
            db_service.execute_query(insert_query, (txt_key, txt_key, art_id))

            results["success"].append({
                "ticker": art_ticker,
                "s3_key": s3_key,
                "new_key": txt_key,
                "chars": len(text)
            })

        except Exception as e:
            logger.error(f"  Error processing {s3_key}: {e}")
            results["failed"].append({
                "ticker": art_ticker,
                "s3_key": s3_key,
                "error": str(e)
            })

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("EXTRACTION SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Success: {len(results['success'])}")
    logger.info(f"Failed:  {len(results['failed'])}")
    logger.info(f"Skipped: {len(results['skipped'])}")

    if results["failed"]:
        logger.info("\nFailed extractions:")
        for f in results["failed"]:
            logger.info(f"  {f['ticker']}: {f.get('error', 'Unknown error')}")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Re-extract PDFs using OCR")
    parser.add_argument("--ticker", help="Process only this ticker")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually extract")
    args = parser.parse_args()

    reextract_pdfs(ticker=args.ticker, dry_run=args.dry_run)
