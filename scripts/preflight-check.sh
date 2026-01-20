#!/bin/bash
# =============================================================================
# CyberRisk Pre-Flight Check
# Run this BEFORE any Terraform or AWS operations
# =============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

EXPECTED_ACCOUNT="000018673740"
EXPECTED_PROFILE="cyber-risk"

echo ""
echo "============================================================"
echo "CyberRisk Pre-Flight Check"
echo "============================================================"
echo ""

ERRORS=0

# Check 1: AWS CLI installed
echo -n "1. AWS CLI installed: "
if command -v aws &> /dev/null; then
    echo -e "${GREEN}✅ Yes${NC}"
else
    echo -e "${RED}❌ No - Install AWS CLI first${NC}"
    ERRORS=$((ERRORS + 1))
fi

# Check 2: Profile exists
echo -n "2. cyber-risk profile exists: "
if aws configure list --profile cyber-risk &> /dev/null; then
    echo -e "${GREEN}✅ Yes${NC}"
else
    echo -e "${RED}❌ No - Run: aws configure --profile cyber-risk${NC}"
    ERRORS=$((ERRORS + 1))
fi

# Check 3: Current profile
echo -n "3. AWS_PROFILE set correctly: "
if [ "$AWS_PROFILE" = "$EXPECTED_PROFILE" ]; then
    echo -e "${GREEN}✅ $AWS_PROFILE${NC}"
else
    echo -e "${YELLOW}⚠️  Current: ${AWS_PROFILE:-'(not set)'} - Expected: $EXPECTED_PROFILE${NC}"
    echo -e "   ${YELLOW}Run: export AWS_PROFILE=cyber-risk${NC}"
    ERRORS=$((ERRORS + 1))
fi

# Check 4: Correct account
echo -n "4. Connected to correct AWS account: "
CURRENT_ACCOUNT=$(aws sts get-caller-identity --profile cyber-risk --query Account --output text 2>/dev/null)
if [ "$CURRENT_ACCOUNT" = "$EXPECTED_ACCOUNT" ]; then
    echo -e "${GREEN}✅ $CURRENT_ACCOUNT${NC}"
else
    echo -e "${RED}❌ Got: $CURRENT_ACCOUNT - Expected: $EXPECTED_ACCOUNT${NC}"
    ERRORS=$((ERRORS + 1))
fi

# Check 5: Terraform installed
echo -n "5. Terraform installed: "
if command -v terraform &> /dev/null; then
    TF_VERSION=$(terraform version -json 2>/dev/null | grep -o '"terraform_version":"[^"]*"' | cut -d'"' -f4)
    echo -e "${GREEN}✅ v$TF_VERSION${NC}"
else
    echo -e "${RED}❌ No - Install Terraform first${NC}"
    ERRORS=$((ERRORS + 1))
fi

# Check 6: In correct directory
echo -n "6. In CyberRisk directory: "
if [[ "$PWD" == *"CyberRisk"* ]]; then
    echo -e "${GREEN}✅ Yes${NC}"
else
    echo -e "${YELLOW}⚠️  Current: $PWD${NC}"
fi

# Check 7: Key pair exists
echo -n "7. EC2 key pair (try2-kh) exists: "
if [ -f ~/.ssh/try2-kh.pem ]; then
    echo -e "${GREEN}✅ Found${NC}"
else
    echo -e "${YELLOW}⚠️  Not found at ~/.ssh/try2-kh.pem${NC}"
fi

echo ""
echo "============================================================"
if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}✅ All checks passed! Safe to proceed.${NC}"
else
    echo -e "${RED}❌ $ERRORS error(s) found. Fix before proceeding.${NC}"
fi
echo "============================================================"
echo ""

exit $ERRORS
