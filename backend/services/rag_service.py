# =============================================================================
# RAG Service - Retrieval-Augmented Generation Pipeline
# =============================================================================
#
# This service implements a complete RAG pipeline for document-based Q&A:
#   1. Document Loading - Via OCR service (SEC filings, transcripts)
#   2. Text Splitting - Chunk documents into semantic units
#   3. Embeddings - Generate vectors using AWS Bedrock Titan
#   4. Vector Store - Store/retrieve from PostgreSQL with pgvector
#   5. Retrieval - Find relevant passages for LLM context
#
# Assessment Requirement:
#   "Build a Retrieval-Augmented Generation (RAG) pipeline with document
#    loading, text splitting, embeddings, and vector store integration"
#
# =============================================================================

import os
import json
import logging
import hashlib
from typing import List, Dict, Optional, Tuple
from datetime import datetime

import boto3
from botocore.config import Config
import psycopg2
from psycopg2.extras import execute_values

logger = logging.getLogger(__name__)


class RAGService:
    """
    RAG pipeline for cybersecurity document retrieval and Q&A.

    Integrates with:
    - OCR Service: Document text extraction
    - AWS Bedrock: Titan embeddings
    - PostgreSQL + pgvector: Vector storage and similarity search
    - LangChain Agent: Provides retrieved context for responses
    """

    # Chunking configuration
    CHUNK_SIZE = 1000  # Characters per chunk
    CHUNK_OVERLAP = 200  # Overlap between chunks for context continuity

    # Embedding configuration
    EMBEDDING_MODEL = "amazon.titan-embed-text-v2:0"
    EMBEDDING_DIMENSIONS = 1024

    def __init__(self):
        """Initialize RAG service with AWS and database connections."""
        self.region = os.environ.get("AWS_REGION", "us-west-2")

        # AWS Bedrock client for embeddings
        config = Config(
            region_name=self.region, retries={"max_attempts": 3, "mode": "adaptive"}
        )
        self.bedrock = boto3.client("bedrock-runtime", config=config)

        # Database connection parameters
        self.db_host = os.environ.get("DB_HOST", "localhost")
        self.db_port = os.environ.get("DB_PORT", "5432")
        self.db_name = os.environ.get("DB_NAME", "cyberrisk")
        self.db_user = os.environ.get("DB_USER", "postgres")
        self.db_password = os.environ.get("DB_PASSWORD", "")

        # Initialize schema
        self._init_schema()

        logger.info("RAG Service initialized")

    def _get_connection(self):
        """Get database connection."""
        return psycopg2.connect(
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
            user=self.db_user,
            password=self.db_password,
        )

    def _init_schema(self):
        """Initialize pgvector extension and document chunks table."""
        try:
            conn = self._get_connection()
            cur = conn.cursor()

            # Enable pgvector extension
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")

            # Create document chunks table with vector column
            cur.execute("""
                CREATE TABLE IF NOT EXISTS document_chunks (
                    id SERIAL PRIMARY KEY,
                    document_id VARCHAR(255) NOT NULL,
                    ticker VARCHAR(10),
                    document_type VARCHAR(50),
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    embedding vector(1024),
                    metadata JSONB DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(document_id, chunk_index)
                );
            """)

            # Create index for vector similarity search
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_chunks_embedding
                ON document_chunks
                USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100);
            """)

            # Create index for filtering by ticker
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_chunks_ticker
                ON document_chunks(ticker);
            """)

            # Create index for document lookup
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_chunks_document
                ON document_chunks(document_id);
            """)

            conn.commit()
            cur.close()
            conn.close()

            logger.info("RAG schema initialized with pgvector")

        except Exception as e:
            logger.error(f"Failed to initialize RAG schema: {e}")
            raise

    # =========================================================================
    # Text Splitting
    # =========================================================================

    def split_text(
        self, text: str, chunk_size: int = None, chunk_overlap: int = None
    ) -> List[Dict]:
        """
        Split text into overlapping chunks for embedding.

        Uses a recursive character-based splitting strategy that tries
        to break at natural boundaries (paragraphs, sentences, words).

        Args:
            text: Full document text
            chunk_size: Max characters per chunk (default: 1000)
            chunk_overlap: Overlap between chunks (default: 200)

        Returns:
            List of chunk dictionaries with content and metadata
        """
        chunk_size = chunk_size or self.CHUNK_SIZE
        chunk_overlap = chunk_overlap or self.CHUNK_OVERLAP

        if not text or len(text) < chunk_size:
            return [{"content": text, "index": 0}] if text else []

        chunks = []
        separators = ["\n\n", "\n", ". ", " ", ""]

        def split_recursive(text: str, separators: List[str]) -> List[str]:
            """Recursively split text using separators."""
            if not separators:
                return [
                    text[i : i + chunk_size]
                    for i in range(0, len(text), chunk_size - chunk_overlap)
                ]

            separator = separators[0]
            splits = text.split(separator) if separator else [text]

            result = []
            current_chunk = ""

            for split in splits:
                # Add separator back (except for empty separator)
                piece = split + separator if separator else split

                if len(current_chunk) + len(piece) <= chunk_size:
                    current_chunk += piece
                else:
                    if current_chunk:
                        result.append(current_chunk.strip())
                    # If single piece is too large, split further
                    if len(piece) > chunk_size:
                        result.extend(split_recursive(piece, separators[1:]))
                        current_chunk = ""
                    else:
                        current_chunk = piece

            if current_chunk.strip():
                result.append(current_chunk.strip())

            return result

        raw_chunks = split_recursive(text, separators)

        # Add overlap between chunks
        for i, chunk in enumerate(raw_chunks):
            chunk_data = {
                "content": chunk,
                "index": i,
                "char_start": sum(len(raw_chunks[j]) for j in range(i)),
                "char_end": sum(len(raw_chunks[j]) for j in range(i + 1)),
            }
            chunks.append(chunk_data)

        logger.info(
            f"Split text into {len(chunks)} chunks (avg {len(text) // max(len(chunks), 1)} chars each)"
        )
        return chunks

    # =========================================================================
    # Embeddings
    # =========================================================================

    def generate_embedding(self, text: str) -> Optional[List[float]]:
        """
        Generate embedding vector using AWS Bedrock Titan.

        Args:
            text: Text to embed (max ~8000 tokens)

        Returns:
            1024-dimensional embedding vector, or None on error
        """
        try:
            # Truncate if too long (Titan limit is ~8000 tokens)
            if len(text) > 25000:
                text = text[:25000]

            response = self.bedrock.invoke_model(
                modelId=self.EMBEDDING_MODEL,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(
                    {
                        "inputText": text,
                        "dimensions": self.EMBEDDING_DIMENSIONS,
                        "normalize": True,
                    }
                ),
            )

            result = json.loads(response["body"].read())
            embedding = result.get("embedding")

            if embedding and len(embedding) == self.EMBEDDING_DIMENSIONS:
                return embedding
            else:
                logger.error(
                    f"Unexpected embedding dimensions: {len(embedding) if embedding else 0}"
                )
                return None

        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            return None

    def generate_embeddings_batch(
        self, texts: List[str], batch_size: int = 10
    ) -> List[Optional[List[float]]]:
        """
        Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed
            batch_size: Process this many at a time

        Returns:
            List of embeddings (same order as input)
        """
        embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            for text in batch:
                embedding = self.generate_embedding(text)
                embeddings.append(embedding)

            logger.info(f"Generated embeddings: {len(embeddings)}/{len(texts)}")

        return embeddings

    # =========================================================================
    # Vector Store Operations
    # =========================================================================

    def index_document(
        self,
        document_id: str,
        text: str,
        ticker: str = None,
        document_type: str = None,
        metadata: Dict = None,
    ) -> int:
        """
        Index a document by chunking, embedding, and storing in pgvector.

        Args:
            document_id: Unique identifier (e.g., S3 key)
            text: Full document text
            ticker: Company ticker symbol
            document_type: Type of document (10-K, 10-Q, transcript, etc.)
            metadata: Additional metadata to store

        Returns:
            Number of chunks indexed
        """
        if not text:
            logger.warning(f"Empty text for document {document_id}")
            return 0

        # Split into chunks
        chunks = self.split_text(text)

        if not chunks:
            logger.warning(f"No chunks generated for document {document_id}")
            return 0

        # Generate embeddings
        embeddings = self.generate_embeddings_batch([c["content"] for c in chunks])

        # Store in database
        conn = self._get_connection()
        cur = conn.cursor()

        try:
            # Delete existing chunks for this document (re-indexing)
            cur.execute(
                "DELETE FROM document_chunks WHERE document_id = %s", (document_id,)
            )

            # Insert new chunks
            indexed = 0
            for chunk, embedding in zip(chunks, embeddings):
                if embedding is None:
                    continue

                chunk_metadata = {
                    **(metadata or {}),
                    "char_start": chunk.get("char_start"),
                    "char_end": chunk.get("char_end"),
                    "indexed_at": datetime.utcnow().isoformat(),
                }

                cur.execute(
                    """
                    INSERT INTO document_chunks
                    (document_id, ticker, document_type, chunk_index, content, embedding, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                    (
                        document_id,
                        ticker,
                        document_type,
                        chunk["index"],
                        chunk["content"],
                        embedding,
                        json.dumps(chunk_metadata),
                    ),
                )
                indexed += 1

            conn.commit()
            logger.info(f"Indexed {indexed} chunks for document {document_id}")
            return indexed

        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to index document {document_id}: {e}")
            raise

        finally:
            cur.close()
            conn.close()

    def search(
        self,
        query: str,
        ticker: str = None,
        document_type: str = None,
        limit: int = 5,
        similarity_threshold: float = 0.7,
    ) -> List[Dict]:
        """
        Search for relevant document chunks using semantic similarity.

        Args:
            query: Search query text
            ticker: Filter by company ticker
            document_type: Filter by document type
            limit: Maximum number of results
            similarity_threshold: Minimum similarity score (0-1)

        Returns:
            List of relevant chunks with similarity scores
        """
        # Generate query embedding
        query_embedding = self.generate_embedding(query)
        if not query_embedding:
            logger.error("Failed to generate query embedding")
            return []

        conn = self._get_connection()
        cur = conn.cursor()

        try:
            # Build query with optional filters
            sql = """
                SELECT
                    document_id,
                    ticker,
                    document_type,
                    chunk_index,
                    content,
                    metadata,
                    1 - (embedding <=> %s::vector) as similarity
                FROM document_chunks
                WHERE 1=1
            """
            params = [query_embedding]

            if ticker:
                sql += " AND ticker = %s"
                params.append(ticker)

            if document_type:
                sql += " AND document_type = %s"
                params.append(document_type)

            sql += """
                AND 1 - (embedding <=> %s::vector) >= %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            """
            params.extend(
                [query_embedding, similarity_threshold, query_embedding, limit]
            )

            cur.execute(sql, params)
            rows = cur.fetchall()

            results = []
            for row in rows:
                results.append(
                    {
                        "document_id": row[0],
                        "ticker": row[1],
                        "document_type": row[2],
                        "chunk_index": row[3],
                        "content": row[4],
                        "metadata": row[5],
                        "similarity": float(row[6]),
                    }
                )

            logger.info(f"Found {len(results)} relevant chunks for query")
            return results

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

        finally:
            cur.close()
            conn.close()

    def get_context_for_query(
        self, query: str, ticker: str = None, max_tokens: int = 3000
    ) -> str:
        """
        Get formatted context string for LLM from relevant documents.

        This is the main method used by the LangChain agent to retrieve
        document context for answering questions.

        Args:
            query: User's question
            ticker: Optional company filter
            max_tokens: Approximate max tokens for context

        Returns:
            Formatted context string with relevant passages
        """
        results = self.search(query, ticker=ticker, limit=10)

        if not results:
            return ""

        context_parts = []
        total_chars = 0
        max_chars = max_tokens * 4  # Rough token-to-char estimate

        for result in results:
            chunk_text = (
                f"[{result['document_type']} - {result['ticker']}]\n{result['content']}"
            )

            if total_chars + len(chunk_text) > max_chars:
                break

            context_parts.append(chunk_text)
            total_chars += len(chunk_text)

        context = "\n\n---\n\n".join(context_parts)

        logger.info(
            f"Retrieved {len(context_parts)} passages ({total_chars} chars) for context"
        )
        return context

    # =========================================================================
    # Document Management
    # =========================================================================

    def get_indexed_documents(self, ticker: str = None) -> List[Dict]:
        """Get list of indexed documents."""
        conn = self._get_connection()
        cur = conn.cursor()

        try:
            sql = """
                SELECT DISTINCT
                    document_id,
                    ticker,
                    document_type,
                    COUNT(*) as chunk_count,
                    MIN(created_at) as indexed_at
                FROM document_chunks
            """

            if ticker:
                sql += " WHERE ticker = %s"
                sql += " GROUP BY document_id, ticker, document_type"
                cur.execute(sql, (ticker,))
            else:
                sql += " GROUP BY document_id, ticker, document_type"
                cur.execute(sql)

            rows = cur.fetchall()

            return [
                {
                    "document_id": row[0],
                    "ticker": row[1],
                    "document_type": row[2],
                    "chunk_count": row[3],
                    "indexed_at": row[4].isoformat() if row[4] else None,
                }
                for row in rows
            ]

        finally:
            cur.close()
            conn.close()

    def delete_document(self, document_id: str) -> int:
        """Delete a document and its chunks from the index."""
        conn = self._get_connection()
        cur = conn.cursor()

        try:
            cur.execute(
                "DELETE FROM document_chunks WHERE document_id = %s", (document_id,)
            )
            deleted = cur.rowcount
            conn.commit()
            logger.info(f"Deleted {deleted} chunks for document {document_id}")
            return deleted

        finally:
            cur.close()
            conn.close()

    def get_stats(self, ticker: str = None) -> Dict:
        """Get RAG index statistics, optionally filtered by ticker."""
        conn = self._get_connection()
        cur = conn.cursor()

        try:
            if ticker:
                cur.execute(
                    """
                    SELECT
                        COUNT(DISTINCT document_id) as document_count,
                        COUNT(*) as chunk_count,
                        COUNT(DISTINCT document_type) as doc_type_count,
                        AVG(LENGTH(content)) as avg_chunk_size
                    FROM document_chunks
                    WHERE ticker = %s
                """,
                    (ticker,),
                )
            else:
                cur.execute("""
                    SELECT
                        COUNT(DISTINCT document_id) as document_count,
                        COUNT(*) as chunk_count,
                        COUNT(DISTINCT ticker) as ticker_count,
                        AVG(LENGTH(content)) as avg_chunk_size
                    FROM document_chunks
                """)

            row = cur.fetchone()

            stats = {
                "documents_indexed": row[0] or 0,
                "total_chunks": row[1] or 0,
                "avg_chunk_size": int(row[3]) if row[3] else 0,
            }

            if ticker:
                stats["ticker"] = ticker
                stats["document_types"] = row[2] or 0
            else:
                stats["tickers_covered"] = row[2] or 0

            return stats

        finally:
            cur.close()
            conn.close()


# =============================================================================
# Integration with OCR Service
# =============================================================================


def index_s3_document(
    s3_key: str, ticker: str = None, document_type: str = None
) -> Dict:
    """
    Convenience function to index a document from S3.

    Combines OCR extraction with RAG indexing.

    Args:
        s3_key: S3 key of the document
        ticker: Company ticker
        document_type: Document type (10-K, 10-Q, transcript)

    Returns:
        Dict with indexing results
    """
    from services.ocr_service import get_ocr_service

    # Extract text
    ocr = get_ocr_service()
    text = ocr.extract_text_from_s3(s3_key)

    if not text:
        logger.error(f"Failed to extract text from {s3_key}")
        return {
            "s3_key": s3_key,
            "success": False,
            "error": "Failed to extract text",
            "chunks_indexed": 0,
        }

    # Check quality
    is_ok, reason = ocr.is_text_quality_acceptable(text)
    quality_warning = None if is_ok else reason

    # Index
    rag = get_rag_service()
    chunks_indexed = rag.index_document(
        document_id=s3_key,
        text=text,
        ticker=ticker,
        document_type=document_type,
        metadata={"s3_key": s3_key, "source": "s3"},
    )

    result = {
        "s3_key": s3_key,
        "success": chunks_indexed > 0,
        "chunks_indexed": chunks_indexed,
        "text_length": len(text),
        "ticker": ticker,
        "document_type": document_type,
    }

    if quality_warning:
        result["quality_warning"] = quality_warning

    return result


# =============================================================================
# Singleton Instance
# =============================================================================

_rag_service = None


def get_rag_service() -> RAGService:
    """Get or create RAG service singleton."""
    global _rag_service
    if _rag_service is None:
        _rag_service = RAGService()
    return _rag_service
