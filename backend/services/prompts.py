# =============================================================================
# Shared LLM Prompts for CyberRisk Dashboard
# =============================================================================
#
# ARCHITECTURE NOTE (2026-01-28):
# Anti-hallucination is now enforced by ARCHITECTURE, not prompts.
#
# The LangChain agent uses:
# 1. Router node - classifies queries and forces tool calls
# 2. Grounded Synthesizer - can only use tool output, no external knowledge
# 3. Hallucination Grader - validates responses against tool output
#
# This file provides MINIMAL prompts that describe roles, not guards.
# The old "CRITICAL", "ABSOLUTELY NO", "NEVER" instructions have been removed.
#
# =============================================================================

import logging

logger = logging.getLogger(__name__)

# Cached company list (refreshed on first use)
_cached_companies = None


def get_tracked_companies() -> list:
    """
    Get list of tracked companies from RDS database.

    Returns list of dicts with ticker, company_name, and sector.
    Falls back to taxonomy if database unavailable.
    """
    global _cached_companies

    if _cached_companies is not None:
        return _cached_companies

    try:
        from services.database_service import db_service

        companies = db_service.get_all_companies()
        if companies:
            _cached_companies = companies
            logger.info(f"Loaded {len(companies)} companies from RDS for prompt")
            return companies
    except Exception as e:
        logger.warning(f"Could not load companies from RDS: {e}")

    # Fallback to taxonomy
    try:
        from data.taxonomy import TRACKED_COMPANIES

        _cached_companies = [
            {
                "ticker": ticker,
                "company_name": info["name"],
                "sector": info.get("cyber_sector", "Cybersecurity")
                .replace("_", " ")
                .title(),
            }
            for ticker, info in TRACKED_COMPANIES.items()
        ]
        logger.info(f"Loaded {len(_cached_companies)} companies from taxonomy fallback")
        return _cached_companies
    except Exception as e:
        logger.error(f"Could not load companies from taxonomy: {e}")
        return []


def refresh_company_cache():
    """Force refresh of company cache from database."""
    global _cached_companies
    _cached_companies = None
    return get_tracked_companies()


def get_tracked_companies_str() -> str:
    """Get formatted string of tracked companies for the prompt."""
    companies = get_tracked_companies()
    return ", ".join(f"{c['ticker']} ({c['company_name']})" for c in companies)


def get_tracked_companies_detailed() -> str:
    """Get detailed list of tracked companies with market segments."""
    companies = get_tracked_companies()
    lines = []
    for c in companies:
        sector = c.get("sector", "Cybersecurity")
        lines.append(f"  - {c['ticker']}: {c['company_name']} - {sector}")
    return "\n".join(lines) if lines else "  (No companies loaded)"


# =============================================================================
# Streamlined System Prompt (Harness handles the Guards)
# =============================================================================


def get_system_prompt() -> str:
    """
    Get the streamlined system prompt.

    NOTE: This prompt is MINIMAL because anti-hallucination is enforced
    by the agent architecture, not by prompt instructions.

    The Router forces tool calls for entity queries.
    The Synthesizer can only use tool output.
    The Grader catches any remaining hallucinations.
    """
    companies_detail = get_tracked_companies_detailed()

    return f"""You are the CyberRisk Dashboard Interface.

Your Role: Translate user questions into correct Tool Calls.

AVAILABLE DATA SCOPE:
- Company Financials & Growth (Source: Database)
- SEC Filings & Earnings Transcripts (Source: RAG)
- Regulatory Compliance (Source: Knowledge Graph)
- Market Intelligence (Source: GDS Analytics)

TRACKED ENTITIES:
{companies_detail}

INSTRUCTIONS:
1. If the user asks for data, invoke the relevant tool
2. Do not answer from memory
3. If no relevant tool exists for the request, inform the user

KNOWLEDGE GRAPH INSIGHTS:
When graph queries reveal inferred relationships, briefly explain the insight.
Example: "CrowdStrike frequently discusses 'cloud security' and 'zero trust' together,
suggesting these are core strategic focus areas."

REGULATORY CONTEXT:
Key agencies: SEC, CISA, FTC, NIST, DOJ
SEC Cybersecurity Disclosure Rule (effective 2023-12-18) requires 4-day disclosure
of material cyber incidents (8-K Item 1.05)."""


def get_system_prompt_short() -> str:
    """Get shorter version of prompt for token-constrained scenarios."""
    companies_str = get_tracked_companies_str()

    return f"""You are the CyberRisk Dashboard assistant.

Your job: Call tools to fetch data, then present results.
Do not answer from memory - use tools.

Tracked companies: {companies_str}"""


def get_tool_agent_prompt() -> str:
    """
    Prompt for the tool execution agent.

    This agent's job is ONLY to call tools and return results.
    It should not synthesize or explain - that's the Synthesizer's job.
    """
    return """You are a data retrieval agent.

Your job is to call the appropriate tools to get data.

RULES:
1. Call tools to fetch data - don't explain or summarize
2. If multiple tools might help, call the most relevant one
3. Return tool results directly - another agent will synthesize
4. Do not make up data - only return what tools provide

Available data types:
- Company info (get_company_info, list_companies)
- Stock forecasts (get_forecast)
- Sentiment analysis (get_sentiment)
- Growth metrics (get_growth_metrics)
- Knowledge graph (query_knowledge_graph)
- Document search (search_documents, get_document_context)
- Regulatory alerts (get_regulatory_alerts, get_company_compliance_status)
- Competitive intelligence (get_market_segments, get_market_leaders, get_similar_companies)"""


def get_synthesis_prompt() -> str:
    """
    Prompt for the grounded synthesizer.

    This prompt RESTRICTS the model to ONLY use provided tool output.
    Temperature=0 ensures deterministic, grounded output.
    """
    return """You are a Data Reporter for the CyberRisk Dashboard.

CONSTRAINT: Answer ONLY based on the DATA_CONTEXT provided.
You have NO external knowledge.

Rules:
1. If DATA_CONTEXT contains data, summarize it clearly
2. If DATA_CONTEXT contains NO_DATA=True, say "I don't have [data type] available"
3. If DATA_CONTEXT contains ERROR=True, say "I wasn't able to retrieve that information"
4. Present data naturally, as if reporting from a database query
5. Do not invent numbers, dates, names, or facts not in DATA_CONTEXT

DATA_CONTEXT:
{tool_output}

USER_QUERY:
{query}"""


def get_router_prompt() -> str:
    """
    Prompt for the query router.

    The router has NO KNOWLEDGE - it can only classify queries.
    Uses cheap Haiku model to prevent hallucination during routing.
    """
    return """You are a Query Router.

Your ONLY job is to classify queries and extract entities.
You have NO knowledge about companies, markets, or regulations.
You CANNOT answer questions - only categorize them.

Categories:
- "financial": Stock prices, forecasts, sentiment, growth, company info
- "regulatory": Regulations, compliance, alerts, SEC/CISA/FTC rules
- "graph": Relationships, competitors, market segments, similar companies
- "document_search": SEC filings, 10-K, 10-Q, earnings transcripts
- "general": Greetings, help requests, questions not requiring data

Extract ticker symbols ONLY if explicitly mentioned.
Set requires_tool=False ONLY for greetings like "hi", "hello", "help"."""


def get_hallucination_grader_prompt() -> str:
    """
    Prompt for the hallucination grader.

    This is the "Reflexion" loop - validates that responses are grounded.
    """
    return """You are a fact-checker.

Determine if the RESPONSE contains ONLY facts present in the DATA.

Mark is_grounded=False if the RESPONSE contains:
- Numbers, dates, or names not in DATA
- Claims about events not mentioned in DATA
- Speculation or analysis beyond what DATA supports

Be strict - if in doubt, mark as not grounded."""


# =============================================================================
# Backward Compatibility
# =============================================================================

# For backward compatibility - these call the functions
# Use get_system_prompt() for dynamic loading
SYSTEM_PROMPT = None  # Deprecated - use get_system_prompt()
SYSTEM_PROMPT_SHORT = None  # Deprecated - use get_system_prompt_short()
