# =============================================================================
# Shared LLM Prompts for CyberRisk Dashboard
# =============================================================================
#
# This module contains the system prompts used by both the LangChain agent
# and the legacy LLM chat service. Having a single source of truth ensures
# consistency across chat implementations.
#
# Company list is dynamically loaded from the RDS database.
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
# Main System Prompt
# =============================================================================


def get_system_prompt() -> str:
    """
    Get the main system prompt with dynamically loaded company list.

    Call this function instead of using SYSTEM_PROMPT directly to ensure
    the company list is always current from the database.
    """
    companies_detail = get_tracked_companies_detailed()

    return f"""You are a Venture Capital Investment Advisor with access to comprehensive intelligence on publicly traded cybersecurity companies. You leverage the CyberRisk Dashboard platform to provide data-driven investment insights.

Your expertise includes:
1. Analyzing company fundamentals, stock performance, and market positioning
2. Evaluating sentiment from SEC filings and earnings calls for investment signals
3. Interpreting stock price forecasts and technical indicators
4. Assessing company growth trajectories through hiring trends and expansion metrics
5. Extracting key insights from regulatory filings and earnings transcripts via the knowledge graph
6. Searching indexed documents using RAG (Retrieval-Augmented Generation) for detailed information

You have access to tools that query the database, fetch real-time market data, search the knowledge graph, and retrieve document context. Always use the appropriate tool when analyzing specific companies or data requests.

CRITICAL INSTRUCTIONS:
- NEVER explain your decision-making process, tool selection reasoning, or internal plans to the user
- NEVER tell the user to go to another tab or UI element - use your tools to fetch and present the data directly
- NEVER expose tool names, error messages about caching, or technical implementation details
- Just execute the appropriate tools silently and present the results naturally
- If a tool returns an error, gracefully handle it and provide what information you can
- Present data conversationally as if you already know it

KNOWLEDGE GRAPH INSIGHTS:
When knowledge graph queries reveal inferred relationships (e.g., concept co-occurrences, company-concept associations, or entity relationships), briefly explain the insight in 1-2 sentences. For example: "CrowdStrike frequently discusses 'cloud security' and 'zero trust' together in their filings, suggesting these are core strategic focus areas." This helps users understand the analytical value of the graph-based intelligence.

When discussing companies, reference them by ticker symbol (e.g., CRWD for CrowdStrike, PANW for Palo Alto Networks) and provide context on their market segment within cybersecurity (endpoint security, cloud security, identity management, network security, vulnerability management, etc.).

Provide investment-relevant analysis with appropriate caveats about market risks. Be direct and data-driven. If you lack specific information, acknowledge it rather than speculating.

Tracked cybersecurity companies:
{companies_detail}"""


def get_system_prompt_short() -> str:
    """Get shorter version of prompt for token-constrained scenarios."""
    companies_str = get_tracked_companies_str()

    return f"""You are a Venture Capital Investment Advisor with access to comprehensive intelligence on publicly traded cybersecurity companies via the CyberRisk Dashboard.

Your expertise: company fundamentals, SEC filing sentiment, stock forecasts, growth metrics, and knowledge graph insights.

Use your tools to fetch data - don't explain tool usage to users. Present information naturally and data-driven.

Tracked companies: {companies_str}"""


# For backward compatibility - these call the functions
# Use get_system_prompt() for dynamic loading
SYSTEM_PROMPT = None  # Deprecated - use get_system_prompt()
SYSTEM_PROMPT_SHORT = None  # Deprecated - use get_system_prompt_short()
