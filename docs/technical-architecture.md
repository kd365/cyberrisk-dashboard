# CyberRisk Dashboard - Technical Architecture Documentation

## Table of Contents
1. [LangChain Chain Architecture](#langchain-chain-architecture)
2. [Mem0 Memory Layer Design](#mem0-memory-layer-design)
3. [Database Schema](#database-schema)
4. [RAG Pipeline Architecture](#rag-pipeline-architecture)

---

## LangChain Chain Architecture

### Overview

The CyberRisk Dashboard uses LangChain to orchestrate a tool-calling agent powered by Claude 3.5 Sonnet via AWS Bedrock. This provides an intelligent chat assistant capable of querying company data, sentiment analysis, forecasts, and searching SEC filings.

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        User Chat Request                             │
│                    POST /api/chat {message, session_id}             │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    LangChainAgentService                             │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                  ChatPromptTemplate                          │   │
│  │  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────┐ │   │
│  │  │   System    │  │ Chat History │  │   Human Message     │ │   │
│  │  │   Prompt    │  │ (from Mem0)  │  │   + Scratchpad      │ │   │
│  │  └─────────────┘  └──────────────┘  └─────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                               │                                      │
│                               ▼                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              create_tool_calling_agent()                     │   │
│  │         LangChain Agent with Tool Bindings                   │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                               │                                      │
│                               ▼                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    AgentExecutor                             │   │
│  │              max_iterations=5, verbose=False                 │   │
│  │              handle_parsing_errors=True                      │   │
│  └─────────────────────────────────────────────────────────────┘   │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
        ▼                      ▼                      ▼
┌───────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  AWS Bedrock  │    │   Tool Layer    │    │  Memory Service │
│  Claude 3.5   │    │   (11 Tools)    │    │   (Mem0 + PG)   │
│    Sonnet     │    │                 │    │                 │
└───────────────┘    └─────────────────┘    └─────────────────┘
```

### Components

#### 1. LangChainAgentService (`langchain_agent.py`)

The main service class that orchestrates the chat workflow:

```python
class LangChainAgentService:
    MODEL_ID = "anthropic.claude-3-5-sonnet-20241022-v2:0"

    def __init__(self):
        # Initialize Claude 3.5 Sonnet via Bedrock
        self.llm = ChatBedrock(
            model_id=self.MODEL_ID,
            region_name="us-west-2",
            model_kwargs={"max_tokens": 4096, "temperature": 0.7}
        )

        # Load tools and create agent
        self.tools = get_all_tools()
        self.agent = create_tool_calling_agent(self.llm, self.tools, self.prompt)
        self.executor = AgentExecutor(agent=self.agent, tools=self.tools, max_iterations=5)
```

#### 2. Tool Definitions (`langchain_tools.py`)

Tools are defined using LangChain's `@tool` decorator:

| Tool | Purpose | Data Source |
|------|---------|-------------|
| `list_companies` | List all tracked cybersecurity companies | PostgreSQL |
| `get_company_info` | Get company details + current stock price | PostgreSQL + Yahoo Finance |
| `get_sentiment` | Retrieve sentiment analysis results | AWS Comprehend cache |
| `get_forecast` | Get stock price predictions | Prophet/Chronos models |
| `get_growth_metrics` | Employee count and hiring trends | CoreSignal API |
| `get_documents` | List SEC filings for a company | S3 artifacts |
| `query_knowledge_graph` | Search Neo4j for entities/relationships | Neo4j |
| `get_patents` | Search patent database | Neo4j |
| `search_documents` | Semantic search over SEC filings | pgvector RAG |
| `get_document_context` | Get formatted context for Q&A | pgvector RAG |
| `get_dashboard_help` | Explain dashboard features | Static |

#### 3. Prompt Template

The system prompt includes:
- Role definition as a cybersecurity analyst
- List of available tools and their purposes
- Current list of tracked companies (loaded dynamically from RDS)
- Instructions for tool usage and response formatting

### Data Flow

1. **Request**: User sends message to `/api/chat`
2. **History**: Memory service retrieves last 5 messages from session
3. **Prompt Assembly**: System prompt + chat history + user message
4. **Agent Loop**: Claude decides which tools to call (up to 5 iterations)
5. **Tool Execution**: Tools query databases, APIs, or caches
6. **Response**: Final response returned to user
7. **Memory Save**: User message and response saved to session

---

## Mem0 Memory Layer Design

### Overview

The memory layer provides two types of memory for the chat assistant:
1. **Session Memory**: Recent conversation history (PostgreSQL tables)
2. **Semantic Memory**: Long-term fact extraction using Mem0 + pgvector

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         MemoryService                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌─────────────────────────┐    ┌─────────────────────────────────┐ │
│  │   Session Memory        │    │      Semantic Memory (Mem0)     │ │
│  │   (PostgreSQL)          │    │      (pgvector + Bedrock)       │ │
│  │                         │    │                                 │ │
│  │  ┌───────────────────┐  │    │  ┌───────────────────────────┐ │ │
│  │  │  chat_sessions    │  │    │  │  LLM: Claude 3.5 Haiku    │ │ │
│  │  │  - session_id     │  │    │  │  (Fact extraction)        │ │ │
│  │  │  - user_email     │  │    │  └───────────────────────────┘ │ │
│  │  │  - created_at     │  │    │                                 │ │
│  │  │  - last_active    │  │    │  ┌───────────────────────────┐ │ │
│  │  │  - metadata       │  │    │  │  Embedder: Titan v2       │ │ │
│  │  └───────────────────┘  │    │  │  (1024 dimensions)        │ │ │
│  │                         │    │  └───────────────────────────┘ │ │
│  │  ┌───────────────────┐  │    │                                 │ │
│  │  │  chat_messages    │  │    │  ┌───────────────────────────┐ │ │
│  │  │  - session_id     │  │    │  │  Vector Store: pgvector   │ │ │
│  │  │  - role           │  │    │  │  (PostgreSQL extension)   │ │ │
│  │  │  - content        │  │    │  └───────────────────────────┘ │ │
│  │  │  - created_at     │  │    │                                 │ │
│  │  └───────────────────┘  │    └─────────────────────────────────┘ │
│  │                         │                                        │
│  │  ┌───────────────────┐  │                                        │
│  │  │  user_memory      │  │    Mem0 Operations:                    │
│  │  │  (fallback)       │  │    - add(): Extract facts from convo  │
│  │  │  - memory_type    │  │    - search(): Semantic similarity    │
│  │  │  - content        │  │    - get_all(): Retrieve user facts   │
│  │  │  - importance     │  │    - delete(): Remove specific memory │
│  │  └───────────────────┘  │                                        │
│  └─────────────────────────┘                                        │
└─────────────────────────────────────────────────────────────────────┘
```

### Mem0 Configuration

```python
config = {
    "llm": {
        "provider": "aws_bedrock",
        "config": {
            "model": "anthropic.claude-3-5-haiku-20241022-v1:0",
            "temperature": 0.1,
            "max_tokens": 1000,
        },
    },
    "embedder": {
        "provider": "aws_bedrock",
        "config": {
            "model": "amazon.titan-embed-text-v2:0",
            "embedding_dims": 1024,
        },
    },
    "vector_store": {
        "provider": "pgvector",
        "config": {
            "host": DB_HOST,
            "dbname": "cyberrisk",
            "embedding_model_dims": 1024,
        },
    },
}

self._mem0 = Memory.from_config(config)
```

### Key Methods

| Method | Purpose |
|--------|---------|
| `create_session()` | Create new chat session with UUID |
| `add_message()` | Store message in chat_messages table |
| `get_session_history()` | Retrieve recent messages for a session |
| `get_context_for_llm()` | Format history for Claude's message format |
| `add_semantic_memory()` | Extract and store facts via Mem0 |
| `search_semantic_memory()` | Similarity search for relevant memories |
| `cleanup_old_sessions()` | Remove sessions older than 30 days |

### Benefits

1. **Session Continuity**: Users can reference earlier messages in conversation
2. **Fact Extraction**: Mem0 automatically extracts key facts (preferences, entities mentioned)
3. **Semantic Search**: Find relevant past context using embeddings
4. **No External APIs**: Uses AWS Bedrock (no OpenAI/external keys needed)
5. **Unified Storage**: Same PostgreSQL instance for all data

---

## Database Schema

### Overview

CyberRisk uses PostgreSQL with the pgvector extension for both relational data and vector similarity search.

### Entity Relationship Diagram

```
┌─────────────────────┐      ┌─────────────────────┐
│     companies       │      │      artifacts      │
├─────────────────────┤      ├─────────────────────┤
│ id (PK)             │      │ id (PK)             │
│ ticker (UNIQUE)     │◄────►│ ticker (FK)         │
│ company_name        │      │ artifact_type       │
│ sector              │      │ s3_key              │
│ exchange            │      │ published_date      │
│ location            │      │ created_at          │
│ description         │      │ metadata (JSONB)    │
│ alternate_names     │      └─────────────────────┘
│ created_at          │
└─────────────────────┘

┌─────────────────────┐      ┌─────────────────────┐
│   chat_sessions     │      │   chat_messages     │
├─────────────────────┤      ├─────────────────────┤
│ id (PK)             │      │ id (PK)             │
│ session_id (UNIQUE) │◄────►│ session_id (FK)     │
│ user_email          │      │ role                │
│ created_at          │      │ content             │
│ last_active         │      │ metadata (JSONB)    │
│ metadata (JSONB)    │      │ created_at          │
└─────────────────────┘      └─────────────────────┘

┌─────────────────────────────────────────────────┐
│              document_chunks (RAG)              │
├─────────────────────────────────────────────────┤
│ id (PK)                                         │
│ document_id                                     │
│ ticker                                          │
│ document_type                                   │
│ chunk_index                                     │
│ content                                         │
│ embedding (vector(1024))  ◄── pgvector column  │
│ metadata (JSONB)                                │
│ created_at                                      │
│ UNIQUE(document_id, chunk_index)                │
└─────────────────────────────────────────────────┘

┌─────────────────────┐      ┌─────────────────────┐
│  sentiment_cache    │      │  forecast_cache     │
├─────────────────────┤      ├─────────────────────┤
│ id (PK)             │      │ id (PK)             │
│ ticker              │      │ ticker              │
│ sentiment_data      │      │ model_type          │
│ cached_at           │      │ forecast_days       │
│ expires_at          │      │ forecast_data       │
└─────────────────────┘      │ cached_at           │
                             └─────────────────────┘

┌─────────────────────┐
│    growth_cache     │
├─────────────────────┤
│ id (PK)             │
│ ticker              │
│ employee_count      │
│ growth_pct          │
│ hiring_data (JSONB) │
│ cached_at           │
└─────────────────────┘
```

### pgvector Indexes

```sql
-- IVFFlat index for approximate nearest neighbor search
CREATE INDEX idx_chunks_embedding
ON document_chunks
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- B-tree indexes for filtering
CREATE INDEX idx_chunks_ticker ON document_chunks(ticker);
CREATE INDEX idx_chunks_document ON document_chunks(document_id);
```

---

## RAG Pipeline Architecture

### Overview

The RAG (Retrieval-Augmented Generation) pipeline enables semantic search over SEC filings and earnings transcripts.

### Pipeline Stages

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Document Ingestion Pipeline                      │
└─────────────────────────────────────────────────────────────────────┘
                               │
        ┌──────────────────────┴──────────────────────┐
        ▼                                             ▼
┌───────────────────┐                    ┌───────────────────────────┐
│  SEC EDGAR API    │                    │    Alpha Vantage API      │
│  (10-K, 10-Q, 8-K)│                    │  (Earnings Transcripts)   │
└────────┬──────────┘                    └─────────────┬─────────────┘
         │                                             │
         └──────────────────┬──────────────────────────┘
                            ▼
              ┌─────────────────────────────┐
              │      OCR Service            │
              │  (Text extraction from PDF) │
              └──────────────┬──────────────┘
                             ▼
              ┌─────────────────────────────┐
              │      Text Splitter          │
              │  chunk_size=1000            │
              │  chunk_overlap=200          │
              └──────────────┬──────────────┘
                             ▼
              ┌─────────────────────────────┐
              │    AWS Bedrock Embeddings   │
              │  amazon.titan-embed-text-v2 │
              │  1024 dimensions            │
              └──────────────┬──────────────┘
                             ▼
              ┌─────────────────────────────┐
              │   PostgreSQL + pgvector     │
              │   document_chunks table     │
              └─────────────────────────────┘
```

### Query Flow

```
User Query: "What are CrowdStrike's main cybersecurity risks?"
                             │
                             ▼
              ┌─────────────────────────────┐
              │    Generate Query Embedding │
              │    (Titan v2, 1024 dims)    │
              └──────────────┬──────────────┘
                             ▼
              ┌─────────────────────────────┐
              │  Cosine Similarity Search   │
              │  SELECT ... ORDER BY        │
              │  embedding <=> query_vec    │
              │  LIMIT 5                    │
              └──────────────┬──────────────┘
                             ▼
              ┌─────────────────────────────┐
              │   Return Top-K Chunks       │
              │   with metadata (source,    │
              │   ticker, document_type)    │
              └─────────────────────────────┘
```

### RAG Service Methods

```python
class RAGService:
    CHUNK_SIZE = 1000
    CHUNK_OVERLAP = 200
    EMBEDDING_MODEL = "amazon.titan-embed-text-v2:0"
    EMBEDDING_DIMENSIONS = 1024

    def split_text(self, text) -> List[Dict]
    def generate_embedding(self, text) -> List[float]
    def index_document(self, document_id, content, metadata)
    def search(self, query, ticker=None, limit=5) -> List[Dict]
    def get_context_for_query(self, query, ticker=None) -> str
```

---

## Summary

The CyberRisk Dashboard integrates:
- **LangChain + Claude 3.5 Sonnet**: Intelligent tool-calling agent
- **Mem0 + pgvector**: Semantic memory with AWS Bedrock embeddings
- **PostgreSQL**: Unified data store for relational and vector data
- **RAG Pipeline**: Document chunking, embedding, and similarity search

All AI services use AWS Bedrock, requiring no external API keys beyond AWS credentials.
