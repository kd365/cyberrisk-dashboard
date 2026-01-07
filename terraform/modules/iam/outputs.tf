# =============================================================================
# IAM Module Outputs
# =============================================================================

# EC2 Role Outputs
output "ec2_role_arn" {
  description = "ARN of the EC2 IAM role"
  value       = aws_iam_role.ec2_role.arn
}

output "ec2_role_name" {
  description = "Name of the EC2 IAM role"
  value       = aws_iam_role.ec2_role.name
}

output "ec2_instance_profile_name" {
  description = "Name of the EC2 instance profile"
  value       = aws_iam_instance_profile.ec2_profile.name
}

output "ec2_instance_profile_arn" {
  description = "ARN of the EC2 instance profile"
  value       = aws_iam_instance_profile.ec2_profile.arn
}

# Lambda Role Outputs
output "lambda_role_arn" {
  description = "ARN of the Lambda IAM role"
  value       = aws_iam_role.lambda_role.arn
}

output "lambda_role_name" {
  description = "Name of the Lambda IAM role"
  value       = aws_iam_role.lambda_role.name
}

# Lex Role Outputs
output "lex_role_arn" {
  description = "ARN of the Lex IAM role"
  value       = aws_iam_role.lex_role.arn
}

output "lex_role_name" {
  description = "Name of the Lex IAM role"
  value       = aws_iam_role.lex_role.name
}
