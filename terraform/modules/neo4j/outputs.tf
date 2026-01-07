# =============================================================================
# Neo4j Module - Outputs
# =============================================================================

output "private_ip" {
  description = "Private IP address of Neo4j instance"
  value       = aws_instance.neo4j.private_ip
}

output "instance_id" {
  description = "EC2 instance ID"
  value       = aws_instance.neo4j.id
}

output "security_group_id" {
  description = "Security group ID"
  value       = aws_security_group.neo4j.id
}

output "bolt_uri" {
  description = "Neo4j Bolt connection URI"
  value       = "bolt://${aws_instance.neo4j.private_ip}:7687"
}

output "http_uri" {
  description = "Neo4j HTTP browser URI"
  value       = "http://${aws_instance.neo4j.private_ip}:7474"
}
