# =============================================================================
# LangChain Tools for CyberRisk Dashboard
# =============================================================================
#
# Wraps existing tool implementations as LangChain-compatible tools
# using the @tool decorator for use with Claude 3.5 Sonnet agent.
#
# =============================================================================

import logging
from typing import Optional
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Lazy-loaded service references
_db_service = None
_neo4j_service = None
_rag_service = None


def get_db_service():
    """Get database service singleton."""
    global _db_service
    if _db_service is None:
        from services.database_service import db_service

        _db_service = db_service
    return _db_service


def get_neo4j_service():
    """Get Neo4j service singleton."""
    global _neo4j_service
    if _neo4j_service is None:
        try:
            from services.neo4j_service import get_neo4j_service as get_neo4j

            _neo4j_service = get_neo4j()
        except Exception as e:
            logger.warning(f"Neo4j service not available: {e}")
    return _neo4j_service


def get_rag_service():
    """Get RAG service singleton."""
    global _rag_service
    if _rag_service is None:
        try:
            from services.rag_service import RAGService

            _rag_service = RAGService()
        except Exception as e:
            logger.warning(f"RAG service not available: {e}")
    return _rag_service


# =============================================================================
# Company Tools
# =============================================================================


@tool
def list_companies() -> dict:
    """List all companies currently tracked in the CyberRisk dashboard.

    Returns a list of companies with their ticker symbols, names, and sectors.
    Use this when asked about what companies are being tracked or for a general overview.
    """
    try:
        db = get_db_service()
        companies = db.get_all_companies()
        return {
            "companies": [
                {
                    "ticker": c["ticker"],
                    "name": c["company_name"],
                    "sector": c.get("sector", "Cybersecurity"),
                }
                for c in companies
            ],
            "count": len(companies),
        }
    except Exception as e:
        return {"error": str(e)}


@tool
def get_company_info(ticker: str) -> dict:
    """Get detailed information about a specific company including current stock price.

    Args:
        ticker: Stock ticker symbol (e.g., CRWD, PANW, ZS)

    Returns company details, current stock price, and price change percentage.
    """
    ticker = ticker.upper()
    try:
        db = get_db_service()
        company = db.get_company(ticker)
        if not company:
            return {"error": f"Company {ticker} not found"}

        from services.forecast_cache import get_stock_data

        stock_data = get_stock_data(ticker)

        return {
            "ticker": ticker,
            "name": company.get("company_name"),
            "sector": company.get("sector", "Cybersecurity"),
            "description": company.get("description", ""),
            "current_price": stock_data.get("current_price") if stock_data else None,
            "price_change_pct": stock_data.get("change_pct") if stock_data else None,
        }
    except Exception as e:
        return {"error": str(e)}


@tool
def add_company(ticker: str, company_name: str, sector: str = "Cybersecurity") -> dict:
    """Add a new company to track in the CyberRisk dashboard.

    Use this when a user wants to start tracking a new cybersecurity company.
    The company will be added to the database and can then be scraped for
    SEC filings and earnings transcripts.

    Args:
        ticker: Stock ticker symbol (e.g., CRWD, PANW, ZS)
        company_name: Full company name (e.g., "CrowdStrike Holdings, Inc.")
        sector: Business sector (defaults to "Cybersecurity")

    Returns:
        Success message or error if company already exists or creation failed.
    """
    ticker = ticker.upper().strip()
    company_name = company_name.strip()

    try:
        db = get_db_service()

        # Check if company already exists
        if db.company_exists(ticker):
            return {
                "status": "exists",
                "message": f"Company {ticker} is already being tracked.",
            }

        # Create the company
        company = db.create_company(company_name, ticker, sector)
        if company:
            return {
                "status": "success",
                "message": f"Successfully added {company_name} ({ticker}) to tracking. You can now scrape SEC filings and earnings transcripts for this company.",
                "company": {
                    "ticker": ticker,
                    "name": company_name,
                    "sector": sector,
                },
            }
        else:
            return {"status": "error", "message": "Failed to create company"}

    except Exception as e:
        return {"status": "error", "message": str(e)}


# =============================================================================
# Analysis Tools
# =============================================================================


@tool
def get_sentiment(ticker: str) -> dict:
    """Get sentiment analysis for a company based on SEC filings and earnings transcripts.

    Args:
        ticker: Stock ticker symbol (e.g., CRWD, PANW)

    Returns overall sentiment scores, document count analyzed, and top keywords.
    Use this when asked about market sentiment, filing analysis, or company outlook.
    """
    ticker = ticker.upper()
    try:
        from services.sentiment_cache import get_cached_sentiment, get_sentiment_cache

        # Try cache first
        sentiment = get_cached_sentiment(ticker)

        if sentiment:
            return {
                "ticker": ticker,
                "overall_sentiment": sentiment.get("overall", {}),
                "document_count": sentiment.get("document_count", 0),
                "top_keywords": sentiment.get("wordFrequency", [])[:10],
                "cached_at": sentiment.get("cached_at"),
            }

        # Cache miss - run Comprehend analysis
        try:
            from services.s3_service import S3ArtifactService
            from services.comprehend_service import ComprehendService

            # Get artifacts from S3
            s3_service = S3ArtifactService()
            artifacts = s3_service.get_artifacts_table()

            if not artifacts:
                return {"error": f"No artifacts available for analysis"}

            # Filter for this ticker
            ticker_artifacts = [a for a in artifacts if a.get("ticker") == ticker]
            if not ticker_artifacts:
                return {"error": f"No documents found for {ticker}"}

            # Run Comprehend analysis
            comprehend = ComprehendService()
            result = comprehend.analyze_ticker_sentiment(
                ticker, artifacts, include_entities=False
            )

            if not result:
                return {"error": f"Sentiment analysis failed for {ticker}"}

            # Cache the result
            cache = get_sentiment_cache()
            cache.set(ticker, artifacts, result)

            return {
                "ticker": ticker,
                "overall_sentiment": result.get("overall", {}),
                "document_count": result.get("document_count", 0),
                "top_keywords": result.get("wordFrequency", [])[:10],
                "cached_at": result.get("cached_at"),
                "freshly_computed": True,
            }

        except Exception as analysis_error:
            return {"error": f"Analysis failed: {str(analysis_error)}"}

    except Exception as e:
        return {"error": str(e)}


@tool
def get_forecast(ticker: str, days: int = 30) -> dict:
    """Get stock price forecast for a company using Chronos or Prophet models.

    Args:
        ticker: Stock ticker symbol (e.g., CRWD, PANW)
        days: Number of days to forecast (default: 30)

    Returns predicted price, expected return, confidence interval, and model accuracy.
    Chronos is the primary model; Prophet is used as fallback.
    """
    ticker = ticker.upper()
    try:
        from services.forecast_cache import get_cached_forecast, forecast_cache

        # Try Chronos cache first
        forecast = get_cached_forecast(ticker, "chronos", days)
        if forecast:
            return {
                "ticker": ticker,
                "model": "chronos",
                "forecast_days": days,
                "current_price": forecast.get("current_price"),
                "predicted_price": forecast.get("predicted_price"),
                "expected_return_pct": forecast.get("expected_return_pct"),
                "confidence": forecast.get("confidence_interval", {}),
                "accuracy": forecast.get("accuracy", {}),
                "computed_at": forecast.get("cached_at"),
            }

        # Try to run Chronos
        try:
            from models.chronos_forecaster import ChronosForecaster

            forecaster = ChronosForecaster(ticker, model_size="small")
            forecaster.fetch_stock_data(period="3y")
            results = forecaster.forecast(days_ahead=days)

            response_data = {
                "ticker": ticker,
                "model": "chronos",
                "current_price": float(results["current_price"]),
                "predicted_price": float(results["predicted_price"]),
                "expected_return_pct": float(results["expected_return_pct"]),
                "confidence_interval": {
                    "lower": float(results["confidence_lower"]),
                    "upper": float(results["confidence_upper"]),
                },
            }
            forecast_cache.set(ticker, days, response_data, "chronos")
            return {**response_data, "forecast_days": days}

        except Exception as chronos_error:
            logger.warning(f"Chronos failed: {chronos_error}, trying Prophet")

        # Fall back to Prophet
        forecast = get_cached_forecast(ticker, "prophet", days)
        if forecast:
            return {
                "ticker": ticker,
                "model": "prophet",
                "model_note": "Using Prophet (Chronos unavailable)",
                "forecast_days": days,
                "current_price": forecast.get("current_price"),
                "predicted_price": forecast.get("predicted_price"),
                "expected_return_pct": forecast.get("expected_return_pct"),
                "confidence": forecast.get("confidence_interval", {}),
                "computed_at": forecast.get("cached_at"),
            }

        return {"error": f"Could not generate forecast for {ticker}"}

    except Exception as e:
        return {"error": str(e)}


@tool
def get_growth_metrics(ticker: str) -> dict:
    """Get company growth metrics including employee count and hiring trends.

    Args:
        ticker: Stock ticker symbol (e.g., CRWD, PANW)

    Returns employee count, growth percentage, hiring intensity, and job breakdowns.
    Data sourced from CoreSignal.
    """
    ticker = ticker.upper()
    try:
        from services.growth_cache import get_cached_growth

        growth = get_cached_growth(ticker)

        if growth:
            return {
                "ticker": ticker,
                "employee_count": growth.get("employee_count"),
                "employee_growth_pct": growth.get("employee_growth_pct"),
                "hiring_intensity": growth.get("hiring_intensity"),
                "hiring_intensity_pct": growth.get("hiring_intensity_pct"),
                "open_positions": growth.get("total_jobs"),
                "jobs_by_function": growth.get("jobs_by_function", {}),
                "jobs_by_seniority": growth.get("jobs_by_seniority", {}),
                "snapshot_date": growth.get("snapshot_date"),
                "cached_at": growth.get("cached_at"),
            }

        return {
            "ticker": ticker,
            "message": "Growth metrics not available for this company",
            "employee_count": None,
        }
    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# Document Tools
# =============================================================================


@tool
def get_documents(ticker: str) -> dict:
    """List SEC filings and earnings transcripts available for a company.

    Args:
        ticker: Stock ticker symbol (e.g., CRWD, PANW)

    Returns list of available documents with types and dates.
    """
    ticker = ticker.upper()
    try:
        db = get_db_service()
        artifacts = db.get_artifacts_by_ticker(ticker)
        return {
            "ticker": ticker,
            "documents": [
                {
                    "type": a["artifact_type"],
                    "published_date": str(a.get("published_date", "")),
                    "s3_key": a["s3_key"],
                }
                for a in artifacts
            ],
            "count": len(artifacts),
        }
    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# Knowledge Graph Tools
# =============================================================================


@tool
def query_knowledge_graph(query: str, ticker: Optional[str] = None) -> dict:
    """Search the knowledge graph for information from SEC filings and documents.

    Args:
        query: Natural language query to search for (e.g., "cloud security risks", "AI investments")
        ticker: Optional ticker to limit search to specific company

    Use this for questions about topics, risks, people, or concepts mentioned in filings.
    Returns relevant entities, concepts, and relationships from the graph.
    """
    neo4j = get_neo4j_service()
    if not neo4j:
        return {
            "error": "Knowledge graph not available",
            "message": "Neo4j service is not connected",
        }

    try:
        ticker = ticker.upper() if ticker else None
        result = neo4j.semantic_query(query, ticker)
        return result
    except Exception as e:
        return {"error": str(e)}


@tool
def get_patents(
    ticker: Optional[str] = None,
    inventor_name: Optional[str] = None,
    search_term: Optional[str] = None,
    limit: int = 10,
) -> dict:
    """Search for patents filed by a company or inventor.

    Args:
        ticker: Stock ticker to search for company patents (e.g., CRWD, PANW)
        inventor_name: Name of an inventor to find their patents
        search_term: General search term for patent titles or content
        limit: Maximum patents to return (default: 10)

    Use when asked about patents, intellectual property, or inventions.
    """
    neo4j = get_neo4j_service()
    if not neo4j:
        return {
            "error": "Knowledge graph not available",
            "message": "Neo4j service is not connected",
        }

    try:
        ticker = ticker.upper() if ticker else None
        result = neo4j.get_patents(
            ticker=ticker,
            inventor_name=inventor_name,
            search_term=search_term,
            limit=limit,
        )
        return result
    except Exception as e:
        return {"error": str(e)}


@tool
def get_executive_events(ticker: Optional[str] = None, limit: int = 10) -> dict:
    """Get executive events (appointments, departures, resignations) for companies.

    Args:
        ticker: Stock ticker to get events for a specific company (e.g., CRWD, PANW)
        limit: Maximum events to return (default: 10)

    Use when asked about executive changes, leadership transitions, C-suite appointments,
    CEO/CFO/CTO changes, or management departures.
    """
    neo4j = get_neo4j_service()
    if not neo4j:
        return {
            "error": "Knowledge graph not available",
            "message": "Neo4j service is not connected",
        }

    try:
        if ticker:
            ticker = ticker.upper()
            query = """
                MATCH (o:Organization {ticker: $ticker})-[:HAS_EXECUTIVE_EVENT]->(e:ExecutiveEvent)
                OPTIONAL MATCH (p:Person)-[:INVOLVED_IN]->(e)
                RETURN e.event_type as event_type,
                       e.person_name as person_name,
                       e.title as title,
                       e.effective_date as effective_date,
                       e.reason as reason,
                       e.filing_date as filing_date,
                       o.name as company_name,
                       o.ticker as ticker,
                       collect(DISTINCT p.name) as involved_persons
                ORDER BY e.filing_date DESC
                LIMIT $limit
            """
            results = neo4j.execute_read(query, {"ticker": ticker, "limit": limit})
        else:
            query = """
                MATCH (o:Organization)-[:HAS_EXECUTIVE_EVENT]->(e:ExecutiveEvent)
                OPTIONAL MATCH (p:Person)-[:INVOLVED_IN]->(e)
                RETURN e.event_type as event_type,
                       e.person_name as person_name,
                       e.title as title,
                       e.effective_date as effective_date,
                       e.reason as reason,
                       e.filing_date as filing_date,
                       o.name as company_name,
                       o.ticker as ticker,
                       collect(DISTINCT p.name) as involved_persons
                ORDER BY e.filing_date DESC
                LIMIT $limit
            """
            results = neo4j.execute_read(query, {"limit": limit})

        # Get total count
        count_query = (
            """
            MATCH (o:Organization)-[:HAS_EXECUTIVE_EVENT]->(e:ExecutiveEvent)
            """
            + (f"WHERE o.ticker = '{ticker}'" if ticker else "")
            + """
            RETURN count(e) as total
        """
        )
        count_result = neo4j.execute_read(
            count_query.replace(f"'{ticker}'", "$ticker") if ticker else count_query,
            {"ticker": ticker} if ticker else {},
        )
        total = count_result[0]["total"] if count_result else 0

        return {
            "events": results,
            "count": len(results),
            "total_in_database": total,
            "ticker": ticker,
            "message": f"Found {len(results)} executive events"
            + (f" for {ticker}" if ticker else ""),
        }
    except Exception as e:
        return {"error": str(e), "events": []}


@tool
def get_vulnerabilities(
    ticker: Optional[str] = None, severity: Optional[str] = None, limit: int = 10
) -> dict:
    """Get CVE vulnerabilities associated with companies.

    Args:
        ticker: Stock ticker to get vulnerabilities for a specific company (e.g., CRWD, PANW)
        severity: Filter by severity level (CRITICAL, HIGH, MEDIUM, LOW)
        limit: Maximum vulnerabilities to return (default: 10)

    Use when asked about security vulnerabilities, CVEs, security issues, or security risks
    affecting a company's products.
    """
    neo4j = get_neo4j_service()
    if not neo4j:
        return {
            "error": "Knowledge graph not available",
            "message": "Neo4j service is not connected",
        }

    try:
        params = {"limit": limit}
        where_clauses = []

        if ticker:
            ticker = ticker.upper()
            params["ticker"] = ticker
            where_clauses.append("o.ticker = $ticker")

        if severity:
            params["severity"] = severity.upper()
            where_clauses.append("v.severity = $severity")

        where_clause = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        query = f"""
            MATCH (o:Organization)-[:HAS_VULNERABILITY]->(v:Vulnerability)
            {where_clause}
            RETURN v.cve_id as cve_id,
                   v.description as description,
                   v.severity as severity,
                   v.published as published_date,
                   v.vendor as vendor,
                   o.name as company_name,
                   o.ticker as ticker
            ORDER BY
                CASE v.severity
                    WHEN 'CRITICAL' THEN 1
                    WHEN 'HIGH' THEN 2
                    WHEN 'MEDIUM' THEN 3
                    WHEN 'LOW' THEN 4
                    ELSE 5
                END,
                v.published DESC
            LIMIT $limit
        """
        results = neo4j.execute_read(query, params)

        # Get severity breakdown
        breakdown_query = (
            """
            MATCH (o:Organization)-[:HAS_VULNERABILITY]->(v:Vulnerability)
            """
            + (f"WHERE o.ticker = $ticker" if ticker else "")
            + """
            RETURN v.severity as severity, count(*) as count
            ORDER BY count DESC
        """
        )
        breakdown = neo4j.execute_read(
            breakdown_query, {"ticker": ticker} if ticker else {}
        )
        severity_counts = {r["severity"]: r["count"] for r in breakdown}

        return {
            "vulnerabilities": results,
            "count": len(results),
            "severity_breakdown": severity_counts,
            "ticker": ticker,
            "message": f"Found {len(results)} vulnerabilities"
            + (f" for {ticker}" if ticker else ""),
        }
    except Exception as e:
        return {"error": str(e), "vulnerabilities": []}


# =============================================================================
# RAG Tools
# =============================================================================


@tool
def search_documents(query: str, ticker: Optional[str] = None, limit: int = 5) -> dict:
    """Search indexed SEC filings and documents using semantic similarity.

    Args:
        query: Natural language query to search for (e.g., "cloud security revenue growth")
        ticker: Optional ticker to limit search to specific company
        limit: Number of relevant passages to return (default: 5)

    Use this tool when asked about specific information from SEC filings, 10-K reports,
    10-Q reports, or earnings transcripts. Returns relevant text passages with sources.
    This is different from query_knowledge_graph - use this for full-text semantic search.
    """
    rag = get_rag_service()
    if not rag:
        return {
            "error": "RAG service not available",
            "message": "Document search is not connected",
        }

    try:
        ticker = ticker.upper() if ticker else None
        results = rag.search(query, ticker=ticker, limit=limit)

        if not results:
            return {
                "query": query,
                "ticker": ticker,
                "results": [],
                "message": "No matching documents found. Try a different query or check if documents have been indexed.",
            }

        return {
            "query": query,
            "ticker": ticker,
            "results": [
                {
                    "content": r["content"],
                    "source": r["metadata"].get("source", "Unknown"),
                    "ticker": r["metadata"].get("ticker"),
                    "document_type": r["metadata"].get("document_type"),
                    "chunk_index": r["metadata"].get("chunk_index"),
                    "similarity_score": r.get("score"),
                }
                for r in results
            ],
            "count": len(results),
        }
    except Exception as e:
        return {"error": str(e)}


@tool
def get_document_context(query: str, ticker: Optional[str] = None) -> dict:
    """Get formatted context from documents for answering a question.

    Args:
        query: The question to find context for
        ticker: Optional ticker to limit to specific company

    Returns formatted text context suitable for answering questions.
    Use this before answering detailed questions about SEC filings or earnings.
    """
    rag = get_rag_service()
    if not rag:
        return {
            "error": "RAG service not available",
            "message": "Document context is not connected",
        }

    try:
        ticker = ticker.upper() if ticker else None
        context = rag.get_context_for_query(query, ticker=ticker)

        if not context or context == "No relevant context found.":
            return {
                "query": query,
                "ticker": ticker,
                "context": None,
                "message": "No relevant context found in indexed documents.",
            }

        return {
            "query": query,
            "ticker": ticker,
            "context": context,
            "message": "Use this context to answer the user's question accurately.",
        }
    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# Help Tool
# =============================================================================


@tool
def get_dashboard_help() -> dict:
    """Get information about CyberRisk dashboard features and capabilities.

    Returns list of features and tracked companies.
    Use when asked about what the dashboard can do or for general help.
    """
    return {
        "features": [
            {
                "name": "Data Collection",
                "description": "SEC filings (10-K, 10-Q, 8-K) and earnings transcripts",
            },
            {
                "name": "Price Forecast",
                "description": "Prophet and Chronos models for stock prediction",
            },
            {
                "name": "Sentiment Analysis",
                "description": "Document sentiment via AWS Comprehend",
            },
            {
                "name": "Company Growth",
                "description": "Employee counts and hiring trends from CoreSignal",
            },
            {
                "name": "Knowledge Graph",
                "description": "Entity relationships from company documents",
            },
            {
                "name": "AI Chat",
                "description": "This assistant - ask questions about any company",
            },
        ],
        "tracked_companies": [
            "CRWD (CrowdStrike)",
            "PANW (Palo Alto Networks)",
            "ZS (Zscaler)",
            "FTNT (Fortinet)",
            "OKTA (Okta)",
            "NET (Cloudflare)",
            "S (SentinelOne)",
            "CYBR (CyberArk)",
            "TENB (Tenable)",
            "RPD (Rapid7)",
        ],
    }


# =============================================================================
# Tool Collection
# =============================================================================


def get_all_tools():
    """Return all available tools for the LangChain agent."""
    return [
        list_companies,
        get_company_info,
        add_company,
        get_sentiment,
        get_forecast,
        get_growth_metrics,
        get_documents,
        query_knowledge_graph,
        get_patents,
        get_executive_events,
        get_vulnerabilities,
        search_documents,
        get_document_context,
        get_dashboard_help,
    ]
