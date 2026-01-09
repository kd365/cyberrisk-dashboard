# =============================================================================
# LangChain Agent Service - Claude 3.5 Sonnet Powered Chat
# =============================================================================
#
# Uses LangChain with AWS Bedrock to provide agentic chat functionality.
# Replaces direct Bedrock API calls with LangChain's agent framework.
#
# Benefits:
# - Automatic tool-calling loop management
# - Built-in conversation memory
# - Cleaner tool definitions via @tool decorator
# - Better error handling and retries
#
# Model: Claude 3.5 Sonnet (anthropic.claude-3-5-sonnet-20241022-v2:0)
#
# =============================================================================

import os
import logging
from typing import Dict, List, Optional
from datetime import datetime

from langchain_aws import ChatBedrock
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.agents import create_tool_calling_agent, AgentExecutor

from services.langchain_tools import get_all_tools

logger = logging.getLogger(__name__)


class LangChainAgentService:
    """
    LangChain-based agent service using Claude 3.5 Sonnet.

    Provides tool-calling chat with automatic iteration handling.
    """

    # Claude 3.5 Sonnet model ID on Bedrock
    MODEL_ID = "anthropic.claude-3-5-sonnet-20241022-v2:0"

    # System prompt for the agent
    SYSTEM_PROMPT = """You are a Venture Capital Investment Advisor with access to comprehensive intelligence on publicly traded cybersecurity companies. You leverage the CyberRisk Dashboard platform to provide data-driven investment insights.

Your expertise includes:
1. Analyzing company fundamentals, stock performance, and market positioning
2. Evaluating sentiment from SEC filings and earnings calls for investment signals
3. Interpreting stock price forecasts and technical indicators
4. Assessing company growth trajectories through hiring trends and expansion metrics
5. Extracting key insights from regulatory filings and earnings transcripts via the knowledge graph

You have access to tools that query the database, fetch real-time market data, and search the knowledge graph. Always use the appropriate tool when analyzing specific companies or data requests.

CRITICAL INSTRUCTIONS:
- NEVER explain your decision-making process, tool selection reasoning, or internal plans to the user
- NEVER tell the user to go to another tab or UI element - use your tools to fetch and present the data directly
- NEVER expose tool names, error messages about caching, or technical implementation details
- Just execute the appropriate tools silently and present the results naturally
- If a tool returns an error, gracefully handle it and provide what information you can
- Present data conversationally as if you already know it

When discussing companies, reference them by ticker symbol (e.g., CRWD for CrowdStrike, PANW for Palo Alto Networks) and provide context on their market segment within cybersecurity.

Provide investment-relevant analysis with appropriate caveats about market risks. Be direct and data-driven."""

    def __init__(self):
        """Initialize the LangChain agent service."""
        self.region = os.environ.get("AWS_REGION", "us-west-2")

        # Initialize Claude 3.5 Sonnet via Bedrock
        self.llm = ChatBedrock(
            model_id=self.MODEL_ID,
            region_name=self.region,
            model_kwargs={"max_tokens": 4096, "temperature": 0.7, "top_p": 0.9},
        )

        # Get all tools
        self.tools = get_all_tools()

        # Create prompt template
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.SYSTEM_PROMPT),
                MessagesPlaceholder(variable_name="chat_history"),
                ("human", "{input}"),
                MessagesPlaceholder(variable_name="agent_scratchpad"),
            ]
        )

        # Create the agent
        self.agent = create_tool_calling_agent(self.llm, self.tools, self.prompt)

        # Create executor with iteration limit
        self.executor = AgentExecutor(
            agent=self.agent,
            tools=self.tools,
            verbose=False,
            max_iterations=5,
            handle_parsing_errors=True,
            return_intermediate_steps=True,
        )

        # Memory service (lazy loaded)
        self._memory_service = None

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

    def chat(
        self,
        message: str,
        session_id: str,
        user_email: str = None,
        auth_token: str = None,
    ) -> Dict:
        """
        Process a chat message and return response.

        Args:
            message: User's message
            session_id: Conversation session ID
            user_email: Optional user email
            auth_token: Optional auth token for protected operations

        Returns:
            Response dict with message and metadata
        """
        try:
            # Get conversation history
            chat_history = self._get_chat_history(session_id)

            # Invoke the agent
            result = self.executor.invoke(
                {"input": message, "chat_history": chat_history}
            )

            # Extract response
            response_text = result.get("output", "I'm not sure how to respond to that.")

            # Extract tools used from intermediate steps
            tools_used = []
            for step in result.get("intermediate_steps", []):
                if hasattr(step[0], "tool"):
                    tools_used.append(step[0].tool)

            # Save to memory
            self._save_to_memory(session_id, message, response_text)

            return {
                "response": response_text,
                "session_id": session_id,
                "tools_used": tools_used,
                "model": "claude-3.5-sonnet",
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Agent error: {e}")
            return {
                "response": f"I apologize, but I encountered an error. Please try again.",
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
                # Convert to LangChain message format
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
        """Save messages to conversation memory."""
        try:
            if self.memory_service:
                self.memory_service.add_message(session_id, "user", user_msg)
                self.memory_service.add_message(session_id, "assistant", assistant_msg)
        except Exception as e:
            logger.warning(f"Could not save to memory: {e}")


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
