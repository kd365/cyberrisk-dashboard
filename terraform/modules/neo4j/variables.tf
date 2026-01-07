# =============================================================================
# Neo4j Module - Variables
# =============================================================================

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID where Neo4j will be deployed"
  type        = string
}

variable "private_subnet_id" {
  description = "Private subnet ID for Neo4j instance"
  type        = string
}

variable "flask_security_group_id" {
  description = "Security group ID of Flask EC2 (for ingress rules)"
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type for Neo4j"
  type        = string
  default     = "t3.small"
}

variable "key_name" {
  description = "SSH key pair name"
  type        = string
}

variable "neo4j_password" {
  description = "Password for Neo4j admin user"
  type        = string
  sensitive   = true
}

variable "admin_cidr_blocks" {
  description = "CIDR blocks allowed SSH access"
  type        = list(string)
  default     = ["0.0.0.0/0"]  # Restrict in production
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}
