"""
Prioritized transcript scraper for top cybersecurity companies

Focuses on:
- Large-cap, well-known companies
- 2 years of earnings calls (8 quarters)
- Companies with robust SEC filing history
"""

from scraper import SecTranscriptScraper
from s3_service import S3ArtifactService
import pandas as pd


def main():
    print("=" * 70)
    print("🔄 PRIORITIZED TRANSCRIPT SCRAPER")
    print("=" * 70)

    scraper = SecTranscriptScraper()
    s3_service = S3ArtifactService()

    # Prioritized list of top cybersecurity companies
    # Ordered by market cap and prominence
    priority_tickers = [
        # Tier 1: Mega-cap leaders
        "CRWD",  # CrowdStrike - $80B+ market cap, leader in endpoint security
        "PANW",  # Palo Alto Networks - $100B+ market cap, firewall/security platform leader
        "FTNT",  # Fortinet - $50B+ market cap, network security leader
        "ZS",  # Zscaler - $30B+ market cap, cloud security leader
        # Tier 2: Large-cap established players
        "CSCO",  # Cisco - Networking giant with security division
        "CHKP",  # Check Point - $15B+ market cap, firewall pioneer
        "CYBR",  # CyberArk - $10B+ market cap, privileged access management
        "OKTA",  # Okta - $10B+ market cap, identity management leader
        "NET",  # Cloudflare - $30B+ market cap, web security/CDN
        "S",  # SentinelOne - $6B+ market cap, endpoint security
        # Tier 3: Mid-cap specialized players
        "TENB",  # Tenable - $5B+ market cap, vulnerability management
        "QLYS",  # Qualys - $4B+ market cap, cloud security/compliance
        "VRNS",  # Varonis - Data security specialist
        "SAIL",  # SailPoint - Identity governance
        "RPD",  # Rapid7 - Security analytics
    ]

    print(f"\n📋 Prioritized list: {len(priority_tickers)} top companies")
    print(f"📊 Fetching up to 20 SEC filings per company (10-K and 10-Q)")
    print(f"📞 Fetching 8 quarters (2 years) of transcripts per company")
    print(f"⏱️  Estimated time: ~{len(priority_tickers) * 8 * 1.5 / 60:.0f} minutes")
    print(f"📈 API usage: ~{len(priority_tickers) * 8} requests (free tier: 25/day)")

    # Calculate how many companies we can do per day
    companies_per_day = 25 // 8  # 25 requests / 8 quarters = 3 companies per day
    print(
        f"\n💡 With free tier (25 requests/day): ~{companies_per_day} companies per day"
    )
    print(
        f"💡 Total time to complete: ~{len(priority_tickers) / companies_per_day:.0f} days"
    )

    all_artifacts = []
    request_count = 0
    daily_limit = 25

    for idx, ticker in enumerate(priority_tickers, 1):
        print(f"\n{'='*70}")
        print(f"[{idx}/{len(priority_tickers)}] Processing {ticker}")
        print(f"{'='*70}")

        # Scrape SEC filings (no API limit)
        sec_filings = scraper.scrape_sec_filings(ticker, num_filings=20)

        # Check if we're approaching daily limit
        if request_count >= daily_limit:
            print(f"\n⚠️  Reached daily API limit ({daily_limit} requests)")
            print(f"✅ Processed {idx-1} companies today")
            print(f"🔄 Resume tomorrow to continue with {ticker} and beyond")
            break

        # Fetch earnings call transcripts (8 quarters = 2 years)
        transcripts = scraper.scrape_earnings_transcripts(ticker, num_quarters=8)

        # Count actual API requests made (not skipped transcripts)
        new_transcripts = len([t for t in transcripts if t])
        request_count += new_transcripts

        print(f"  📊 API requests used: {request_count}/{daily_limit}")

        # Save raw SEC files
        if sec_filings:
            scraper.save_raw_files(sec_filings)

        all_artifacts.extend(sec_filings)
        all_artifacts.extend(transcripts)

        # Check if approaching limit
        if request_count >= daily_limit - 8:
            print(f"\n⚠️  Approaching daily limit - stopping after this company")
            break

    # Generate artifacts CSV from all files in S3
    companies = s3_service.get_companies()
    companies_df = pd.DataFrame(companies)

    print(f"\n{'='*70}")
    print("📊 Generating artifacts CSV...")
    scraper.generate_artifacts_csv(companies_df)

    print("\n" + "=" * 70)
    print(f"✅ SCRAPING COMPLETE")
    print(f"📄 SEC filings collected: {len([a for a in all_artifacts if 'form' in a])}")
    print(
        f"📞 Transcripts collected: {len([a for a in all_artifacts if a.get('type') == 'transcript'])}"
    )
    print(f"🔢 Total API requests used: {request_count}/{daily_limit}")
    print("=" * 70)


if __name__ == "__main__":
    main()
