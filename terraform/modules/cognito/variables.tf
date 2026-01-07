# =============================================================================
# Cognito Module - Variables
# =============================================================================

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "create_admin_user" {
  description = "Whether to create an admin user"
  type        = bool
  default     = true
}

variable "admin_email" {
  description = "Email address for admin user"
  type        = string
  default     = ""
}

variable "admin_temp_password" {
  description = "Temporary password for admin user (must be changed on first login)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}
