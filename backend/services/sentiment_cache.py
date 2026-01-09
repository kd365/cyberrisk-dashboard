"""
Sentiment Analysis Cache Service
Persists sentiment analysis results in RDS PostgreSQL to reduce AWS Comprehend costs
Falls back to in-memory cache if database is unavailable
"""

import json
import time
import hashlib
import os
from datetime import datetime
from typing import Optional, Dict, Any, List

# Database support (optional - falls back to in-memory if unavailable)
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor

    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False
    print("⚠️  psycopg2 not installed. Using in-memory cache only.")


class SentimentCache:
    """
    Hybrid cache for sentiment analysis results
    - Primary: RDS PostgreSQL (persistent across restarts)
    - Fallback: In-memory dict (if DB unavailable)
    """

    def __init__(self, ttl_seconds: int = 86400):  # Default 24 hours for RDS cache
        """
        Initialize cache

        Args:
            ttl_seconds: Time to live for cached items (default 24 hours for persistent cache)
        """
        self.memory_cache = {}
        self.ttl = ttl_seconds
        self.db_connection = None
        self.use_database = False

        # Try to connect to database
        self._init_database()

    def _init_database(self):
        """Initialize database connection if credentials are available"""
        if not PSYCOPG2_AVAILABLE:
            print("📦 SentimentCache: Using in-memory cache (psycopg2 not available)")
            return

        db_host = os.environ.get("DB_HOST")
        db_name = os.environ.get("DB_NAME", "cyberrisk")
        db_user = os.environ.get("DB_USER", "cyberrisk_admin")
        db_password = os.environ.get("DB_PASSWORD")

        if not db_host or not db_password:
            print(
                "📦 SentimentCache: Using in-memory cache (DB credentials not configured)"
            )
            return

        try:
            self.db_connection = psycopg2.connect(
                host=db_host,
                database=db_name,
                user=db_user,
                password=db_password,
                port=5432,
            )
            self.use_database = True
            print(f"✅ SentimentCache: Connected to RDS PostgreSQL at {db_host}")

            # Ensure cache table exists
            self._ensure_table_exists()

        except Exception as e:
            print(
                f"⚠️  SentimentCache: Database connection failed ({e}), using in-memory cache"
            )
            self.use_database = False

    def _ensure_table_exists(self):
        """Create sentiment_cache table if it doesn't exist"""
        if not self.use_database:
            return

        try:
            cursor = self.db_connection.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS sentiment_cache (
                    id SERIAL PRIMARY KEY,
                    ticker VARCHAR(10) NOT NULL,
                    artifact_hash VARCHAR(64) NOT NULL,
                    sentiment_data JSONB NOT NULL,
                    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(ticker, artifact_hash)
                );
                CREATE INDEX IF NOT EXISTS idx_sentiment_cache_lookup
                    ON sentiment_cache(ticker, artifact_hash);
            """
            )
            self.db_connection.commit()
            cursor.close()
        except Exception as e:
            print(f"⚠️  Error creating sentiment_cache table: {e}")

    def _get_db_connection(self):
        """Get or refresh database connection"""
        if not self.use_database:
            return None

        try:
            # Test if connection is alive
            cursor = self.db_connection.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            return self.db_connection
        except:
            # Reconnect
            self._init_database()
            return self.db_connection if self.use_database else None

    def _generate_cache_key(self, ticker: str, artifacts: List[Dict]) -> str:
        """
        Generate unique cache key based on ticker and artifacts

        Args:
            ticker: Stock ticker symbol
            artifacts: List of artifacts

        Returns:
            str: MD5 hash of ticker + artifact keys
        """
        # Create hash of ticker + artifact keys to detect changes
        artifact_keys = sorted(
            [a.get("s3_key", "") for a in artifacts if a.get("ticker") == ticker]
        )
        content = f"{ticker}:{':'.join(artifact_keys)}"
        return hashlib.md5(content.encode()).hexdigest()

    def get(self, ticker: str, artifacts: List[Dict]) -> Optional[Dict[str, Any]]:
        """
        Get cached sentiment data if available

        Args:
            ticker: Stock ticker symbol
            artifacts: List of artifacts

        Returns:
            dict or None: Cached sentiment data or None if not found
        """
        cache_key = self._generate_cache_key(ticker, artifacts)

        # Try database first
        if self.use_database:
            result = self._get_from_db(ticker, cache_key)
            if result:
                print(
                    f"✅ Cache HIT (RDS) for {ticker} - saved AWS Comprehend API calls!"
                )
                return result

        # Fall back to memory cache
        memory_key = f"sentiment_{ticker}_{cache_key}"
        if memory_key in self.memory_cache:
            cached_item = self.memory_cache[memory_key]
            # Check if expired (only for memory cache)
            if time.time() - cached_item["timestamp"] <= self.ttl:
                print(f"✅ Cache HIT (memory) for {ticker}")
                return cached_item["data"]
            else:
                del self.memory_cache[memory_key]

        return None

    def _get_from_db(self, ticker: str, artifact_hash: str) -> Optional[Dict[str, Any]]:
        """Get sentiment data from database"""
        conn = self._get_db_connection()
        if not conn:
            return None

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                """
                SELECT sentiment_data, computed_at
                FROM sentiment_cache
                WHERE ticker = %s AND artifact_hash = %s
            """,
                (ticker, artifact_hash),
            )

            row = cursor.fetchone()
            cursor.close()

            if row:
                # Return the cached data (JSONB is auto-converted to dict)
                return row["sentiment_data"]
            return None

        except Exception as e:
            print(f"⚠️  Error reading from sentiment_cache: {e}")
            return None

    def set(self, ticker: str, artifacts: List[Dict], data: Dict[str, Any]):
        """
        Store sentiment data in cache

        Args:
            ticker: Stock ticker symbol
            artifacts: List of artifacts
            data: Sentiment analysis data to cache
        """
        cache_key = self._generate_cache_key(ticker, artifacts)

        # Store in database
        if self.use_database:
            self._set_in_db(ticker, cache_key, data)

        # Also store in memory for fast access
        memory_key = f"sentiment_{ticker}_{cache_key}"
        self.memory_cache[memory_key] = {
            "data": data,
            "timestamp": time.time(),
            "ticker": ticker,
        }

        print(f"💾 Cached sentiment data for {ticker}")

    def _set_in_db(self, ticker: str, artifact_hash: str, data: Dict[str, Any]):
        """Store sentiment data in database"""
        conn = self._get_db_connection()
        if not conn:
            return

        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO sentiment_cache (ticker, artifact_hash, sentiment_data, computed_at)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (ticker, artifact_hash)
                DO UPDATE SET
                    sentiment_data = EXCLUDED.sentiment_data,
                    computed_at = CURRENT_TIMESTAMP
            """,
                (ticker, artifact_hash, json.dumps(data)),
            )

            conn.commit()
            cursor.close()
            print(f"💾 Saved to RDS: sentiment for {ticker}")

        except Exception as e:
            print(f"⚠️  Error writing to sentiment_cache: {e}")
            try:
                conn.rollback()
            except:
                pass

    def invalidate(self, ticker: str = None):
        """
        Invalidate cache entries (used by refresh button)

        Args:
            ticker: If provided, only invalidate this ticker. Otherwise clear all.
        """
        # Clear memory cache
        if ticker is None:
            count = len(self.memory_cache)
            self.memory_cache = {}
            print(f"🗑️  Cleared memory cache ({count} entries)")
        else:
            keys_to_delete = [
                k
                for k in self.memory_cache.keys()
                if self.memory_cache[k]["ticker"] == ticker
            ]
            for key in keys_to_delete:
                del self.memory_cache[key]
            print(f"🗑️  Cleared memory cache for {ticker}")

        # Clear database cache
        if self.use_database:
            self._invalidate_db(ticker)

    def _invalidate_db(self, ticker: str = None):
        """Clear database cache entries"""
        conn = self._get_db_connection()
        if not conn:
            return

        try:
            cursor = conn.cursor()
            if ticker:
                cursor.execute(
                    "DELETE FROM sentiment_cache WHERE ticker = %s", (ticker,)
                )
                print(f"🗑️  Cleared RDS cache for {ticker}")
            else:
                cursor.execute("DELETE FROM sentiment_cache")
                print(f"🗑️  Cleared all RDS sentiment cache")
            conn.commit()
            cursor.close()
        except Exception as e:
            print(f"⚠️  Error clearing sentiment_cache: {e}")

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics

        Returns:
            dict: Cache statistics including both memory and DB counts
        """
        stats = {
            "memory_entries": len(self.memory_cache),
            "by_ticker": {},
            "ttl_seconds": self.ttl,
            "using_database": self.use_database,
        }

        # Count memory cache by ticker
        for item in self.memory_cache.values():
            ticker = item["ticker"]
            stats["by_ticker"][ticker] = stats["by_ticker"].get(ticker, 0) + 1

        # Get database stats
        if self.use_database:
            conn = self._get_db_connection()
            if conn:
                try:
                    cursor = conn.cursor(cursor_factory=RealDictCursor)
                    cursor.execute(
                        """
                        SELECT ticker, COUNT(*) as count, MAX(computed_at) as last_computed
                        FROM sentiment_cache
                        GROUP BY ticker
                    """
                    )
                    rows = cursor.fetchall()
                    cursor.close()

                    stats["database_entries"] = sum(row["count"] for row in rows)
                    stats["database_by_ticker"] = {
                        row["ticker"]: {
                            "count": row["count"],
                            "last_computed": (
                                row["last_computed"].isoformat()
                                if row["last_computed"]
                                else None
                            ),
                        }
                        for row in rows
                    }
                except Exception as e:
                    stats["database_error"] = str(e)

        return stats

    def cleanup_expired(self) -> int:
        """
        Remove expired entries from memory cache
        (Database entries don't expire - they're updated on next refresh)

        Returns:
            int: Number of memory entries removed
        """
        current_time = time.time()
        keys_to_delete = []

        for key, item in self.memory_cache.items():
            if current_time - item["timestamp"] > self.ttl:
                keys_to_delete.append(key)

        for key in keys_to_delete:
            del self.memory_cache[key]

        if keys_to_delete:
            print(f"🧹 Cleaned up {len(keys_to_delete)} expired memory cache entries")

        return len(keys_to_delete)
