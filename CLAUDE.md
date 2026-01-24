# CLAUDE.md - Project Context & Session Notes

## Project Overview
- **Project**: CyberRisk Dashboard - AWS Deployment
- **Created By**: Kathleen Hill (utilizing Claude Code)
- **Repository**: https://github.com/kd365/cyberrisk-dashboard
- **Working Directory**: `/Users/kathleenhill/CyberRisk/cyber-risk-deploy`

A comprehensive cybersecurity risk analytics platform analyzing SEC filings, earnings transcripts, and financial data for 30+ cybersecurity companies. Features AI-powered sentiment analysis, knowledge graph exploration, price forecasting, and a conversational chatbot assistant.

## Tech Stack

### Backend
- **Framework**: Flask + Gunicorn (Docker containerized)
- **Database**: PostgreSQL with pgvector extension (RDS)
- **Graph Database**: Neo4j (EC2)
- **AI/ML**:
  - AWS Bedrock (Claude 3.5 Sonnet for LangChain agent, Titan embeddings)
  - AWS Comprehend (NLP sentiment analysis)
  - Amazon Lex V2 (Chatbot)
  - Prophet/Chronos (Price forecasting)
- **Memory**: Mem0 + pgvector for semantic memory

### Frontend
- **Framework**: React
- **Hosting**: S3 + CloudFront CDN
- **Auth**: Amazon Cognito (JWT tokens)

### Infrastructure
- **IaC**: Terraform (modular structure)
- **CI/CD**: GitHub Actions
- **Container Registry**: AWS ECR
- **Compute**: EC2 via SSM (no SSH exposure)
- **Networking**: VPC with public/private subnets

## AWS Services
| Service | Purpose |
|---------|---------|
| Amazon Bedrock | Claude 3.5 Sonnet + Titan embeddings |
| Amazon Comprehend | NLP sentiment & entity extraction |
| Amazon Lex V2 | Chatbot assistant |
| Amazon Cognito | User authentication |
| Amazon SSM | Secure EC2 deployment |
| RDS PostgreSQL | Relational DB + pgvector |
| EC2 + Gunicorn | Flask API backend |
| S3 + CloudFront | Frontend hosting + artifacts |
| Lambda | Lex fulfillment handler |
| ECR | Docker container registry |
| VPC | Network isolation |

## Key API Endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/companies` | GET | List tracked companies |
| `/api/artifacts` | GET | SEC filings & transcripts |
| `/api/scraping/start` | POST | Trigger data collection |
| `/api/sentiment/{ticker}` | GET | Comprehend NLP analysis |
| `/api/forecast/{ticker}` | GET | Price predictions |
| `/api/growth/{ticker}` | GET | Employee growth metrics |
| `/api/chat` | POST | LangChain RAG agent |
| `/api/auth/login` | POST | Cognito authentication |
| `/api/evaluation/ablation-study` | POST | ML model ablation study |

## Deployment
- **GitHub Actions Workflows**:
  - `ci-backend.yml` - Backend lint, test, build
  - `ci-frontend.yml` - Frontend lint, test, build
  - `deploy-backend.yml` - ECR push + SSM deploy
  - `deploy-frontend.yml` - S3 sync + CloudFront invalidation
  - `health-check.yml` - Scheduled health monitoring
  - `db-migration.yml` - Database migrations

- **CloudFront URL**: `https://dim0ckdh1dco1.cloudfront.net`

## Data Sources
| Source | Data Type |
|--------|-----------|
| SEC EDGAR | 10-K, 10-Q, 8-K filings |
| Alpha Vantage | Earnings transcripts |
| NVD | CVE vulnerabilities |
| CoreSignal | Employee growth metrics |
| Yahoo Finance | Stock prices |

## Cost Management
```bash
./scripts/hibernate.sh  # Stop EC2, RDS, delete NAT Gateway
./scripts/wakeup.sh     # Restart resources
```

---

## Session Notes

### 2026-01-24: Fixed Evaluation API NumPy Error

**Issue**: `/api/evaluation/feature-importance` and `/api/evaluation/ablation-study` returning error:
```
{"error":"setting an array element with a sequence."}
```

**Root Cause**: In `backend/services/feature_evaluation_service.py`, the `get_llm_features()` method was returning `threat_specialization` and `analyst_concerns` as lists. When these list columns were included in the pandas DataFrame and passed to `StandardScaler.fit_transform()`, NumPy failed because it cannot convert lists to a numeric array.

**Fix**: Modified `get_llm_features()` to remove the list fields after extracting numeric counts:
```python
features.pop("threat_specialization", None)
features.pop("analyst_concerns", None)
```

**File Changed**: [feature_evaluation_service.py](backend/services/feature_evaluation_service.py) (lines 118-120)

**Action Required**: Deploy backend changes via GitHub Actions or manual deploy.

---

### LLM Chat Assistant Test Questions

Questions to test the LangChain RAG agent in the frontend:

**Company Research**
1. "What companies do you track?"
2. "Tell me about CrowdStrike's business model"
3. "Compare Palo Alto Networks and Fortinet"
4. "Which companies focus on endpoint security?"

**Sentiment & Analysis**
5. "What's the sentiment for CRWD?"
6. "What are analysts saying about Zscaler?"
7. "Show me any concerning management tone patterns"

**Financial & Forecasts**
8. "What's the price forecast for PANW?"
9. "Which cybersecurity stocks have the highest growth potential?"

**Knowledge Graph**
10. "What vulnerabilities affect CrowdStrike?"
11. "Show me executive changes at Fortinet"
12. "What patents has Palo Alto Networks filed?"

**SEC Filings**
13. "What are the main risks mentioned in CrowdStrike's 10-K?"
14. "Summarize OKTA's latest earnings call"
15. "What cybersecurity threats are mentioned in recent filings?"

**Dashboard Help**
16. "How do I use this dashboard?"
17. "What data sources do you use?"

---
*Last Updated: 2026-01-24*
