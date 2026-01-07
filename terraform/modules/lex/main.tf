# =============================================================================
# Amazon Lex V2 Module - Cyber Risk Dashboard Chatbot (Simplified)
# =============================================================================
# Note: Using simplified configuration to avoid AWS provider bugs with slots
# The Lambda function handles all intent fulfillment including entity extraction

# -----------------------------------------------------------------------------
# Lambda Function for Lex Fulfillment
# -----------------------------------------------------------------------------

data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/lambda"
  output_path = "${path.module}/lambda.zip"
}

resource "aws_lambda_function" "lex_fulfillment" {
  filename         = data.archive_file.lambda_zip.output_path
  function_name    = "${var.name_prefix}-lex-fulfillment"
  role             = var.lambda_role_arn
  handler          = "index.handler"
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  runtime          = "python3.11"
  timeout          = 30
  memory_size      = 256

  environment {
    variables = {
      DB_HOST     = var.db_host
      DB_NAME     = var.db_name
      DB_USER     = var.db_username
      DB_PASSWORD = var.db_password
    }
  }

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.lambda_sg.id]
  }

  tags = var.tags
}

# Security group for Lambda in VPC
resource "aws_security_group" "lambda_sg" {
  name        = "${var.name_prefix}-lambda-sg"
  description = "Security group for Lex Lambda function"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-lambda-sg"
  })
}

# Allow Lambda to invoke from Lex
resource "aws_lambda_permission" "lex_invoke" {
  statement_id  = "AllowLexInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.lex_fulfillment.function_name
  principal     = "lexv2.amazonaws.com"
  source_arn    = "${aws_lexv2models_bot.cyber_risk_bot.arn}/*"
}

# -----------------------------------------------------------------------------
# Lex V2 Bot Definition
# -----------------------------------------------------------------------------

resource "aws_lexv2models_bot" "cyber_risk_bot" {
  name                        = "${var.name_prefix}-bot"
  description                 = "Cyber Risk Dashboard Assistant - helps users navigate and understand dashboard data"
  role_arn                    = var.lex_role_arn
  data_privacy {
    child_directed = false
  }
  idle_session_ttl_in_seconds = 300

  tags = var.tags
}

resource "aws_lexv2models_bot_locale" "en_us" {
  bot_id                           = aws_lexv2models_bot.cyber_risk_bot.id
  bot_version                      = "DRAFT"
  locale_id                        = "en_US"
  n_lu_intent_confidence_threshold = 0.70

  description = "English (US) locale for Cyber Risk Bot"
}

# -----------------------------------------------------------------------------
# Intents (Simplified - no slots to avoid provider bugs)
# -----------------------------------------------------------------------------

# Welcome Intent
resource "aws_lexv2models_intent" "welcome" {
  bot_id      = aws_lexv2models_bot.cyber_risk_bot.id
  bot_version = "DRAFT"
  locale_id   = aws_lexv2models_bot_locale.en_us.locale_id
  name        = "WelcomeIntent"
  description = "Greets users and explains available features"

  sample_utterance {
    utterance = "hello"
  }
  sample_utterance {
    utterance = "hi"
  }
  sample_utterance {
    utterance = "hey"
  }
  sample_utterance {
    utterance = "help"
  }
  sample_utterance {
    utterance = "what can you do"
  }
  sample_utterance {
    utterance = "get started"
  }

  fulfillment_code_hook {
    enabled = true
  }
}

# List Companies Intent
resource "aws_lexv2models_intent" "list_companies" {
  bot_id      = aws_lexv2models_bot.cyber_risk_bot.id
  bot_version = "DRAFT"
  locale_id   = aws_lexv2models_bot_locale.en_us.locale_id
  name        = "ListCompaniesIntent"
  description = "Lists all companies available in the dashboard"

  sample_utterance {
    utterance = "what companies are available"
  }
  sample_utterance {
    utterance = "list companies"
  }
  sample_utterance {
    utterance = "show me all companies"
  }
  sample_utterance {
    utterance = "which companies can I analyze"
  }
  sample_utterance {
    utterance = "what companies do you have"
  }
  sample_utterance {
    utterance = "how many companies are tracked"
  }
  sample_utterance {
    utterance = "how many companies do you have"
  }
  sample_utterance {
    utterance = "count the companies"
  }

  fulfillment_code_hook {
    enabled = true
  }
}

# Company Info Intent (simplified - extracts company from utterance in Lambda)
resource "aws_lexv2models_intent" "company_info" {
  bot_id      = aws_lexv2models_bot.cyber_risk_bot.id
  bot_version = "DRAFT"
  locale_id   = aws_lexv2models_bot_locale.en_us.locale_id
  name        = "CompanyInfoIntent"
  description = "Provides information about a specific company"

  sample_utterance {
    utterance = "tell me about crowdstrike"
  }
  sample_utterance {
    utterance = "tell me about palo alto"
  }
  sample_utterance {
    utterance = "tell me about fortinet"
  }
  sample_utterance {
    utterance = "tell me about zscaler"
  }
  sample_utterance {
    utterance = "tell me about sentinelone"
  }
  sample_utterance {
    utterance = "info on crwd"
  }
  sample_utterance {
    utterance = "info on panw"
  }

  fulfillment_code_hook {
    enabled = true
  }
}

# Sentiment Analysis Intent
resource "aws_lexv2models_intent" "sentiment_analysis" {
  bot_id      = aws_lexv2models_bot.cyber_risk_bot.id
  bot_version = "DRAFT"
  locale_id   = aws_lexv2models_bot_locale.en_us.locale_id
  name        = "SentimentAnalysisIntent"
  description = "Explains sentiment analysis for a company"

  sample_utterance {
    utterance = "what is the sentiment"
  }
  sample_utterance {
    utterance = "show sentiment analysis"
  }
  sample_utterance {
    utterance = "how is sentiment"
  }
  sample_utterance {
    utterance = "analyze sentiment"
  }
  sample_utterance {
    utterance = "sentiment for crowdstrike"
  }
  sample_utterance {
    utterance = "sentiment for palo alto"
  }

  fulfillment_code_hook {
    enabled = true
  }
}

# Forecast Intent
resource "aws_lexv2models_intent" "forecast" {
  bot_id      = aws_lexv2models_bot.cyber_risk_bot.id
  bot_version = "DRAFT"
  locale_id   = aws_lexv2models_bot_locale.en_us.locale_id
  name        = "ForecastIntent"
  description = "Provides forecast information for a company"

  sample_utterance {
    utterance = "what is the forecast"
  }
  sample_utterance {
    utterance = "show me predictions"
  }
  sample_utterance {
    utterance = "predict stock"
  }
  sample_utterance {
    utterance = "forecast"
  }
  sample_utterance {
    utterance = "price prediction"
  }
  sample_utterance {
    utterance = "forecast predictions for crowdstrike"
  }
  sample_utterance {
    utterance = "view forecast predictions"
  }
  sample_utterance {
    utterance = "stock forecast for palo alto"
  }
  sample_utterance {
    utterance = "price forecast for fortinet"
  }

  fulfillment_code_hook {
    enabled = true
  }
}

# Dashboard Features Intent
resource "aws_lexv2models_intent" "dashboard_features" {
  bot_id      = aws_lexv2models_bot.cyber_risk_bot.id
  bot_version = "DRAFT"
  locale_id   = aws_lexv2models_bot_locale.en_us.locale_id
  name        = "DashboardFeaturesIntent"
  description = "Explains dashboard features and tabs"

  sample_utterance {
    utterance = "what features are available"
  }
  sample_utterance {
    utterance = "explain the dashboard"
  }
  sample_utterance {
    utterance = "what tabs are there"
  }
  sample_utterance {
    utterance = "how do I use the dashboard"
  }
  sample_utterance {
    utterance = "what can I see on the dashboard"
  }

  fulfillment_code_hook {
    enabled = true
  }
}

# Add Company Intent - allows users to add new companies via chat
resource "aws_lexv2models_intent" "add_company" {
  bot_id      = aws_lexv2models_bot.cyber_risk_bot.id
  bot_version = "DRAFT"
  locale_id   = aws_lexv2models_bot_locale.en_us.locale_id
  name        = "AddCompanyIntent"
  description = "Add a new company to track in the dashboard"

  sample_utterance {
    utterance = "add a new company"
  }
  sample_utterance {
    utterance = "add company"
  }
  sample_utterance {
    utterance = "I want to add a company"
  }
  sample_utterance {
    utterance = "track a new company"
  }
  sample_utterance {
    utterance = "add crowdstrike"
  }
  sample_utterance {
    utterance = "add palo alto networks"
  }
  sample_utterance {
    utterance = "add ticker CRWD"
  }
  sample_utterance {
    utterance = "add PANW to the dashboard"
  }
  sample_utterance {
    utterance = "I want to track fortinet"
  }
  sample_utterance {
    utterance = "can you add zscaler"
  }

  fulfillment_code_hook {
    enabled = true
  }
}

# Remove Company Intent - allows users to remove companies via chat
resource "aws_lexv2models_intent" "remove_company" {
  bot_id      = aws_lexv2models_bot.cyber_risk_bot.id
  bot_version = "DRAFT"
  locale_id   = aws_lexv2models_bot_locale.en_us.locale_id
  name        = "RemoveCompanyIntent"
  description = "Remove a company from the dashboard"

  sample_utterance {
    utterance = "remove a company"
  }
  sample_utterance {
    utterance = "delete company"
  }
  sample_utterance {
    utterance = "I want to remove a company"
  }
  sample_utterance {
    utterance = "stop tracking a company"
  }
  sample_utterance {
    utterance = "remove crowdstrike"
  }
  sample_utterance {
    utterance = "delete CRWD"
  }
  sample_utterance {
    utterance = "remove ticker PANW"
  }

  fulfillment_code_hook {
    enabled = true
  }
}

# Document Inventory Intent - shows what documents are available for a company
resource "aws_lexv2models_intent" "document_inventory" {
  bot_id      = aws_lexv2models_bot.cyber_risk_bot.id
  bot_version = "DRAFT"
  locale_id   = aws_lexv2models_bot_locale.en_us.locale_id
  name        = "DocumentInventoryIntent"
  description = "Shows what documents are available for a company"

  sample_utterance {
    utterance = "what documents do I have for crowdstrike"
  }
  sample_utterance {
    utterance = "what type of documents do I have for CRWD"
  }
  sample_utterance {
    utterance = "show documents for palo alto"
  }
  sample_utterance {
    utterance = "what filings are available for fortinet"
  }
  sample_utterance {
    utterance = "list documents for zscaler"
  }
  sample_utterance {
    utterance = "what data do you have for sentinelone"
  }
  sample_utterance {
    utterance = "show me the documents for PANW"
  }
  sample_utterance {
    utterance = "what SEC filings do I have"
  }
  sample_utterance {
    utterance = "how many earnings calls for crowdstrike"
  }
  sample_utterance {
    utterance = "document inventory"
  }

  fulfillment_code_hook {
    enabled = true
  }
}

# Growth Metrics Intent - shows hiring and employee growth trends
resource "aws_lexv2models_intent" "growth_metrics" {
  bot_id      = aws_lexv2models_bot.cyber_risk_bot.id
  bot_version = "DRAFT"
  locale_id   = aws_lexv2models_bot_locale.en_us.locale_id
  name        = "GrowthMetricsIntent"
  description = "Shows employee and hiring growth trends"

  sample_utterance {
    utterance = "show growth metrics for crowdstrike"
  }
  sample_utterance {
    utterance = "what is the hiring trend for PANW"
  }
  sample_utterance {
    utterance = "employee count for fortinet"
  }
  sample_utterance {
    utterance = "is zscaler hiring"
  }
  sample_utterance {
    utterance = "growth trend for sentinelone"
  }
  sample_utterance {
    utterance = "how fast is crowdstrike growing"
  }
  sample_utterance {
    utterance = "hiring velocity for palo alto"
  }
  sample_utterance {
    utterance = "workforce trends"
  }

  fulfillment_code_hook {
    enabled = true
  }
}

# -----------------------------------------------------------------------------
# Bot Version
# -----------------------------------------------------------------------------

resource "aws_lexv2models_bot_version" "v1" {
  bot_id = aws_lexv2models_bot.cyber_risk_bot.id

  locale_specification = {
    (aws_lexv2models_bot_locale.en_us.locale_id) = {
      source_bot_version = "DRAFT"
    }
  }

  depends_on = [
    aws_lexv2models_intent.welcome,
    aws_lexv2models_intent.list_companies,
    aws_lexv2models_intent.company_info,
    aws_lexv2models_intent.sentiment_analysis,
    aws_lexv2models_intent.forecast,
    aws_lexv2models_intent.dashboard_features,
    aws_lexv2models_intent.add_company,
    aws_lexv2models_intent.remove_company,
    aws_lexv2models_intent.document_inventory,
    aws_lexv2models_intent.growth_metrics
  ]
}

# -----------------------------------------------------------------------------
# Bot Alias - Created via AWS CLI
# -----------------------------------------------------------------------------

resource "null_resource" "bot_alias" {
  depends_on = [aws_lexv2models_bot_version.v1]

  provisioner "local-exec" {
    command = <<-EOT
      export AWS_PROFILE=${var.aws_profile}
      ALIAS_ID=$(aws lexv2-models list-bot-aliases --bot-id ${aws_lexv2models_bot.cyber_risk_bot.id} --query "botAliasSummaries[?botAliasName=='production'].botAliasId" --output text --region ${data.aws_region.current.name})
      if [ -z "$ALIAS_ID" ] || [ "$ALIAS_ID" = "None" ]; then
        echo "Creating new bot alias..."
        aws lexv2-models create-bot-alias \
          --bot-id ${aws_lexv2models_bot.cyber_risk_bot.id} \
          --bot-alias-name production \
          --bot-version ${aws_lexv2models_bot_version.v1.bot_version} \
          --bot-alias-locale-settings '{"en_US":{"enabled":true,"codeHookSpecification":{"lambdaCodeHook":{"lambdaARN":"${aws_lambda_function.lex_fulfillment.arn}","codeHookInterfaceVersion":"1.0"}}}}' \
          --region ${data.aws_region.current.name} \
          --no-cli-pager
      else
        echo "Updating existing bot alias: $ALIAS_ID"
        aws lexv2-models update-bot-alias \
          --bot-id ${aws_lexv2models_bot.cyber_risk_bot.id} \
          --bot-alias-id "$ALIAS_ID" \
          --bot-alias-name production \
          --bot-version ${aws_lexv2models_bot_version.v1.bot_version} \
          --bot-alias-locale-settings '{"en_US":{"enabled":true,"codeHookSpecification":{"lambdaCodeHook":{"lambdaARN":"${aws_lambda_function.lex_fulfillment.arn}","codeHookInterfaceVersion":"1.0"}}}}' \
          --region ${data.aws_region.current.name} \
          --output text \
          --no-cli-pager > /dev/null
      fi
    EOT
  }

  triggers = {
    bot_version = aws_lexv2models_bot_version.v1.bot_version
    lambda_arn  = aws_lambda_function.lex_fulfillment.arn
  }
}

data "aws_region" "current" {}
