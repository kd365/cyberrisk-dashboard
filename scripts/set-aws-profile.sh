#!/bin/bash
# Source this file before running ANY AWS/Terraform commands
# Usage: source scripts/set-aws-profile.sh

export AWS_PROFILE=cyber-risk
export AWS_DEFAULT_REGION=us-west-2

echo "✅ AWS Profile set to: $AWS_PROFILE"
echo "✅ AWS Region set to: $AWS_DEFAULT_REGION"

# Verify we're in the right account
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null)
if [ "$ACCOUNT_ID" != "000018673740" ]; then
    echo "⚠️  WARNING: Account ID ($ACCOUNT_ID) doesn't match expected CyberRisk account!"
    echo "   Expected: 000018673740"
else
    echo "✅ Confirmed: Using CyberRisk AWS account ($ACCOUNT_ID)"
fi
