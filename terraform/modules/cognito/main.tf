# =============================================================================
# Cognito Module - User Authentication for CyberRisk Dashboard
# =============================================================================
#
# This module provisions AWS Cognito User Pool for authentication.
# Used to protect write operations (add/remove companies) while allowing
# public read access to the dashboard.
#
# Cost: FREE for first 50,000 monthly active users
#
# =============================================================================

# -----------------------------------------------------------------------------
# Cognito User Pool
# -----------------------------------------------------------------------------

resource "aws_cognito_user_pool" "main" {
  name = "${var.name_prefix}-user-pool"

  # Password policy
  password_policy {
    minimum_length    = 8
    require_lowercase = true
    require_numbers   = true
    require_symbols   = false
    require_uppercase = true
  }

  # Auto-verify email
  auto_verified_attributes = ["email"]

  # Account recovery via email
  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  # Username configuration - use email as username
  username_configuration {
    case_sensitive = false
  }

  # Schema - email required
  schema {
    name                = "email"
    attribute_data_type = "String"
    required            = true
    mutable             = true

    string_attribute_constraints {
      min_length = 5
      max_length = 256
    }
  }

  # MFA disabled for simplicity (portfolio app)
  mfa_configuration = "OFF"

  # Email configuration - use Cognito default
  email_configuration {
    email_sending_account = "COGNITO_DEFAULT"
  }

  # Verification message customization
  verification_message_template {
    default_email_option = "CONFIRM_WITH_CODE"
    email_subject        = "CyberRisk Dashboard - Verify your email"
    email_message        = "Your verification code is {####}"
  }

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-cognito"
  })
}

# -----------------------------------------------------------------------------
# Cognito User Pool Client (for web app)
# -----------------------------------------------------------------------------

resource "aws_cognito_user_pool_client" "web_client" {
  name         = "${var.name_prefix}-web-client"
  user_pool_id = aws_cognito_user_pool.main.id

  # No client secret for browser apps (SPA)
  generate_secret = false

  # Auth flows supported
  explicit_auth_flows = [
    "ALLOW_USER_PASSWORD_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
    "ALLOW_USER_SRP_AUTH"
  ]

  # Token validity
  access_token_validity  = 1   # 1 hour
  id_token_validity      = 1   # 1 hour
  refresh_token_validity = 30  # 30 days

  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }

  # Prevent user existence errors (security best practice)
  prevent_user_existence_errors = "ENABLED"

  # Supported identity providers
  supported_identity_providers = ["COGNITO"]
}

# -----------------------------------------------------------------------------
# Create Admin User (optional - can also create via console)
# -----------------------------------------------------------------------------

resource "aws_cognito_user" "admin" {
  count = var.create_admin_user ? 1 : 0

  user_pool_id = aws_cognito_user_pool.main.id
  username     = var.admin_email

  attributes = {
    email          = var.admin_email
    email_verified = true
  }

  # Temporary password - user must change on first login
  temporary_password = var.admin_temp_password

  lifecycle {
    ignore_changes = [
      temporary_password,
      attributes
    ]
  }
}
