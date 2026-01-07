variable "project_name" {
  description = "Name of the project"
  type        = string
  default     = "cyberrisk"
}

variable "environment" {
  description = "Environment (dev, staging, prod)"
  type        = string
  default     = "prod"
}

variable "ci_role_arn" {
  description = "ARN of the IAM role used by CI/CD"
  type        = string
}

variable "ec2_role_arn" {
  description = "ARN of the EC2 instance role"
  type        = string
}
