#!/usr/bin/env python3
"""
Classify Companies with Cybersecurity Taxonomy

This script updates all companies in the RDS database with proper
cybersecurity sector classifications. It uses known mappings for
common companies and can optionally use LLM to classify unknown ones.

Usage:
    python scripts/classify_companies.py [--dry-run] [--use-llm]

Requirements:
    - Database connection (uses same env vars as backend)
    - Optional: AWS Bedrock access for LLM classification
"""

import os
import sys
import argparse
from typing import Dict, List, Optional

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import psycopg2
from psycopg2.extras import RealDictCursor

# =============================================================================
# Known Company Classifications
# =============================================================================
# These are well-known cybersecurity companies with verified classifications

KNOWN_CLASSIFICATIONS = {
    # Endpoint Security
    "CRWD": {
        "cyber_sector": "endpoint_security",
        "cyber_focus": [
            "EDR",
            "XDR",
            "Threat Intelligence",
            "Cloud Workload Protection",
        ],
        "gics_sector": "Information Technology",
        "gics_industry": "Systems Software",
        "gics_sub_industry_code": "45103020",
        "exchange": "NASDAQ",
        "location": "Austin, TX",
        "domain": "crowdstrike.com",
        "alternate_names": ["CrowdStrike", "Crowd Strike", "crowdstrike holdings"],
    },
    "S": {
        "cyber_sector": "endpoint_security",
        "cyber_focus": ["EDR", "XDR", "AI-Powered Security"],
        "gics_sector": "Information Technology",
        "gics_industry": "Systems Software",
        "gics_sub_industry_code": "45103020",
        "exchange": "NYSE",
        "location": "Mountain View, CA",
        "domain": "sentinelone.com",
        "alternate_names": ["SentinelOne", "Sentinel One", "S1"],
    },
    # Network Security
    "PANW": {
        "cyber_sector": "network_security",
        "cyber_focus": ["NGFW", "SASE", "Cloud Security", "SOC"],
        "gics_sector": "Information Technology",
        "gics_industry": "Systems Software",
        "gics_sub_industry_code": "45103020",
        "exchange": "NASDAQ",
        "location": "Santa Clara, CA",
        "domain": "paloaltonetworks.com",
        "alternate_names": ["Palo Alto Networks", "Palo Alto", "PAN"],
    },
    "FTNT": {
        "cyber_sector": "network_security",
        "cyber_focus": ["NGFW", "SD-WAN", "SASE", "OT Security"],
        "gics_sector": "Information Technology",
        "gics_industry": "Communications Equipment",
        "gics_sub_industry_code": "45201020",
        "exchange": "NASDAQ",
        "location": "Sunnyvale, CA",
        "domain": "fortinet.com",
        "alternate_names": ["Fortinet", "Forti"],
    },
    "CHKP": {
        "cyber_sector": "network_security",
        "cyber_focus": ["NGFW", "Cloud Security", "Mobile Security"],
        "gics_sector": "Information Technology",
        "gics_industry": "Systems Software",
        "gics_sub_industry_code": "45103020",
        "exchange": "NASDAQ",
        "location": "Tel Aviv, Israel",
        "domain": "checkpoint.com",
        "alternate_names": ["Check Point", "CheckPoint", "Check Point Software"],
    },
    # Cloud Security
    "ZS": {
        "cyber_sector": "cloud_security",
        "cyber_focus": ["SASE", "Zero Trust", "SWG", "CASB"],
        "gics_sector": "Information Technology",
        "gics_industry": "Systems Software",
        "gics_sub_industry_code": "45103020",
        "exchange": "NASDAQ",
        "location": "San Jose, CA",
        "domain": "zscaler.com",
        "alternate_names": ["Zscaler", "Z Scaler"],
    },
    "NET": {
        "cyber_sector": "cloud_security",
        "cyber_focus": ["CDN", "DDoS Protection", "Zero Trust", "Edge Security"],
        "gics_sector": "Information Technology",
        "gics_industry": "Systems Software",
        "gics_sub_industry_code": "45103020",
        "exchange": "NYSE",
        "location": "San Francisco, CA",
        "domain": "cloudflare.com",
        "alternate_names": ["Cloudflare", "Cloud Flare"],
    },
    # Identity & Access Management
    "OKTA": {
        "cyber_sector": "identity_access",
        "cyber_focus": ["IAM", "SSO", "MFA", "Workforce Identity"],
        "gics_sector": "Information Technology",
        "gics_industry": "Systems Software",
        "gics_sub_industry_code": "45103020",
        "exchange": "NASDAQ",
        "location": "San Francisco, CA",
        "domain": "okta.com",
        "alternate_names": ["Okta"],
    },
    "CYBR": {
        "cyber_sector": "identity_access",
        "cyber_focus": ["PAM", "Secrets Management", "Identity Security"],
        "gics_sector": "Information Technology",
        "gics_industry": "Systems Software",
        "gics_sub_industry_code": "45103020",
        "exchange": "NASDAQ",
        "location": "Newton, MA",
        "domain": "cyberark.com",
        "alternate_names": ["CyberArk", "Cyber Ark", "CyberArk Software"],
    },
    "SAIL": {
        "cyber_sector": "identity_access",
        "cyber_focus": ["Identity Governance", "IAM", "Access Management"],
        "gics_sector": "Information Technology",
        "gics_industry": "Systems Software",
        "gics_sub_industry_code": "45103020",
        "exchange": "NYSE",
        "location": "Austin, TX",
        "domain": "sailpoint.com",
        "alternate_names": ["SailPoint", "Sail Point"],
    },
    # Vulnerability Management
    "TENB": {
        "cyber_sector": "vulnerability_management",
        "cyber_focus": [
            "Vulnerability Management",
            "Exposure Management",
            "OT Security",
        ],
        "gics_sector": "Information Technology",
        "gics_industry": "Systems Software",
        "gics_sub_industry_code": "45103020",
        "exchange": "NASDAQ",
        "location": "Columbia, MD",
        "domain": "tenable.com",
        "alternate_names": ["Tenable", "Tenable Holdings"],
    },
    "QLYS": {
        "cyber_sector": "vulnerability_management",
        "cyber_focus": ["Vulnerability Management", "Compliance", "Cloud Security"],
        "gics_sector": "Information Technology",
        "gics_industry": "Systems Software",
        "gics_sub_industry_code": "45103020",
        "exchange": "NASDAQ",
        "location": "Foster City, CA",
        "domain": "qualys.com",
        "alternate_names": ["Qualys"],
    },
    # Security Operations
    "RPD": {
        "cyber_sector": "security_operations",
        "cyber_focus": ["SIEM", "Vulnerability Management", "Detection & Response"],
        "gics_sector": "Information Technology",
        "gics_industry": "Systems Software",
        "gics_sub_industry_code": "45103020",
        "exchange": "NASDAQ",
        "location": "Boston, MA",
        "domain": "rapid7.com",
        "alternate_names": ["Rapid7", "Rapid 7"],
    },
    "SPLK": {
        "cyber_sector": "security_operations",
        "cyber_focus": ["SIEM", "Security Analytics", "Observability"],
        "gics_sector": "Information Technology",
        "gics_industry": "Systems Software",
        "gics_sub_industry_code": "45103020",
        "exchange": "NASDAQ",
        "location": "San Francisco, CA",
        "domain": "splunk.com",
        "alternate_names": ["Splunk"],
    },
    # Data Security
    "VRNS": {
        "cyber_sector": "data_security",
        "cyber_focus": ["Data Security", "DSPM", "Insider Threat"],
        "gics_sector": "Information Technology",
        "gics_industry": "Systems Software",
        "gics_sub_industry_code": "45103020",
        "exchange": "NASDAQ",
        "location": "New York, NY",
        "domain": "varonis.com",
        "alternate_names": ["Varonis", "Varonis Systems"],
    },
    # Email Security
    "PFPT": {
        "cyber_sector": "email_security",
        "cyber_focus": ["Email Gateway", "Phishing Protection", "Security Awareness"],
        "gics_sector": "Information Technology",
        "gics_industry": "Systems Software",
        "gics_sub_industry_code": "45103020",
        "exchange": "NASDAQ",
        "location": "Sunnyvale, CA",
        "domain": "proofpoint.com",
        "alternate_names": ["Proofpoint"],
    },
    # Application Security
    "SNYK": {
        "cyber_sector": "application_security",
        "cyber_focus": ["SAST", "SCA", "Container Security", "DevSecOps"],
        "gics_sector": "Information Technology",
        "gics_industry": "Systems Software",
        "gics_sub_industry_code": "45103020",
        "exchange": "Private",
        "location": "Boston, MA",
        "domain": "snyk.io",
        "alternate_names": ["Snyk"],
    },
    # Managed Security / MDR
    "SCWX": {
        "cyber_sector": "managed_security",
        "cyber_focus": ["MDR", "Threat Intelligence", "Incident Response"],
        "gics_sector": "Information Technology",
        "gics_industry": "IT Consulting & Other Services",
        "gics_sub_industry_code": "45102010",
        "exchange": "NASDAQ",
        "location": "Atlanta, GA",
        "domain": "secureworks.com",
        "alternate_names": ["Secureworks", "SecureWorks"],
    },
}

# Sector inference based on company name/description keywords
SECTOR_KEYWORDS = {
    "endpoint_security": [
        "endpoint",
        "edr",
        "xdr",
        "antivirus",
        "malware",
        "workstation",
    ],
    "network_security": ["firewall", "network", "ngfw", "sd-wan", "intrusion"],
    "cloud_security": ["cloud", "sase", "casb", "cwpp", "saas security", "zero trust"],
    "identity_access": [
        "identity",
        "iam",
        "pam",
        "sso",
        "mfa",
        "authentication",
        "access management",
    ],
    "security_operations": ["siem", "soar", "soc", "analytics", "monitoring", "log"],
    "application_security": [
        "appsec",
        "sast",
        "dast",
        "devsecops",
        "code security",
        "software composition",
    ],
    "data_security": [
        "data protection",
        "dlp",
        "encryption",
        "data security",
        "backup",
    ],
    "email_security": ["email", "phishing", "spam", "messaging security"],
    "vulnerability_management": [
        "vulnerability",
        "scanning",
        "pen test",
        "attack surface",
    ],
    "managed_security": ["managed", "mdr", "mssp", "consulting"],
}


def get_db_connection():
    """Get database connection using environment variables."""
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=os.environ.get("DB_PORT", "5432"),
        database=os.environ.get("DB_NAME", "cyberrisk"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASSWORD", ""),
    )


def infer_sector_from_description(company_name: str, description: str) -> Optional[str]:
    """
    Infer cyber sector from company name and description using keywords.

    Returns the best matching sector or None if no match.
    """
    if not description:
        description = ""

    text = f"{company_name} {description}".lower()

    best_sector = None
    best_score = 0

    for sector, keywords in SECTOR_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > best_score:
            best_score = score
            best_sector = sector

    return best_sector if best_score > 0 else None


def classify_with_llm(company_name: str, description: str) -> Optional[Dict]:
    """
    Use AWS Bedrock Claude to classify a company.

    Returns classification dict or None if LLM unavailable.
    """
    try:
        import boto3
        import json

        bedrock = boto3.client("bedrock-runtime", region_name="us-west-2")

        prompt = f"""Classify this cybersecurity company into one of these sectors:
- endpoint_security: EDR, XDR, antivirus, endpoint protection
- network_security: Firewalls, IDS/IPS, network segmentation
- cloud_security: CASB, CSPM, CWPP, SASE, zero trust
- identity_access: IAM, PAM, SSO, MFA
- security_operations: SIEM, SOAR, threat intelligence
- application_security: SAST, DAST, SCA, DevSecOps
- data_security: DLP, encryption, data classification
- email_security: Email gateways, phishing protection
- vulnerability_management: Vulnerability scanning, pen testing
- managed_security: MDR, MSSP, security consulting

Company: {company_name}
Description: {description or 'No description available'}

Respond with JSON only:
{{"cyber_sector": "sector_name", "cyber_focus": ["focus1", "focus2"]}}
"""

        response = bedrock.invoke_model(
            modelId="anthropic.claude-3-haiku-20240307-v1:0",
            body=json.dumps(
                {
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 200,
                    "messages": [{"role": "user", "content": prompt}],
                }
            ),
        )

        result = json.loads(response["body"].read())
        content = result["content"][0]["text"]

        # Parse JSON from response
        import re

        json_match = re.search(r"\{[^}]+\}", content)
        if json_match:
            return json.loads(json_match.group())

    except Exception as e:
        print(f"  LLM classification failed: {e}")

    return None


def update_company_taxonomy(
    conn,
    ticker: str,
    cyber_sector: str,
    cyber_focus: List[str],
    gics_sector: str = None,
    gics_industry: str = None,
    gics_sub_industry_code: str = None,
    exchange: str = None,
    location: str = None,
    domain: str = None,
    alternate_names: List[str] = None,
    dry_run: bool = False,
) -> bool:
    """Update a company's taxonomy in the database."""
    import json

    if dry_run:
        print(f"  [DRY RUN] Would update {ticker}: {cyber_sector}, focus={cyber_focus}")
        return True

    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE companies
            SET cyber_sector = %s,
                cyber_focus = %s,
                gics_sector = %s,
                gics_industry = %s,
                gics_sub_industry_code = %s,
                exchange = %s,
                location = %s,
                domain = %s,
                alternate_names = %s
            WHERE ticker = %s
        """,
            (
                cyber_sector,
                cyber_focus,
                gics_sector or "Information Technology",
                gics_industry or "Systems Software",
                gics_sub_industry_code or "45103020",
                exchange,
                location,
                domain,
                json.dumps(alternate_names) if alternate_names else None,
                ticker,
            ),
        )
        conn.commit()
        cursor.close()
        return True
    except Exception as e:
        print(f"  Error updating {ticker}: {e}")
        conn.rollback()
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Classify companies with cybersecurity taxonomy"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Don't actually update database"
    )
    parser.add_argument(
        "--use-llm", action="store_true", help="Use LLM to classify unknown companies"
    )
    parser.add_argument("--ticker", help="Only classify specific ticker")
    args = parser.parse_args()

    print("=" * 60)
    print("CyberRisk Company Taxonomy Classification")
    print("=" * 60)

    if args.dry_run:
        print("DRY RUN MODE - No changes will be made")
    print()

    # Connect to database
    try:
        conn = get_db_connection()
        print("✅ Connected to database")
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        sys.exit(1)

    # Get all companies
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    if args.ticker:
        cursor.execute(
            "SELECT ticker, company_name, sector, description, cyber_sector FROM companies WHERE ticker = %s",
            (args.ticker.upper(),),
        )
    else:
        cursor.execute(
            "SELECT ticker, company_name, sector, description, cyber_sector FROM companies ORDER BY ticker"
        )

    companies = cursor.fetchall()
    cursor.close()

    print(f"\nFound {len(companies)} companies to classify\n")

    stats = {"known": 0, "inferred": 0, "llm": 0, "skipped": 0, "failed": 0}

    for company in companies:
        ticker = company["ticker"]
        name = company["company_name"]
        desc = company.get("description", "")
        current_sector = company.get("cyber_sector")

        print(f"Processing {ticker} ({name})...")

        # Skip if already classified
        if current_sector and not args.ticker:
            print(f"  Already classified as: {current_sector}")
            stats["skipped"] += 1
            continue

        # Check known classifications first
        if ticker in KNOWN_CLASSIFICATIONS:
            classification = KNOWN_CLASSIFICATIONS[ticker]
            print(f"  Known classification: {classification['cyber_sector']}")

            success = update_company_taxonomy(
                conn,
                ticker,
                classification["cyber_sector"],
                classification["cyber_focus"],
                classification.get("gics_sector"),
                classification.get("gics_industry"),
                classification.get("gics_sub_industry_code"),
                classification.get("exchange"),
                classification.get("location"),
                classification.get("domain"),
                classification.get("alternate_names"),
                dry_run=args.dry_run,
            )

            if success:
                stats["known"] += 1
            else:
                stats["failed"] += 1
            continue

        # Try keyword-based inference
        inferred_sector = infer_sector_from_description(name, desc)
        if inferred_sector:
            print(f"  Inferred sector: {inferred_sector}")

            success = update_company_taxonomy(
                conn,
                ticker,
                inferred_sector,
                [],  # No specific focus inferred
                dry_run=args.dry_run,
            )

            if success:
                stats["inferred"] += 1
            else:
                stats["failed"] += 1
            continue

        # Try LLM classification if enabled
        if args.use_llm:
            print(f"  Attempting LLM classification...")
            llm_result = classify_with_llm(name, desc)

            if llm_result:
                print(f"  LLM classified: {llm_result.get('cyber_sector')}")

                success = update_company_taxonomy(
                    conn,
                    ticker,
                    llm_result.get("cyber_sector", "security_operations"),
                    llm_result.get("cyber_focus", []),
                    dry_run=args.dry_run,
                )

                if success:
                    stats["llm"] += 1
                else:
                    stats["failed"] += 1
                continue

        # Default fallback
        print(f"  Could not classify - using default: security_operations")
        success = update_company_taxonomy(
            conn,
            ticker,
            "security_operations",  # Safe default
            [],
            dry_run=args.dry_run,
        )

        if success:
            stats["inferred"] += 1
        else:
            stats["failed"] += 1

    conn.close()

    print("\n" + "=" * 60)
    print("Classification Summary")
    print("=" * 60)
    print(f"  Known classifications: {stats['known']}")
    print(f"  Inferred from keywords: {stats['inferred']}")
    print(f"  LLM classified: {stats['llm']}")
    print(f"  Already classified (skipped): {stats['skipped']}")
    print(f"  Failed: {stats['failed']}")
    print()


if __name__ == "__main__":
    main()
