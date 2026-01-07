# =============================================================================
# Lex Module Outputs
# =============================================================================

output "bot_id" {
  description = "Lex bot ID"
  value       = aws_lexv2models_bot.cyber_risk_bot.id
}

output "bot_arn" {
  description = "Lex bot ARN"
  value       = aws_lexv2models_bot.cyber_risk_bot.arn
}

output "bot_alias_name" {
  description = "Lex bot alias name (created via AWS CLI)"
  value       = "production"
}

output "bot_version" {
  description = "Lex bot version"
  value       = aws_lexv2models_bot_version.v1.bot_version
}

output "lambda_function_arn" {
  description = "ARN of the Lex fulfillment Lambda function"
  value       = aws_lambda_function.lex_fulfillment.arn
}

output "lambda_function_name" {
  description = "Name of the Lex fulfillment Lambda function"
  value       = aws_lambda_function.lex_fulfillment.function_name
}

output "lambda_security_group_id" {
  description = "Security group ID for the Lambda function"
  value       = aws_security_group.lambda_sg.id
}

output "production_alias_id" {
  description = "Production bot alias ID"
  value       = "ORMKEIX36W"  # Created manually via AWS CLI
}
