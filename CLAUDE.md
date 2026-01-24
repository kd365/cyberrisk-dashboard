# CLAUDE.md - Project Context & Session Notes

## Project Overview
- **Project**: CyberRisk Dashboard - AWS Deployment
- **Created By**: Kathleen Hill (utilizing Claude Code)
- **Repository**: https://github.com/kd365/cyberrisk-dashboard
- **Working Directory**: `/Users/kathleenhill/CyberRisk/cyber-risk-deploy`

A comprehensive cybersecurity risk analytics platform analyzing SEC filings, earnings transcripts, and financial data for 30+ cybersecurity companies. Features AI-powered sentiment analysis, knowledge graph exploration, price forecasting, and a conversational chatbot assistant.

## CRITICAL: AWS Profile Requirement

**ALWAYS use the `cyber-risk` AWS profile when working in this directory.**

```bash
# Set before ANY AWS commands
export AWS_PROFILE=cyber-risk

# Or source the helper script
source scripts/set-aws-profile.sh

# Verify correct account (MUST be 000018673740)
aws sts get-caller-identity
```

| Correct Account | Wrong Account |
|-----------------|---------------|
| `000018673740` (cyber-risk) | Any other account ID |

If you see a different account ID, STOP and switch profiles. Infrastructure resources (EC2, RDS, etc.) only exist in the cyber-risk account.

---

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

### Graph Sync API Endpoints
| Endpoint | Purpose |
|----------|---------|
| `POST /api/admin/build-graph` | Rebuild document graphs for all companies |
| `POST /api/admin/sync-cache-to-graph` | **NEW** - Sync cache nodes (sentiment, growth, forecast, headcount, jobs) |
| `POST /api/admin/infer-relationships` | Infer entity/concept relationships |
| `POST /api/enrichment/run-all` | Full LLM enrichment pipeline |

### Cache-to-Graph Sync
The `/api/admin/sync-cache-to-graph` endpoint populates these nodes from PostgreSQL:
- `SentimentSnapshot` ← `sentiment_cache` table
- `GrowthSnapshot` ← `growth_cache` table
- `ForecastSnapshot` ← `forecast_cache` table
- `HeadcountPoint` ← `headcount_history` table
- `JobFunction` ← `jobs_by_function` in `growth_cache`

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

### 2026-01-24: Fixed Cache-to-Graph Sync Error

**Issue**: `/api/admin/sync-cache-to-graph` endpoint failing with:
```
'Neo4jService' object has no attribute 'create_company'
```

**Root Cause**: `GraphEnrichmentService._ensure_company_node()` called `neo4j.create_company()` but the method is actually `create_organization()`.

**Fix**: Updated method call in [graph_enrichment_service.py](backend/services/graph_enrichment_service.py) (line 154):
```python
# Before (broken):
self.neo4j.create_company(ticker=ticker, name=..., sector=...)

# After (fixed):
self.neo4j.create_organization(name=..., ticker=ticker, tracked=True, cyber_sector=...)
```

**Commit**: `67aa517` - Fix Neo4j method call in graph enrichment service

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

### 2026-01-24: Integrated Mem0 Semantic Memory into LangChain Agent

**Problem**: Mem0 infrastructure existed but wasn't wired into the chat workflow. The `MemoryService` had `add_semantic_memory()` and `search_semantic_memory()` methods, but `LangChainAgentService` only used PostgreSQL conversation history.

**Fix** ([langchain_agent.py](backend/services/langchain_agent.py)):
Added full Mem0 integration:
- `_get_semantic_memories(query, user_id)` - Searches Mem0 for relevant past facts before agent invocation
- `_save_to_semantic_memory(user_id, user_msg, assistant_msg)` - Extracts facts via Claude Haiku and stores embeddings
- Modified `chat()` to inject semantic context as SystemMessage before chat history
- Uses `user_email` when available, falls back to `session_id` for memory isolation
- Response includes `semantic_memory_used: true/false` flag

**Architecture**:
```
READ PHASE (Before Agent):
  search_semantic_memory(query) → Mem0 → pgvector similarity search
  get_context_for_llm(session_id) → PostgreSQL chat_messages

WRITE PHASE (After Agent):
  add_message() → PostgreSQL chat_messages
  add_semantic_memory() → Claude Haiku extracts facts → Titan embeds → pgvector
```

**Commit**: `86cb497` - Integrate Mem0 semantic memory into LangChain agent

---

### 2026-01-24: Migrated from LangChain AgentExecutor to LangGraph

**Problem**: LangChain 1.x removed `create_tool_calling_agent` from `langchain.agents`. The backend was falling back to legacy chat (no tools, no Mem0) with error:
```
cannot import name 'create_tool_calling_agent' from 'langchain.agents'
```

**Background - LangChain vs LangGraph**:
| Package | Purpose |
|---------|---------|
| `langchain` | Core library - prompts, chains, tools, message types |
| `langchain-aws` | AWS integrations (Bedrock, etc.) |
| `langgraph` | Agent orchestration graphs - replaces old `AgentExecutor` |

In LangChain 1.x, agent APIs were restructured:
- **Old (0.x)**: `create_tool_calling_agent()` + `AgentExecutor` from `langchain.agents`
- **New (1.x)**: `create_react_agent()` from `langgraph.prebuilt`

**Fix** ([langchain_agent.py](backend/services/langchain_agent.py)):
```python
# Old import (broken in LangChain 1.x):
from langchain.agents import create_tool_calling_agent, AgentExecutor

# New import:
from langgraph.prebuilt import create_react_agent

# Old agent creation:
agent = create_tool_calling_agent(llm, tools, prompt)
executor = AgentExecutor(agent=agent, tools=tools, ...)
result = executor.invoke({"input": message, "chat_history": history})

# New agent creation (NOTE: use 'prompt', NOT 'state_modifier'):
agent = create_react_agent(model=llm, tools=tools, prompt=system_prompt)
result = agent.invoke({"messages": messages}, config={"recursion_limit": 10})
```

**Commits**:
- `3e31075` - Migrate from LangChain AgentExecutor to LangGraph create_react_agent
- `133a9ab` - Fix parameter: `state_modifier` → `prompt`

---

### 2026-01-24: Fixed user_email Not Being Passed to Chat Endpoint

**Problem**: Mem0 semantic memory wasn't persisting across sessions because `user_email` was `None`. The backend fell back to `session_id` for memory isolation, but each browser session got a new ID.

**Fix**:
- [Dashboard.jsx](frontend/src/components/Dashboard.jsx): Get `user` from `useAuth()`, pass `user.email` to GraphRAGAssistant
- [GraphRAGAssistant.jsx](frontend/src/components/GraphRAGAssistant.jsx): Accept `userEmail` prop, include in `/api/chat` request body

**Commit**: `2558292` - Pass user_email to chat endpoint for Mem0 semantic memory

---

### 2026-01-24: Fixed Cognito Email Verification Flow

**Problem**: After signup, users were redirected to signin screen with no indication that email verification was needed. When they tried to sign in, they got "User is not confirmed" error but had no way to enter the verification code.

**Fix** ([AuthProvider.jsx](frontend/src/components/AuthProvider.jsx)):
- Modified `handleSignIn` to detect "not confirmed" errors and switch to verify mode
- Improved signup success message to clearly indicate verification email was sent
- User now automatically sees verification code input form when needed

---

### EC2 Instance Reference
- **Flask Backend**: `i-0bdafbb7e0387b4cb` (cyberrisk-dev-kh-flask-backend)
- **Neo4j**: `i-0aefeaee10f6fdeea` (cyberrisk-dev-kh-neo4j)

---
*Last Updated: 2026-01-24*
