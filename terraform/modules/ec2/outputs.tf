# =============================================================================
# EC2 Module - Outputs
# =============================================================================

output "instance_id" {
  description = "EC2 instance ID"
  value       = aws_instance.flask.id
}

output "public_ip" {
  description = "Public IP address"
  value       = aws_eip.flask.public_ip
}

output "public_dns" {
  description = "Public DNS name (from Elastic IP)"
  value       = aws_eip.flask.public_dns
}

output "security_group_id" {
  description = "Security group ID"
  value       = aws_security_group.ec2.id
}
