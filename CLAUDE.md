# CLAUDE.md - Project Context & Session Notes

## Project Overview
- **Project**: CyberRisk Dashboard - AWS Deployment
- **Created By**: Kathleen Hill (utilizing Claude Code)
- **Repository**: https://github.com/kd365/cyberrisk-dashboard
- **Working Directory**: `/Users/kathleenhill/CyberRisk/cyber-risk-deploy`

A comprehensive cybersecurity risk analytics platform analyzing SEC filings, earnings transcripts, and financial data for 30+ cybersecurity companies. Features AI-powered sentiment analysis, knowledge graph exploration, price forecasting, and a conversational chatbot assistant.

---

## Primary Architecture Files

### Backend Core (Flask API)
| File | Purpose |
|------|---------|
| [app.py](backend/app.py) | Main Flask application, all API endpoints |
| [langchain_agent.py](backend/services/langchain_agent.py) | **LangGraph agent** with hybrid Haiku/Sonnet routing |
| [langchain_tools.py](backend/services/langchain_tools.py) | 25 tools for agent (sentiment, forecast, graph queries, regulatory) |
| [prompts.py](backend/services/prompts.py) | System prompt with anti-hallucination rules |

### Data Services
| File | Purpose |
|------|---------|
| [database_service.py](backend/services/database_service.py) | PostgreSQL CRUD (companies, artifacts, regulations) |
| [neo4j_service.py](backend/services/neo4j_service.py) | Neo4j graph database operations |
| [gds_service.py](backend/services/gds_service.py) | Graph Data Science analytics (PageRank, Louvain) |
| [memory_service.py](backend/services/memory_service.py) | Mem0 semantic memory + pgvector |

### Feature Services
| File | Purpose |
|------|---------|
| [regulatory_service.py](backend/services/regulatory_service.py) | Federal Register API, relevance scoring, alerts |
| [comprehend_service.py](backend/services/comprehend_service.py) | AWS Comprehend NLP sentiment analysis |
| [scraper.py](backend/services/scraper.py) | SEC EDGAR + Alpha Vantage data collection |
| [graph_builder_service.py](backend/services/graph_builder_service.py) | LLM entity extraction → Neo4j |

### Frontend (React)
| File | Purpose |
|------|---------|
| [Dashboard.jsx](frontend/src/components/Dashboard.jsx) | Main navigation, tab routing |
| [GraphRAGAssistant.jsx](frontend/src/components/GraphRAGAssistant.jsx) | AI chat interface + competitive intelligence |
| [ComplianceMonitor.jsx](frontend/src/components/ComplianceMonitor.jsx) | Regulatory alerts dashboard |
| [AuthProvider.jsx](frontend/src/components/AuthProvider.jsx) | Cognito authentication |

### Infrastructure
| File | Purpose |
|------|---------|
| [terraform/](terraform/) | AWS infrastructure as code |
| [.github/workflows/](/.github/workflows/) | CI/CD pipelines |
| [scripts/hibernate.sh](scripts/hibernate.sh) | Cost management - stop resources |
| [scripts/wakeup.sh](scripts/wakeup.sh) | Cost management - restart resources |

### Archived Files
Development artifacts, test results, and one-time scripts have been moved to `archive/`:
- `archive/test-results/` - Agent test logs
- `archive/raw-data/` - JSON data dumps, ad-hoc scripts
- `archive/one-time-scripts/` - Migration scripts

---

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

## User Preferences

- **Git commits**: Do NOT add "Co-Authored-By" lines to commit messages

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

### Nodes (12 types, ~136K total after cleanup)
| Node Label | Count | Description |
|------------|-------|-------------|
| Concept | 129,344 | Key phrases from documents |
| Organization | 2,732 | Companies (31 tracked + mentioned) |
| Person | 2,662 | People mentioned in filings |
| Patent | 791 | Filed patents |
| Document | 869 | SEC filings & transcripts |
| Location | 586 | Geographic locations |
| Event | 156 | General events |
| ExecutiveEvent | 127 | C-suite appointments/departures |
| Vulnerability | 77 | CVE vulnerabilities |
| MAEvent | 15 | M&A events |
| RestructuringEvent | 1 | Restructuring events |
| SecurityEvent | 1 | Security incidents |

### Relationships (14 types, 668,339 total)
| From | Relationship | To | Count |
|------|--------------|-----|-------|
| Document | DISCUSSES | Concept | 632,197 |
| Document | MENTIONS | * | 25,855 |
| Organization | FILED | Patent | 2,634 |
| Person | INVENTED | Patent | 2,343 |
| Organization | COMPETES_WITH | Organization | 2,285 |
| Organization | OPERATES_IN | Location | 1,803 |
| Organization | HAS_FILING | Document | 583 |
| Event | INVOLVES | Organization | 291 |
| Organization | HAS_EXECUTIVE_EVENT | ExecutiveEvent | 127 |
| Person | INVOLVED_IN | ExecutiveEvent | 127 |
| Organization | HAS_VULNERABILITY | Vulnerability | 77 |
| Organization | HAS_MA_EVENT | MAEvent | 15 |
| Organization | HAS_RESTRUCTURING_EVENT | RestructuringEvent | 1 |
| Organization | HAS_SECURITY_EVENT | SecurityEvent | 1 |

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

**Tool Count**: 12 → 14 → 20 tools (see session below for new additions)

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

### 2026-01-24: LangChain Agent Improvements

**Issues Fixed**:

1. **504 Gateway Timeouts**: Complex multi-tool queries were timing out because CloudFront's default origin timeout was 30 seconds.
   - **Fix**: Updated CloudFront API origin settings via AWS CLI:
     - `OriginReadTimeout`: 30s → 60s
     - `OriginKeepaliveTimeout`: 5s → 60s

2. **Recursion Limit Too Low**: LangGraph agent was limited to 10 turns, not enough for complex queries.
   - **Fix**: Increased `recursion_limit` from 10 to 25 in [langchain_agent.py](backend/services/langchain_agent.py)

3. **Tool Extraction Bug**: Only tools from the LAST AI message were reported, missing earlier tool calls.
   - **Fix**: Now collects ALL tools used across entire agent run

4. **Sentiment Cache Miss Not Running Comprehend**: `get_sentiment` tool only read from cache, returning error on miss.
   - **Fix**: Now runs AWS Comprehend analysis on cache miss, caches result, returns data

**Commits**:
- `cc28f44` - Increase recursion limit and fix tool extraction
- `e5a5610` - Add on-demand Comprehend analysis for sentiment cache misses

**Test Results** (after fixes):
- 15/15 tests passed (100%)
- 10 unique tools used
- Semantic memory active in all responses
- Average response time: 26.5s

---

### 2026-01-24: Added Knowledge Graph Query Tools

**Problem**: Agent could only query ExecutiveEvent and Vulnerability nodes. Users needed to query all 12 node types in the knowledge graph.

**New Tools Added** ([langchain_tools.py](backend/services/langchain_tools.py)):
| Tool | Node Type | Description |
|------|-----------|-------------|
| `get_events(ticker, limit)` | Event | General business events from SEC filings |
| `get_persons(ticker, name, role, limit)` | Person | People mentioned or patent inventors |
| `get_ma_events(ticker, limit)` | MAEvent | Merger & acquisition events |
| `get_security_incidents(ticker, limit)` | SecurityEvent | Security breaches and incidents |
| `get_graph_documents(ticker, doc_type, limit)` | Document | List documents in knowledge graph |
| `get_locations(ticker, limit)` | Location | Geographic locations of operations |

**Total Tools**: 14 → 20

**Commit**: `2a198c0` - Add LangChain tools for all Neo4j node types

---

### Terraform State Issue (Important!)

**Warning**: The main `terraform.tfstate` file was empty (0 bytes). Restored from backup:
```bash
cp terraform.tfstate.backup.20260119_225517 terraform.tfstate
```

**DO NOT run `terraform apply`** without first verifying the plan. Current state has drift that would recreate VPC resources. Use AWS CLI for infrastructure changes until state is fully reconciled.

---

### EC2 Instance Reference
- **Flask Backend**: `i-0bdafbb7e0387b4cb` (cyberrisk-dev-kh-flask-backend)
- **Neo4j**: `i-0aefeaee10f6fdeea` (cyberrisk-dev-kh-neo4j)

---

### 2026-01-24: Knowledge Graph Cleanup & Quality Improvements

**Problem**: Graph had data quality issues:
- 6,428 Concept nodes with newlines/separators (parsing artifacts)
- 346 orphan Organization nodes (garbage/misclassified)
- 24 bad Location nodes (SEC metadata, incomplete phrases)
- 4 duplicate Organization pairs (tracked + non-tracked versions)

**Cleanup Script Enhancements** ([cleanup_graph.py](scripts/cleanup_graph.py)):

1. **Location Cleanup with ISO Code Preservation**:
   - Added comprehensive list of ISO 3166-1 country codes + US state abbreviations
   - Preserves valid 2-letter codes (US, UK, CA, NY, etc.)
   - Deletes: pure numbers, SEC metadata, incomplete phrases ("Middle East and"), company names as locations ("okta"), malformed newlines

2. **Duplicate Organization Merge**:
   - New `merge_duplicate_organizations()` function
   - Moves relationships from non-tracked to tracked version
   - Handles common relationship types without APOC dependency
   - Deletes non-tracked duplicates after merging

3. **Orphan Organization Cleanup**:
   - Deletes organizations with no relationships
   - Preserves all `tracked=true` companies

**Execution Results**:
| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Concepts | 135,772 | 129,344 | -6,428 |
| Locations | 610 | 586 | -24 |
| Organizations | 3,078 | 2,732 | -346 |
| Relationships | 681,059 | 668,339 | -12,720 |
| Tracked Companies | 31 | 31 | 0 ✓ |

**Admin API for Cleanup**:
- `POST /api/admin/neo4j/write` with `admin_key: "cleanup-2026"`
- Executes write Cypher queries for cleanup operations

**Commit**: `03ace8a` - Enhance graph cleanup with ISO code preservation and org deduplication

---

### 2026-01-24: GDS (Graph Data Science) Implementation Plan

**Current Graph Structure** (14 relationship types, 668K relationships):
| Relationship | Count | Use Case |
|--------------|-------|----------|
| DISCUSSES | 632,197 | Document → Concept topic analysis |
| MENTIONS | 25,855 | Document → Entity extraction |
| FILED | 2,634 | Organization → Patent IP analysis |
| INVENTED | 2,343 | Person → Patent inventor network |
| COMPETES_WITH | 2,285 | Competition landscape |
| OPERATES_IN | 1,803 | Geographic footprint |
| HAS_FILING | 583 | Organization → SEC filings |
| INVOLVES | 291 | Event participation |
| HAS_EXECUTIVE_EVENT | 127 | Executive changes |
| HAS_VULNERABILITY | 77 | Security risks |
| HAS_MA_EVENT | 15 | M&A activity |

**Proposed GDS Analytics**:

**Phase 1 - Competitive Intelligence**:
- PageRank on COMPETES_WITH → Market leaders
- Betweenness Centrality → Acquisition targets
- Louvain Community → Market segments

**Phase 2 - Innovation Analysis**:
- Node Similarity on FILED patents → Similar IP portfolios
- Jaccard Similarity on concepts → Emerging competitors
- Triangle Count → R&D collaboration density

**Phase 3 - Risk Assessment**:
- Label Propagation → Vulnerability spread patterns
- Weakly Connected Components → Portfolio diversification
- Shortest Path → Due diligence traces

**Phase 4 - Executive Intelligence**:
- Degree Centrality on Persons → Key executives
- Common Neighbors → Board/executive connections

**Implementation Steps**:
1. ✅ Enable GDS plugin on Neo4j instance
2. Create graph projections for each analysis type
3. Add API endpoints to expose analytics
4. Build dashboard visualizations

---

### 2026-01-25: GDS Plugin Installation Complete

**Neo4j GDS 2.13.2** installed on Neo4j 5.26.19:

**Installation**:
1. Downloaded GDS JAR from GitHub releases (64MB)
2. Transferred via Flask bastion to Neo4j private subnet
3. Installed to `/var/lib/neo4j/plugins/`
4. Updated `/etc/neo4j/neo4j.conf`:
   ```
   dbms.security.procedures.unrestricted=apoc.*,gds.*
   dbms.security.procedures.allowlist=apoc.*,gds.*
   ```
5. Restarted Neo4j service

**Verification**:
```cypher
RETURN gds.version() AS version  -- Returns "2.13.2"
CALL gds.list() YIELD name       -- Lists all GDS procedures
```

**Available Algorithms**:
- Centrality: PageRank, Betweenness, Degree, Closeness
- Community: Louvain, Label Propagation, WCC, Triangle Count
- Similarity: Node Similarity, Jaccard, Cosine
- Path Finding: Dijkstra, A*, Delta-Stepping
- Node Embedding: FastRP, GraphSAGE, Node2Vec

**GDS API Endpoints** (deployed 2026-01-25):
```
GET  /api/gds/version              - GDS version info
GET  /api/gds/summary              - Available analytics and graphs
GET  /api/gds/graphs               - List graph projections

Centrality Analysis:
GET  /api/gds/centrality/pagerank      - Market leaders (PageRank)
GET  /api/gds/centrality/betweenness   - Strategic bridges
GET  /api/gds/centrality/degree        - Competitor counts

Community Detection:
GET  /api/gds/community/louvain        - Market segments
GET  /api/gds/community/wcc            - Connected components

Similarity Analysis:
GET  /api/gds/similarity/patents       - Patent portfolio similarity
GET  /api/gds/similarity/company/<ticker>  - Similar to company

Risk & Executive:
GET  /api/gds/risk/vulnerabilities     - Vulnerability distribution
GET  /api/gds/executive/network        - Executive network analysis
```

**Sample PageRank Results**:
| Rank | Company | Ticker | Score |
|------|---------|--------|-------|
| 1 | Okta | OKTA | 5.04 |
| 2 | Tenable | TENB | 3.35 |
| 3 | Rapid7 | RPD | 2.20 |
| 4 | Akamai | AKAM | 1.94 |
| 5 | F5 Networks | FFIV | 1.49 |

**Market Segments** (Louvain):
- Segment 1 (19 companies): A10, Check Point, Corero, CyberArk, FireEye, Juniper, Mitek, Cloudflare, ServiceNow, Qualys...
- Segment 2 (7 companies): CrowdStrike, Cisco, F5, Fortinet, Palo Alto, Rapid7, Splunk
- Segment 3 (2 companies): Okta, Tenable

**Dashboard Visualizations** (deployed 2026-01-25):

Added "Competitive Intelligence" tab to Knowledge Assistant page with:
- **Market Leaders Panel**: Ranked bar display with PageRank scores, clickable to select company
- **Market Segments Panel**: Louvain community clusters with company chips, color-coded by segment
- **Similar Companies Panel**: Dynamic similarity analysis for selected company, showing shared competitors/concepts

**LangChain Agent Tools** (5 new GDS tools):
- `get_market_segments` - Louvain community detection results
- `get_market_leaders` - PageRank centrality rankings
- `get_similar_companies` - Find companies similar to a given ticker
- `get_competitive_intelligence_summary` - Combined overview
- `get_strategic_positions` - Betweenness centrality for acquisition targets

Example queries the AI can now answer:
- "What are the market segments for tracked companies?"
- "Who are the market leaders in cybersecurity?"
- "What companies are similar to CrowdStrike?"
- "Give me a competitive intelligence overview"

---

### 2026-01-25: Graph Data Quality Cleanup

**Problem**: Verint Systems had 2,248 spurious COMPETES_WITH relationships, skewing all GDS analytics.

**Root Cause**: Bad SEC filing extraction on `2026-01-23T16:33:17` created garbage relationships including:
- Parsing fragments ("2021)", "from Abbott", "$ 382 million of investments in")
- Non-competitors (patent offices, investment banks, government agencies)
- Duplicate entities (6x Microsoft nodes, 6x Google nodes)

**Cleanup Performed via Admin API**:
| Action | Nodes Deleted | Relationships Deleted |
|--------|--------------|----------------------|
| Verint bad batch | 0 | 2,248 |
| Microsoft duplicates | 5 | 143 |
| Google duplicates | 5 | 70 |
| Amazon duplicates | 5 | 121 |
| Lumen/StackPath/garbage | 4 | 9 |
| **Total** | **19** | **2,591** |

**Updated Graph Stats**:
- Organizations: 2,713 (was 2,732)
- Relationships: 665,748 (was 668,339)
- COMPETES_WITH: 32 clean relationships (was ~4,500 polluted)

**Updated PageRank Results** (balanced):
| Rank | Company | Ticker | Score |
|------|---------|--------|-------|
| 1 | Rapid7 | RPD | 1.83 |
| 2 | Okta | OKTA | 1.65 |
| 3 | Akamai | AKAM | 1.40 |
| 4 | F5 Networks | FFIV | 1.36 |
| 5 | Tenable | TENB | 1.15 |

**Segment Descriptions Enhancement** (pending deployment):
- Added TF-IDF style scoring to `gds_service.py` to identify distinctive concepts per segment
- Rewards concepts popular within cluster but rare globally
- Auto-filters generic noise (revenue, company, quarter)
- Code in repo, will deploy on next git push

---

### 2026-01-25: Regulatory Alert Dashboard Implementation

**Feature**: Added comprehensive regulatory compliance monitoring to track SEC, CISA, FTC, NIST regulations impacting tracked cybersecurity companies.

**Components Created**:

**Backend** ([regulatory_service.py](backend/services/regulatory_service.py)):
- Federal Register API integration for automated regulation fetching
- TF-IDF style relevance scoring (sector match 40%, keyword overlap 40%, base relevance 20%)
- Severity determination based on document type (final rule vs guidance)
- Impact level calculation combining relevance score and regulation severity

**Database** ([database_service.py](backend/services/database_service.py)):
```sql
-- New tables added
CREATE TABLE regulations (
    id SERIAL PRIMARY KEY,
    external_id VARCHAR(100) UNIQUE,  -- Federal Register doc_number
    title VARCHAR(500) NOT NULL,
    agency VARCHAR(50) NOT NULL,       -- SEC, CISA, FTC, NIST, DOJ
    summary TEXT,
    effective_date DATE,
    publication_date DATE,
    source_url TEXT,
    severity VARCHAR(20) DEFAULT 'MEDIUM',  -- CRITICAL, HIGH, MEDIUM, INFO
    keywords JSONB,
    sectors_affected JSONB
);

CREATE TABLE regulatory_alerts (
    id SERIAL PRIMARY KEY,
    regulation_id INT REFERENCES regulations(id) ON DELETE CASCADE,
    company_id INT REFERENCES companies(id) ON DELETE CASCADE,
    relevance_score FLOAT,             -- TF-IDF score (0-1)
    impact_level VARCHAR(20),          -- CRITICAL, HIGH, MEDIUM, LOW
    status VARCHAR(30) DEFAULT 'UNACKNOWLEDGED',
    ai_impact_analysis TEXT,
    matched_keywords JSONB,
    UNIQUE(regulation_id, company_id)
);
```

**API Endpoints** ([app.py](backend/app.py)):
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/regulatory/dashboard/summary` | GET | Dashboard metrics |
| `/api/regulatory/alerts` | GET | List alerts (filter by ticker, status, impact) |
| `/api/regulatory/alerts/<id>/acknowledge` | POST | Acknowledge alert (requires auth) |
| `/api/regulatory/regulations` | GET | List all regulations |
| `/api/regulatory/regulations` | POST | Manually add regulation |
| `/api/regulatory/company/<ticker>/alerts` | GET | Company-specific alerts |
| `/api/regulatory/ingest` | POST | Trigger Federal Register API fetch |

**LangChain Tools** ([langchain_tools.py](backend/services/langchain_tools.py)):
- `get_regulatory_alerts(ticker, status)` - Query alerts for companies
- `get_regulation_impact(regulation_id, ticker)` - Detailed regulation impact
- `get_company_compliance_status(ticker)` - Compliance summary with risk level

**Frontend** ([ComplianceMonitor.jsx](frontend/src/components/ComplianceMonitor.jsx)):
- **Alert Overview**: Summary cards (Critical, High, Total Active, Acknowledged) + agency breakdown
- **Regulation Timeline**: Upcoming effective dates + recent regulations list
- **Impact Analysis**: Heat Map showing regulation severity vs company exposure
- **Compliance Status**: Company-specific compliance drill-down

**Color Scheme**:
- CRITICAL: `#dc2626` (red)
- HIGH: `#f59e0b` (amber)
- MEDIUM: `#3b82f6` (blue)
- LOW/INFO: `#22c55e`/`#6b7280` (green/gray)

**Agent Integration** ([prompts.py](backend/services/prompts.py)):
Added regulatory expertise and tool usage instructions. Agent can answer:
- "What regulatory alerts affect CrowdStrike?"
- "Show compliance status for PANW"
- "What SEC rules apply to our tracked companies?"
- "Are there any critical regulatory alerts?"

References SEC Cybersecurity Disclosure Rule (effective 2023-12-18, 8-K Item 1.05 for 4-day material incident disclosure).

**Tracked Agencies**: SEC, CISA, FTC, NIST, DOJ, Commerce, OCC

**Enhancements** (same day):

1. **Bedrock LLM Validation** ([regulatory_service.py:311-416](backend/services/regulatory_service.py#L311-L416)):
   - Added `_validate_with_llm()` method to filter false positives
   - Prompt covers all cybersecurity domains: endpoint, network, cloud, identity, SecOps, AppSec, data security, GRC, MSSP, IoT/OT, email security
   - Returns YES/NO with confidence (HIGH/MEDIUM/LOW) and reasoning
   - Skips irrelevant regulations (e.g., auto dealer rules) before creating alerts

2. **Neo4j Graph Integration** ([regulatory_service.py:418-531](backend/services/regulatory_service.py#L418-L531)):
   - Creates `:Regulation` nodes with timeline attributes (`effective_date`, `publication_date`, `timeline_status`)
   - Adds source attributes (`source`, `source_url`, `summary`)
   - Creates `(Regulation)-[:IMPACTS]->(Organization)` relationships with `relevance_score` and `impact_level`

3. **Clear & Re-ingest** ([app.py](backend/app.py)):
   - Added `clear_existing` flag to `/api/regulatory/ingest` endpoint
   - Added `DELETE /api/regulatory/clear` endpoint
   - Frontend prompts to clear before ingesting (recommended for fresh start)

**Ingestion Statistics** now include:
- `regulations_skipped` - count filtered by LLM
- `graph_nodes_synced` - count synced to Neo4j
- `cleared` - stats if clear_existing was used

4. **UI Enhancements** ([ComplianceMonitor.jsx](frontend/src/components/ComplianceMonitor.jsx)):
   - Added **Acknowledge button** (green checkmark) to each alert card
   - Acknowledged alerts show badge instead of button
   - Auto-refreshes data after acknowledgment
   - Added **Impact Rating & Relevance Score legend** explaining:
     - Impact colors: CRITICAL (red), HIGH (amber), MEDIUM (blue), LOW (green)
     - Relevance calculation: Sector (40%) + Keywords (40%) + Base (20%)
     - Score thresholds: 70%+ → CRITICAL/HIGH, 50-70% → HIGH, 30-50% → MEDIUM

**Known Issues**:
- Impact Analysis heat map needs redesign (all companies show ~60% due to uniform scoring)

5. **Federal Register Ingestion Fixes** (2026-01-25):
   - **TRACKED_AGENCIES**: Added `homeland-security-department` (for CISA), `federal-communications-commission`, `federal-reserve-system`
   - **Removed non-existent slug**: `cybersecurity-and-infrastructure-security-agency` returns 0 results (CISA publishes via DHS)
   - **Search ALL 17 keywords**: Changed `CYBER_KEYWORDS[:5]` → `CYBER_KEYWORDS`
   - **Extended date window**: 90 days → 365 days to capture historical regulations like SEC 2023 Disclosure Rule
   - To test: Clear existing data and re-ingest via the Regulatory Alerts tab

6. **Async Ingestion with Polling** (2026-01-26):
   - **Problem**: CloudFront/ALB 30-60s timeout caused HTML error page when ingestion took too long
   - **Solution**: Background threading with polling
   - **Backend changes** ([regulatory_service.py](backend/services/regulatory_service.py)):
     - Added `start_ingestion_async()` - spawns background thread, returns immediately
     - Added `get_ingestion_status()` - returns progress (0-100%), status, message
     - Added `_ingestion_worker()` - actual ingestion logic with progress updates
   - **API changes** ([app.py](backend/app.py)):
     - `POST /api/regulatory/ingest` now returns `202 Accepted` and runs async
     - Added `GET /api/regulatory/ingest/status` for polling
   - **Frontend changes** ([ComplianceMonitor.jsx](frontend/src/components/ComplianceMonitor.jsx)):
     - Added progress bar showing percentage and current article being processed
     - Polls `/api/regulatory/ingest/status` every 2 seconds
     - Shows completion alert with stats when done

7. **Keyword Modernization & Cost Optimization** (2026-01-26):
   - **Updated CYBER_KEYWORDS** (22 terms) for 2026 regulatory landscape:
     - Added AI governance: `artificial intelligence security`, `model risk management`
     - Added SBOM: `software bill of materials`, `sbom`
     - Added resilience: `cyber resilience` (DORA trend)
     - Made terms specific: `data privacy` (vs `privacy`), `cryptography` (vs `encryption`)
     - Removed trap keywords: `privacy`, `disclosure`, `authentication` (too broad)
   - **Added NON_CYBER_KEYWORDS** negative filter (13 terms):
     - Fast-fail filter runs BEFORE Bedrock LLM validation
     - Filters: `motor vehicle`, `dealer`, `livestock`, `agriculture`, `medicare`, etc.
     - Reduces Bedrock API costs by skipping obvious non-cyber regulations
   - **Stats now show 3 filter stages**:
     - `negative_filtered` - Skipped by keyword filter (fast/free)
     - `regulations_skipped` - Skipped by LLM validation (slow/costs $)
     - `regulations_created` - Final count

---

### 2026-01-26: Hybrid Model Routing + Smarter Relevance Scoring

**Problem 1 - Latency**: Agent used Claude 3.5 Sonnet for all queries, causing high latency on simple lookups.

**Problem 2 - Irrelevant Alerts**: CrowdStrike (endpoint security) was getting alerts for FCC telecom regulations because relevance scoring was too generic (all cyber companies scored ~60%).

**Fix 1 - Hybrid Routing** ([langchain_agent.py](backend/services/langchain_agent.py)):
- Added query complexity classification with regex patterns
- Simple queries → Claude 3.5 Haiku (3-5x faster)
- Complex queries → Claude 3.5 Sonnet (deeper analysis)
- Response includes `model` and `query_complexity` fields

```python
SIMPLE_QUERY_PATTERNS = [
    r"^(list|show|what are|get)\s+(the\s+)?(companies|tickers|tracked)",
    r"^(how many|count)", r"^help", r"^hi|hello|hey",
]
COMPLEX_QUERY_PATTERNS = [
    r"(analyze|analysis|compare|comparison|evaluate|assess)",
    r"(strategy|strategic|implications|impact)",
    r"(recommend|suggest|advise|should i)",
]
```

**Fix 2 - Business-Aware Relevance** ([regulatory_service.py](backend/services/regulatory_service.py)):
- Added `COMPANY_BUSINESS_FOCUS` mapping (ticker → business areas)
- Added `AGENCY_BUSINESS_RELEVANCE` (agency → business relevance scores)
- FCC now scores 0.2 for pure software companies (was ~0.6)
- Raised relevance threshold from 0.3 to 0.5

**Fix 3 - Dashboard Prioritization** ([ComplianceMonitor.jsx](frontend/src/components/ComplianceMonitor.jsx)):
- Primary metric changed to "Active Regulations" (35) instead of alert count (1050)
- Added explanation: "Alerts = regulations × companies"

---

### 2026-01-28: Anti-Hallucination Architecture (Structural Enforcement)

**Problem**: The old approach used "prompt-based guards" - yelling at the LLM with "CRITICAL", "ABSOLUTELY NO HALLUCINATION", "NEVER" instructions. This was unreliable.

**Solution**: Move anti-hallucination from prompts to **architecture**. The harness now enforces data grounding structurally.

**New Architecture** ([langchain_agent.py](backend/services/langchain_agent.py)):

```
User Query → Router → Tool Execution → Grounded Synthesizer → Response
                                              ↓
                                    Hallucination Grader (optional loop)
```

**Component 1: Router Node** (Haiku, temp=0)
- Classifies queries: `financial`, `regulatory`, `graph`, `document_search`, `general`
- Extracts entities (tickers, regulation IDs)
- **FORCES tool calls** for entity-specific queries
- Has NO knowledge - cannot hallucinate during routing

```python
class RouteQuery(BaseModel):
    destination: Literal["financial", "regulatory", "graph", "document_search", "general"]
    ticker: Optional[str]
    requires_tool: bool
```

**Component 2: Tool Empty Result Handling** ([langchain_tools.py](backend/services/langchain_tools.py))
- Tools return structured `NO_DATA` or `ERROR` responses instead of empty results
- Responses include `SYSTEM_NOTIFICATION` string that triggers short-circuit
- Agent cannot "fill in the gaps" with hallucinated data

```python
def no_data_response(data_type: str, entity: str = None) -> Dict:
    return {
        "status": "no_data",
        "NO_DATA": True,
        "data_type": data_type,
        "entity": entity,
        "message": f"SYSTEM_NOTIFICATION: NO_DATA_FOUND for {data_type} ({entity}). Do not guess."
    }
```

**Component 3: Grounded Synthesizer** (Sonnet, temp=0)
- "Reporter" prompt that can ONLY use tool output
- **SHORT-CIRCUIT**: If `SYSTEM_NOTIFICATION` detected, skip LLM entirely
- Returns canned response for no-data cases (zero hallucination risk)
- For valid data: generates response with restricted context

```python
def synthesize_response(state, llm):
    tool_output_str = json.dumps(tool_output)

    # SHORT-CIRCUIT: Skip LLM entirely for no-data cases
    if "SYSTEM_NOTIFICATION: NO_DATA_FOUND" in tool_output_str:
        return "I checked the CyberRisk Dashboard, but I don't have that data available."

    # Only reach LLM with valid data
    return llm.invoke(SYNTHESIS_PROMPT.format(tool_output=tool_output))
```

**Component 4: Hallucination Grader** (Haiku, temp=0)
- Validates that response contains ONLY facts from tool output
- Returns `is_grounded: bool` and `problematic_claims: list`
- If hallucination detected, regenerates response

**Prompt Simplification** ([prompts.py](backend/services/prompts.py)):
- Removed ~60% of prompt text (all the "CRITICAL", "NEVER" guards)
- Prompts now describe roles, not rules
- Architecture enforces what prompts used to beg for

**Files Changed**:
| File | Changes |
|------|---------|
| `langchain_agent.py` | Complete rewrite with Router → Tools → Synthesizer flow |
| `langchain_tools.py` | Added `no_data_response()`, `error_response()` helpers |
| `prompts.py` | Simplified prompts, added role-specific prompts |

**Response Metadata** now includes:
- `route`: Which category the query was routed to
- `ticker`: Extracted ticker (if any)
- `has_data`: Whether tools returned actual data

---
*Last Updated: 2026-01-28*
