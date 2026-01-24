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
from services.prompts import get_system_prompt

logger = logging.getLogger(__name__)


class LangChainAgentService:
    """
    LangChain-based agent service using Claude 3.5 Sonnet.

    Provides tool-calling chat with automatic iteration handling.
    """

    # Claude 3.5 Sonnet model ID on Bedrock
    MODEL_ID = "anthropic.claude-3-5-sonnet-20241022-v2:0"

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

        # Get system prompt (dynamically loads companies from RDS)
        self.system_prompt = get_system_prompt()

        # Create prompt template
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.system_prompt),
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
            user_email: Optional user email for semantic memory
            auth_token: Optional auth token for protected operations

        Returns:
            Response dict with message and metadata
        """
        try:
            # Determine user_id for semantic memory (prefer email, fallback to session)
            user_id = user_email or session_id

            # Get conversation history from PostgreSQL
            chat_history = self._get_chat_history(session_id)

            # Get relevant semantic memories from Mem0
            semantic_context = self._get_semantic_memories(message, user_id)

            # If we have semantic memories, prepend them to chat history
            if semantic_context:
                memory_message = SystemMessage(
                    content=f"Relevant context from previous conversations:\n{semantic_context}"
                )
                chat_history = [memory_message] + chat_history

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

            # Save to PostgreSQL conversation memory
            self._save_to_memory(session_id, message, response_text)

            # Save to Mem0 semantic memory (extracts facts asynchronously)
            self._save_to_semantic_memory(user_id, message, response_text)

            return {
                "response": response_text,
                "session_id": session_id,
                "tools_used": tools_used,
                "model": "claude-3.5-sonnet",
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
