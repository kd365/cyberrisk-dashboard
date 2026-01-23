# CyberRisk Dashboard - AWS Deployment
## Created By: Kathleen Hill
### Utilizing Claude Code

A comprehensive cybersecurity risk analytics platform that analyzes SEC filings, earnings transcripts, and financial data for 30+ cybersecurity companies. Features AI-powered sentiment analysis, knowledge graph exploration, price forecasting, and a conversational chatbot assistant.

## Architecture

![Project Architecture](docs/architecture-diagram.png)

## AWS Services Used

| Service | Purpose | Assessment Category |
|---------|---------|-------------------|
| **Amazon Bedrock** | Claude 3.5 Sonnet for LangChain agent, Titan embeddings | AI Service #1 |
| **Amazon Comprehend** | NLP sentiment analysis & entity extraction | AI Service #2 |
| **Amazon Lex V2** | Chatbot assistant | AI Service #3 |
| **Amazon Cognito** | User authentication (JWT tokens) | Security |
| **Amazon SSM** | Secure EC2 deployment & command execution | Operations |
| **RDS PostgreSQL** | Relational database + pgvector | Database |
| **EC2 + Gunicorn** | Flask API backend (Docker) | Compute |
| **S3 + CloudFront** | React frontend hosting + Artifacts storage | Storage/CDN |
| **Lambda** | Lex fulfillment handler | Serverless |
| **ECR** | Docker container registry | CI/CD |
| **VPC** | Network isolation | Networking |
| **IAM** | Role-based access | Security |



## Dashboard Features

- **Data Collection** - View SEC filings and earnings transcripts
- **Price Forecast** - Prophet or Chronos ML predictions for stock prices
- **Sentiment Analysis** - AWS Comprehend NLP analysis
- **Company Growth** - Workforce trends from CoreSignal
- **AI Assistant** - Amazon Lex chatbot for navigation help
- **SEC Filing Analysis**: 10-K, 10-Q, and 8-K filings with OCR text extraction
- **Earnings Transcripts**: Alpha Vantage integration for call transcripts
- **Sentiment Analysis**: AWS Comprehend for document-level sentiment and entity extraction
- **Knowledge Graph**: Neo4j graph database with company relationships and entity visualization
- **Price Forecasting**: Dual-model support (Prophet and Chronos) - user-selectable for stock price predictions
- **AI Chat Assistant**: LangChain + Bedrock RAG-powered conversational agent with semantic memory
- **Growth Analytics**: Company workforce and funding trends via CoreSignal employee metrics
- **Cognito Authentication**: Secure user login with JWT tokens


## Project Structure

```
cyber-risk-deploy/
├── .github/workflows/           # CI/CD pipelines
│   ├── ci-backend.yml          # Backend lint, test, build
│   ├── ci-frontend.yml         # Frontend lint, test, build
│   ├── deploy-backend.yml      # ECR push + SSM deploy
│   ├── deploy-frontend.yml     # S3 sync + CloudFront invalidation
│   ├── health-check.yml        # Scheduled health monitoring
│   └── db-migration.yml        # Database migrations
│
├── terraform/
│   ├── main.tf                 # Root module composition
│   ├── variables.tf            # Input variables
│   ├── outputs.tf              # Output values
│   └── modules/
│       ├── vpc/                # VPC, subnets, routing
│       ├── rds/                # PostgreSQL + pgvector
│       ├── ec2/                # Flask backend instance
│       ├── s3/                 # Frontend + artifacts buckets
│       ├── cloudfront/         # CDN distribution
│       ├── iam/                # Roles and policies
│       ├── lex/                # Chatbot + Lambda fulfillment
│       ├── cognito/            # User pool configuration
│       ├── ecr/                # Container registry
│       └── neo4j/              # Graph database EC2
│
├── backend/
│   ├── app.py                  # Flask application
│   ├── Dockerfile              # Production container
│   ├── requirements.txt        # Python dependencies
│   └── services/
│       ├── scraper.py              # SEC EDGAR + Alpha Vantage scraper
│       ├── comprehend_service.py   # AWS Comprehend NLP
│       ├── langchain_agent.py      # Bedrock RAG agent
│       ├── memory_service.py       # Mem0 semantic memory
│       ├── graph_builder_service.py # Neo4j knowledge graph
│       ├── data_enrichment_service.py # NVD/CVE vulnerabilities
│       ├── forecast_service.py     # Prophet/Chronos price predictions
│       ├── coresignal_service.py   # Employee growth metrics
│       ├── lex_service.py          # Lex bot integration
│       ├── cognito_auth_service.py # JWT authentication
│       └── s3_service.py           # S3 artifacts management
│
├── frontend/
│   ├── src/
│   │   ├── App.js              # Root component with AuthProvider
│   │   └── components/
│   │       ├── Dashboard.jsx       # Main tabbed interface
│   │       ├── AuthProvider.jsx    # Cognito auth context
│   │       ├── ScrapingInterface.jsx # Data collection UI
│   │       ├── SentimentDashboard.jsx # NLP analysis
│   │       ├── PriceForecast.jsx   # ML predictions (Prophet/Chronos)
│   │       ├── KnowledgeGraph.jsx  # Neo4j visualization
│   │       └── LexChatbot.jsx      # AI Assistant
│   └── package.json
│
├── scripts/
│   ├── setup-github-secrets.sh     # Configure GH Actions secrets
│   ├── setup-remote-state.sh       # Terraform S3 backend
│   ├── preflight-check.sh          # Deployment verification
│   ├── wakeup.sh / hibernate.sh    # Cost management
│   └── rebuild-knowledge-graph.sh  # Graph rebuild utility
│
├── docs/
│   ├── architecture-diagram.png
│   ├── assessment_recs.md
│   └── architecture-additions.md
│
└── README.md
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/companies` | GET | List tracked companies |
| `/api/artifacts` | GET | SEC filings & transcripts |
| `/api/scraping/start` | POST | Trigger data collection (supports 8-K filings) |
| `/api/sentiment/{ticker}` | GET | Comprehend NLP analysis |
| `/api/forecast/{ticker}` | GET | Price predictions (Prophet or Chronos) |
| `/api/growth/{ticker}` | GET | Employee growth metrics (CoreSignal) |
| `/api/chat` | POST | LangChain RAG agent |
| `/api/auth/login` | POST | Cognito authentication |
| `/api/auth/refresh` | POST | Token refresh |

## Data Sources

| Source | Data Type | Access |
|--------|-----------|--------|
| SEC EDGAR | 10-K, 10-Q, 8-K filings | Free API |
| Alpha Vantage | Earnings transcripts | Free API key |
| NVD | CVE vulnerabilities | Free API |
| CoreSignal | Employee growth metrics | API key |
| Yahoo Finance | Stock prices | Free (yfinance) |

## Security

- Cognito user authentication with JWT tokens
- RDS in private subnets (not publicly accessible)
- EC2 security groups restrict inbound access
- SSM for secure deployment without SSH exposure
- IAM roles with least-privilege principle
- CloudFront HTTPS termination
- Secrets managed via GitHub Secrets

## Setup & Deployment

### Prerequisites

- AWS Account with appropriate permissions
- AWS CLI configured (`aws configure`)
- Terraform 1.0+ installed
- Node.js 18+ and npm
- Python 3.9+
- Docker installed
- GitHub account with repository access

### Initial Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/kd365/cyberrisk-dashboard.git
   cd cyberrisk-dashboard
   ```

2. **Set AWS Profile**
   ```bash
   export AWS_PROFILE=your-aws-profile
   aws sts get-caller-identity  # Verify correct account
   ```

3. **Configure GitHub Secrets** (Settings → Secrets → Actions)
   - `AWS_ACCESS_KEY_ID`
   - `AWS_SECRET_ACCESS_KEY`
   - `EC2_INSTANCE_ID` (from Terraform output)

### Infrastructure Deployment

**Note:** Some Terraform resources require manual steps or may have dependencies that don't work in a single `terraform apply`. Follow this order:

1. **Initialize Terraform**
   ```bash
   cd terraform
   terraform init
   ```

2. **Deploy Core Infrastructure First**
   ```bash
   # VPC, RDS, S3, ECR must be created first
   terraform apply -target=module.vpc
   terraform apply -target=module.rds
   terraform apply -target=module.s3
   terraform apply -target=module.ecr
   ```

3. **Deploy EC2 and Cognito**
   ```bash
   terraform apply -target=module.ec2
   terraform apply -target=module.cognito
   ```

4. **Deploy Remaining Resources**
   ```bash
   terraform apply  # Apply all remaining resources
   ```

5. **Get Output Values**
   ```bash
   terraform output frontend_url
   terraform output rds_endpoint
   terraform output cognito_user_pool_id
   terraform output cognito_client_id
   ```

### Backend Deployment

The backend deploys automatically via GitHub Actions when you push to `main`:

1. **Backend CI** runs linting, tests, and builds Docker image
2. **Deploy Backend** pushes to ECR and deploys to EC2 via SSM

For manual deployment:
```bash
# SSH to EC2 (if needed)
aws ssm start-session --target <instance-id>

# Or deploy via SSM command
aws ssm send-command \
  --instance-ids "<instance-id>" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["docker pull <ecr-url>:latest && docker restart cyberrisk-backend"]'
```

### Frontend Deployment

Frontend deploys automatically when Frontend CI passes:

1. Build React app
2. Sync to S3
3. Invalidate CloudFront cache

For manual deployment:
```bash
cd frontend
npm install
npm run build
aws s3 sync build/ s3://<frontend-bucket> --delete
aws cloudfront create-invalidation --distribution-id <dist-id> --paths "/*"
```

### Environment Variables

**Backend (.env on EC2)**
```bash
DB_HOST=<rds-endpoint>
DB_NAME=your-db-name
DB_USER=your-db-username
DB_PASSWORD=<your-db-password>
AWS_REGION=us-west-2
ARTIFACTS_BUCKET=<s3-bucket>
COGNITO_USER_POOL_ID=<pool-id>
COGNITO_CLIENT_ID=<client-id>
```

**Frontend (.env)**
```bash
REACT_APP_API_URL=/api
REACT_APP_AWS_REGION=us-west-2
REACT_APP_COGNITO_USER_POOL_ID=<pool-id>
REACT_APP_COGNITO_CLIENT_ID=<client-id>
```

### Cost Management

Use the hibernate/wakeup scripts to stop resources when not in use:

```bash
# Stop EC2, RDS, and delete NAT Gateway (saves ~$100+/month)
./scripts/hibernate.sh

# Restart resources
./scripts/wakeup.sh
```

## Troubleshooting

### GitHub Actions Failures

| Issue | Cause | Solution |
|-------|-------|----------|
| Deploy Backend timeout | SSM waiter times out before Docker pull completes | Workflow uses polling loop (5 min timeout) - usually succeeds even if marked "failed" |
| Frontend CI ESLint errors | Unused variables or imports | Fix the ESLint errors in the failing files |
| Deploy skipped | CI workflow failed | Fix CI issues first, deploy runs after CI success |

**Check recent runs:**
```bash
gh run list --limit 10
gh run view <run-id> --log-failed
```

### Terraform Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| `InvalidInstanceId` | Wrong AWS profile or instance terminated | Run `export AWS_PROFILE=your-aws-profile` |
| State lock error | Previous apply didn't complete | Wait or manually unlock DynamoDB |
| Resource already exists | Import existing resource or remove from state | `terraform import` or `terraform state rm` |
| NAT Gateway cost | NAT Gateway is expensive (~$32/month) | Use hibernate.sh to delete when not needed |

**Useful commands:**
```bash
terraform plan                    # Preview changes
terraform state list             # List all resources
terraform state show <resource>  # Show resource details
terraform refresh                # Sync state with AWS
```

### EC2/Backend Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Container unhealthy | App crash or missing env vars | Check logs: `docker logs cyberrisk-backend` |
| SSM not working | Instance not registered with SSM | Check IAM role has SSM permissions |
| API returns 502 | Container not running or port mismatch | Restart container, check port 5000 |

**Debug commands (via SSM):**
```bash
aws ssm start-session --target <instance-id>

# Inside instance
docker ps                        # Check container status
docker logs cyberrisk-backend    # View logs
curl localhost:5000/health       # Test health endpoint
cat /opt/cyberrisk/.env          # Check environment
```

### Database Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Connection refused | RDS stopped or security group issue | Start RDS, check security groups allow EC2 |
| pgvector not installed | Extension not created | Run `CREATE EXTENSION vector;` |
| Slow queries | Missing indexes | Check indexes exist on ticker, document_id columns |

### Frontend Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Old version showing | CloudFront cache | Create invalidation: `aws cloudfront create-invalidation ...` |
| API calls fail | CORS or proxy issue | Check CloudFront origin settings |
| Login not working | Cognito not configured | Verify REACT_APP_COGNITO_* env vars in build |

### Common AWS Errors

| Error | Meaning | Solution |
|-------|---------|----------|
| `ExpiredTokenException` | AWS credentials expired | Run `aws configure` or refresh SSO |
| `AccessDenied` | IAM permissions missing | Add required permissions to role/user |
| `ResourceNotFoundException` | Resource doesn't exist | Check resource name/ID, may need to create |

## Cleanup

```bash
cd terraform
terraform destroy
```

**Warning:** This deletes all resources including the RDS database.
