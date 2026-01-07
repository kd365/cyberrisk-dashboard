#!/usr/bin/env python3
"""
Fetch CoreSignal Job Data for All Companies

Queries the CoreSignal jobs endpoint to get active job counts
by function and seniority for each company.

Usage: python3 fetch_jobs_data.py
Output: jobs_data.json with aggregated results
"""

import json
import requests
from datetime import datetime
from pathlib import Path
import time

API_KEY = "lLJMkasA7hJ86hpAlE7j4YcOBdnLOEJ3"
BASE_URL = "https://api.coresignal.com/cdapi/v2/job_multi_source/search/es_dsl"

# Company IDs from CoreSignal (LinkedIn company IDs)
COMPANIES = {
    "CRWD": 10020216,
    "ZS": 1114997,
    "NET": 10826791,
    "PANW": 7898996,
    "FTNT": 9560844,
    "OKTA": 5929958,
    "S": 10842616,
    "CYBR": 1904796,
    "TENB": 11438875,
    "SPLK": 4268152,
}

FUNCTIONS = [
    "Engineering", "Sales", "Information Technology", "Marketing",
    "Finance", "Human Resources", "Product Management", "Research",
    "Legal", "Operations", "Customer Service", "Administrative"
]

SENIORITIES = [
    "Entry level", "Associate", "Mid-Senior level", "Director", "Executive"
]

HEADERS = {
    "Content-Type": "application/json",
    "apikey": API_KEY
}


def fetch_job_count(company_id: int, filter_type: str, filter_value: str) -> int:
    """Fetch job count for a specific filter"""
    if filter_type == "function":
        query = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"company_ids.li_company_id": str(company_id)}},
                        {"term": {"status": 1}},
                        {"match": {"functions": filter_value}}
                    ]
                }
            },
            "size": 0
        }
    else:  # seniority
        query = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"company_ids.li_company_id": str(company_id)}},
                        {"term": {"status": 1}},
                        {"match_phrase": {"seniority": filter_value}}
                    ]
                }
            },
            "size": 0
        }

    try:
        response = requests.post(BASE_URL, headers=HEADERS, json=query, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get("total", 0)
    except Exception as e:
        print(f"    Error: {e}")
        return 0


def main():
    print("=" * 60)
    print("CoreSignal Job Data Fetcher")
    print("=" * 60)

    output_file = Path(__file__).parent / "jobs_data.json"
    print(f"Output file: {output_file}\n")

    result = {
        "fetched_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "companies": {}
    }

    for ticker, company_id in COMPANIES.items():
        print(f"Processing {ticker} (ID: {company_id})...")

        company_data = {
            "coresignal_id": company_id,
            "jobs_by_function": {},
            "jobs_by_seniority": {}
        }

        # Fetch jobs by function
        print("  Functions: ", end="", flush=True)
        for func in FUNCTIONS:
            count = fetch_job_count(company_id, "function", func)
            company_data["jobs_by_function"][func] = count
            print(".", end="", flush=True)
            time.sleep(0.3)  # Rate limiting
        print()

        # Fetch jobs by seniority
        print("  Seniority: ", end="", flush=True)
        for level in SENIORITIES:
            count = fetch_job_count(company_id, "seniority", level)
            company_data["jobs_by_seniority"][level] = count
            print(".", end="", flush=True)
            time.sleep(0.3)  # Rate limiting
        print()

        # Calculate totals
        total_by_func = sum(company_data["jobs_by_function"].values())
        total_by_sen = sum(company_data["jobs_by_seniority"].values())
        print(f"  Total jobs (by function): {total_by_func}")
        print(f"  Total jobs (by seniority): {total_by_sen}")

        result["companies"][ticker] = company_data

    # Save results
    with open(output_file, "w") as f:
        json.dump(result, f, indent=2)

    print("\n" + "=" * 60)
    print(f"Job data saved to: {output_file}")
    print("=" * 60)
    print("\nTo import this data to RDS, run:")
    print("  python3 import_jobs_to_rds.py")


if __name__ == "__main__":
    main()
