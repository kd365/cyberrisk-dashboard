# =============================================================================
# CyberRisk Dashboard - Terraform Outputs
# =============================================================================

# -----------------------------------------------------------------------------
# VPC Outputs
# -----------------------------------------------------------------------------

output "vpc_id" {
  description = "ID of the VPC"
  value       = module.vpc.vpc_id
}

output "public_subnet_ids" {
  description = "IDs of public subnets"
  value       = module.vpc.public_subnet_ids
}

output "private_subnet_ids" {
  description = "IDs of private subnets"
  value       = module.vpc.private_subnet_ids
}

# -----------------------------------------------------------------------------
# RDS Outputs
# -----------------------------------------------------------------------------

output "rds_endpoint" {
  description = "RDS PostgreSQL endpoint"
  value       = module.rds.db_endpoint
}

output "rds_port" {
  description = "RDS PostgreSQL port"
  value       = module.rds.db_port
}

output "rds_database_name" {
  description = "RDS database name"
  value       = var.db_name
}

# -----------------------------------------------------------------------------
# EC2 Outputs
# -----------------------------------------------------------------------------

output "ec2_public_ip" {
  description = "Public IP of EC2 instance"
  value       = module.ec2.public_ip
}

output "ec2_public_dns" {
  description = "Public DNS of EC2 instance"
  value       = module.ec2.public_dns
}

output "flask_api_url" {
  description = "Flask API URL"
  value       = "http://${module.ec2.public_ip}:5000"
}

output "ssh_command" {
  description = "SSH command to connect to EC2 instance"
  value       = "ssh -i ~/.ssh/${var.ec2_key_name}.pem ec2-user@${module.ec2.public_ip}"
}

# -----------------------------------------------------------------------------
# S3 & CloudFront Outputs
# -----------------------------------------------------------------------------

output "s3_bucket_name" {
  description = "S3 bucket name for frontend"
  value       = module.s3.bucket_id
}

output "s3_artifacts_bucket_name" {
  description = "S3 bucket name for artifacts (SEC filings, transcripts)"
  value       = module.s3.artifacts_bucket_id
}

output "cloudfront_domain_name" {
  description = "CloudFront distribution domain name"
  value       = module.cloudfront.domain_name
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID"
  value       = module.cloudfront.distribution_id
}

output "frontend_url" {
  description = "Frontend URL (CloudFront)"
  value       = "https://${module.cloudfront.domain_name}"
}

# -----------------------------------------------------------------------------
# Lex Outputs
# -----------------------------------------------------------------------------

output "lex_bot_id" {
  description = "Amazon Lex bot ID"
  value       = module.lex.bot_id
}

output "lex_bot_alias_name" {
  description = "Amazon Lex bot alias name"
  value       = module.lex.bot_alias_name
}

# -----------------------------------------------------------------------------
# Neo4j Outputs
# -----------------------------------------------------------------------------

output "neo4j_private_ip" {
  description = "Private IP of Neo4j instance"
  value       = module.neo4j.private_ip
}

output "neo4j_bolt_uri" {
  description = "Neo4j Bolt connection URI"
  value       = module.neo4j.bolt_uri
}

# -----------------------------------------------------------------------------
# Cognito Outputs
# -----------------------------------------------------------------------------

output "cognito_user_pool_id" {
  description = "Cognito User Pool ID"
  value       = module.cognito.user_pool_id
}

output "cognito_client_id" {
  description = "Cognito User Pool Client ID"
  value       = module.cognito.user_pool_client_id
}

output "cognito_endpoint" {
  description = "Cognito User Pool endpoint"
  value       = module.cognito.user_pool_endpoint
}

# -----------------------------------------------------------------------------
# Summary Output
# -----------------------------------------------------------------------------

output "deployment_summary" {
  description = "Summary of deployed resources"
  value       = <<-EOT

    ============================================================
    CyberRisk Dashboard - Deployment Complete
    ============================================================

    Frontend (React):
      URL: https://${module.cloudfront.domain_name}
      S3 Bucket: ${module.s3.bucket_id}

    Backend (Flask):
      API URL: http://${module.ec2.public_ip}:5000
      SSH: ssh -i ~/.ssh/${var.ec2_key_name}.pem ec2-user@${module.ec2.public_ip}

    Database (PostgreSQL):
      Endpoint: ${module.rds.db_endpoint}
      Database: ${var.db_name}

    Neo4j (Knowledge Graph):
      Bolt URI: ${module.neo4j.bolt_uri}
      Private IP: ${module.neo4j.private_ip}

    Cognito (Authentication):
      User Pool ID: ${module.cognito.user_pool_id}
      Client ID: ${module.cognito.user_pool_client_id}

    Lex Chatbot:
      Bot ID: ${module.lex.bot_id}

    ============================================================
  EOT
}
