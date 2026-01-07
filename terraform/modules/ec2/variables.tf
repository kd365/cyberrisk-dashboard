# =============================================================================
# EC2 Module - Variables
# =============================================================================

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "vpc_id" {
  description = "ID of the VPC"
  type        = string
}

variable "public_subnet_id" {
  description = "ID of public subnet for EC2"
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t2.micro"
}

variable "key_name" {
  description = "Name of EC2 key pair"
  type        = string
}

variable "iam_instance_profile" {
  description = "IAM instance profile name"
  type        = string
}

variable "db_host" {
  description = "Database host endpoint"
  type        = string
}

variable "db_name" {
  description = "Database name"
  type        = string
}

variable "db_username" {
  description = "Database username"
  type        = string
}

variable "db_password" {
  description = "Database password"
  type        = string
  sensitive   = true
}

variable "artifacts_bucket" {
  description = "S3 bucket for artifacts"
  type        = string
  default     = ""
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}

variable "explorium_api_key" {
  description = "Explorium API key for company growth data"
  type        = string
  sensitive   = true
  default     = ""
}

variable "alphavantage_api_key" {
  description = "Alpha Vantage API key for earnings transcripts"
  type        = string
  sensitive   = true
  default     = ""
}

variable "lex_bot_id" {
  description = "Amazon Lex bot ID"
  type        = string
  default     = ""
}

variable "lex_bot_alias_id" {
  description = "Amazon Lex bot alias ID"
  type        = string
  default     = ""
}

variable "coresignal_api_key" {
  description = "CoreSignal API key for employee growth and job data"
  type        = string
  sensitive   = true
  default     = ""
}

# -----------------------------------------------------------------------------
# Neo4j Configuration
# -----------------------------------------------------------------------------

variable "neo4j_host" {
  description = "Neo4j private IP address"
  type        = string
  default     = ""
}

variable "neo4j_password" {
  description = "Neo4j password"
  type        = string
  sensitive   = true
  default     = ""
}

# -----------------------------------------------------------------------------
# Cognito Configuration
# -----------------------------------------------------------------------------

variable "cognito_user_pool_id" {
  description = "Cognito User Pool ID"
  type        = string
  default     = ""
}

variable "cognito_client_id" {
  description = "Cognito User Pool Client ID"
  type        = string
  default     = ""
}

variable "cognito_region" {
  description = "Cognito AWS region"
  type        = string
  default     = "us-west-2"
}

# -----------------------------------------------------------------------------
# USPTO API Configuration
# -----------------------------------------------------------------------------

variable "uspto_api_key" {
  description = "USPTO Open Data Portal API key for patent searches"
  type        = string
  sensitive   = true
  default     = ""
}
