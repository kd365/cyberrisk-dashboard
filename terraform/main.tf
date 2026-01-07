# =============================================================================
# CyberRisk Dashboard - Main Terraform Configuration
# =============================================================================
#
# PROJECT: Cyber Risk Assessment Dashboard (Class Assessment)
# AUTHOR:  Kathleen Hill - With Claude Code Assistance
# DATE:    December 2025
#
# DESCRIPTION:
# This Terraform configuration provisions the complete infrastructure for a
# cybersecurity risk assessment dashboard. The application uses AWS AI services
# to analyze SEC filings, earnings transcripts, financial metrics, and company growth data.
#
# ARCHITECTURE:
# - VPC with public/private subnets across 2 availability zones
# - RDS PostgreSQL database (private subnets) for caching and data persistence
# - EC2 instance (public subnet) running Flask/Gunicorn backend API
# - S3 bucket for React frontend static hosting
# - CloudFront distribution for global CDN and API proxying
# - IAM roles for AWS AI services (Comprehend, Lex, S3)
# - Amazon Lex V2 chatbot with Lambda fulfillment
#
# AWS AI SERVICES USED:
# 1. Amazon Comprehend - Sentiment analysis, key phrase extraction, entity detection
# 2. Amazon Lex V2 - Conversational chatbot interface for dashboard queries
# 3. (External) Explorium API - Company growth metrics and hiring trends
#
# MODULES:
# - vpc:        Network infrastructure (VPC, subnets, route tables, NAT gateway)
# - iam:        IAM roles and policies for EC2, Lambda, and Lex
# - rds:        PostgreSQL database instance with security groups
# - ec2:        Backend server with user data bootstrap script
# - s3:         Static website hosting bucket
# - cloudfront: CDN distribution with S3 origin and API origin
# - lex:        Lex V2 bot, intents, and Lambda fulfillment function
#
# USAGE:
#   terraform init
#   terraform plan -var-file="terraform.tfvars"
#   terraform apply -var-file="terraform.tfvars"
#
# REQUIRED VARIABLES (in terraform.tfvars):
#   - aws_profile: AWS CLI profile to use
#   - db_password: PostgreSQL database password
#   - ec2_key_name: SSH key pair name for EC2 access
#   - source_s3_bucket: S3 bucket containing source artifacts
#
# =============================================================================

terraform {
  required_version = ">= 1.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # ---------------------------------------------------------------------------
  # TERRAFORM STATE BACKEND CONFIGURATION
  # ---------------------------------------------------------------------------
  # By default, Terraform stores state locally in terraform.tfstate file.
  # This works well for single-developer projects like this class assessment.
  #
  # LOCAL STATE (current configuration):
  # - State stored in ./terraform.tfstate on your machine
  # - Simple setup, no additional infrastructure needed
  # - Appropriate for individual development and class projects
  # - Risk: state file can be lost if machine fails (backup recommended)
  #
  # REMOTE STATE (S3 backend - commented out below):
  # - State stored in S3 bucket with optional DynamoDB locking
  # - Required for team collaboration (prevents concurrent modifications)
  # - Required for CI/CD pipelines (Jenkins, GitHub Actions, etc.)
  # - Provides state versioning and encryption at rest
  # - Typical for dev/staging/prod environment splits
  #
  # To enable remote state:
  # 1. Create S3 bucket: aws s3 mb s3://cyberrisk-terraform-state
  # 2. Create DynamoDB table for locking (optional but recommended):
  #    aws dynamodb create-table \
  #      --table-name cyberrisk-terraform-locks \
  #      --attribute-definitions AttributeName=LockID,AttributeType=S \
  #      --key-schema AttributeName=LockID,KeyType=HASH \
  #      --billing-mode PAY_PER_REQUEST
  # 3. Uncomment the backend block below
  # 4. Run: terraform init -migrate-state
  #
  # For this class project, local state is sufficient since there's no
  # dev/staging/prod split and only one developer is managing the infrastructure.
  # ---------------------------------------------------------------------------
  #
  # backend "s3" {
  #   bucket         = "cyberrisk-terraform-state"
  #   key            = "terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "cyberrisk-terraform-locks"
  #   encrypt        = true
  # }
}

provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile

  # Note: default_tags removed because iam:TagInstanceProfile permission is not available
  # Tags are applied individually to resources that support them
}

# =============================================================================
# Data Sources
# =============================================================================

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

# =============================================================================
# Local Variables
# =============================================================================

locals {
  name_prefix = "cyberrisk-${var.environment}${var.name_suffix}"

  common_tags = {
    Project     = "CyberRisk-Dashboard"
    Environment = var.environment
    Owner       = "kh"
  }
}

# =============================================================================
# VPC Module
# =============================================================================

module "vpc" {
  source = "./modules/vpc"

  name_prefix        = local.name_prefix
  vpc_cidr           = var.vpc_cidr
  availability_zones = slice(data.aws_availability_zones.available.names, 0, 2)

  tags = local.common_tags
}

# =============================================================================
# IAM Module
# =============================================================================

module "iam" {
  source = "./modules/iam"

  name_prefix = local.name_prefix
  aws_region  = var.aws_region
  account_id  = data.aws_caller_identity.current.account_id

  tags = local.common_tags
}

# =============================================================================
# RDS PostgreSQL Module
# =============================================================================

module "rds" {
  source = "./modules/rds"

  name_prefix         = local.name_prefix
  vpc_id              = module.vpc.vpc_id
  private_subnet_ids  = module.vpc.private_subnet_ids
  ec2_security_group_id = module.ec2.security_group_id

  db_name             = var.db_name
  db_username         = var.db_username
  db_password         = var.db_password
  db_instance_class   = var.db_instance_class

  tags = local.common_tags
}

# =============================================================================
# S3 Module (React Frontend Hosting + Artifacts)
# =============================================================================
# NOTE: S3 module is defined early so artifacts_bucket_id can be used by EC2

module "s3" {
  source = "./modules/s3"

  name_prefix    = local.name_prefix

  tags = local.common_tags
}

# =============================================================================
# EC2 Module (Flask Backend with Gunicorn)
# =============================================================================

module "ec2" {
  source = "./modules/ec2"

  name_prefix       = local.name_prefix
  vpc_id            = module.vpc.vpc_id
  public_subnet_id  = module.vpc.public_subnet_ids[0]

  instance_type     = var.ec2_instance_type
  key_name          = var.ec2_key_name

  # Database connection info
  db_host           = module.rds.db_endpoint
  db_name           = var.db_name
  db_username       = var.db_username
  db_password       = var.db_password

  # IAM role for AI services
  iam_instance_profile = module.iam.ec2_instance_profile_name

  # S3 bucket for artifacts (created in S3 module)
  artifacts_bucket  = module.s3.artifacts_bucket_id

  # API keys for external services
  explorium_api_key    = var.explorium_api_key
  alphavantage_api_key = var.alphavantage_api_key
  coresignal_api_key   = var.coresignal_api_key

  # Lex bot configuration
  lex_bot_id       = module.lex.bot_id
  lex_bot_alias_id = module.lex.production_alias_id

  # Neo4j configuration (Knowledge Graph)
  neo4j_host     = module.neo4j.private_ip
  neo4j_password = var.neo4j_password

  # Cognito configuration (Authentication)
  cognito_user_pool_id = module.cognito.user_pool_id
  cognito_client_id    = module.cognito.user_pool_client_id
  cognito_region       = var.aws_region

  # USPTO API key for patent searches
  uspto_api_key = var.uspto_api_key

  tags = local.common_tags
}

# =============================================================================
# CloudFront Module
# =============================================================================

module "cloudfront" {
  source = "./modules/cloudfront"

  name_prefix              = local.name_prefix
  s3_bucket_id             = module.s3.bucket_id
  s3_bucket_domain_name    = module.s3.bucket_regional_domain_name
  s3_bucket_arn            = module.s3.bucket_arn
  api_endpoint             = module.ec2.public_dns  # DNS hostname required by CloudFront (no IP addresses)

  tags = local.common_tags
}

# =============================================================================
# Lex Module (Chatbot)
# =============================================================================

module "lex" {
  source = "./modules/lex"

  name_prefix      = local.name_prefix
  lambda_role_arn  = module.iam.lambda_role_arn
  lex_role_arn     = module.iam.lex_role_arn

  # Database connection for Lambda
  db_host          = module.rds.db_endpoint
  db_name          = var.db_name
  db_username      = var.db_username
  db_password      = var.db_password

  # VPC config for Lambda to access RDS
  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids

  # AWS profile for local-exec commands
  aws_profile        = var.aws_profile

  tags = local.common_tags
}

# =============================================================================
# Neo4j Module (Knowledge Graph Database)
# =============================================================================

module "neo4j" {
  source = "./modules/neo4j"

  name_prefix             = local.name_prefix
  vpc_id                  = module.vpc.vpc_id
  private_subnet_id       = module.vpc.private_subnet_ids[0]
  flask_security_group_id = module.ec2.security_group_id
  key_name                = var.ec2_key_name
  instance_type           = var.neo4j_instance_type
  neo4j_password          = var.neo4j_password

  tags = local.common_tags
}

# =============================================================================
# Cognito Module (User Authentication)
# =============================================================================

module "cognito" {
  source = "./modules/cognito"

  name_prefix         = local.name_prefix
  create_admin_user   = var.cognito_admin_email != ""
  admin_email         = var.cognito_admin_email
  admin_temp_password = var.cognito_admin_temp_password

  tags = local.common_tags
}
