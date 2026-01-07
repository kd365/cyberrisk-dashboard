# =============================================================================
# Neo4j Module - Graph Database for Knowledge Graph
# =============================================================================
#
# This module provisions a Neo4j Community Edition instance on EC2 for the
# GraphRAG knowledge graph. Uses t3.small for cost efficiency (~$15/month).
#
# Neo4j stores:
# - Company entities and relationships
# - Document metadata and connections
# - Extracted entities from SEC filings
# - Sentiment, growth, and forecast snapshots
#
# =============================================================================

# -----------------------------------------------------------------------------
# Security Group for Neo4j
# -----------------------------------------------------------------------------

resource "aws_security_group" "neo4j" {
  name        = "${var.name_prefix}-neo4j-sg"
  description = "Security group for Neo4j graph database"
  vpc_id      = var.vpc_id

  # Neo4j Bolt protocol (from Flask EC2 only)
  ingress {
    from_port       = 7687
    to_port         = 7687
    protocol        = "tcp"
    security_groups = [var.flask_security_group_id]
    description     = "Neo4j Bolt protocol from Flask backend"
  }

  # Neo4j HTTP browser (from Flask EC2 only - for debugging)
  ingress {
    from_port       = 7474
    to_port         = 7474
    protocol        = "tcp"
    security_groups = [var.flask_security_group_id]
    description     = "Neo4j HTTP browser from Flask backend"
  }

  # SSH access (for maintenance)
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = var.admin_cidr_blocks
    description = "SSH access for maintenance"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound"
  }

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-neo4j-sg"
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
# Neo4j EC2 Instance
# -----------------------------------------------------------------------------

resource "aws_instance" "neo4j" {
  ami                    = data.aws_ami.amazon_linux.id
  instance_type          = var.instance_type
  key_name               = var.key_name
  subnet_id              = var.private_subnet_id
  vpc_security_group_ids = [aws_security_group.neo4j.id]

  root_block_device {
    volume_size = 30  # 30GB minimum for AL2023 AMI snapshot
    volume_type = "gp3"
    encrypted   = true
  }

  user_data = base64encode(templatefile("${path.module}/user_data.sh", {
    neo4j_password = var.neo4j_password
  }))

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-neo4j"
  })

  lifecycle {
    create_before_destroy = true
  }
}
