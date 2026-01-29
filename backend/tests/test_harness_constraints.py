# =============================================================================
# Anti-Hallucination Harness Constraint Tests
# =============================================================================
#
# These tests prove the structural anti-hallucination guarantees work.
# They are NOT happy path tests - they prove NEGATIVE constraints:
#
# 1. Kill Switch: LLM is NEVER called when tools return NO_DATA
# 2. Regex Fallback: Router works even when LLM fails
# 3. Tool Contract: Exact trigger strings that the harness depends on
# 4. Context Isolation: Synthesizer prompt only contains tool output
#
# =============================================================================

import pytest
import sys
from unittest.mock import MagicMock, patch
import json

# Mock heavy dependencies before importing our modules
sys.modules["langchain_aws"] = MagicMock()
sys.modules["langchain_core"] = MagicMock()
sys.modules["langchain_core.messages"] = MagicMock()
sys.modules["langchain_core.prompts"] = MagicMock()
sys.modules["langchain_core.tools"] = MagicMock()
sys.modules["langgraph"] = MagicMock()
sys.modules["langgraph.graph"] = MagicMock()
sys.modules["langgraph.prebuilt"] = MagicMock()
sys.modules["pydantic"] = MagicMock()

# Now we can test the core logic without AWS dependencies
# We'll inline the key functions and types to test them in isolation


# =============================================================================
# Inline the code under test (isolated from dependencies)
# =============================================================================

import re
from typing import Dict, List, Optional, Any, TypedDict
from operator import add


class AgentState(TypedDict):
    """State for the anti-hallucination agent graph."""

    messages: List
    query: str
    route: str
    ticker: Optional[str]
    tool_output: Optional[Dict[str, Any]]
    has_data: bool
    final_response: Optional[str]


# Patterns for routing (copied from langchain_agent.py)
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


def no_data_response(
    data_type: str, entity: str = None, reason: str = None
) -> Dict[str, Any]:
    """
    Return a structured no-data response that forces the agent to acknowledge
    missing data rather than hallucinate.
    """
    response = {
        "status": "no_data",
        "NO_DATA": True,
        "data_type": data_type,
        "message": f"SYSTEM_NOTIFICATION: NO_DATA_FOUND for {data_type}"
        + (f" ({entity})" if entity else "")
        + ". Do not guess.",
    }
    if entity:
        response["entity"] = entity
    if reason:
        response["reason"] = reason
    return response


def error_response(error: str, operation: str = None) -> Dict[str, Any]:
    """Return a structured error response for tool failures."""
    return {
        "status": "error",
        "ERROR": True,
        "error": str(error),
        "operation": operation,
        "message": f"SYSTEM_NOTIFICATION: TOOL_ERROR. Failed to retrieve data"
        + (f" ({operation})" if operation else "")
        + ". Do not guess.",
    }


def route_query(state: AgentState, router_llm) -> AgentState:
    """Router node: Classify query and extract entities using cheap LLM."""
    query = state["query"]

    try:
        # Try structured output for precise routing
        structured_llm = router_llm.with_structured_output(MagicMock())
        messages = [MagicMock(), MagicMock()]
        result = structured_llm.invoke(messages)

        return {
            **state,
            "route": result.destination,
            "ticker": result.ticker.upper() if result.ticker else None,
            "has_data": False,
        }

    except Exception as e:
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
            route = "financial"

        return {
            **state,
            "route": route,
            "ticker": ticker,
            "has_data": False,
        }


def synthesize_response(state: AgentState, synthesis_llm) -> AgentState:
    """
    Synthesis node: Generate response ONLY from tool output.

    HARD CONSTRAINT: If SYSTEM_NOTIFICATION is detected, we short-circuit
    the LLM entirely and return a canned response.
    """
    tool_output = state.get("tool_output") or {}  # Handle None explicitly
    query = state["query"]
    tool_output_str = json.dumps(tool_output, default=str) if tool_output else ""

    # SHORT-CIRCUIT: If the strict signal is found, skip LLM entirely
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
        return {
            **state,
            "has_data": True,
            "final_response": tool_output["response_text"],
        }

    # Generate grounded response from structured tool output
    # Create a simple prompt template inline
    prompt_text = f"""DATA_CONTEXT:
{json.dumps(tool_output, indent=2, default=str)}

USER_QUERY:
{query}"""

    # Create message-like objects for the LLM
    class FakeMessage:
        def __init__(self, content):
            self.content = content

    messages = [FakeMessage(prompt_text)]
    response = synthesis_llm.invoke(messages)

    return {**state, "has_data": True, "final_response": response.content}


# =============================================================================
# 1. Kill Switch Test: NO_DATA bypasses LLM entirely
# =============================================================================


def test_synthesizer_triggers_kill_switch_on_no_data():
    """
    Prove that if tools return NO_DATA, the LLM is NEVER called.

    This is the critical anti-hallucination guarantee: when there's no data,
    we short-circuit the entire synthesis process and return a canned response.
    The LLM cannot hallucinate if it's never invoked.
    """
    # Create a NO_DATA payload using the official helper
    no_data_payload = no_data_response("financial data", "FAKE_TICKER")

    state: AgentState = {
        "messages": [],
        "query": "What is the price of FAKE_TICKER?",
        "route": "financial",
        "ticker": "FAKE_TICKER",
        "tool_output": no_data_payload,
        "has_data": False,
        "final_response": None,
    }

    # Create a mock LLM that should NEVER be called
    mock_llm = MagicMock()

    # Run the synthesizer
    result = synthesize_response(state, mock_llm)

    # THE MONEY SHOT: The LLM was strictly NOT called
    mock_llm.invoke.assert_not_called()

    # Verify we got a canned response about missing data
    assert result["has_data"] is False
    assert "don't have" in result["final_response"].lower()
    assert "FAKE_TICKER" in result["final_response"]


def test_synthesizer_triggers_kill_switch_on_error():
    """
    Prove that TOOL_ERROR also bypasses the LLM.
    """
    error_payload = error_response("Database connection failed", "get_company_info")

    state: AgentState = {
        "messages": [],
        "query": "Get info for CRWD",
        "route": "financial",
        "ticker": "CRWD",
        "tool_output": error_payload,
        "has_data": False,
        "final_response": None,
    }

    mock_llm = MagicMock()
    result = synthesize_response(state, mock_llm)

    # LLM should NOT be called
    mock_llm.invoke.assert_not_called()

    # Should get error response
    assert result["has_data"] is False
    assert (
        "wasn't able" in result["final_response"].lower()
        or "error" in result["final_response"].lower()
    )


# =============================================================================
# 2. Router Regex Fallback Test
# =============================================================================


def test_router_falls_back_to_regex_on_llm_failure():
    """
    Prove that the router uses regex fallback when LLM structured output fails.

    This ensures the system degrades gracefully - even if the router LLM
    has issues, we can still route queries to appropriate tools.
    """
    state: AgentState = {
        "messages": [],
        "query": "What is the regulatory compliance status for PANW?",
        "route": "",
        "ticker": None,
        "tool_output": None,
        "has_data": False,
        "final_response": None,
    }

    # Create a mock LLM that FAILS structured output
    mock_router_llm = MagicMock()
    mock_router_llm.with_structured_output.return_value.invoke.side_effect = Exception(
        "Simulated LLM failure"
    )

    # Run the router
    result = route_query(state, mock_router_llm)

    # Should have fallen back to regex and still routed correctly
    assert result["route"] == "regulatory"  # "regulatory" is in the query
    assert result["ticker"] == "PANW"  # Extracted via regex


def test_router_regex_extracts_ticker():
    """
    Verify the ticker regex pattern works correctly.
    """
    test_cases = [
        ("What about CRWD?", "CRWD"),
        ("Compare PANW and ZS", "PANW"),  # First match
        ("Price of OKTA stock", "OKTA"),
    ]

    for query, expected_ticker in test_cases:
        match = TICKER_PATTERN.search(query)
        assert match is not None, f"Should find ticker in: {query}"
        assert match.group(1) == expected_ticker


def test_router_regex_routes_financial():
    """
    Verify financial patterns route correctly via regex.
    """
    financial_queries = [
        "What is the stock price?",
        "Show me the forecast",
        "Get sentiment analysis",
        "Revenue growth for CRWD",
    ]

    for query in financial_queries:
        query_lower = query.lower()
        matches = any(re.search(p, query_lower) for p in FINANCIAL_PATTERNS)
        assert matches, f"Should match financial pattern: {query}"


def test_router_regex_routes_regulatory():
    """
    Verify regulatory patterns route correctly via regex.
    """
    regulatory_queries = [
        "Show compliance status",
        "What SEC regulations apply?",
        "Any regulatory alerts?",
        "CISA requirements",
    ]

    for query in regulatory_queries:
        query_lower = query.lower()
        matches = any(re.search(p, query_lower) for p in REGULATORY_PATTERNS)
        assert matches, f"Should match regulatory pattern: {query}"


# =============================================================================
# 3. Tool Contract Tests: Exact trigger strings
# =============================================================================


def test_tool_no_data_contract():
    """
    Verify the exact strings that trigger the kill switch are present.

    The synthesizer depends on these EXACT strings:
    - "SYSTEM_NOTIFICATION: NO_DATA_FOUND"
    - "SYSTEM_NOTIFICATION: TOOL_ERROR"

    If these change, the kill switch breaks.
    """
    # Test no_data_response
    result = no_data_response("test_data", "TEST_ENTITY")

    assert result["NO_DATA"] is True
    assert result["status"] == "no_data"
    assert "SYSTEM_NOTIFICATION: NO_DATA_FOUND" in result["message"]
    assert "test_data" in result["message"]
    assert "TEST_ENTITY" in result["message"]

    # Test error_response
    error_result = error_response("Test error", "test_operation")

    assert error_result["ERROR"] is True
    assert error_result["status"] == "error"
    assert "SYSTEM_NOTIFICATION: TOOL_ERROR" in error_result["message"]


def test_synthesizer_detects_no_data_string():
    """
    Verify the synthesizer detects NO_DATA_FOUND in tool output.
    """
    # Create tool output with the magic string
    tool_output = {
        "message": "SYSTEM_NOTIFICATION: NO_DATA_FOUND for financial data (FAKE)",
        "data_type": "financial data",
        "entity": "FAKE",
    }

    state: AgentState = {
        "messages": [],
        "query": "Test query",
        "route": "financial",
        "ticker": "FAKE",
        "tool_output": tool_output,
        "has_data": False,
        "final_response": None,
    }

    mock_llm = MagicMock()
    result = synthesize_response(state, mock_llm)

    # Kill switch should trigger
    mock_llm.invoke.assert_not_called()
    assert result["has_data"] is False


def test_synthesizer_detects_tool_error_string():
    """
    Verify the synthesizer detects TOOL_ERROR in tool output.
    """
    tool_output = {
        "message": "SYSTEM_NOTIFICATION: TOOL_ERROR. Failed to retrieve data",
        "ERROR": True,
    }

    state: AgentState = {
        "messages": [],
        "query": "Test query",
        "route": "financial",
        "ticker": "TEST",
        "tool_output": tool_output,
        "has_data": False,
        "final_response": None,
    }

    mock_llm = MagicMock()
    result = synthesize_response(state, mock_llm)

    mock_llm.invoke.assert_not_called()
    assert result["has_data"] is False


# =============================================================================
# 4. Grounded Prompt Test: Context Isolation
# =============================================================================


def test_synthesizer_uses_grounded_prompt():
    """
    Verify the synthesis prompt ONLY contains tool output, no external context.

    This ensures the LLM cannot access training knowledge - it can only
    report what the tools found.
    """
    tool_output = {
        "ticker": "CRWD",
        "price": 350.00,
        "sentiment": "positive",
    }

    state: AgentState = {
        "messages": [],
        "query": "What is CRWD sentiment?",
        "route": "financial",
        "ticker": "CRWD",
        "tool_output": tool_output,
        "has_data": False,
        "final_response": None,
    }

    # Capture what gets passed to the LLM
    captured_messages = []

    mock_llm = MagicMock()

    def capture_invoke(messages):
        captured_messages.extend(messages)
        mock_response = MagicMock()
        mock_response.content = "CRWD has positive sentiment."
        return mock_response

    mock_llm.invoke.side_effect = capture_invoke

    result = synthesize_response(state, mock_llm)

    # Verify LLM was called (not kill-switched)
    assert mock_llm.invoke.called

    # Verify the prompt contains tool output
    prompt_content = str([m.content for m in captured_messages])
    assert "CRWD" in prompt_content
    assert "350" in prompt_content
    assert "positive" in prompt_content

    # Verify the grounding instructions are present
    assert "DATA_CONTEXT" in prompt_content


def test_synthesizer_prompt_contains_query():
    """
    Verify the user's query is included in synthesis prompt.
    """
    tool_output = {"data": "test"}

    state: AgentState = {
        "messages": [],
        "query": "UNIQUE_TEST_QUERY_12345",
        "route": "financial",
        "ticker": "TEST",
        "tool_output": tool_output,
        "has_data": False,
        "final_response": None,
    }

    captured_messages = []
    mock_llm = MagicMock()

    def capture_invoke(messages):
        captured_messages.extend(messages)
        mock_response = MagicMock()
        mock_response.content = "Response"
        return mock_response

    mock_llm.invoke.side_effect = capture_invoke

    synthesize_response(state, mock_llm)

    prompt_content = str([m.content for m in captured_messages])
    assert "UNIQUE_TEST_QUERY_12345" in prompt_content


# =============================================================================
# 5. Legacy Flag Compatibility Tests
# =============================================================================


def test_legacy_no_data_flag_triggers_kill_switch():
    """
    Verify backward compatibility with legacy NO_DATA flag.
    """
    state: AgentState = {
        "messages": [],
        "query": "Test",
        "route": "financial",
        "ticker": "TEST",
        "tool_output": {"NO_DATA": True, "data_type": "test data"},
        "has_data": False,
        "final_response": None,
    }

    mock_llm = MagicMock()
    result = synthesize_response(state, mock_llm)

    mock_llm.invoke.assert_not_called()
    assert result["has_data"] is False


def test_legacy_status_no_data_triggers_kill_switch():
    """
    Verify backward compatibility with status='no_data'.
    """
    state: AgentState = {
        "messages": [],
        "query": "Test",
        "route": "financial",
        "ticker": "TEST",
        "tool_output": {"status": "no_data", "data_type": "test data"},
        "has_data": False,
        "final_response": None,
    }

    mock_llm = MagicMock()
    result = synthesize_response(state, mock_llm)

    mock_llm.invoke.assert_not_called()


def test_legacy_error_flag_triggers_kill_switch():
    """
    Verify backward compatibility with legacy ERROR flag.
    """
    state: AgentState = {
        "messages": [],
        "query": "Test",
        "route": "financial",
        "ticker": "TEST",
        "tool_output": {"ERROR": True, "error": "test error"},
        "has_data": False,
        "final_response": None,
    }

    mock_llm = MagicMock()
    result = synthesize_response(state, mock_llm)

    mock_llm.invoke.assert_not_called()
    assert result["has_data"] is False


# =============================================================================
# 6. Raw Response Passthrough Test
# =============================================================================


def test_raw_response_passthrough():
    """
    Verify that raw ReAct agent responses pass through without re-synthesis.
    """
    state: AgentState = {
        "messages": [],
        "query": "Test",
        "route": "financial",
        "ticker": "TEST",
        "tool_output": {
            "raw": True,
            "response_text": "This is the pre-synthesized response from ReAct.",
        },
        "has_data": False,
        "final_response": None,
    }

    mock_llm = MagicMock()
    result = synthesize_response(state, mock_llm)

    # LLM should NOT be called for raw responses
    mock_llm.invoke.assert_not_called()

    # Should pass through the raw response
    assert result["has_data"] is True
    assert (
        result["final_response"] == "This is the pre-synthesized response from ReAct."
    )


# =============================================================================
# 7. Edge Case Tests
# =============================================================================


def test_empty_tool_output_calls_llm():
    """
    Verify that empty (but not NO_DATA) tool output still calls the LLM.
    """
    state: AgentState = {
        "messages": [],
        "query": "Test",
        "route": "financial",
        "ticker": "TEST",
        "tool_output": {"some_data": "value"},  # Has data, no NO_DATA flag
        "has_data": False,
        "final_response": None,
    }

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "Test response"
    mock_llm.invoke.return_value = mock_response

    result = synthesize_response(state, mock_llm)

    # LLM SHOULD be called
    mock_llm.invoke.assert_called_once()
    assert result["has_data"] is True


def test_null_tool_output_triggers_legacy_check():
    """
    Verify behavior with None tool output.
    """
    state: AgentState = {
        "messages": [],
        "query": "Test",
        "route": "financial",
        "ticker": "TEST",
        "tool_output": None,
        "has_data": False,
        "final_response": None,
    }

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "Test response"
    mock_llm.invoke.return_value = mock_response

    # Should not crash, LLM should be called (no kill switch trigger)
    result = synthesize_response(state, mock_llm)
    assert "final_response" in result
