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

## Cleanup

```bash
cd terraform
terraform destroy
```

**Warning:** This deletes all resources including the RDS database.
