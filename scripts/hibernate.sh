#!/bin/bash
# =============================================================================
# CyberRisk Dashboard - Hibernation Script
# Stops resources to minimize costs while preserving all data/artifacts
# Estimated savings: ~$80-88/month
# =============================================================================

set -e

# Configuration - Update these values from your Terraform outputs
AWS_REGION="${AWS_REGION:-us-west-2}"
AWS_PROFILE="${AWS_PROFILE:-cyber-risk}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}============================================================${NC}"
echo -e "${BLUE}CyberRisk Dashboard - Hibernation Mode${NC}"
echo -e "${BLUE}============================================================${NC}"
echo ""

# Check AWS CLI is available
if ! command -v aws &> /dev/null; then
    echo -e "${RED}ERROR: AWS CLI not found. Please install it first.${NC}"
    exit 1
fi

# CRITICAL: Verify we're using the correct AWS account
EXPECTED_ACCOUNT="000018673740"
CURRENT_ACCOUNT=$(aws sts get-caller-identity --profile "$AWS_PROFILE" --query Account --output text 2>/dev/null)
if [ "$CURRENT_ACCOUNT" != "$EXPECTED_ACCOUNT" ]; then
    echo -e "${RED}============================================================${NC}"
    echo -e "${RED}FATAL ERROR: Wrong AWS Account!${NC}"
    echo -e "${RED}============================================================${NC}"
    echo -e "${RED}Expected account: $EXPECTED_ACCOUNT (cyber-risk)${NC}"
    echo -e "${RED}Current account:  $CURRENT_ACCOUNT${NC}"
    echo -e "${RED}Profile in use:   $AWS_PROFILE${NC}"
    echo ""
    echo -e "${YELLOW}Run: export AWS_PROFILE=cyber-risk${NC}"
    echo -e "${YELLOW}Or:  source scripts/set-aws-profile.sh${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Verified: Using CyberRisk AWS account ($CURRENT_ACCOUNT)${NC}"

# Set profile
export AWS_PROFILE="$AWS_PROFILE"
export AWS_DEFAULT_REGION="$AWS_REGION"

echo -e "${YELLOW}Using AWS Profile: $AWS_PROFILE${NC}"
echo -e "${YELLOW}Using AWS Region: $AWS_REGION${NC}"
echo ""

# Create state file to store resource IDs for wakeup
STATE_FILE="$(dirname "$0")/.hibernate_state.json"

echo -e "${BLUE}Step 1: Discovering resources...${NC}"

# Find EC2 instances by tag (using exact name pattern)
FLASK_INSTANCE_ID=$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=cyberrisk-dev-kh-flask-backend" "Name=instance-state-name,Values=running,stopped" \
    --query 'Reservations[*].Instances[*].InstanceId' \
    --output text 2>/dev/null | tr '\t' '\n' | head -1)

if [ -z "$FLASK_INSTANCE_ID" ] || [ "$FLASK_INSTANCE_ID" == "None" ]; then
    # Fallback: try wildcard pattern
    FLASK_INSTANCE_ID=$(aws ec2 describe-instances \
        --filters "Name=tag:Name,Values=*flask*" "Name=instance-state-name,Values=running,stopped" \
        --query 'Reservations[*].Instances[*].InstanceId' \
        --output text 2>/dev/null | tr '\t' '\n' | head -1)
fi

NEO4J_INSTANCE_ID=$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=cyberrisk-dev-kh-neo4j" "Name=instance-state-name,Values=running,stopped" \
    --query 'Reservations[*].Instances[*].InstanceId' \
    --output text 2>/dev/null | tr '\t' '\n' | head -1)

if [ -z "$NEO4J_INSTANCE_ID" ] || [ "$NEO4J_INSTANCE_ID" == "None" ]; then
    # Fallback: try wildcard pattern
    NEO4J_INSTANCE_ID=$(aws ec2 describe-instances \
        --filters "Name=tag:Name,Values=*neo4j*" "Name=instance-state-name,Values=running,stopped" \
        --query 'Reservations[*].Instances[*].InstanceId' \
        --output text 2>/dev/null | tr '\t' '\n' | head -1)
fi

# Find RDS instance
RDS_INSTANCE_ID=$(aws rds describe-db-instances \
    --query "DBInstances[?contains(DBInstanceIdentifier, 'cyberrisk')].DBInstanceIdentifier" \
    --output text 2>/dev/null | tr '\t' '\n' | head -1)

# Find NAT Gateways (get ALL of them since you have 2)
NAT_GATEWAY_IDS=$(aws ec2 describe-nat-gateways \
    --filter "Name=state,Values=available" "Name=tag:Name,Values=cyberrisk-dev-kh-nat" \
    --query 'NatGateways[*].NatGatewayId' \
    --output text 2>/dev/null)

# If no tagged NAT found, try to find by VPC
if [ -z "$NAT_GATEWAY_IDS" ] || [ "$NAT_GATEWAY_IDS" == "None" ]; then
    VPC_ID=$(aws ec2 describe-vpcs \
        --filters "Name=tag:Name,Values=*cyberrisk*" \
        --query 'Vpcs[0].VpcId' \
        --output text 2>/dev/null)

    if [ -n "$VPC_ID" ] && [ "$VPC_ID" != "None" ]; then
        NAT_GATEWAY_IDS=$(aws ec2 describe-nat-gateways \
            --filter "Name=vpc-id,Values=$VPC_ID" "Name=state,Values=available" \
            --query 'NatGateways[*].NatGatewayId' \
            --output text 2>/dev/null)
    fi
fi

# Get first NAT Gateway ID for state file (for backward compat)
NAT_GATEWAY_ID=$(echo "$NAT_GATEWAY_IDS" | tr '\t' '\n' | head -1)

# Get NAT Gateway's Elastic IP allocation ID
if [ -n "$NAT_GATEWAY_ID" ] && [ "$NAT_GATEWAY_ID" != "None" ]; then
    NAT_EIP_ALLOCATION_ID=$(aws ec2 describe-nat-gateways \
        --nat-gateway-ids "$NAT_GATEWAY_ID" \
        --query 'NatGateways[0].NatGatewayAddresses[0].AllocationId' \
        --output text 2>/dev/null)

    NAT_SUBNET_ID=$(aws ec2 describe-nat-gateways \
        --nat-gateway-ids "$NAT_GATEWAY_ID" \
        --query 'NatGateways[0].SubnetId' \
        --output text 2>/dev/null)
fi

echo ""
echo -e "${BLUE}Discovered Resources:${NC}"
echo "  Flask EC2:     ${FLASK_INSTANCE_ID:-Not found}"
echo "  Neo4j EC2:     ${NEO4J_INSTANCE_ID:-Not found}"
echo "  RDS Instance:  ${RDS_INSTANCE_ID:-Not found}"
echo "  NAT Gateways:  ${NAT_GATEWAY_IDS:-Not found}"
echo ""

# Save state for wakeup script
cat > "$STATE_FILE" << EOF
{
    "hibernated_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
    "aws_region": "$AWS_REGION",
    "aws_profile": "$AWS_PROFILE",
    "flask_instance_id": "${FLASK_INSTANCE_ID:-}",
    "neo4j_instance_id": "${NEO4J_INSTANCE_ID:-}",
    "rds_instance_id": "${RDS_INSTANCE_ID:-}",
    "nat_gateway_ids": "${NAT_GATEWAY_IDS:-}",
    "nat_gateway_id": "${NAT_GATEWAY_ID:-}",
    "nat_eip_allocation_id": "${NAT_EIP_ALLOCATION_ID:-}",
    "nat_subnet_id": "${NAT_SUBNET_ID:-}"
}
EOF

echo -e "${GREEN}State saved to: $STATE_FILE${NC}"
echo ""

# Confirm before proceeding
echo -e "${YELLOW}WARNING: This will stop the following resources:${NC}"
echo "  - EC2 instances (Flask and Neo4j)"
echo "  - RDS database instance"
echo "  - NAT Gateway (will be DELETED - costs ~\$45/month even when idle)"
echo ""
echo -e "${GREEN}The following will be PRESERVED:${NC}"
echo "  - S3 buckets (artifacts and frontend)"
echo "  - EBS volumes (EC2 data)"
echo "  - RDS data (snapshots and storage)"
echo "  - CloudFront distribution"
echo "  - Cognito user pool"
echo "  - Lex bot configuration"
echo ""
echo -e "${YELLOW}GitHub Actions Impact:${NC}"
echo "  - deploy-backend.yml will FAIL (EC2 is stopped)"
echo "  - deploy-frontend.yml will WORK (S3/CloudFront still active)"
echo "  - Consider disabling backend deploy workflow while hibernating"
echo ""

read -p "Do you want to proceed? (yes/no): " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    echo -e "${RED}Aborted.${NC}"
    exit 0
fi

echo ""
echo -e "${BLUE}Step 2: Stopping EC2 instances...${NC}"

if [ -n "$FLASK_INSTANCE_ID" ] && [ "$FLASK_INSTANCE_ID" != "None" ]; then
    FLASK_STATE=$(aws ec2 describe-instances --instance-ids "$FLASK_INSTANCE_ID" \
        --query 'Reservations[0].Instances[0].State.Name' --output text 2>/dev/null)

    if [ "$FLASK_STATE" == "running" ]; then
        echo "  Stopping Flask EC2: $FLASK_INSTANCE_ID"
        aws ec2 stop-instances --instance-ids "$FLASK_INSTANCE_ID" > /dev/null
        echo -e "  ${GREEN}Flask EC2 stop initiated${NC}"
    else
        echo -e "  ${YELLOW}Flask EC2 already stopped/stopping${NC}"
    fi
else
    echo -e "  ${YELLOW}Flask EC2 not found, skipping${NC}"
fi

if [ -n "$NEO4J_INSTANCE_ID" ] && [ "$NEO4J_INSTANCE_ID" != "None" ]; then
    NEO4J_STATE=$(aws ec2 describe-instances --instance-ids "$NEO4J_INSTANCE_ID" \
        --query 'Reservations[0].Instances[0].State.Name' --output text 2>/dev/null)

    if [ "$NEO4J_STATE" == "running" ]; then
        echo "  Stopping Neo4j EC2: $NEO4J_INSTANCE_ID"
        aws ec2 stop-instances --instance-ids "$NEO4J_INSTANCE_ID" > /dev/null
        echo -e "  ${GREEN}Neo4j EC2 stop initiated${NC}"
    else
        echo -e "  ${YELLOW}Neo4j EC2 already stopped/stopping${NC}"
    fi
else
    echo -e "  ${YELLOW}Neo4j EC2 not found, skipping${NC}"
fi

echo ""
echo -e "${BLUE}Step 3: Stopping RDS instance...${NC}"

if [ -n "$RDS_INSTANCE_ID" ] && [ "$RDS_INSTANCE_ID" != "None" ]; then
    RDS_STATUS=$(aws rds describe-db-instances --db-instance-identifier "$RDS_INSTANCE_ID" \
        --query 'DBInstances[0].DBInstanceStatus' --output text 2>/dev/null)

    if [ "$RDS_STATUS" == "available" ]; then
        echo "  Stopping RDS: $RDS_INSTANCE_ID"
        aws rds stop-db-instance --db-instance-identifier "$RDS_INSTANCE_ID" > /dev/null
        echo -e "  ${GREEN}RDS stop initiated${NC}"
        echo -e "  ${YELLOW}NOTE: RDS auto-restarts after 7 days. Re-run hibernate if needed.${NC}"
    else
        echo -e "  ${YELLOW}RDS status is '$RDS_STATUS', skipping${NC}"
    fi
else
    echo -e "  ${YELLOW}RDS instance not found, skipping${NC}"
fi

echo ""
echo -e "${BLUE}Step 4: Deleting NAT Gateways (biggest cost saver ~\$45/month EACH)...${NC}"

if [ -n "$NAT_GATEWAY_IDS" ] && [ "$NAT_GATEWAY_IDS" != "None" ]; then
    # Delete ALL NAT Gateways
    for NAT_GW_ID in $(echo "$NAT_GATEWAY_IDS" | tr '\t' ' '); do
        if [ -n "$NAT_GW_ID" ] && [ "$NAT_GW_ID" != "None" ]; then
            echo "  Deleting NAT Gateway: $NAT_GW_ID"
            aws ec2 delete-nat-gateway --nat-gateway-id "$NAT_GW_ID" > /dev/null
            echo -e "  ${GREEN}NAT Gateway $NAT_GW_ID deletion initiated${NC}"
        fi
    done
    echo -e "  ${YELLOW}NOTE: NAT Gateway will be recreated by wakeup script${NC}"
else
    echo -e "  ${YELLOW}NAT Gateway not found, skipping${NC}"
fi

echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}Hibernation Complete!${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""
echo "Estimated monthly savings: ~\$80-88"
echo ""
echo "Remaining costs (approximate):"
echo "  - S3 storage:        ~\$1-5/month"
echo "  - EBS volumes:       ~\$6-9/month"
echo "  - CloudFront:        ~\$0-10/month (minimal if no traffic)"
echo "  - Elastic IP (idle): ~\$3.60/month"
echo "  - Total:             ~\$15-30/month"
echo ""
echo -e "${YELLOW}To wake up the infrastructure, run:${NC}"
echo "  ./scripts/wakeup.sh"
echo ""
echo -e "${YELLOW}GitHub Actions Reminder:${NC}"
echo "  Consider disabling the deploy-backend.yml workflow while hibernating:"
echo "  1. Go to GitHub repo > Actions > Deploy Backend"
echo "  2. Click '...' menu > Disable workflow"
echo ""
