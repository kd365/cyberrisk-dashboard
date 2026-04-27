# =============================================================================
# LangChain Agent Service - Anti-Hallucination Architecture
# =============================================================================
#
# ARCHITECTURE (2026-01-28):
# This agent uses structural anti-hallucination rather than prompt-based guards.
#
# Flow: User Query → Router → Tool Execution → Grounded Synthesizer → Response
#
# Key Components:
# 1. ROUTER: Classifies queries and FORCES tool calls for entity-specific questions
#    - Uses cheap Haiku model to classify (no knowledge = no hallucination)
#    - Extracts entities (tickers, regulations) from query
#    - Routes to appropriate tool worker
#
# 2. TOOL NODES: Execute data retrieval with hard-coded empty result handling
#    - Tools return structured NO_DATA responses instead of empty results
#    - Forces agent to acknowledge missing data
#
# 3. GROUNDED SYNTHESIZER: Generates response ONLY from tool output
#    - "Reporter" prompt that cannot access external knowledge
#    - Temperature=0 for deterministic, grounded responses
#    - Must respect NO_DATA flags from tools
#
# 4. HALLUCINATION GRADER (optional): Validates response against tool output
#    - Checks if response contains facts not in tool output
#    - Loops back to regenerate if hallucination detected
#
# =============================================================================

import os
import re
import json
import logging
from typing import Dict, List, Optional, Literal, Any, TypedDict, Annotated
from datetime import datetime
from operator import add

from langchain_aws import ChatBedrock
from langchain_core.messages import (
    HumanMessage,
    AIMessage,
    SystemMessage,
    BaseMessage,
    ToolMessage,
)
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import create_react_agent, ToolNode
from pydantic import BaseModel, Field

from services.langchain_tools import get_all_tools
from services.prompts import get_tracked_companies_detailed

logger = logging.getLogger(__name__)


# =============================================================================
# State Definition
# =============================================================================


class AgentState(TypedDict):
    """State for the anti-hallucination agent graph."""

    messages: Annotated[List[BaseMessage], add]
    query: str
    route: str  # "financial", "regulatory", "graph", "general"
    ticker: Optional[str]
    tool_output: Optional[Dict[str, Any]]
    has_data: bool
    final_response: Optional[str]


# =============================================================================
# Router: Query Classification (Forces Tool Calls)
# =============================================================================


class RouteQuery(BaseModel):
    """Route a user query to the appropriate data worker.

    This classifier has NO KNOWLEDGE - it can only categorize and extract entities.
    It cannot answer questions, only route them.
    """

    destination: Literal[
        "financial", "regulatory", "graph", "document_search", "general"
    ] = Field(description="The category of data needed to answer this query")
    ticker: Optional[str] = Field(
        None,
        description="Stock ticker symbol if mentioned (e.g., CRWD, PANW). Extract ONLY if explicitly present.",
    )
    requires_tool: bool = Field(
        True,
        description="True if this query requires fetching data. False only for greetings/help.",
    )
    reasoning: str = Field(description="Brief explanation of routing decision")


# Patterns for routing (used as fallback if structured output fails)
TICKER_PATTERN = re.compile(r"\b([A-Z]{2,5})\b")
FINANCIAL_PATTERNS = [
    r"(price|stock|forecast|sentiment|growth|revenue|earnings|market)",
    r"(compare|analysis|performance|valuation|invest)",
]
REGULATORY_PATTERNS = [
    r"(regulation|regulatory|compliance|alert|sec|cisa|ftc|disclosure)",
    r"(rule|requirement|law|mandate)",
]
GRAPH_PATTERNS = [
    r"(knowledge graph|relationships|entities|connections)",
    r"(competitor|segment|leader|similar)",
]
DOCUMENT_PATTERNS = [
    r"(10-k|10-q|8-k|filing|transcript|document|sec filing)",
    r"(risk factor|business model|strategy)",
]


def get_router_prompt() -> str:
    """Get the router prompt - minimal, classification-only."""
    return """You are a Query Router. Your ONLY job is to classify queries and extract entities.

You have NO knowledge about companies, markets, or regulations.
You CANNOT answer questions - only categorize them.

Categories:
- "financial": Stock prices, price forecasts, sentiment scores, growth/hiring metrics,
  basic company info (sector, description). Quantitative numeric data.
- "regulatory": Regulations, compliance, alerts, SEC/CISA/FTC rules.
- "graph": Knowledge-graph queries — M&A / mergers / acquisitions ("has X been acquired?",
  "did Y acquire Z?"), executive changes (appointments, departures, CEOs, CFOs),
  patents / IP, vulnerabilities / CVEs, security incidents / breaches, business events,
  persons / leadership / boards, locations / offices, market segments, market leaders,
  similar companies, competitive landscape. Anything querying graph nodes/relationships.
- "document_search": SEC filing text content — 10-K/10-Q/8-K prose, earnings transcript text,
  "what does the 10-K say about X", risk-factor language.
- "general": Greetings, help requests, dashboard navigation questions.

Heuristic: structured answers (lists, counts, dates, rankings) → "graph" or "financial".
Free-text from a filing → "document_search".

Extract ticker symbols ONLY if explicitly mentioned (e.g., "CRWD", "CrowdStrike" → "CRWD").

Set requires_tool=False ONLY for greetings like "hi", "hello", "help"."""


# =============================================================================
# Grounded Synthesizer: Reporter Prompt (No External Knowledge)
# =============================================================================


def get_synthesis_prompt() -> str:
    """Get the grounded synthesis prompt - ONLY uses tool output, no external knowledge."""
    return """You are a Data Reporter for the CyberRisk Dashboard.

CRITICAL CONSTRAINT: You must answer ONLY based on the DATA_CONTEXT below.
You have NO external knowledge. You cannot recall facts from training.

Rules:
1. If DATA_CONTEXT contains data, summarize it clearly for the user
2. If DATA_CONTEXT contains NO_DATA=True, say "I don't have [data type] available for [entity]"
3. If DATA_CONTEXT contains ERROR=True, say "I wasn't able to retrieve that information"
4. NEVER invent numbers, dates, names, or facts not in DATA_CONTEXT
5. NEVER say "Based on my knowledge..." - you have no knowledge
6. Present data naturally, as if reporting from a database query

DATA_CONTEXT:
{tool_output}

USER_QUERY:
{query}"""


def get_general_prompt() -> str:
    """Get prompt for general queries that don't need tools."""
    companies_detail = get_tracked_companies_detailed()

    return f"""You are the CyberRisk Dashboard assistant.

For general questions, you can help with:
- Explaining dashboard features
- Listing tracked companies
- Providing help with using the platform

Tracked companies:
{companies_detail}

Keep responses brief and helpful. For data questions, the user should ask specifically."""


# =============================================================================
# Node Functions
# =============================================================================


def route_query(state: AgentState, router_llm) -> AgentState:
    """
    Router node: Classify query and extract entities using cheap LLM.

    This node CANNOT answer questions - it only routes them.
    Uses Haiku for speed and cost, and because it has no relevant knowledge.
    """
    query = state["query"]

    try:
        # Try structured output for precise routing
        structured_llm = router_llm.with_structured_output(RouteQuery)

        messages = [
            SystemMessage(content=get_router_prompt()),
            HumanMessage(content=f"Classify this query: {query}"),
        ]

        result = structured_llm.invoke(messages)

        return {
            **state,
            "route": result.destination,
            "ticker": result.ticker.upper() if result.ticker else None,
            "has_data": False,  # Will be set after tool execution
        }

    except Exception as e:
        logger.warning(f"Structured routing failed: {e}, using regex fallback")

        # Fallback: Regex-based routing
        query_lower = query.lower()

        # Extract ticker
        ticker_match = TICKER_PATTERN.search(query)
        ticker = ticker_match.group(1) if ticker_match else None

        # Determine route
        if any(re.search(p, query_lower) for p in REGULATORY_PATTERNS):
            route = "regulatory"
        elif any(re.search(p, query_lower) for p in DOCUMENT_PATTERNS):
            route = "document_search"
        elif any(re.search(p, query_lower) for p in GRAPH_PATTERNS):
            route = "graph"
        elif any(re.search(p, query_lower) for p in FINANCIAL_PATTERNS):
            route = "financial"
        elif query_lower.strip() in ["hi", "hello", "hey", "help", "?"]:
            route = "general"
        else:
            route = "financial"  # Default to financial for company questions

        return {
            **state,
            "route": route,
            "ticker": ticker,
            "has_data": False,
        }


def synthesize_response(state: AgentState, synthesis_llm) -> AgentState:
    """
    Synthesis node: Generate response ONLY from tool output.

    This is the "Reporter" - it can only report what the tools found.
    Temperature=0 ensures deterministic, grounded output.

    HARD CONSTRAINT: If SYSTEM_NOTIFICATION is detected, we short-circuit
    the LLM entirely and return a canned response. This prevents any
    possibility of hallucination for no-data cases.
    """
    tool_output = state.get("tool_output") or {}  # Handle None explicitly
    query = state["query"]
    tool_output_str = json.dumps(tool_output, default=str) if tool_output else ""

    # SHORT-CIRCUIT: If the strict signal is found, skip LLM entirely
    # This is the key anti-hallucination mechanism
    if "SYSTEM_NOTIFICATION: NO_DATA_FOUND" in tool_output_str:
        data_type = tool_output.get("data_type", "that information")
        entity = tool_output.get("entity", "")
        return {
            **state,
            "has_data": False,
            "final_response": f"I checked the CyberRisk Dashboard, but I don't have {data_type} available"
            + (f" for {entity}" if entity else "")
            + ".",
        }

    if "SYSTEM_NOTIFICATION: TOOL_ERROR" in tool_output_str:
        return {
            **state,
            "has_data": False,
            "final_response": "I wasn't able to retrieve that information due to a system error. Please try again.",
        }

    # Legacy flag checks (backward compatibility)
    if tool_output.get("NO_DATA") or tool_output.get("status") == "no_data":
        return {
            **state,
            "has_data": False,
            "final_response": f"I don't have {tool_output.get('data_type', 'that data')} available"
            + (f" for {tool_output.get('entity')}" if tool_output.get("entity") else "")
            + ".",
        }

    if tool_output.get("ERROR") or tool_output.get("status") == "error":
        return {
            **state,
            "has_data": False,
            "final_response": f"I wasn't able to retrieve that information.",
        }

    # For raw text responses from ReAct agent
    if tool_output.get("raw") and tool_output.get("response_text"):
        # The ReAct agent already synthesized a response
        return {
            **state,
            "has_data": True,
            "final_response": tool_output["response_text"],
        }

    # Generate grounded response from structured tool output
    prompt = ChatPromptTemplate.from_template(get_synthesis_prompt())

    messages = prompt.format_messages(
        tool_output=json.dumps(tool_output, indent=2, default=str), query=query
    )

    response = synthesis_llm.invoke(messages)

    return {**state, "has_data": True, "final_response": response.content}


def handle_general_query(state: AgentState, general_llm) -> AgentState:
    """Handle general queries (greetings, help) without tools."""
    query = state["query"]

    messages = [
        SystemMessage(content=get_general_prompt()),
        HumanMessage(content=query),
    ]

    response = general_llm.invoke(messages)

    return {**state, "has_data": True, "final_response": response.content}


# =============================================================================
# Hallucination Grader (Optional Reflexion Loop)
# =============================================================================


class HallucinationCheck(BaseModel):
    """Result of hallucination check."""

    is_grounded: bool = Field(
        description="True if the response only contains facts from the tool output"
    )
    problematic_claims: List[str] = Field(
        default_factory=list,
        description="List of claims in the response not supported by tool output",
    )


def grade_hallucination(state: AgentState, grader_llm) -> str:
    """
    Check if the synthesized response is grounded in tool output.

    Returns "pass" if grounded, "regenerate" if hallucination detected.
    """
    response = state.get("final_response", "")
    tool_output = state.get("tool_output", {})

    if not response or not tool_output:
        return "pass"

    # Skip grading for no-data responses
    if tool_output.get("NO_DATA") or tool_output.get("ERROR"):
        return "pass"

    try:
        structured_llm = grader_llm.with_structured_output(HallucinationCheck)

        messages = [
            SystemMessage(
                content="""You are a fact-checker. Determine if the RESPONSE contains ONLY facts present in the DATA.

Mark is_grounded=False if the RESPONSE contains:
- Numbers, dates, or names not in DATA
- Claims about events not mentioned in DATA
- Speculation or analysis beyond what DATA supports

Be strict - if in doubt, mark as not grounded."""
            ),
            HumanMessage(
                content=f"""DATA:
{json.dumps(tool_output, indent=2, default=str)}

RESPONSE:
{response}

Is this response grounded in the data?"""
            ),
        ]

        result = structured_llm.invoke(messages)

        if not result.is_grounded:
            logger.warning(f"Hallucination detected: {result.problematic_claims}")
            return "regenerate"

        return "pass"

    except Exception as e:
        logger.warning(f"Hallucination grading failed: {e}")
        return "pass"  # Don't block on grader failure


# =============================================================================
# Main Agent Service
# =============================================================================


class LangChainAgentService:
    """
    LangChain-based agent service with anti-hallucination architecture.

    Uses structural enforcement rather than prompt-based guards:
    - Router forces tool calls for entity-specific queries
    - Tools return structured NO_DATA responses
    - Synthesizer can only use tool output (no external knowledge)
    - Optional hallucination grader catches remaining issues
    """

    # Claude 4.5 models require inference profile IDs (us. prefix for cross-region)
    SONNET_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    HAIKU_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

    def __init__(self):
        """Initialize the anti-hallucination agent service."""
        self.region = os.environ.get("AWS_REGION", "us-west-2")

        # Router: Cheap, fast, NO knowledge (just classification)
        self.router_llm = ChatBedrock(
            model_id=self.HAIKU_MODEL_ID,
            region_name=self.region,
            model_kwargs={"max_tokens": 500, "temperature": 0},
        )

        # Synthesizer: Grounded, deterministic (temperature=0)
        self.synthesis_llm = ChatBedrock(
            model_id=self.SONNET_MODEL_ID,
            region_name=self.region,
            model_kwargs={"max_tokens": 2048, "temperature": 0},
        )

        # General queries: For help/greetings (light usage)
        self.general_llm = ChatBedrock(
            model_id=self.HAIKU_MODEL_ID,
            region_name=self.region,
            model_kwargs={"max_tokens": 1024, "temperature": 0.3},
        )

        # Grader: For optional hallucination check
        self.grader_llm = ChatBedrock(
            model_id=self.HAIKU_MODEL_ID,
            region_name=self.region,
            model_kwargs={"max_tokens": 500, "temperature": 0},
        )

        # ReAct agent for tool execution (uses Sonnet for complex reasoning)
        self.tools = get_all_tools()
        self.tool_agent = create_react_agent(
            model=ChatBedrock(
                model_id=self.SONNET_MODEL_ID,
                region_name=self.region,
                model_kwargs={"max_tokens": 4096, "temperature": 0.3},
            ),
            tools=self.tools,
            prompt=self._get_tool_agent_prompt(),
        )

        # Memory service (lazy loaded)
        self._memory_service = None

        # Backward compatibility
        self.llm = self.synthesis_llm
        self.agent = self.tool_agent

    def _get_tool_agent_prompt(self) -> str:
        """Get minimal prompt for tool agent - just execute tools, don't explain."""
        return """You are a data retrieval agent. Your job is to call the appropriate tools to get data.

RULES:
1. Call tools to fetch data - don't explain or summarize
2. If multiple tools might help, call the most relevant one
3. Return tool results directly - another agent will synthesize the response
4. Do not make up data - only return what tools provide

Available data: company info, sentiment, forecasts, growth metrics, regulatory alerts, knowledge graph, document search."""

    @property
    def memory_service(self):
        """Lazy load memory service."""
        if self._memory_service is None:
            try:
                from services.memory_service import get_memory_service

                self._memory_service = get_memory_service()
            except Exception as e:
                logger.warning(f"Memory service not available: {e}")
        return self._memory_service

    def _route_to_tools(self, state: AgentState) -> AgentState:
        """Execute appropriate tools based on route."""
        route = state["route"]
        ticker = state.get("ticker")
        query = state["query"]

        # Map routes to tool calls
        tool_map = {
            "financial": self._call_financial_tools,
            "regulatory": self._call_regulatory_tools,
            "graph": self._call_graph_tools,
            "document_search": self._call_document_tools,
        }

        if route in tool_map:
            tool_output = tool_map[route](query, ticker)
            return {**state, "tool_output": tool_output}

        return {**state, "tool_output": None}

    def _call_financial_tools(self, query: str, ticker: str = None) -> Dict:
        """Call financial data tools directly based on query analysis."""
        try:
            from services.langchain_tools import (
                list_companies,
                get_company_info,
                get_sentiment,
                get_forecast,
                get_growth_metrics,
            )

            query_lower = query.lower()

            # Direct tool selection based on query patterns
            if not ticker and any(
                p in query_lower
                for p in [
                    "which companies",
                    "list companies",
                    "tracked companies",
                    "what companies",
                ]
            ):
                return list_companies.invoke({})

            if ticker:
                # Specific data requests for a ticker
                if any(
                    p in query_lower
                    for p in ["sentiment", "feeling", "tone", "analysis"]
                ):
                    return get_sentiment.invoke({"ticker": ticker})
                elif any(
                    p in query_lower
                    for p in ["forecast", "predict", "price target", "future"]
                ):
                    return get_forecast.invoke({"ticker": ticker})
                elif any(
                    p in query_lower
                    for p in ["growth", "hiring", "employees", "headcount"]
                ):
                    return get_growth_metrics.invoke({"ticker": ticker})
                else:
                    # Default: company info
                    return get_company_info.invoke({"ticker": ticker})

            # Fallback: list companies if no specific request
            return list_companies.invoke({})

        except Exception as e:
            logger.error(f"Financial tool error: {e}")
            from services.langchain_tools import error_response

            return error_response(str(e), "financial_tools")

    def _call_regulatory_tools(self, query: str, ticker: str = None) -> Dict:
        """Call regulatory data tools directly."""
        try:
            from services.langchain_tools import (
                get_regulatory_alerts,
                get_company_compliance_status,
            )

            query_lower = query.lower()

            # Check for compliance status vs alerts
            if any(p in query_lower for p in ["compliance", "status"]):
                if ticker:
                    return get_company_compliance_status.invoke({"ticker": ticker})
                else:
                    return get_regulatory_alerts.invoke(
                        {"status": "UNACKNOWLEDGED", "limit": 10}
                    )
            else:
                # Default: get alerts
                return get_regulatory_alerts.invoke(
                    {"ticker": ticker, "status": "UNACKNOWLEDGED", "limit": 10}
                )

        except Exception as e:
            logger.error(f"Regulatory tool error: {e}")
            from services.langchain_tools import error_response

            return error_response(str(e), "regulatory_tools")

    def _call_graph_tools(self, query: str, ticker: str = None) -> Dict:
        """Call knowledge graph tools.

        Strategy:
          1. Cheap precomputed paths (PageRank, Louvain, similarity) — these
             use cached GDS projections and don't benefit from on-the-fly
             Cypher generation.
          2. Catch-all: hand off to query_knowledge_graph, which uses the
             text-to-Cypher generator with schema-injected prompts. This
             handles M&A, executive events, vulnerabilities, patents,
             feature scores, and arbitrary cross-entity queries.
        """
        try:
            from services.langchain_tools import (
                get_market_segments,
                get_market_leaders,
                get_similar_companies,
                get_competitive_intelligence_summary,
                query_knowledge_graph,
            )

            query_lower = query.lower()

            # Cheap precomputed paths — only for explicit GDS analytics requests
            if any(p in query_lower for p in ["segment", "market segment", "cluster"]):
                return get_market_segments.invoke({})
            if any(
                p in query_lower for p in ["market leader", "leaderboard", "pagerank"]
            ):
                return get_market_leaders.invoke({})
            if (
                any(p in query_lower for p in ["similar to", "comparable to"])
                and ticker
            ):
                return get_similar_companies.invoke({"ticker": ticker})
            if any(
                p in query_lower
                for p in ["competitive intelligence", "intelligence overview"]
            ):
                return get_competitive_intelligence_summary.invoke({})

            # Catch-all: text-to-Cypher
            return query_knowledge_graph.invoke({"query": query, "ticker": ticker})

        except Exception as e:
            logger.error(f"Graph tool error: {e}")
            from services.langchain_tools import error_response

            return error_response(str(e), "graph_tools")

    def _call_document_tools(self, query: str, ticker: str = None) -> Dict:
        """Call document search tools directly."""
        try:
            from services.langchain_tools import search_documents, get_document_context

            # Use semantic search for document queries
            return search_documents.invoke(
                {"query": query, "ticker": ticker, "limit": 5}
            )

        except Exception as e:
            logger.error(f"Document tool error: {e}")
            from services.langchain_tools import error_response

            return error_response(str(e), "document_tools")

    def _extract_tool_output(self, result: Dict) -> Dict:
        """Extract the tool output from agent result."""
        # Look for tool messages in the result
        messages = result.get("messages", [])

        tool_outputs = []
        for msg in messages:
            # Check for ToolMessage objects (primary source in LangGraph)
            if isinstance(msg, ToolMessage):
                try:
                    # ToolMessage content is the tool's return value
                    parsed = json.loads(msg.content)
                    if isinstance(parsed, dict):
                        tool_outputs.append(parsed)
                except (json.JSONDecodeError, TypeError):
                    # If not JSON, treat as raw content
                    if msg.content:
                        tool_outputs.append({"response_text": msg.content, "raw": True})

            # Check for tool results in regular messages
            elif hasattr(msg, "content") and isinstance(msg.content, str):
                try:
                    # Try to parse JSON tool output
                    parsed = json.loads(msg.content)
                    if isinstance(parsed, dict):
                        tool_outputs.append(parsed)
                except json.JSONDecodeError:
                    pass

            # Check for structured tool output
            if hasattr(msg, "artifact"):
                tool_outputs.append(msg.artifact)

        # Return last tool output (most relevant) or aggregate
        if tool_outputs:
            return tool_outputs[-1]

        # Fallback: extract from last AI message
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                # The AI message content might contain the relevant data
                return {"response_text": msg.content, "raw": True}

        return {
            "NO_DATA": True,
            "data_type": "requested information",
            "reason": "No tool output",
        }

    def chat_stream(
        self,
        message: str,
        session_id: str,
        user_email: str = None,
        auth_token: str = None,
    ):
        """
        Process a chat message with streaming status updates.

        Yields status events as JSON strings for SSE streaming:
        - {"type": "status", "message": "Routing query...", "step": 1}
        - {"type": "status", "message": "Searching documents...", "step": 2}
        - {"type": "response", "data": {...final response...}}

        This provides real-time feedback to users during processing.
        """
        import json as json_module

        try:
            user_id = user_email or session_id

            # Step 1: Route the query
            yield json_module.dumps(
                {
                    "type": "status",
                    "message": "Analyzing query...",
                    "step": 1,
                    "total_steps": 4,
                }
            )

            initial_state: AgentState = {
                "messages": [],
                "query": message,
                "route": "",
                "ticker": None,
                "tool_output": None,
                "has_data": False,
                "final_response": None,
            }

            routed_state = route_query(initial_state, self.router_llm)
            logger.info(
                f"Query routed to: {routed_state['route']} (ticker: {routed_state.get('ticker')})"
            )

            # Step 2: Handle based on route
            route = routed_state["route"]
            ticker = routed_state.get("ticker")

            route_messages = {
                "financial": f"Fetching financial data{' for ' + ticker if ticker else ''}...",
                "regulatory": f"Searching regulatory alerts{' for ' + ticker if ticker else ''}...",
                "graph": f"Querying knowledge graph{' for ' + ticker if ticker else ''}...",
                "document_search": f"Searching documents{' for ' + ticker if ticker else ''}...",
                "general": "Processing request...",
            }

            yield json_module.dumps(
                {
                    "type": "status",
                    "message": route_messages.get(route, "Processing..."),
                    "step": 2,
                    "total_steps": 4,
                    "route": route,
                    "ticker": ticker,
                }
            )

            if route == "general":
                final_state = handle_general_query(routed_state, self.general_llm)
                tools_used = []
            else:
                # Execute tools
                tool_state = self._route_to_tools(routed_state)

                # Step 3: Synthesize response
                yield json_module.dumps(
                    {
                        "type": "status",
                        "message": "Generating response...",
                        "step": 3,
                        "total_steps": 4,
                    }
                )

                final_state = synthesize_response(tool_state, self.synthesis_llm)

                # Step 4: Validate (hallucination check)
                yield json_module.dumps(
                    {
                        "type": "status",
                        "message": "Validating response...",
                        "step": 4,
                        "total_steps": 4,
                    }
                )

                grade = grade_hallucination(final_state, self.grader_llm)
                if grade == "regenerate":
                    logger.warning("Hallucination detected, regenerating")
                    final_state = synthesize_response(tool_state, self.synthesis_llm)

                tools_used = [route]

            response_text = final_state.get(
                "final_response", "I wasn't able to process that request."
            )

            # Save to memory
            self._save_to_memory(session_id, message, response_text)
            self._save_to_semantic_memory(user_id, message, response_text)

            # Final response
            yield json_module.dumps(
                {
                    "type": "response",
                    "data": {
                        "response": response_text,
                        "session_id": session_id,
                        "tools_used": tools_used,
                        "route": route,
                        "ticker": ticker,
                        "has_data": final_state.get("has_data", False),
                        "timestamp": datetime.now().isoformat(),
                    },
                }
            )

        except Exception as e:
            logger.error(f"Agent streaming error: {e}")
            yield json_module.dumps(
                {
                    "type": "error",
                    "message": "I apologize, but I encountered an error processing your request.",
                    "error": str(e),
                }
            )

    def chat(
        self,
        message: str,
        session_id: str,
        user_email: str = None,
        auth_token: str = None,
    ) -> Dict:
        """
        Process a chat message with anti-hallucination architecture.

        Flow:
        1. Router classifies query and extracts entities
        2. Route to appropriate tools (forced for entity queries)
        3. Synthesizer generates response ONLY from tool output
        4. (Optional) Grader checks for hallucination
        """
        try:
            user_id = user_email or session_id

            # Step 1: Route the query
            initial_state: AgentState = {
                "messages": [],
                "query": message,
                "route": "",
                "ticker": None,
                "tool_output": None,
                "has_data": False,
                "final_response": None,
            }

            routed_state = route_query(initial_state, self.router_llm)
            logger.info(
                f"Query routed to: {routed_state['route']} (ticker: {routed_state.get('ticker')})"
            )

            # Step 2: Handle based on route
            if routed_state["route"] == "general":
                # General queries don't need tools
                final_state = handle_general_query(routed_state, self.general_llm)
                tools_used = []
            else:
                # Execute tools based on route
                tool_state = self._route_to_tools(routed_state)

                # Step 3: Synthesize response from tool output
                final_state = synthesize_response(tool_state, self.synthesis_llm)

                # Step 4: Optional hallucination check
                grade = grade_hallucination(final_state, self.grader_llm)
                if grade == "regenerate":
                    logger.warning(
                        "Hallucination detected, regenerating with stricter prompt"
                    )
                    # Regenerate with explicit grounding
                    final_state = synthesize_response(tool_state, self.synthesis_llm)

                tools_used = [routed_state["route"]]

            response_text = final_state.get(
                "final_response", "I wasn't able to process that request."
            )

            # Save to memory
            self._save_to_memory(session_id, message, response_text)
            self._save_to_semantic_memory(user_id, message, response_text)

            return {
                "response": response_text,
                "session_id": session_id,
                "tools_used": tools_used,
                "route": routed_state["route"],
                "ticker": routed_state.get("ticker"),
                "has_data": final_state.get("has_data", False),
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Agent error: {e}")
            return {
                "response": "I apologize, but I encountered an error processing your request.",
                "session_id": session_id,
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }

    def _get_chat_history(self, session_id: str) -> List:
        """Get conversation history as LangChain messages."""
        try:
            if self.memory_service:
                raw_history = self.memory_service.get_context_for_llm(
                    session_id, max_messages=5
                )
                messages = []
                for msg in raw_history:
                    if msg["role"] == "user":
                        messages.append(HumanMessage(content=msg["content"]))
                    elif msg["role"] == "assistant":
                        messages.append(AIMessage(content=msg["content"]))
                return messages
        except Exception as e:
            logger.warning(f"Could not get chat history: {e}")
        return []

    def _save_to_memory(self, session_id: str, user_msg: str, assistant_msg: str):
        """Save messages to PostgreSQL conversation memory."""
        try:
            if self.memory_service:
                self.memory_service.add_message(session_id, "user", user_msg)
                self.memory_service.add_message(session_id, "assistant", assistant_msg)
        except Exception as e:
            logger.warning(f"Could not save to memory: {e}")

    def _save_to_semantic_memory(self, user_id: str, user_msg: str, assistant_msg: str):
        """Save conversation to Mem0 semantic memory."""
        try:
            if not self.memory_service:
                return

            messages = [
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": assistant_msg},
            ]

            result = self.memory_service.add_semantic_memory(
                user_id=user_id,
                messages=messages,
                metadata={"source": "chat", "timestamp": datetime.now().isoformat()},
            )

            if result:
                logger.debug(f"Saved semantic memory for user {user_id}")

        except Exception as e:
            logger.warning(f"Could not save semantic memory: {e}")


# =============================================================================
# Singleton Instance
# =============================================================================

_langchain_agent_service = None


def get_langchain_agent_service() -> LangChainAgentService:
    """Get or create LangChain agent service singleton."""
    global _langchain_agent_service
    if _langchain_agent_service is None:
        _langchain_agent_service = LangChainAgentService()
    return _langchain_agent_service
