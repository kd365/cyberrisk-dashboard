"""
Forecast Cache Service
Persists forecast results (Prophet and Chronos) in RDS PostgreSQL
Falls back to in-memory cache if database is unavailable
Supports multiple model types with separate cache entries
"""

import json
import time
import os
from datetime import datetime, date
from typing import Optional, Dict, Any

# Database support (optional - falls back to in-memory if unavailable)
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor

    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False


class ForecastCache:
    """
    Hybrid cache for forecast results
    - Primary: RDS PostgreSQL (persistent across restarts)
    - Fallback: In-memory dict (if DB unavailable)

    Forecasts are cached per ticker + forecast_days + model_type for one day
    Supports both Prophet and Chronos models with separate cache entries
    """

    def __init__(self):
        """Initialize cache"""
        self.memory_cache = {}
        self.db_connection = None
        self.use_database = False

        # Try to connect to database
        self._init_database()

    def _init_database(self):
        """Initialize database connection if credentials are available"""
        if not PSYCOPG2_AVAILABLE:
            print("📦 ForecastCache: Using in-memory cache (psycopg2 not available)")
            return

        db_host = os.environ.get("DB_HOST")
        db_name = os.environ.get("DB_NAME", "cyberrisk")
        db_user = os.environ.get("DB_USER", "cyberrisk_admin")
        db_password = os.environ.get("DB_PASSWORD")

        if not db_host or not db_password:
            print(
                "📦 ForecastCache: Using in-memory cache (DB credentials not configured)"
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
            print(f"✅ ForecastCache: Connected to RDS PostgreSQL at {db_host}")

            # Ensure cache table exists
            self._ensure_table_exists()

        except Exception as e:
            print(
                f"⚠️  ForecastCache: Database connection failed ({e}), using in-memory cache"
            )
            self.use_database = False

    def _ensure_table_exists(self):
        """Create forecast_cache table if it doesn't exist, and add model_type column"""
        if not self.use_database:
            return

        try:
            cursor = self.db_connection.cursor()
            # Create table with model_type column
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS forecast_cache (
                    id SERIAL PRIMARY KEY,
                    ticker VARCHAR(10) NOT NULL,
                    forecast_days INT NOT NULL,
                    model_type VARCHAR(20) NOT NULL DEFAULT 'prophet',
                    forecast_data JSONB NOT NULL,
                    model_metrics JSONB,
                    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            self.db_connection.commit()

            # Add model_type column if it doesn't exist (migration for existing tables)
            cursor.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'forecast_cache' AND column_name = 'model_type'
                    ) THEN
                        ALTER TABLE forecast_cache
                        ADD COLUMN model_type VARCHAR(20) NOT NULL DEFAULT 'prophet';
                    END IF;
                END $$;
            """)
            self.db_connection.commit()

            # Create index including model_type
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_forecast_cache_model_lookup
                    ON forecast_cache(ticker, forecast_days, model_type, computed_at);
            """)
            self.db_connection.commit()
            cursor.close()
        except Exception as e:
            print(f"⚠️  Error creating/updating forecast_cache table: {e}")

    def _get_db_connection(self):
        """Get or refresh database connection"""
        if not self.use_database:
            return None

        try:
            cursor = self.db_connection.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            return self.db_connection
        except:
            self._init_database()
            return self.db_connection if self.use_database else None

    def _get_cache_key(
        self, ticker: str, forecast_days: int, model_type: str = "prophet"
    ) -> str:
        """Generate cache key including model type"""
        today = date.today().isoformat()
        return f"forecast_{ticker}_{forecast_days}_{model_type}_{today}"

    def get(
        self, ticker: str, forecast_days: int = 30, model_type: str = "prophet"
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached forecast if available from today

        Args:
            ticker: Stock ticker symbol
            forecast_days: Number of days forecasted
            model_type: Model type - 'prophet' or 'chronos'

        Returns:
            dict or None: Cached forecast data or None if not found
        """
        # Try database first
        if self.use_database:
            result = self._get_from_db(ticker, forecast_days, model_type)
            if result:
                print(f"✅ Forecast Cache HIT (RDS) for {ticker} [{model_type}]")
                return result

        # Fall back to memory cache
        cache_key = self._get_cache_key(ticker, forecast_days, model_type)
        if cache_key in self.memory_cache:
            print(f"✅ Forecast Cache HIT (memory) for {ticker} [{model_type}]")
            return self.memory_cache[cache_key]["data"]

        return None

    def get_all_models(
        self, ticker: str, forecast_days: int = 30
    ) -> Dict[str, Optional[Dict[str, Any]]]:
        """
        Get cached forecasts for ALL models for a ticker

        Args:
            ticker: Stock ticker symbol
            forecast_days: Number of days forecasted

        Returns:
            Dict with 'prophet' and 'chronos' keys, each containing cached data or None
        """
        return {
            "prophet": self.get(ticker, forecast_days, "prophet"),
            "chronos": self.get(ticker, forecast_days, "chronos"),
        }

    def _get_from_db(
        self, ticker: str, forecast_days: int, model_type: str = "prophet"
    ) -> Optional[Dict[str, Any]]:
        """Get forecast from database (only if computed today)"""
        conn = self._get_db_connection()
        if not conn:
            return None

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            # Only get forecasts computed today for specific model
            cursor.execute(
                """
                SELECT forecast_data, model_metrics, computed_at
                FROM forecast_cache
                WHERE ticker = %s
                  AND forecast_days = %s
                  AND model_type = %s
                  AND DATE(computed_at) = CURRENT_DATE
                ORDER BY computed_at DESC
                LIMIT 1
            """,
                (ticker, forecast_days, model_type),
            )

            row = cursor.fetchone()
            cursor.close()

            if row:
                data = row["forecast_data"]
                if row["model_metrics"]:
                    data["model_metrics"] = row["model_metrics"]
                data["cached_at"] = row["computed_at"].isoformat()
                data["model_type"] = model_type
                return data
            return None

        except Exception as e:
            print(f"⚠️  Error reading from forecast_cache: {e}")
            return None

    def set(
        self,
        ticker: str,
        forecast_days: int,
        data: Dict[str, Any],
        model_type: str = "prophet",
        model_metrics: Optional[Dict] = None,
    ):
        """
        Store forecast data in cache

        Args:
            ticker: Stock ticker symbol
            forecast_days: Number of days forecasted
            data: Forecast data to cache
            model_type: Model type - 'prophet' or 'chronos'
            model_metrics: Optional model evaluation metrics
        """
        # Store in database
        if self.use_database:
            self._set_in_db(ticker, forecast_days, data, model_type, model_metrics)

        # Also store in memory for fast access
        cache_key = self._get_cache_key(ticker, forecast_days, model_type)
        self.memory_cache[cache_key] = {
            "data": data,
            "timestamp": time.time(),
            "ticker": ticker,
            "model_type": model_type,
        }

        print(
            f"💾 Cached forecast data for {ticker} ({forecast_days} days) [{model_type}]"
        )

    def _set_in_db(
        self,
        ticker: str,
        forecast_days: int,
        data: Dict[str, Any],
        model_type: str = "prophet",
        model_metrics: Optional[Dict] = None,
    ):
        """Store forecast data in database"""
        conn = self._get_db_connection()
        if not conn:
            return

        try:
            cursor = conn.cursor()

            # Clean the data for JSON serialization
            clean_data = self._clean_for_json(data)
            clean_metrics = (
                self._clean_for_json(model_metrics) if model_metrics else None
            )

            cursor.execute(
                """
                INSERT INTO forecast_cache (ticker, forecast_days, model_type, forecast_data, model_metrics, computed_at)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            """,
                (
                    ticker,
                    forecast_days,
                    model_type,
                    json.dumps(clean_data),
                    json.dumps(clean_metrics) if clean_metrics else None,
                ),
            )

            conn.commit()
            cursor.close()
            print(f"💾 Saved to RDS: forecast for {ticker} [{model_type}]")

        except Exception as e:
            print(f"⚠️  Error writing to forecast_cache: {e}")
            try:
                conn.rollback()
            except:
                pass

    def _clean_for_json(self, obj):
        """Convert non-JSON-serializable objects (numpy, pandas, datetime)"""
        if obj is None:
            return None

        if isinstance(obj, dict):
            return {k: self._clean_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._clean_for_json(item) for item in obj]
        elif hasattr(obj, "tolist"):  # numpy array
            return obj.tolist()
        elif hasattr(obj, "isoformat"):  # datetime
            return obj.isoformat()
        elif hasattr(obj, "item"):  # numpy scalar
            return obj.item()
        else:
            return obj

    def invalidate(self, ticker: str = None, model_type: str = None):
        """
        Invalidate cache entries (used by refresh button)

        Args:
            ticker: If provided, only invalidate this ticker. Otherwise clear all.
            model_type: If provided, only invalidate this model type. Otherwise clear all models.
        """
        # Clear memory cache
        if ticker is None:
            count = len(self.memory_cache)
            self.memory_cache = {}
            print(f"🗑️  Cleared all forecast memory cache ({count} entries)")
        else:
            keys_to_delete = [
                k
                for k in self.memory_cache.keys()
                if ticker in k and (model_type is None or model_type in k)
            ]
            for key in keys_to_delete:
                del self.memory_cache[key]
            model_info = f" [{model_type}]" if model_type else ""
            print(f"🗑️  Cleared forecast memory cache for {ticker}{model_info}")

        # Clear database cache
        if self.use_database:
            self._invalidate_db(ticker, model_type)

    def _invalidate_db(self, ticker: str = None, model_type: str = None):
        """Clear database cache entries"""
        conn = self._get_db_connection()
        if not conn:
            return

        try:
            cursor = conn.cursor()
            if ticker and model_type:
                cursor.execute(
                    "DELETE FROM forecast_cache WHERE ticker = %s AND model_type = %s",
                    (ticker, model_type),
                )
                print(f"🗑️  Cleared RDS forecast cache for {ticker} [{model_type}]")
            elif ticker:
                cursor.execute(
                    "DELETE FROM forecast_cache WHERE ticker = %s", (ticker,)
                )
                print(f"🗑️  Cleared RDS forecast cache for {ticker}")
            else:
                cursor.execute("DELETE FROM forecast_cache")
                print(f"🗑️  Cleared all RDS forecast cache")
            conn.commit()
            cursor.close()
        except Exception as e:
            print(f"⚠️  Error clearing forecast_cache: {e}")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        stats = {
            "memory_entries": len(self.memory_cache),
            "using_database": self.use_database,
        }

        if self.use_database:
            conn = self._get_db_connection()
            if conn:
                try:
                    cursor = conn.cursor(cursor_factory=RealDictCursor)
                    cursor.execute("""
                        SELECT ticker, forecast_days, COUNT(*) as count,
                               MAX(computed_at) as last_computed
                        FROM forecast_cache
                        GROUP BY ticker, forecast_days
                        ORDER BY last_computed DESC
                    """)
                    rows = cursor.fetchall()
                    cursor.close()

                    stats["database_entries"] = sum(row["count"] for row in rows)
                    stats["database_by_ticker"] = {}
                    for row in rows:
                        ticker = row["ticker"]
                        if ticker not in stats["database_by_ticker"]:
                            stats["database_by_ticker"][ticker] = []
                        stats["database_by_ticker"][ticker].append(
                            {
                                "forecast_days": row["forecast_days"],
                                "count": row["count"],
                                "last_computed": (
                                    row["last_computed"].isoformat()
                                    if row["last_computed"]
                                    else None
                                ),
                            }
                        )
                except Exception as e:
                    stats["database_error"] = str(e)

        return stats


# Global forecast cache instance
forecast_cache = ForecastCache()


# Helper functions for LLM chat service
def get_cached_forecast(
    ticker: str, model: str = "prophet", days: int = 30
) -> Optional[Dict[str, Any]]:
    """Get cached forecast - wrapper for LLM service."""
    return forecast_cache.get(ticker, days, model)


def get_stock_data(ticker: str) -> Optional[Dict[str, Any]]:
    """Get current stock data for a ticker using yfinance."""
    try:
        import yfinance as yf

        stock = yf.Ticker(ticker)
        hist = stock.history(period="5d")
        if hist.empty:
            return None

        current_price = float(hist["Close"].iloc[-1])
        prev_close = float(hist["Close"].iloc[-2]) if len(hist) > 1 else current_price
        change_pct = ((current_price - prev_close) / prev_close) * 100

        return {
            "current_price": round(current_price, 2),
            "previous_close": round(prev_close, 2),
            "change_pct": round(change_pct, 2),
        }
    except Exception as e:
        print(f"Error fetching stock data for {ticker}: {e}")
        return None
