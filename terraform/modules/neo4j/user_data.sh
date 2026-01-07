#!/bin/bash
# =============================================================================
# Neo4j Community Edition Installation Script
# =============================================================================
# Installs Neo4j on Amazon Linux 2023 with optimized settings for t3.small
# =============================================================================

set -e

# Log all output
exec > >(tee /var/log/neo4j-install.log) 2>&1

echo "=========================================="
echo "Starting Neo4j installation..."
echo "=========================================="

# Update system
dnf update -y

# Install Java 17 (required for Neo4j 5.x)
dnf install -y java-17-amazon-corretto-headless

# Verify Java installation
java -version

# Add Neo4j repository
rpm --import https://debian.neo4j.com/neotechnology.gpg.key

cat > /etc/yum.repos.d/neo4j.repo << 'EOF'
[neo4j]
name=Neo4j RPM Repository
baseurl=https://yum.neo4j.com/stable/5
enabled=1
gpgcheck=1
gpgkey=https://debian.neo4j.com/neotechnology.gpg.key
EOF

# Install Neo4j Community Edition
dnf install -y neo4j

# Configure Neo4j
cat > /etc/neo4j/neo4j.conf << 'EOF'
# =============================================================================
# Neo4j Configuration for CyberRisk Knowledge Graph
# =============================================================================

# Network connector configuration
server.default_listen_address=0.0.0.0
server.bolt.enabled=true
server.bolt.listen_address=0.0.0.0:7687
server.http.enabled=true
server.http.listen_address=0.0.0.0:7474

# Disable HTTPS (internal network only)
server.https.enabled=false

# Memory configuration for t3.small (2GB RAM)
# Leave ~512MB for OS, allocate rest to Neo4j
server.memory.heap.initial_size=512m
server.memory.heap.max_size=1g
server.memory.pagecache.size=256m

# Transaction log settings
db.tx_log.rotation.retention_policy=1 days

# Security
dbms.security.auth_enabled=true
dbms.security.procedures.unrestricted=apoc.*
dbms.security.procedures.allowlist=apoc.*

# APOC configuration
dbms.security.procedures.unrestricted=apoc.coll.*,apoc.load.*

# Logging
dbms.logs.query.enabled=INFO
dbms.logs.query.threshold=1s
EOF

# Set initial password
neo4j-admin dbms set-initial-password "${neo4j_password}"

# Enable and start Neo4j service
systemctl enable neo4j
systemctl start neo4j

# Wait for Neo4j to start
echo "Waiting for Neo4j to start..."
sleep 30

# Verify Neo4j is running
systemctl status neo4j

# Test connection
curl -s http://localhost:7474/ || echo "Neo4j HTTP interface check (may take a moment)"

echo "=========================================="
echo "Neo4j installation complete!"
echo "Bolt: bolt://localhost:7687"
echo "HTTP: http://localhost:7474"
echo "=========================================="
