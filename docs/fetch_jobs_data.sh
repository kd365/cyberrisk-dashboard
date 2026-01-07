#!/bin/bash
# =============================================================================
# Fetch CoreSignal Job Data for All Companies
# =============================================================================
#
# This script queries the CoreSignal jobs endpoint to get active job counts
# by function and seniority for each company.
#
# Usage: ./fetch_jobs_data.sh
# Output: jobs_data.json with aggregated results
#
# API: https://api.coresignal.com/cdapi/v2/job_multi_source/search/es_dsl
# =============================================================================

API_KEY="lLJMkasA7hJ86hpAlE7j4YcOBdnLOEJ3"
OUTPUT_DIR="$(dirname "$0")"
OUTPUT_FILE="$OUTPUT_DIR/jobs_data.json"

# Company IDs from CoreSignal (LinkedIn company IDs)
declare -A COMPANIES=(
    ["CRWD"]="10020216"
    ["ZS"]="1114997"
    ["NET"]="10826791"
    ["PANW"]="7898996"
    ["FTNT"]="9560844"
    ["OKTA"]="5929958"
    ["S"]="10842616"
    ["CYBR"]="1904796"
    ["TENB"]="11438875"
    ["SPLK"]="4268152"
)

FUNCTIONS=("Engineering" "Sales" "Information Technology" "Marketing" "Finance" "Human Resources" "Product Management" "Research" "Legal" "Operations" "Customer Service" "Administrative")
SENIORITIES=("Entry level" "Associate" "Mid-Senior level" "Director" "Executive")

echo "=============================================="
echo "CoreSignal Job Data Fetcher"
echo "=============================================="
echo "Output file: $OUTPUT_FILE"
echo ""

# Initialize output JSON
echo "{" > "$OUTPUT_FILE"
echo '  "fetched_at": "'$(date -u +"%Y-%m-%dT%H:%M:%SZ")'",' >> "$OUTPUT_FILE"
echo '  "companies": {' >> "$OUTPUT_FILE"

first_company=true

for ticker in "${!COMPANIES[@]}"; do
    company_id="${COMPANIES[$ticker]}"

    echo "Processing $ticker (ID: $company_id)..."

    if [ "$first_company" = false ]; then
        echo "    ," >> "$OUTPUT_FILE"
    fi
    first_company=false

    echo "    \"$ticker\": {" >> "$OUTPUT_FILE"
    echo "      \"coresignal_id\": $company_id," >> "$OUTPUT_FILE"

    # Fetch jobs by function
    echo "      \"jobs_by_function\": {" >> "$OUTPUT_FILE"
    first_func=true
    for func in "${FUNCTIONS[@]}"; do
        count=$(curl -s 'https://api.coresignal.com/cdapi/v2/job_multi_source/search/es_dsl' \
            --header 'Content-Type: application/json' \
            --header "apikey: $API_KEY" \
            --data "{
                \"query\": {
                    \"bool\": {
                        \"must\": [
                            {\"term\": {\"company_ids.li_company_id\": \"$company_id\"}},
                            {\"term\": {\"status\": 1}},
                            {\"match\": {\"functions\": \"$func\"}}
                        ]
                    }
                },
                \"size\": 0
            }" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('total', 0))" 2>/dev/null || echo "0")

        if [ "$first_func" = false ]; then
            echo "," >> "$OUTPUT_FILE"
        fi
        first_func=false
        printf "        \"%s\": %s" "$func" "$count" >> "$OUTPUT_FILE"
        echo -n "."
    done
    echo "" >> "$OUTPUT_FILE"
    echo "      }," >> "$OUTPUT_FILE"

    # Fetch jobs by seniority
    echo "      \"jobs_by_seniority\": {" >> "$OUTPUT_FILE"
    first_sen=true
    for level in "${SENIORITIES[@]}"; do
        count=$(curl -s 'https://api.coresignal.com/cdapi/v2/job_multi_source/search/es_dsl' \
            --header 'Content-Type: application/json' \
            --header "apikey: $API_KEY" \
            --data "{
                \"query\": {
                    \"bool\": {
                        \"must\": [
                            {\"term\": {\"company_ids.li_company_id\": \"$company_id\"}},
                            {\"term\": {\"status\": 1}},
                            {\"match_phrase\": {\"seniority\": \"$level\"}}
                        ]
                    }
                },
                \"size\": 0
            }" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('total', 0))" 2>/dev/null || echo "0")

        if [ "$first_sen" = false ]; then
            echo "," >> "$OUTPUT_FILE"
        fi
        first_sen=false
        printf "        \"%s\": %s" "$level" "$count" >> "$OUTPUT_FILE"
    done
    echo "" >> "$OUTPUT_FILE"
    echo "      }" >> "$OUTPUT_FILE"
    echo "    }" >> "$OUTPUT_FILE"

    echo " done"

    # Small delay to avoid rate limiting
    sleep 0.5
done

echo "  }" >> "$OUTPUT_FILE"
echo "}" >> "$OUTPUT_FILE"

echo ""
echo "=============================================="
echo "Job data saved to: $OUTPUT_FILE"
echo "=============================================="
echo ""
echo "To import this data to RDS, run:"
echo "  python3 import_jobs_to_rds.py"
