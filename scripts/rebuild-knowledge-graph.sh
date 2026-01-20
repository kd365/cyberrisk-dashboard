#!/bin/bash
# =============================================================================
# Rebuild Neo4j Knowledge Graph
# =============================================================================
#
# This script clears the existing graph (which may have junk nodes) and
# rebuilds it using the improved entity extraction with:
#   - 0.85 confidence threshold
#   - Entity blocklist filtering
#   - Proper organization resolution
#
# Prerequisites:
#   - Backend API must be running
#   - Neo4j must be accessible
#   - Valid Cognito token (for admin endpoints)
#
# Usage:
#   ./scripts/rebuild-knowledge-graph.sh [API_URL]
#
# =============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
API_URL="${1:-http://localhost:5000}"
AUTH_TOKEN="${COGNITO_TOKEN:-}"

echo -e "${BLUE}============================================================${NC}"
echo -e "${BLUE}CyberRisk Knowledge Graph Rebuild${NC}"
echo -e "${BLUE}============================================================${NC}"
echo ""
echo -e "API URL: ${YELLOW}$API_URL${NC}"
echo ""

# Check if API is reachable
echo -e "${BLUE}Step 1: Checking API health...${NC}"
HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/health" 2>/dev/null || echo "000")

if [ "$HEALTH" != "200" ]; then
    echo -e "${RED}ERROR: API not reachable at $API_URL (HTTP $HEALTH)${NC}"
    echo "Make sure the backend is running and try again."
    exit 1
fi
echo -e "${GREEN}API is healthy${NC}"
echo ""

# Check current graph stats
echo -e "${BLUE}Step 2: Current graph statistics...${NC}"
STATS=$(curl -s "$API_URL/api/knowledge-graph/stats" 2>/dev/null || echo "{}")
echo "$STATS" | python3 -m json.tool 2>/dev/null || echo "$STATS"
echo ""

# Confirm before clearing
echo -e "${YELLOW}WARNING: This will delete ALL nodes and relationships from Neo4j${NC}"
echo -e "${YELLOW}and rebuild the graph from scratch using improved filtering.${NC}"
echo ""
read -p "Are you sure you want to proceed? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo -e "${RED}Aborted.${NC}"
    exit 0
fi

echo ""

# Clear the graph
echo -e "${BLUE}Step 3: Clearing existing graph...${NC}"

# Build auth header if token provided
if [ -n "$AUTH_TOKEN" ]; then
    AUTH_HEADER="Authorization: Bearer $AUTH_TOKEN"
else
    AUTH_HEADER=""
fi

CLEAR_RESULT=$(curl -s -X POST "$API_URL/api/admin/clear-graph" \
    ${AUTH_TOKEN:+-H "$AUTH_HEADER"} \
    -H "Content-Type: application/json" 2>/dev/null || echo '{"error": "Request failed"}')

echo "$CLEAR_RESULT" | python3 -m json.tool 2>/dev/null || echo "$CLEAR_RESULT"

if echo "$CLEAR_RESULT" | grep -q '"error"'; then
    echo -e "${RED}Failed to clear graph. Check authentication.${NC}"
    echo ""
    echo "If you need to authenticate, set COGNITO_TOKEN environment variable:"
    echo "  export COGNITO_TOKEN=your_id_token"
    echo "  ./scripts/rebuild-knowledge-graph.sh"
    exit 1
fi
echo -e "${GREEN}Graph cleared successfully${NC}"
echo ""

# Rebuild the graph
echo -e "${BLUE}Step 4: Rebuilding knowledge graph for all companies...${NC}"
echo -e "${YELLOW}This may take 10-30 minutes depending on document count.${NC}"
echo ""

BUILD_RESULT=$(curl -s -X POST "$API_URL/api/admin/build-graph" \
    ${AUTH_TOKEN:+-H "$AUTH_HEADER"} \
    -H "Content-Type: application/json" \
    --max-time 1800 2>/dev/null || echo '{"error": "Request timed out or failed"}')

echo "$BUILD_RESULT" | python3 -m json.tool 2>/dev/null || echo "$BUILD_RESULT"

if echo "$BUILD_RESULT" | grep -q '"error"'; then
    echo -e "${YELLOW}Warning: Some errors occurred during build. Check the response above.${NC}"
fi
echo ""

# Show final stats
echo -e "${BLUE}Step 5: Final graph statistics...${NC}"
FINAL_STATS=$(curl -s "$API_URL/api/knowledge-graph/stats" 2>/dev/null || echo "{}")
echo "$FINAL_STATS" | python3 -m json.tool 2>/dev/null || echo "$FINAL_STATS"
echo ""

echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}Knowledge Graph Rebuild Complete!${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""
echo "The graph now contains entities extracted with:"
echo "  - 0.85 confidence threshold (filters low-quality entities)"
echo "  - Blocklist filtering (removes XBRL/PDF artifacts)"
echo "  - Proper organization resolution (links to tracked companies)"
echo "  - Numeric filtering (removes date/number-only concepts)"
echo ""
echo "Graph relationships include:"
echo "  - Entity co-occurrence (RELATED_TO between organizations)"
echo "  - Concept co-occurrence (RELATED_TO between concepts)"
echo "  - Company-concept associations (ASSOCIATED_WITH with frequency)"
echo ""
echo "Concept categories: RISK, TECHNOLOGY, PRODUCT, MARKET, COMPETITOR,"
echo "                    OPPORTUNITY, FINANCIAL, GENERAL"
echo ""
