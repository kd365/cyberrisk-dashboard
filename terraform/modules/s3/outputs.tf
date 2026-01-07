# =============================================================================
# S3 Module - Outputs
# =============================================================================

output "bucket_id" {
  description = "S3 bucket ID"
  value       = aws_s3_bucket.frontend.id
}

output "bucket_arn" {
  description = "S3 bucket ARN"
  value       = aws_s3_bucket.frontend.arn
}

output "bucket_regional_domain_name" {
  description = "S3 bucket regional domain name"
  value       = aws_s3_bucket.frontend.bucket_regional_domain_name
}

output "bucket_website_endpoint" {
  description = "S3 website endpoint"
  value       = aws_s3_bucket_website_configuration.frontend.website_endpoint
}

# Artifacts bucket outputs
output "artifacts_bucket_id" {
  description = "Artifacts S3 bucket ID"
  value       = aws_s3_bucket.artifacts.id
}

output "artifacts_bucket_arn" {
  description = "Artifacts S3 bucket ARN"
  value       = aws_s3_bucket.artifacts.arn
}
