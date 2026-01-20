#!/bin/bash
# =============================================================================
# Setup Remote Terraform State (S3 + DynamoDB)
# This prevents state corruption and wrong-account issues
# =============================================================================

set -e

# Source the profile settings
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/set-aws-profile.sh"

STATE_BUCKET="cyberrisk-terraform-state-kh"
LOCK_TABLE="cyberrisk-terraform-locks"
REGION="us-west-2"

echo ""
echo "Creating S3 bucket for Terraform state..."
aws s3 mb "s3://${STATE_BUCKET}" --region "$REGION" 2>/dev/null || echo "Bucket already exists"

echo "Enabling versioning on state bucket..."
aws s3api put-bucket-versioning \
    --bucket "$STATE_BUCKET" \
    --versioning-configuration Status=Enabled

echo "Enabling encryption on state bucket..."
aws s3api put-bucket-encryption \
    --bucket "$STATE_BUCKET" \
    --server-side-encryption-configuration '{
        "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
    }'

echo "Blocking public access on state bucket..."
aws s3api put-public-access-block \
    --bucket "$STATE_BUCKET" \
    --public-access-block-configuration '{
        "BlockPublicAcls": true,
        "IgnorePublicAcls": true,
        "BlockPublicPolicy": true,
        "RestrictPublicBuckets": true
    }'

echo ""
echo "Creating DynamoDB table for state locking..."
aws dynamodb create-table \
    --table-name "$LOCK_TABLE" \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --region "$REGION" 2>/dev/null || echo "Table already exists"

echo ""
echo "============================================================"
echo "✅ Remote state infrastructure created!"
echo "============================================================"
echo ""
echo "Now update terraform/main.tf - uncomment the backend block:"
echo ""
echo '  backend "s3" {'
echo "    bucket         = \"${STATE_BUCKET}\""
echo '    key            = "terraform.tfstate"'
echo "    region         = \"${REGION}\""
echo "    dynamodb_table = \"${LOCK_TABLE}\""
echo "    encrypt        = true"
echo "    profile        = \"cyber-risk\""
echo '  }'
echo ""
echo "Then run: terraform init -migrate-state"
echo ""
