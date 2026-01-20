# =============================================================================
# Memory Service - Conversation History & Semantic Memory with mem0
# =============================================================================
#
# This service manages conversation memory for the LLM chat:
# - Session memory: Recent conversation history (PostgreSQL tables)
# - Long-term memory: Semantic memories using mem0 with pgvector
#
# Uses existing PostgreSQL database with pgvector extension for vector storage.
# Uses AWS Bedrock for LLM and embeddings (no external API keys required).
#
# =============================================================================

import os
import json
import uuid
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

# Lazy import mem0 to avoid startup errors if not installed
Memory = None
MEM0_AVAILABLE = False


def _load_mem0():
    """Lazy load mem0 library."""
    global Memory, MEM0_AVAILABLE
    if Memory is not None:
        return MEM0_AVAILABLE
    try:
        from mem0 import Memory as Mem0Memory

        Memory = Mem0Memory
        MEM0_AVAILABLE = True
        logger.info("mem0 library loaded successfully")
    except ImportError as e:
        logger.warning(f"mem0 library not available: {e}")
        MEM0_AVAILABLE = False
    return MEM0_AVAILABLE


class MemoryService:
    """
    Conversation memory service using PostgreSQL + mem0.

    Manages:
    - Chat sessions (grouping of messages)
    - Chat messages (conversation history)
    - Long-term semantic memory (using mem0 with pgvector + AWS Bedrock)
    """

    def __init__(
        self,
        db_host: str = None,
        db_name: str = None,
        db_user: str = None,
        db_password: str = None,
    ):
        """
        Initialize memory service with database connection.

        Args:
            db_host: Database host (default from environment)
            db_name: Database name
            db_user: Database username
            db_password: Database password
        """
        self.db_host = db_host or os.environ.get("DB_HOST", "localhost")
        self.db_name = db_name or os.environ.get("DB_NAME", "cyberrisk")
        self.db_user = db_user or os.environ.get("DB_USER", "cyberrisk_admin")
        self.db_password = db_password or os.environ.get("DB_PASSWORD", "")
        self.db_port = os.environ.get("DB_PORT", "5432")

        self._connection = None
        self._mem0 = None
        self._mem0_initialized = False

    def _get_connection(self):
        """Get or create database connection."""
        if self._connection is None or self._connection.closed:
            self._connection = psycopg2.connect(
                host=self.db_host,
                database=self.db_name,
                user=self.db_user,
                password=self.db_password,
            )
            self._connection.autocommit = True
        return self._connection

    def _get_mem0(self):
        """Get or initialize mem0 instance with AWS Bedrock."""
        if self._mem0 is not None:
            return self._mem0

        if not _load_mem0():
            return None

        try:
            # Ensure AWS_REGION is set for Bedrock (uses boto3 session)
            if not os.environ.get("AWS_REGION"):
                os.environ["AWS_REGION"] = "us-west-2"

            # Configure mem0 with AWS Bedrock for LLM and embeddings
            # No external API keys needed - uses IAM role credentials
            # Region is picked up from AWS_REGION environment variable
            config = {
                "llm": {
                    "provider": "aws_bedrock",
                    "config": {
                        # Claude 3.5 Haiku for fact extraction
                        "model": "anthropic.claude-3-5-haiku-20241022-v1:0",
                        "temperature": 0.1,
                        "max_tokens": 1000,
                    },
                },
                "embedder": {
                    "provider": "aws_bedrock",
                    "config": {
                        # Amazon Titan v2 embeddings (1024 dimensions)
                        "model": "amazon.titan-embed-text-v2:0",
                        "embedding_dims": 1024,
                    },
                },
                "vector_store": {
                    "provider": "pgvector",
                    "config": {
                        "host": self.db_host,
                        "port": int(self.db_port),
                        "user": self.db_user,
                        "password": self.db_password,
                        "dbname": self.db_name,
                        "embedding_model_dims": 1024,
                    },
                },
            }

            self._mem0 = Memory.from_config(config)
            self._mem0_initialized = True
            logger.info("mem0 initialized with AWS Bedrock + pgvector")
            return self._mem0

        except Exception as e:
            logger.error(f"Failed to initialize mem0: {e}")
            return None

    def close(self):
        """Close database connection."""
        if self._connection and not self._connection.closed:
            self._connection.close()
            self._connection = None

    # =========================================================================
    # Schema Initialization
    # =========================================================================

    def init_schema(self):
        """
        Create chat memory tables if they don't exist.

        Call this at application startup.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # Enable pgvector extension for mem0
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")

            # Chat sessions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id SERIAL PRIMARY KEY,
                    session_id VARCHAR(255) NOT NULL UNIQUE,
                    user_email VARCHAR(255),
                    created_at TIMESTAMP DEFAULT NOW(),
                    last_active TIMESTAMP DEFAULT NOW(),
                    metadata JSONB DEFAULT '{}'::jsonb
                );

                CREATE INDEX IF NOT EXISTS idx_chat_sessions_session_id
                    ON chat_sessions(session_id);
                CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_email
                    ON chat_sessions(user_email);
                CREATE INDEX IF NOT EXISTS idx_chat_sessions_last_active
                    ON chat_sessions(last_active);
            """)

            # Chat messages table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id SERIAL PRIMARY KEY,
                    session_id VARCHAR(255) NOT NULL,
                    role VARCHAR(20) NOT NULL,
                    content TEXT NOT NULL,
                    metadata JSONB DEFAULT '{}'::jsonb,
                    created_at TIMESTAMP DEFAULT NOW(),
                    FOREIGN KEY (session_id)
                        REFERENCES chat_sessions(session_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id
                    ON chat_messages(session_id);
                CREATE INDEX IF NOT EXISTS idx_chat_messages_created_at
                    ON chat_messages(created_at);
            """)

            # User memory table (for simple long-term preferences, fallback if mem0 unavailable)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_memory (
                    id SERIAL PRIMARY KEY,
                    user_email VARCHAR(255),
                    memory_type VARCHAR(50) NOT NULL,
                    content TEXT NOT NULL,
                    importance FLOAT DEFAULT 0.5,
                    created_at TIMESTAMP DEFAULT NOW(),
                    accessed_at TIMESTAMP DEFAULT NOW(),
                    metadata JSONB DEFAULT '{}'::jsonb
                );

                CREATE INDEX IF NOT EXISTS idx_user_memory_email
                    ON user_memory(user_email);
                CREATE INDEX IF NOT EXISTS idx_user_memory_type
                    ON user_memory(memory_type);
            """)

            logger.info("Chat memory schema initialized (with pgvector)")

        except Exception as e:
            logger.error(f"Failed to initialize memory schema: {e}")
            raise
        finally:
            cursor.close()

        # Initialize mem0 (non-blocking, will be initialized on first use)
        try:
            self._get_mem0()
        except Exception as e:
            logger.warning(f"mem0 initialization deferred: {e}")

    # =========================================================================
    # Session Management
    # =========================================================================

    def create_session(
        self, session_id: str = None, user_email: str = None, metadata: Dict = None
    ) -> str:
        """
        Create a new chat session.

        Args:
            session_id: Optional custom session ID
            user_email: Optional user email for tracking
            metadata: Optional session metadata

        Returns:
            Session ID
        """
        if not session_id:
            session_id = str(uuid.uuid4())

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO chat_sessions (session_id, user_email, metadata)
                VALUES (%s, %s, %s)
                ON CONFLICT (session_id) DO UPDATE
                SET last_active = NOW()
                RETURNING session_id
            """,
                (session_id, user_email, json.dumps(metadata or {})),
            )

            result = cursor.fetchone()
            return result[0]

        finally:
            cursor.close()

    def get_session(self, session_id: str) -> Optional[Dict]:
        """Get session details."""
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cursor.execute(
                """
                SELECT session_id, user_email, created_at, last_active, metadata
                FROM chat_sessions
                WHERE session_id = %s
            """,
                (session_id,),
            )

            result = cursor.fetchone()
            return dict(result) if result else None

        finally:
            cursor.close()

    def update_session_activity(self, session_id: str):
        """Update session last_active timestamp."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                UPDATE chat_sessions
                SET last_active = NOW()
                WHERE session_id = %s
            """,
                (session_id,),
            )
        finally:
            cursor.close()

    def delete_session(self, session_id: str):
        """Delete a session and all its messages."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                DELETE FROM chat_sessions WHERE session_id = %s
            """,
                (session_id,),
            )
        finally:
            cursor.close()

    def cleanup_old_sessions(self, days: int = 30):
        """Delete sessions older than specified days."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cutoff = datetime.now() - timedelta(days=days)
            cursor.execute(
                """
                DELETE FROM chat_sessions
                WHERE last_active < %s
            """,
                (cutoff,),
            )
            deleted = cursor.rowcount
            logger.info(f"Cleaned up {deleted} old chat sessions")
            return deleted
        finally:
            cursor.close()

    # =========================================================================
    # Message Management
    # =========================================================================

    def add_message(
        self, session_id: str, role: str, content: str, metadata: Dict = None
    ) -> int:
        """
        Add a message to conversation history.

        Args:
            session_id: Session ID
            role: Message role ('user' or 'assistant')
            content: Message content
            metadata: Optional message metadata

        Returns:
            Message ID
        """
        # Ensure session exists
        if not self.get_session(session_id):
            self.create_session(session_id)

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO chat_messages (session_id, role, content, metadata)
                VALUES (%s, %s, %s, %s)
                RETURNING id
            """,
                (session_id, role, content, json.dumps(metadata or {})),
            )

            message_id = cursor.fetchone()[0]

            # Update session activity
            self.update_session_activity(session_id)

            return message_id

        finally:
            cursor.close()

    def get_session_history(
        self, session_id: str, limit: int = 10, include_metadata: bool = False
    ) -> List[Dict]:
        """
        Get recent conversation history for a session.

        Args:
            session_id: Session ID
            limit: Maximum messages to return
            include_metadata: Whether to include metadata

        Returns:
            List of messages (oldest first)
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cursor.execute(
                """
                SELECT role, content, created_at, metadata
                FROM chat_messages
                WHERE session_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            """,
                (session_id, limit),
            )

            messages = cursor.fetchall()

            # Reverse to get chronological order
            messages.reverse()

            result = []
            for msg in messages:
                item = {
                    "role": msg["role"],
                    "content": msg["content"],
                    "created_at": (
                        msg["created_at"].isoformat() if msg["created_at"] else None
                    ),
                }
                if include_metadata:
                    item["metadata"] = msg["metadata"]
                result.append(item)

            return result

        finally:
            cursor.close()

    def get_message_count(self, session_id: str) -> int:
        """Get total message count for a session."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT COUNT(*) FROM chat_messages WHERE session_id = %s
            """,
                (session_id,),
            )
            return cursor.fetchone()[0]
        finally:
            cursor.close()

    # =========================================================================
    # Context Building for LLM
    # =========================================================================

    def get_context_for_llm(
        self, session_id: str, max_messages: int = 5, max_tokens: int = 2000
    ) -> List[Dict]:
        """
        Get formatted conversation context for LLM prompt.

        Returns recent messages formatted for Claude's message format.

        Args:
            session_id: Session ID
            max_messages: Maximum messages to include
            max_tokens: Approximate token limit (rough estimate)

        Returns:
            List of message dicts with 'role' and 'content'
        """
        messages = self.get_session_history(session_id, limit=max_messages)

        # Rough token estimation and truncation
        result = []
        total_chars = 0
        char_limit = max_tokens * 4  # Rough: 1 token ≈ 4 chars

        for msg in reversed(messages):
            content_len = len(msg["content"])
            if total_chars + content_len > char_limit:
                # Truncate this message
                remaining = char_limit - total_chars
                if remaining > 100:
                    truncated_content = msg["content"][:remaining] + "..."
                    result.insert(
                        0, {"role": msg["role"], "content": truncated_content}
                    )
                break

            result.insert(0, {"role": msg["role"], "content": msg["content"]})
            total_chars += content_len

        return result

    # =========================================================================
    # Semantic Memory (mem0 with pgvector + AWS Bedrock)
    # =========================================================================

    def add_semantic_memory(
        self, user_id: str, messages: List[Dict], metadata: Dict = None
    ) -> Optional[Dict]:
        """
        Add semantic memories from a conversation using mem0.

        mem0 automatically extracts facts and preferences from the conversation
        and stores them as embeddings for semantic search.

        Args:
            user_id: User identifier (email or session_id)
            messages: List of messages with 'role' and 'content'
            metadata: Optional metadata to attach

        Returns:
            mem0 response or None if mem0 unavailable
        """
        mem0 = self._get_mem0()
        if not mem0:
            logger.debug("mem0 not available, skipping semantic memory")
            return None

        try:
            result = mem0.add(messages, user_id=user_id, metadata=metadata or {})
            logger.debug(f"Added semantic memory for {user_id}: {result}")
            return result
        except Exception as e:
            logger.error(f"Failed to add semantic memory: {e}")
            return None

    def search_semantic_memory(
        self, query: str, user_id: str = None, limit: int = 5
    ) -> List[Dict]:
        """
        Search semantic memories using similarity search.

        Args:
            query: Search query
            user_id: Optional user ID to filter
            limit: Maximum results

        Returns:
            List of relevant memories
        """
        mem0 = self._get_mem0()
        if not mem0:
            return []

        try:
            results = mem0.search(query, user_id=user_id, limit=limit)
            return results.get("results", []) if isinstance(results, dict) else results
        except Exception as e:
            logger.error(f"Failed to search semantic memory: {e}")
            return []

    def get_all_semantic_memories(self, user_id: str) -> List[Dict]:
        """
        Get all semantic memories for a user.

        Args:
            user_id: User identifier

        Returns:
            List of all memories
        """
        mem0 = self._get_mem0()
        if not mem0:
            return []

        try:
            results = mem0.get_all(user_id=user_id)
            return results.get("results", []) if isinstance(results, dict) else results
        except Exception as e:
            logger.error(f"Failed to get semantic memories: {e}")
            return []

    def delete_semantic_memory(self, memory_id: str) -> bool:
        """Delete a specific semantic memory."""
        mem0 = self._get_mem0()
        if not mem0:
            return False

        try:
            mem0.delete(memory_id)
            return True
        except Exception as e:
            logger.error(f"Failed to delete semantic memory: {e}")
            return False

    # =========================================================================
    # User Memory (Simple PostgreSQL fallback)
    # =========================================================================

    def save_user_memory(
        self,
        user_email: str,
        memory_type: str,
        content: str,
        importance: float = 0.5,
        metadata: Dict = None,
    ) -> int:
        """
        Save a long-term memory for a user (simple PostgreSQL storage).

        Args:
            user_email: User email
            memory_type: Type of memory ('preference', 'fact', 'context')
            content: Memory content
            importance: Importance score (0-1)
            metadata: Optional metadata

        Returns:
            Memory ID
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO user_memory
                    (user_email, memory_type, content, importance, metadata)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """,
                (
                    user_email,
                    memory_type,
                    content,
                    importance,
                    json.dumps(metadata or {}),
                ),
            )

            return cursor.fetchone()[0]

        finally:
            cursor.close()

    def get_user_memories(
        self, user_email: str, memory_type: str = None, limit: int = 10
    ) -> List[Dict]:
        """
        Get user's long-term memories.

        Args:
            user_email: User email
            memory_type: Optional type filter
            limit: Maximum memories to return

        Returns:
            List of memory records
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            if memory_type:
                cursor.execute(
                    """
                    SELECT id, memory_type, content, importance, created_at
                    FROM user_memory
                    WHERE user_email = %s AND memory_type = %s
                    ORDER BY importance DESC, accessed_at DESC
                    LIMIT %s
                """,
                    (user_email, memory_type, limit),
                )
            else:
                cursor.execute(
                    """
                    SELECT id, memory_type, content, importance, created_at
                    FROM user_memory
                    WHERE user_email = %s
                    ORDER BY importance DESC, accessed_at DESC
                    LIMIT %s
                """,
                    (user_email, limit),
                )

            return [dict(row) for row in cursor.fetchall()]

        finally:
            cursor.close()

    def update_memory_access(self, memory_id: int):
        """Update memory accessed_at timestamp."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                UPDATE user_memory
                SET accessed_at = NOW()
                WHERE id = %s
            """,
                (memory_id,),
            )
        finally:
            cursor.close()


# =============================================================================
# Singleton Instance
# =============================================================================

_memory_service = None


def get_memory_service() -> MemoryService:
    """Get or create memory service singleton."""
    global _memory_service
    if _memory_service is None:
        _memory_service = MemoryService()
    return _memory_service


# Convenience alias
memory_service = None


def init_memory_service():
    """Initialize the memory service (call at app startup)."""
    global memory_service
    try:
        memory_service = get_memory_service()
        memory_service.init_schema()
        logger.info("Memory service initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize memory service: {e}")
        memory_service = None
