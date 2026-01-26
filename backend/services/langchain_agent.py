# =============================================================================
# LangChain Agent Service - Hybrid Claude Routing (Haiku + Sonnet)
# =============================================================================
#
# Uses LangGraph with AWS Bedrock to provide agentic chat functionality.
# Replaces direct Bedrock API calls with LangGraph's agent framework.
#
# Benefits:
# - Automatic tool-calling loop management
# - Built-in conversation memory
# - Cleaner tool definitions via @tool decorator
# - Better error handling and retries
#
# Hybrid Routing (2026-01-26):
# - Claude 3.5 Haiku for simple queries (list, lookup, status) → 3-5x faster
# - Claude 3.5 Sonnet for complex queries (analysis, comparison, strategy)
#
# =============================================================================

import os
import re
import logging
from typing import Dict, List, Optional
from datetime import datetime

from langchain_aws import ChatBedrock
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from services.langchain_tools import get_all_tools
from services.prompts import get_system_prompt

logger = logging.getLogger(__name__)


class LangChainAgentService:
    """
    LangChain-based agent service with hybrid Haiku/Sonnet routing.

    Routes simple queries to fast Haiku, complex analysis to Sonnet.
    """

    # Model IDs on Bedrock
    SONNET_MODEL_ID = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    HAIKU_MODEL_ID = "anthropic.claude-3-5-haiku-20241022-v1:0"

    # Query patterns that indicate simple queries (use Haiku)
    SIMPLE_QUERY_PATTERNS = [
        r"^(list|show|what are|get)\s+(the\s+)?(companies|tickers|tracked)",
        r"^(what|show|get)\s+(is|are)\s+(the\s+)?(stock\s+)?price",
        r"^(what|show|get)\s+companies",
        r"^(how many|count)",
        r"^(what|show)\s+alerts",
        r"^help",
        r"^hi|hello|hey",
        r"^(show|list|get)\s+(me\s+)?(the\s+)?sentiment",
        r"^(show|list|get)\s+(me\s+)?(the\s+)?forecast",
        r"^(what|show|get)\s+(is|are)\s+\w{2,5}('s)?\s+(price|stock)",
    ]

    # Query patterns that indicate complex queries (use Sonnet)
    COMPLEX_QUERY_PATTERNS = [
        r"(analyze|analysis|compare|comparison|evaluate|assess)",
        r"(strategy|strategic|implications|impact)",
        r"(why|how come|explain|reasoning)",
        r"(recommend|suggest|advise|should i)",
        r"(risk|opportunity|threat|advantage)",
        r"(summary|summarize|overview).*(multiple|all|several)",
        r"(trend|pattern|insight)",
        r"(predict|forecast|outlook).*(market|industry|sector)",
    ]

    def __init__(self):
        """Initialize the LangChain agent service with hybrid routing."""
        self.region = os.environ.get("AWS_REGION", "us-west-2")

        # Initialize Haiku (fast, for simple queries)
        self.llm_haiku = ChatBedrock(
            model_id=self.HAIKU_MODEL_ID,
            region_name=self.region,
            model_kwargs={"max_tokens": 4096, "temperature": 0.5, "top_p": 0.9},
        )

        # Initialize Sonnet (powerful, for complex analysis)
        self.llm_sonnet = ChatBedrock(
            model_id=self.SONNET_MODEL_ID,
            region_name=self.region,
            model_kwargs={"max_tokens": 4096, "temperature": 0.7, "top_p": 0.9},
        )

        # Get all tools
        self.tools = get_all_tools()

        # Get system prompt (dynamically loads companies from RDS)
        self.system_prompt = get_system_prompt()

        # Create two agents for hybrid routing
        self.agent_haiku = create_react_agent(
            model=self.llm_haiku,
            tools=self.tools,
            prompt=self.system_prompt,
        )

        self.agent_sonnet = create_react_agent(
            model=self.llm_sonnet,
            tools=self.tools,
            prompt=self.system_prompt,
        )

        # Keep backward compatibility
        self.llm = self.llm_sonnet
        self.agent = self.agent_sonnet

        # Memory service (lazy loaded)
        self._memory_service = None

    def _classify_query_complexity(self, message: str) -> str:
        """
        Classify query as 'simple' or 'complex' for model routing.

        Args:
            message: User's query

        Returns:
            'simple' for Haiku, 'complex' for Sonnet
        """
        message_lower = message.lower().strip()

        # Check for complex patterns first (they take priority)
        for pattern in self.COMPLEX_QUERY_PATTERNS:
            if re.search(pattern, message_lower):
                logger.info(f"Query classified as COMPLEX (matched: {pattern})")
                return "complex"

        # Check for simple patterns
        for pattern in self.SIMPLE_QUERY_PATTERNS:
            if re.search(pattern, message_lower):
                logger.info(f"Query classified as SIMPLE (matched: {pattern})")
                return "simple"

        # Default to complex for longer queries, simple for short
        word_count = len(message.split())
        if word_count > 15:
            logger.info(f"Query classified as COMPLEX (word count: {word_count})")
            return "complex"

        # Default to Haiku for unclassified short queries
        logger.info("Query classified as SIMPLE (default)")
        return "simple"

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

        Uses hybrid routing: Haiku for simple queries, Sonnet for complex analysis.

        Args:
            message: User's message
            session_id: Conversation session ID
            user_email: Optional user email for semantic memory
            auth_token: Optional auth token for protected operations

        Returns:
            Response dict with message and metadata
        """
        try:
            # Determine user_id for semantic memory (prefer email, fallback to session)
            user_id = user_email or session_id

            # Classify query complexity for hybrid routing
            complexity = self._classify_query_complexity(message)
            selected_agent = (
                self.agent_haiku if complexity == "simple" else self.agent_sonnet
            )
            model_name = (
                "claude-3.5-haiku" if complexity == "simple" else "claude-3.5-sonnet"
            )

            # Get conversation history from PostgreSQL
            chat_history = self._get_chat_history(session_id)

            # Get relevant semantic memories from Mem0
            semantic_context = self._get_semantic_memories(message, user_id)

            # Build messages list for LangGraph agent
            messages = []

            # If we have semantic memories, add as system message
            if semantic_context:
                messages.append(
                    SystemMessage(
                        content=f"Relevant context from previous conversations:\n{semantic_context}"
                    )
                )

            # Add chat history
            messages.extend(chat_history)

            # Add current user message
            messages.append(HumanMessage(content=message))

            # Invoke the selected agent (Haiku or Sonnet)
            # Higher recursion_limit allows complex multi-tool queries
            result = selected_agent.invoke(
                {"messages": messages},
                config={"recursion_limit": 25},
            )

            # Extract response from the last AI message
            response_text = "I'm not sure how to respond to that."
            tools_used = []

            # Collect ALL tools used across the entire agent run (not just last message)
            for msg in result.get("messages", []):
                if isinstance(msg, AIMessage):
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        for tc in msg.tool_calls:
                            tool_name = tc.get("name", "")
                            if tool_name and tool_name not in tools_used:
                                tools_used.append(tool_name)

            # Get the final response from the last AI message
            for msg in reversed(result.get("messages", [])):
                if isinstance(msg, AIMessage):
                    response_text = msg.content
                    break

            # Save to PostgreSQL conversation memory
            self._save_to_memory(session_id, message, response_text)

            # Save to Mem0 semantic memory (extracts facts asynchronously)
            self._save_to_semantic_memory(user_id, message, response_text)

            return {
                "response": response_text,
                "session_id": session_id,
                "tools_used": tools_used,
                "model": model_name,
                "query_complexity": complexity,
                "timestamp": datetime.now().isoformat(),
                "semantic_memory_used": bool(semantic_context),
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
        """Save messages to PostgreSQL conversation memory."""
        try:
            if self.memory_service:
                self.memory_service.add_message(session_id, "user", user_msg)
                self.memory_service.add_message(session_id, "assistant", assistant_msg)
        except Exception as e:
            logger.warning(f"Could not save to memory: {e}")

    def _get_semantic_memories(self, query: str, user_id: str) -> Optional[str]:
        """
        Search Mem0 for relevant semantic memories.

        Args:
            query: The user's current message to find relevant context for
            user_id: User identifier (email or session_id)

        Returns:
            Formatted string of relevant memories, or None if none found
        """
        try:
            if not self.memory_service:
                return None

            # Search semantic memory for relevant facts
            memories = self.memory_service.search_semantic_memory(
                query=query, user_id=user_id, limit=3
            )

            if not memories:
                return None

            # Format memories into context string
            memory_texts = []
            for mem in memories:
                # Mem0 returns dicts with 'memory' key containing the fact
                if isinstance(mem, dict):
                    text = mem.get("memory") or mem.get("text") or str(mem)
                else:
                    text = str(mem)
                memory_texts.append(f"- {text}")

            if memory_texts:
                logger.debug(
                    f"Found {len(memory_texts)} semantic memories for user {user_id}"
                )
                return "\n".join(memory_texts)

            return None

        except Exception as e:
            logger.warning(f"Could not get semantic memories: {e}")
            return None

    def _save_to_semantic_memory(self, user_id: str, user_msg: str, assistant_msg: str):
        """
        Save conversation to Mem0 semantic memory.

        Mem0 automatically extracts facts and preferences from the conversation.

        Args:
            user_id: User identifier (email or session_id)
            user_msg: User's message
            assistant_msg: Assistant's response
        """
        try:
            if not self.memory_service:
                return

            # Format as conversation for Mem0 to extract facts from
            messages = [
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": assistant_msg},
            ]

            # Mem0 will extract facts/preferences and store as embeddings
            result = self.memory_service.add_semantic_memory(
                user_id=user_id,
                messages=messages,
                metadata={"source": "chat", "timestamp": datetime.now().isoformat()},
            )

            if result:
                logger.debug(f"Saved semantic memory for user {user_id}: {result}")

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
