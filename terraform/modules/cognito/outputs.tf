# =============================================================================
# Cognito Module - Outputs
# =============================================================================

output "user_pool_id" {
  description = "Cognito User Pool ID"
  value       = aws_cognito_user_pool.main.id
}

output "user_pool_arn" {
  description = "Cognito User Pool ARN"
  value       = aws_cognito_user_pool.main.arn
}

output "user_pool_client_id" {
  description = "Cognito User Pool Client ID (for frontend)"
  value       = aws_cognito_user_pool_client.web_client.id
}

output "user_pool_endpoint" {
  description = "Cognito User Pool endpoint"
  value       = aws_cognito_user_pool.main.endpoint
}

output "cognito_domain" {
  description = "Cognito domain for hosted UI (if configured)"
  value       = "cognito-idp.${data.aws_region.current.name}.amazonaws.com/${aws_cognito_user_pool.main.id}"
}

# Data source for current region
data "aws_region" "current" {}
