#!/bin/bash
# =============================================================================
# Setup GitHub Secrets for CyberRisk CI/CD Pipeline
# This script configures all required secrets for GitHub Actions workflows
# =============================================================================
#
# Prerequisites:
#   1. GitHub CLI installed: brew install gh
#   2. Authenticated: gh auth login
#   3. AWS CLI configured with cyber-risk profile
#
# Usage:
#   ./scripts/setup-github-secrets.sh
#
# =============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}============================================================${NC}"
echo -e "${BLUE}CyberRisk - GitHub Secrets Setup${NC}"
echo -e "${BLUE}============================================================${NC}"
echo ""

# Check prerequisites
echo -e "${YELLOW}Checking prerequisites...${NC}"

if ! command -v gh &> /dev/null; then
    echo -e "${RED}ERROR: GitHub CLI (gh) not installed${NC}"
    echo "Install with: brew install gh"
    exit 1
fi

if ! gh auth status &> /dev/null; then
    echo -e "${RED}ERROR: Not authenticated with GitHub CLI${NC}"
    echo "Run: gh auth login"
    exit 1
fi

if ! command -v aws &> /dev/null; then
    echo -e "${RED}ERROR: AWS CLI not installed${NC}"
    exit 1
fi

echo -e "${GREEN}All prerequisites met!${NC}"
echo ""

# Set AWS profile
export AWS_PROFILE=cyber-risk
export AWS_DEFAULT_REGION=us-west-2

# Verify AWS account
EXPECTED_ACCOUNT="000018673740"
CURRENT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text 2>/dev/null)
if [ "$CURRENT_ACCOUNT" != "$EXPECTED_ACCOUNT" ]; then
    echo -e "${RED}ERROR: Wrong AWS account. Expected $EXPECTED_ACCOUNT, got $CURRENT_ACCOUNT${NC}"
    exit 1
fi
echo -e "${GREEN}Verified AWS account: $CURRENT_ACCOUNT${NC}"
echo ""

# Get repository name
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)
if [ -z "$REPO" ]; then
    echo -e "${RED}ERROR: Could not determine repository. Make sure you're in a git repo.${NC}"
    exit 1
fi
echo -e "${GREEN}Repository: $REPO${NC}"
echo ""

# Gather values from AWS
echo -e "${YELLOW}Gathering values from AWS...${NC}"

# EC2 Instance ID
EC2_INSTANCE_ID=$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=cyberrisk-dev-kh-flask-backend" "Name=instance-state-name,Values=running" \
    --query 'Reservations[0].Instances[0].InstanceId' \
    --output text)
echo "  EC2_INSTANCE_ID: $EC2_INSTANCE_ID"

# S3 Bucket
S3_BUCKET_NAME=$(aws s3 ls | grep "cyberrisk-dev-kh-frontend" | awk '{print $3}' | head -1)
echo "  S3_BUCKET_NAME: $S3_BUCKET_NAME"

# S3 Artifacts Bucket
S3_ARTIFACTS_BUCKET=$(aws s3 ls | grep "cyberrisk-dev-kh-artifacts" | awk '{print $3}' | head -1)
echo "  S3_ARTIFACTS_BUCKET: $S3_ARTIFACTS_BUCKET"

# CloudFront Distribution ID
CLOUDFRONT_DISTRIBUTION_ID=$(aws cloudfront list-distributions \
    --query 'DistributionList.Items[?contains(Comment, `CyberRisk`)].Id' \
    --output text | head -1)
echo "  CLOUDFRONT_DISTRIBUTION_ID: $CLOUDFRONT_DISTRIBUTION_ID"

# Cognito User Pool ID
COGNITO_USER_POOL_ID=$(aws cognito-idp list-user-pools --max-results 10 \
    --query 'UserPools[?contains(Name, `cyberrisk`)].Id' \
    --output text | head -1)
echo "  COGNITO_USER_POOL_ID: $COGNITO_USER_POOL_ID"

# Cognito Client ID
if [ -n "$COGNITO_USER_POOL_ID" ]; then
    COGNITO_CLIENT_ID=$(aws cognito-idp list-user-pool-clients \
        --user-pool-id "$COGNITO_USER_POOL_ID" \
        --query 'UserPoolClients[0].ClientId' \
        --output text)
    echo "  COGNITO_CLIENT_ID: $COGNITO_CLIENT_ID"
fi

# RDS Endpoint
RDS_ENDPOINT=$(aws rds describe-db-instances \
    --db-instance-identifier cyberrisk-dev-kh-postgres \
    --query 'DBInstances[0].Endpoint.Address' \
    --output text 2>/dev/null || echo "")
echo "  RDS_ENDPOINT: $RDS_ENDPOINT"

# Flask API URL
FLASK_PUBLIC_IP=$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=cyberrisk-dev-kh-flask-backend" "Name=instance-state-name,Values=running" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' \
    --output text)
REACT_APP_API_URL="http://${FLASK_PUBLIC_IP}:5000"
echo "  REACT_APP_API_URL: $REACT_APP_API_URL"

echo ""
echo -e "${YELLOW}Setting GitHub secrets...${NC}"

# Function to set a secret
set_secret() {
    local name=$1
    local value=$2
    if [ -n "$value" ] && [ "$value" != "None" ] && [ "$value" != "null" ]; then
        echo -n "  Setting $name... "
        echo "$value" | gh secret set "$name" --repo "$REPO"
        echo -e "${GREEN}Done${NC}"
    else
        echo -e "  ${YELLOW}Skipping $name (no value)${NC}"
    fi
}

# Set all secrets
set_secret "EC2_INSTANCE_ID" "$EC2_INSTANCE_ID"
set_secret "S3_BUCKET_NAME" "$S3_BUCKET_NAME"
set_secret "S3_ARTIFACTS_BUCKET" "$S3_ARTIFACTS_BUCKET"
set_secret "CLOUDFRONT_DISTRIBUTION_ID" "$CLOUDFRONT_DISTRIBUTION_ID"
set_secret "COGNITO_USER_POOL_ID" "$COGNITO_USER_POOL_ID"
set_secret "COGNITO_CLIENT_ID" "$COGNITO_CLIENT_ID"
set_secret "RDS_ENDPOINT" "$RDS_ENDPOINT"
set_secret "REACT_APP_API_URL" "$REACT_APP_API_URL"

echo ""
echo -e "${YELLOW}Note: AWS credentials must be set manually for security:${NC}"
echo "  - AWS_ACCESS_KEY_ID"
echo "  - AWS_SECRET_ACCESS_KEY"
echo ""
echo "Run these commands to set them (replace with your actual values):"
echo -e "${BLUE}  gh secret set AWS_ACCESS_KEY_ID --repo $REPO${NC}"
echo -e "${BLUE}  gh secret set AWS_SECRET_ACCESS_KEY --repo $REPO${NC}"
echo ""

echo -e "${BLUE}============================================================${NC}"
echo -e "${GREEN}GitHub secrets setup complete!${NC}"
echo -e "${BLUE}============================================================${NC}"
echo ""
echo "To verify, run: gh secret list --repo $REPO"
