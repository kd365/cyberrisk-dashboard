#!/bin/bash
# =============================================================================
# CyberRisk Dashboard - Wakeup Script
# Restarts hibernated resources
# =============================================================================

set -e

# Configuration
AWS_REGION="${AWS_REGION:-us-west-2}"
AWS_PROFILE="${AWS_PROFILE:-cyber-risk}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}============================================================${NC}"
echo -e "${BLUE}CyberRisk Dashboard - Wakeup Mode${NC}"
echo -e "${BLUE}============================================================${NC}"
echo ""

# Check AWS CLI is available
if ! command -v aws &> /dev/null; then
    echo -e "${RED}ERROR: AWS CLI not found. Please install it first.${NC}"
    exit 1
fi

# Set profile
export AWS_PROFILE="$AWS_PROFILE"
export AWS_DEFAULT_REGION="$AWS_REGION"

echo -e "${YELLOW}Using AWS Profile: $AWS_PROFILE${NC}"
echo -e "${YELLOW}Using AWS Region: $AWS_REGION${NC}"
echo ""

# CRITICAL: Verify we're using the correct AWS account
EXPECTED_ACCOUNT="000018673740"
CURRENT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text 2>/dev/null)
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
echo ""

# Load state file
STATE_FILE="$(dirname "$0")/.hibernate_state.json"

if [ ! -f "$STATE_FILE" ]; then
    echo -e "${RED}ERROR: State file not found at $STATE_FILE${NC}"
    echo "Please ensure you ran hibernate.sh first, or manually specify resource IDs."
    exit 1
fi

echo -e "${BLUE}Loading hibernation state...${NC}"

FLASK_INSTANCE_ID=$(cat "$STATE_FILE" | grep -o '"flask_instance_id": "[^"]*"' | cut -d'"' -f4)
NEO4J_INSTANCE_ID=$(cat "$STATE_FILE" | grep -o '"neo4j_instance_id": "[^"]*"' | cut -d'"' -f4)
RDS_INSTANCE_ID=$(cat "$STATE_FILE" | grep -o '"rds_instance_id": "[^"]*"' | cut -d'"' -f4)
NAT_SUBNET_ID=$(cat "$STATE_FILE" | grep -o '"nat_subnet_id": "[^"]*"' | cut -d'"' -f4)
HIBERNATED_AT=$(cat "$STATE_FILE" | grep -o '"hibernated_at": "[^"]*"' | cut -d'"' -f4)

echo ""
echo -e "${BLUE}Hibernation State (from $HIBERNATED_AT):${NC}"
echo "  Flask EC2:     ${FLASK_INSTANCE_ID:-Not saved}"
echo "  Neo4j EC2:     ${NEO4J_INSTANCE_ID:-Not saved}"
echo "  RDS Instance:  ${RDS_INSTANCE_ID:-Not saved}"
echo "  NAT Subnet:    ${NAT_SUBNET_ID:-Not saved}"
echo ""

# Confirm before proceeding
echo -e "${YELLOW}This will restart the following resources:${NC}"
echo "  - EC2 instances (Flask and Neo4j)"
echo "  - RDS database instance"
echo "  - Create a NEW NAT Gateway (required for private subnet internet access)"
echo ""
echo -e "${YELLOW}Estimated startup time: 5-10 minutes${NC}"
echo ""

read -p "Do you want to proceed? (yes/no): " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    echo -e "${RED}Aborted.${NC}"
    exit 0
fi

echo ""
echo -e "${BLUE}Step 1: Creating NAT Gateway (takes 2-3 minutes)...${NC}"

if [ -n "$NAT_SUBNET_ID" ] && [ "$NAT_SUBNET_ID" != "None" ]; then
    # Check if NAT Gateway already exists
    EXISTING_NAT=$(aws ec2 describe-nat-gateways \
        --filter "Name=subnet-id,Values=$NAT_SUBNET_ID" "Name=state,Values=available,pending" \
        --query 'NatGateways[0].NatGatewayId' \
        --output text 2>/dev/null)

    if [ -n "$EXISTING_NAT" ] && [ "$EXISTING_NAT" != "None" ]; then
        echo -e "  ${YELLOW}NAT Gateway already exists: $EXISTING_NAT${NC}"
        NAT_GATEWAY_ID="$EXISTING_NAT"
    else
        # Allocate new Elastic IP
        echo "  Allocating Elastic IP..."
        NEW_EIP_ALLOCATION_ID=$(aws ec2 allocate-address \
            --domain vpc \
            --query 'AllocationId' \
            --output text)
        echo -e "  ${GREEN}Elastic IP allocated: $NEW_EIP_ALLOCATION_ID${NC}"

        # Create NAT Gateway
        echo "  Creating NAT Gateway..."
        NAT_GATEWAY_ID=$(aws ec2 create-nat-gateway \
            --subnet-id "$NAT_SUBNET_ID" \
            --allocation-id "$NEW_EIP_ALLOCATION_ID" \
            --query 'NatGateway.NatGatewayId' \
            --output text)
        echo -e "  ${GREEN}NAT Gateway created: $NAT_GATEWAY_ID${NC}"

        # Tag the NAT Gateway
        aws ec2 create-tags --resources "$NAT_GATEWAY_ID" \
            --tags "Key=Name,Value=cyberrisk-nat-gateway" "Key=Project,Value=cyberrisk"

        echo "  Waiting for NAT Gateway to become available..."
        aws ec2 wait nat-gateway-available --nat-gateway-ids "$NAT_GATEWAY_ID"
        echo -e "  ${GREEN}NAT Gateway is now available${NC}"

        # Update route table for private subnets
        echo "  Updating private subnet route tables..."

        # Find VPC ID
        VPC_ID=$(aws ec2 describe-subnets --subnet-ids "$NAT_SUBNET_ID" \
            --query 'Subnets[0].VpcId' --output text)

        # Find private route tables (those without IGW route)
        PRIVATE_ROUTE_TABLES=$(aws ec2 describe-route-tables \
            --filters "Name=vpc-id,Values=$VPC_ID" \
            --query "RouteTables[?!Routes[?GatewayId && starts_with(GatewayId, 'igw-')]].RouteTableId" \
            --output text)

        for RT_ID in $PRIVATE_ROUTE_TABLES; do
            # Check if route already exists
            EXISTING_ROUTE=$(aws ec2 describe-route-tables --route-table-ids "$RT_ID" \
                --query "RouteTables[0].Routes[?DestinationCidrBlock=='0.0.0.0/0'].NatGatewayId" \
                --output text 2>/dev/null)

            if [ -z "$EXISTING_ROUTE" ] || [ "$EXISTING_ROUTE" == "None" ]; then
                # Delete old blackhole route if exists
                aws ec2 delete-route --route-table-id "$RT_ID" \
                    --destination-cidr-block "0.0.0.0/0" 2>/dev/null || true

                # Create new route to NAT Gateway
                aws ec2 create-route --route-table-id "$RT_ID" \
                    --destination-cidr-block "0.0.0.0/0" \
                    --nat-gateway-id "$NAT_GATEWAY_ID" > /dev/null
                echo -e "  ${GREEN}Updated route table: $RT_ID${NC}"
            else
                # Replace existing route
                aws ec2 replace-route --route-table-id "$RT_ID" \
                    --destination-cidr-block "0.0.0.0/0" \
                    --nat-gateway-id "$NAT_GATEWAY_ID" > /dev/null
                echo -e "  ${GREEN}Replaced route in: $RT_ID${NC}"
            fi
        done
    fi
else
    echo -e "  ${YELLOW}NAT subnet not saved, skipping NAT Gateway creation${NC}"
    echo -e "  ${YELLOW}You may need to manually create NAT Gateway via Terraform${NC}"
fi

echo ""
echo -e "${BLUE}Step 2: Starting RDS instance...${NC}"

if [ -n "$RDS_INSTANCE_ID" ] && [ "$RDS_INSTANCE_ID" != "None" ]; then
    RDS_STATUS=$(aws rds describe-db-instances --db-instance-identifier "$RDS_INSTANCE_ID" \
        --query 'DBInstances[0].DBInstanceStatus' --output text 2>/dev/null)

    if [ "$RDS_STATUS" == "stopped" ]; then
        echo "  Starting RDS: $RDS_INSTANCE_ID"
        aws rds start-db-instance --db-instance-identifier "$RDS_INSTANCE_ID" > /dev/null
        echo -e "  ${GREEN}RDS start initiated (takes 5-10 minutes to be available)${NC}"
    elif [ "$RDS_STATUS" == "available" ]; then
        echo -e "  ${GREEN}RDS is already available${NC}"
    else
        echo -e "  ${YELLOW}RDS status is '$RDS_STATUS'${NC}"
    fi
else
    echo -e "  ${YELLOW}RDS instance ID not saved, skipping${NC}"
fi

echo ""
echo -e "${BLUE}Step 3: Starting EC2 instances...${NC}"

if [ -n "$FLASK_INSTANCE_ID" ] && [ "$FLASK_INSTANCE_ID" != "None" ]; then
    FLASK_STATE=$(aws ec2 describe-instances --instance-ids "$FLASK_INSTANCE_ID" \
        --query 'Reservations[0].Instances[0].State.Name' --output text 2>/dev/null)

    if [ "$FLASK_STATE" == "stopped" ]; then
        echo "  Starting Flask EC2: $FLASK_INSTANCE_ID"
        aws ec2 start-instances --instance-ids "$FLASK_INSTANCE_ID" > /dev/null
        echo -e "  ${GREEN}Flask EC2 start initiated${NC}"
    elif [ "$FLASK_STATE" == "running" ]; then
        echo -e "  ${GREEN}Flask EC2 is already running${NC}"
    else
        echo -e "  ${YELLOW}Flask EC2 state is '$FLASK_STATE'${NC}"
    fi
else
    echo -e "  ${YELLOW}Flask EC2 instance ID not saved, skipping${NC}"
fi

if [ -n "$NEO4J_INSTANCE_ID" ] && [ "$NEO4J_INSTANCE_ID" != "None" ]; then
    NEO4J_STATE=$(aws ec2 describe-instances --instance-ids "$NEO4J_INSTANCE_ID" \
        --query 'Reservations[0].Instances[0].State.Name' --output text 2>/dev/null)

    if [ "$NEO4J_STATE" == "stopped" ]; then
        echo "  Starting Neo4j EC2: $NEO4J_INSTANCE_ID"
        aws ec2 start-instances --instance-ids "$NEO4J_INSTANCE_ID" > /dev/null
        echo -e "  ${GREEN}Neo4j EC2 start initiated${NC}"
    elif [ "$NEO4J_STATE" == "running" ]; then
        echo -e "  ${GREEN}Neo4j EC2 is already running${NC}"
    else
        echo -e "  ${YELLOW}Neo4j EC2 state is '$NEO4J_STATE'${NC}"
    fi
else
    echo -e "  ${YELLOW}Neo4j EC2 instance ID not saved, skipping${NC}"
fi

echo ""
echo -e "${BLUE}Step 4: Waiting for instances to be ready...${NC}"

# Wait for EC2 instances
if [ -n "$FLASK_INSTANCE_ID" ] && [ "$FLASK_INSTANCE_ID" != "None" ]; then
    echo "  Waiting for Flask EC2 to be running..."
    aws ec2 wait instance-running --instance-ids "$FLASK_INSTANCE_ID" 2>/dev/null || true

    NEW_PUBLIC_IP=$(aws ec2 describe-instances --instance-ids "$FLASK_INSTANCE_ID" \
        --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
    echo -e "  ${GREEN}Flask EC2 is running. Public IP: $NEW_PUBLIC_IP${NC}"
fi

if [ -n "$NEO4J_INSTANCE_ID" ] && [ "$NEO4J_INSTANCE_ID" != "None" ]; then
    echo "  Waiting for Neo4j EC2 to be running..."
    aws ec2 wait instance-running --instance-ids "$NEO4J_INSTANCE_ID" 2>/dev/null || true

    NEO4J_PRIVATE_IP=$(aws ec2 describe-instances --instance-ids "$NEO4J_INSTANCE_ID" \
        --query 'Reservations[0].Instances[0].PrivateIpAddress' --output text)
    echo -e "  ${GREEN}Neo4j EC2 is running. Private IP: $NEO4J_PRIVATE_IP${NC}"
fi

# Check RDS status
if [ -n "$RDS_INSTANCE_ID" ] && [ "$RDS_INSTANCE_ID" != "None" ]; then
    echo ""
    echo "  Checking RDS status (may still be starting)..."
    RDS_STATUS=$(aws rds describe-db-instances --db-instance-identifier "$RDS_INSTANCE_ID" \
        --query 'DBInstances[0].DBInstanceStatus' --output text 2>/dev/null)
    RDS_ENDPOINT=$(aws rds describe-db-instances --db-instance-identifier "$RDS_INSTANCE_ID" \
        --query 'DBInstances[0].Endpoint.Address' --output text 2>/dev/null)

    if [ "$RDS_STATUS" == "available" ]; then
        echo -e "  ${GREEN}RDS is available: $RDS_ENDPOINT${NC}"
    else
        echo -e "  ${YELLOW}RDS status: $RDS_STATUS (will be available in a few minutes)${NC}"
    fi
fi

echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}Wakeup Complete!${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""

# Print summary with new IPs
echo -e "${BLUE}Resource Summary:${NC}"
echo ""

if [ -n "$FLASK_INSTANCE_ID" ] && [ "$FLASK_INSTANCE_ID" != "None" ]; then
    NEW_PUBLIC_IP=$(aws ec2 describe-instances --instance-ids "$FLASK_INSTANCE_ID" \
        --query 'Reservations[0].Instances[0].PublicIpAddress' --output text 2>/dev/null)
    echo "Flask Backend:"
    echo "  Instance ID: $FLASK_INSTANCE_ID"
    echo "  Public IP:   $NEW_PUBLIC_IP"
    echo "  API URL:     http://$NEW_PUBLIC_IP:5000"
    echo ""
fi

if [ -n "$RDS_INSTANCE_ID" ] && [ "$RDS_INSTANCE_ID" != "None" ]; then
    RDS_ENDPOINT=$(aws rds describe-db-instances --db-instance-identifier "$RDS_INSTANCE_ID" \
        --query 'DBInstances[0].Endpoint.Address' --output text 2>/dev/null)
    echo "RDS Database:"
    echo "  Instance ID: $RDS_INSTANCE_ID"
    echo "  Endpoint:    $RDS_ENDPOINT"
    echo ""
fi

echo -e "${YELLOW}Post-Wakeup Checklist:${NC}"
echo "  1. Wait 5-10 minutes for all services to fully initialize"
echo "  2. Test the Flask API: curl http://<flask-ip>:5000/health"
echo "  3. Re-enable GitHub Actions deploy-backend workflow if disabled"
echo "  4. Update CloudFront origin if Flask IP changed (check Terraform)"
echo ""

echo -e "${YELLOW}If Flask IP changed, update CloudFront:${NC}"
echo "  cd terraform && terraform apply"
echo ""

echo -e "${YELLOW}GitHub Actions:${NC}"
echo "  If you disabled deploy-backend.yml, re-enable it:"
echo "  1. Go to GitHub repo > Actions > Deploy Backend"
echo "  2. Click '...' menu > Enable workflow"
echo ""
