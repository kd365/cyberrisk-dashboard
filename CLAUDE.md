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

## Neo4j Knowledge Graph Schema

### Nodes (12 types, 83,346 total)
| Node Label | Count | Description |
|------------|-------|-------------|
| Concept | 76,821 | Key phrases from documents |
| Organization | 2,249 | Companies (30 tracked + mentioned) |
| Person | 2,086 | People mentioned in filings |
| Patent | 791 | Filed patents |
| Document | 670 | SEC filings & transcripts |
| Location | 396 | Geographic locations |
| ExecutiveEvent | 127 | C-suite appointments/departures |
| Event | 112 | General events |
| Vulnerability | 77 | CVE vulnerabilities |
| MAEvent | 15 | M&A events |
| RestructuringEvent | 1 | Restructuring events |
| SecurityEvent | 1 | Security incidents |

### Relationships (14 types, 412,873 total)
| From | Relationship | To | Count |
|------|--------------|-----|-------|
| Document | DISCUSSES | Concept | 384,173 |
| Document | MENTIONS | Organization | 12,148 |
| Document | MENTIONS | Location | 5,084 |
| Person | INVENTED | Patent | 2,343 |
| Organization | COMPETES_WITH | Organization | 2,286 |
| Organization | FILED | Patent | 2,035 |
| Organization | OPERATES_IN | Location | 1,812 |
| Document | MENTIONS | Person | 1,446 |
| Organization | HAS_FILING | Document | 583 |
| Document | MENTIONS | Event | 324 |
| Event | INVOLVES | Organization | 291 |
| Organization | HAS_EXECUTIVE_EVENT | ExecutiveEvent | 127 |
| Person | INVOLVED_IN | ExecutiveEvent | 127 |
| Organization | HAS_VULNERABILITY | Vulnerability | 77 |
| Organization | HAS_MA_EVENT | MAEvent | 15 |

### Known Issue: Graph Sync Gap
- **PostgreSQL artifacts**: 857 documents (387 10-Q, 187 8-K, 179 10-K, 104 transcripts)
- **Neo4j documents**: 670 documents
- **Missing**: ~187 documents (mainly 8-K filings not synced to graph)
- **Root Cause**: Graph build only runs for companies with new docs in *current* scrape. If previous scrape succeeded but graph build failed, documents are orphaned.
- **Fix Options**:
  1. `POST /api/admin/build-graph` (requires auth) - Rebuilds all company graphs
  2. `POST /api/graph/build-all` - Alternative rebuild endpoint
  3. `POST /api/enrichment/run-all` - Full enrichment pipeline including graph

---

## Session Notes

### 2026-01-24: Fixed Evaluation API NumPy Error

**Issue**: `/api/evaluation/feature-importance` and `/api/evaluation/ablation-study` returning error:
```
{"error":"setting an array element with a sequence."}
```

**Root Cause**: `get_llm_features()` returned `threat_specialization` and `analyst_concerns` as lists. When passed to `StandardScaler.fit_transform()`, NumPy failed.

**Fix**: Remove list fields after extracting numeric counts:
```python
features.pop("threat_specialization", None)
features.pop("analyst_concerns", None)
```

**File**: [feature_evaluation_service.py](backend/services/feature_evaluation_service.py) (lines 118-120)

---

### 2026-01-24: Added Anti-Hallucination Rules & New Tools

**Problem**: LangChain agent was fabricating executive events, dates, and data when tools returned empty results or failed.

**Fix 1 - Prompt Updates** ([prompts.py](backend/services/prompts.py)):
Added strict anti-hallucination rules:
- NEVER invent data not returned by tools
- If tool returns error/empty, say "I don't have data for that"
- NEVER invent specific dates, names, or events
- When uncertain, cite only what tools actually returned

**Fix 2 - New Tools** ([langchain_tools.py](backend/services/langchain_tools.py)):
- `get_executive_events(ticker, limit)` - Queries HAS_EXECUTIVE_EVENT from Neo4j
- `get_vulnerabilities(ticker, severity, limit)` - Queries HAS_VULNERABILITY from Neo4j

**Tool Count**: 12 → 14 tools

**Commits**:
- `bf6a9ab` - Fix NumPy array error in evaluation API
- `78373d4` - Add anti-hallucination rules and new LangChain tools

---

### LLM Chat Assistant Test Questions

**Company Research**
1. "What companies do you track?"
2. "Tell me about CrowdStrike's business model"
3. "Compare Palo Alto Networks and Fortinet"

**Sentiment & Analysis**
4. "What's the sentiment for CRWD?"
5. "What are analysts saying about Zscaler?"

**Financial & Forecasts**
6. "What's the price forecast for PANW?"
7. "Which cybersecurity stocks have the highest growth potential?"

**Knowledge Graph (should use new tools)**
8. "What vulnerabilities affect CrowdStrike?" → `get_vulnerabilities`
9. "Show me executive changes at Fortinet" → `get_executive_events`
10. "What patents has Palo Alto Networks filed?" → `get_patents`

**SEC Filings**
11. "What are the main risks mentioned in CrowdStrike's 10-K?"
12. "Summarize OKTA's latest earnings call"

**Dashboard Help**
13. "How do I use this dashboard?"

---
*Last Updated: 2026-01-24*
