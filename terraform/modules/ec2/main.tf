# =============================================================================
# EC2 Module - Flask Backend with Gunicorn
# =============================================================================

# -----------------------------------------------------------------------------
# Security Group
# -----------------------------------------------------------------------------

resource "aws_security_group" "ec2" {
  name        = "${var.name_prefix}-ec2-sg"
  description = "Security group for Flask EC2 instance"
  vpc_id      = var.vpc_id

  # SSH access
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "SSH access"
  }

  # HTTP (Flask/Gunicorn)
  ingress {
    from_port   = 5000
    to_port     = 5000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Flask API"
  }

  # HTTPS (if using nginx)
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTPS"
  }

  # HTTP (nginx)
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTP"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound"
  }

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-ec2-sg"
  })
}

# -----------------------------------------------------------------------------
# Get Latest Amazon Linux 2023 AMI
# -----------------------------------------------------------------------------

data "aws_ami" "amazon_linux" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# -----------------------------------------------------------------------------
# EC2 Instance
# -----------------------------------------------------------------------------

resource "aws_instance" "flask" {
  ami                    = data.aws_ami.amazon_linux.id
  instance_type          = var.instance_type
  key_name               = var.key_name
  subnet_id              = var.public_subnet_id
  vpc_security_group_ids = [aws_security_group.ec2.id]
  iam_instance_profile   = var.iam_instance_profile

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
    encrypted   = true
  }

  user_data = base64encode(templatefile("${path.module}/user_data.sh", {
    db_host              = var.db_host
    db_name              = var.db_name
    db_username          = var.db_username
    db_password          = var.db_password
    artifacts_bucket     = var.artifacts_bucket
    explorium_api_key    = var.explorium_api_key
    alphavantage_api_key = var.alphavantage_api_key
    coresignal_api_key   = var.coresignal_api_key
    lex_bot_id           = var.lex_bot_id
    lex_bot_alias_id     = var.lex_bot_alias_id
    neo4j_host           = var.neo4j_host
    neo4j_password       = var.neo4j_password
    cognito_user_pool_id = var.cognito_user_pool_id
    cognito_client_id    = var.cognito_client_id
    cognito_region       = var.cognito_region
    uspto_api_key        = var.uspto_api_key
  }))

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-flask-backend"
  })

  lifecycle {
    create_before_destroy = true
  }
}

# -----------------------------------------------------------------------------
# Elastic IP
# -----------------------------------------------------------------------------

resource "aws_eip" "flask" {
  instance = aws_instance.flask.id
  domain   = "vpc"

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-flask-eip"
  })
}
