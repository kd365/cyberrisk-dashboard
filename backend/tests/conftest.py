# =============================================================================
# Pytest Fixtures for CyberRisk Dashboard Tests
# =============================================================================

import pytest
import sys
from unittest.mock import MagicMock


# Mock heavy dependencies before any test imports
# This allows tests to run without AWS/LangChain infrastructure
@pytest.fixture(autouse=True)
def mock_heavy_deps():
    """Auto-mock heavy dependencies for all tests."""
    # These are mocked at module level in each test file
    # This fixture ensures clean state between tests
    pass


@pytest.fixture
def mock_llm():
    """Create a mock LLM for testing."""
    mock = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "Mock response"
    mock.invoke.return_value = mock_response
    return mock


@pytest.fixture
def sample_agent_state():
    """Create a sample agent state for testing."""
    return {
        "messages": [],
        "query": "Test query",
        "route": "financial",
        "ticker": "TEST",
        "tool_output": None,
        "has_data": False,
        "final_response": None,
    }
