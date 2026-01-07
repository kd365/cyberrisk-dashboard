# =============================================================================
# CloudFront Module - Outputs
# =============================================================================

output "distribution_id" {
  description = "CloudFront distribution ID"
  value       = aws_cloudfront_distribution.frontend.id
}

output "domain_name" {
  description = "CloudFront domain name"
  value       = aws_cloudfront_distribution.frontend.domain_name
}

output "arn" {
  description = "CloudFront distribution ARN"
  value       = aws_cloudfront_distribution.frontend.arn
}
