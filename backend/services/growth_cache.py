"""
Growth Metrics Cache Service
Persists Explorium growth data (employee counts, hiring events) in RDS PostgreSQL
Tracks historical growth trends for trend classification (accelerating, stable, slowing, declining)
"""

import json
import time
import hashlib
import os
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List

# Database support
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False
    print("⚠️  psycopg2 not installed. Growth cache operations unavailable.")


class GrowthCache:
    """
    Cache for Explorium growth metrics data
    - Stores employee count snapshots over time
    - Tracks hiring events for velocity analysis
    - Computes and caches growth trend classifications
    """

    def __init__(self, cache_ttl_hours: int = 24):
        """
        Initialize growth cache

        Args:
            cache_ttl_hours: Time to live for cached API responses (default 24 hours)
        """
        self.cache_ttl_hours = cache_ttl_hours
        self.db_connection = None
        self.use_database = False
        self._init_database()

    def _init_database(self):
        """Initialize database connection"""
        if not PSYCOPG2_AVAILABLE:
            print("📦 GrowthCache: psycopg2 not available")
            return

        db_host = os.environ.get('DB_HOST')
        db_name = os.environ.get('DB_NAME', 'cyberrisk')
        db_user = os.environ.get('DB_USER', 'cyberrisk_admin')
        db_password = os.environ.get('DB_PASSWORD')

        if not db_host or not db_password:
            print("📦 GrowthCache: DB credentials not configured")
            return

        try:
            self.db_connection = psycopg2.connect(
                host=db_host,
                database=db_name,
                user=db_user,
                password=db_password,
                port=5432
            )
            self.use_database = True
            print(f"✅ GrowthCache: Connected to RDS PostgreSQL at {db_host}")

        except Exception as e:
            print(f"⚠️  GrowthCache: Database connection failed ({e})")
            self.use_database = False

    def _get_connection(self):
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

    def _get_company_id(self, ticker: str) -> Optional[int]:
        """Get company ID from ticker"""
        conn = self._get_connection()
        if not conn:
            return None

        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM companies WHERE LOWER(ticker) = LOWER(%s)", (ticker,))
            row = cursor.fetchone()
            cursor.close()
            return row[0] if row else None
        except Exception as e:
            print(f"⚠️  Error getting company ID: {e}")
            return None

    # =========================================================================
    # EMPLOYEE COUNT TRACKING
    # =========================================================================

    def store_employee_count(self, ticker: str, employee_count: int,
                             snapshot_date: date = None,
                             data_source: str = 'explorium') -> bool:
        """
        Store an employee count snapshot

        Args:
            ticker: Stock ticker symbol
            employee_count: Number of employees
            snapshot_date: Date of the snapshot (default: today)
            data_source: Source of the data ('explorium', 'sec_filing', 'manual')

        Returns:
            bool: True if stored successfully
        """
        conn = self._get_connection()
        if not conn:
            return False

        company_id = self._get_company_id(ticker)
        if not company_id:
            print(f"⚠️  Company not found: {ticker}")
            return False

        if snapshot_date is None:
            snapshot_date = date.today()

        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO employee_counts (company_id, snapshot_date, employee_count, data_source)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (company_id, snapshot_date, data_source) DO UPDATE SET
                    employee_count = EXCLUDED.employee_count
            """, (company_id, snapshot_date, employee_count, data_source))

            conn.commit()
            cursor.close()
            print(f"💾 Stored employee count for {ticker}: {employee_count:,}")
            return True

        except Exception as e:
            conn.rollback()
            print(f"⚠️  Error storing employee count: {e}")
            return False

    def get_employee_history(self, ticker: str, days_back: int = 365) -> List[Dict[str, Any]]:
        """
        Get employee count history for a company

        Args:
            ticker: Stock ticker symbol
            days_back: Number of days of history to retrieve

        Returns:
            List of employee count snapshots
        """
        conn = self._get_connection()
        if not conn:
            return []

        company_id = self._get_company_id(ticker)
        if not company_id:
            return []

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("""
                SELECT snapshot_date, employee_count, data_source
                FROM employee_counts
                WHERE company_id = %s
                  AND snapshot_date >= CURRENT_DATE - %s
                ORDER BY snapshot_date DESC
            """, (company_id, days_back))

            rows = cursor.fetchall()
            cursor.close()

            return [dict(row) for row in rows]

        except Exception as e:
            print(f"⚠️  Error getting employee history: {e}")
            return []

    # =========================================================================
    # HIRING EVENT TRACKING
    # =========================================================================

    def store_hiring_events(self, ticker: str, events: List[Dict[str, Any]],
                           data_source: str = 'explorium') -> int:
        """
        Store multiple hiring events

        Args:
            ticker: Stock ticker symbol
            events: List of hiring event dicts with keys:
                    - event_date, event_type, department, location, job_title, job_count, description
            data_source: Source of the data

        Returns:
            int: Number of events stored
        """
        conn = self._get_connection()
        if not conn:
            return 0

        company_id = self._get_company_id(ticker)
        if not company_id:
            print(f"⚠️  Company not found: {ticker}")
            return 0

        stored_count = 0
        try:
            cursor = conn.cursor()

            for event in events:
                cursor.execute("""
                    INSERT INTO hiring_events
                    (company_id, event_date, event_type, department, location,
                     job_title, job_count, description, data_source)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    company_id,
                    event.get('event_date', date.today()),
                    event.get('event_type', 'job_posting'),
                    event.get('department'),
                    event.get('location'),
                    event.get('job_title'),
                    event.get('job_count', 1),
                    event.get('description'),
                    data_source
                ))
                stored_count += 1

            conn.commit()
            cursor.close()
            print(f"💾 Stored {stored_count} hiring events for {ticker}")
            return stored_count

        except Exception as e:
            conn.rollback()
            print(f"⚠️  Error storing hiring events: {e}")
            return 0

    def get_hiring_velocity(self, ticker: str, days_back: int = 90) -> Dict[str, Any]:
        """
        Calculate hiring velocity for a company

        Args:
            ticker: Stock ticker symbol
            days_back: Number of days to analyze

        Returns:
            Dict with velocity metrics
        """
        conn = self._get_connection()
        if not conn:
            return {'velocity': 0, 'classification': 'unknown'}

        company_id = self._get_company_id(ticker)
        if not company_id:
            return {'velocity': 0, 'classification': 'unknown'}

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # Count job postings by period
            cursor.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE event_date >= CURRENT_DATE - 30) as last_30_days,
                    COUNT(*) FILTER (WHERE event_date >= CURRENT_DATE - 60 AND event_date < CURRENT_DATE - 30) as prev_30_days,
                    COUNT(*) as total
                FROM hiring_events
                WHERE company_id = %s
                  AND event_date >= CURRENT_DATE - %s
                  AND event_type = 'job_posting'
            """, (company_id, days_back))

            row = cursor.fetchone()
            cursor.close()

            if not row or row['total'] == 0:
                return {'velocity': 0, 'classification': 'unknown', 'total_postings': 0}

            # Calculate velocity and classification
            last_30 = row['last_30_days'] or 0
            prev_30 = row['prev_30_days'] or 0
            total = row['total']

            if prev_30 > 0:
                velocity = ((last_30 - prev_30) / prev_30) * 100
            else:
                velocity = 100 if last_30 > 0 else 0

            if velocity > 20:
                classification = 'accelerating'
            elif velocity > -10:
                classification = 'stable'
            elif velocity > -30:
                classification = 'slowing'
            else:
                classification = 'declining'

            return {
                'velocity': round(velocity, 1),
                'classification': classification,
                'last_30_days': last_30,
                'prev_30_days': prev_30,
                'total_postings': total
            }

        except Exception as e:
            print(f"⚠️  Error calculating hiring velocity: {e}")
            return {'velocity': 0, 'classification': 'unknown'}

    # =========================================================================
    # GROWTH TREND TRACKING
    # =========================================================================

    def calculate_and_store_trend(self, ticker: str, metric_type: str = 'overall',
                                  lookback_days: int = 90) -> Optional[str]:
        """
        Calculate growth trend and store in database

        Args:
            ticker: Stock ticker symbol
            metric_type: Type of metric ('employee_growth', 'hiring_velocity', 'overall')
            lookback_days: Number of days to analyze

        Returns:
            Trend classification or None
        """
        conn = self._get_connection()
        if not conn:
            return None

        company_id = self._get_company_id(ticker)
        if not company_id:
            return None

        try:
            # Calculate trend based on metric type
            if metric_type == 'employee_growth':
                trend_data = self._calculate_employee_trend(company_id, lookback_days)
            elif metric_type == 'hiring_velocity':
                velocity = self.get_hiring_velocity(ticker, lookback_days)
                trend_data = {
                    'classification': velocity['classification'],
                    'value': velocity['velocity'],
                    'data_points': velocity.get('total_postings', 0)
                }
            else:  # overall
                emp_trend = self._calculate_employee_trend(company_id, lookback_days)
                velocity = self.get_hiring_velocity(ticker, lookback_days)

                # Combine for overall trend
                trend_data = self._combine_trends(emp_trend, velocity)

            if not trend_data:
                return None

            # Store the trend
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO growth_trends
                (company_id, metric_type, trend_classification, trend_value,
                 period_start, period_end, data_points, confidence_score)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (company_id, metric_type, period_end) DO UPDATE SET
                    trend_classification = EXCLUDED.trend_classification,
                    trend_value = EXCLUDED.trend_value,
                    data_points = EXCLUDED.data_points,
                    confidence_score = EXCLUDED.confidence_score,
                    computed_at = CURRENT_TIMESTAMP
            """, (
                company_id,
                metric_type,
                trend_data['classification'],
                trend_data.get('value'),
                date.today() - timedelta(days=lookback_days),
                date.today(),
                trend_data.get('data_points', 0),
                trend_data.get('confidence', 0.5)
            ))

            conn.commit()
            cursor.close()

            print(f"💾 Stored {metric_type} trend for {ticker}: {trend_data['classification']}")
            return trend_data['classification']

        except Exception as e:
            print(f"⚠️  Error calculating trend: {e}")
            return None

    def _calculate_employee_trend(self, company_id: int, lookback_days: int) -> Optional[Dict]:
        """Calculate employee growth trend"""
        conn = self._get_connection()
        if not conn:
            return None

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("""
                SELECT employee_count, snapshot_date
                FROM employee_counts
                WHERE company_id = %s
                  AND snapshot_date >= CURRENT_DATE - %s
                ORDER BY snapshot_date ASC
            """, (company_id, lookback_days))

            rows = cursor.fetchall()
            cursor.close()

            if len(rows) < 2:
                return None

            first_count = rows[0]['employee_count']
            last_count = rows[-1]['employee_count']

            if first_count and first_count > 0:
                growth_rate = ((last_count - first_count) / first_count) * 100
            else:
                growth_rate = 0

            if growth_rate > 10:
                classification = 'accelerating'
            elif growth_rate > 0:
                classification = 'stable'
            elif growth_rate > -5:
                classification = 'slowing'
            else:
                classification = 'declining'

            return {
                'classification': classification,
                'value': round(growth_rate, 1),
                'data_points': len(rows),
                'confidence': min(len(rows) / 10, 1.0)
            }

        except Exception as e:
            print(f"⚠️  Error calculating employee trend: {e}")
            return None

    def _combine_trends(self, emp_trend: Optional[Dict], velocity: Dict) -> Dict:
        """Combine employee and hiring trends into overall trend"""
        trend_scores = {
            'accelerating': 3,
            'stable': 2,
            'slowing': 1,
            'declining': 0,
            'unknown': 1.5
        }

        scores = []
        if emp_trend:
            scores.append(trend_scores.get(emp_trend['classification'], 1.5))
        if velocity:
            scores.append(trend_scores.get(velocity['classification'], 1.5))

        if not scores:
            return {'classification': 'unknown', 'value': 0, 'data_points': 0, 'confidence': 0}

        avg_score = sum(scores) / len(scores)

        if avg_score >= 2.5:
            classification = 'accelerating'
        elif avg_score >= 1.75:
            classification = 'stable'
        elif avg_score >= 1:
            classification = 'slowing'
        else:
            classification = 'declining'

        return {
            'classification': classification,
            'value': round(avg_score, 2),
            'data_points': (emp_trend.get('data_points', 0) if emp_trend else 0) +
                          velocity.get('total_postings', 0),
            'confidence': 0.7 if len(scores) == 2 else 0.5
        }

    def get_trend(self, ticker: str, metric_type: str = 'overall') -> Optional[Dict[str, Any]]:
        """
        Get stored growth trend for a company

        Args:
            ticker: Stock ticker symbol
            metric_type: Type of metric

        Returns:
            Trend data or None
        """
        conn = self._get_connection()
        if not conn:
            return None

        company_id = self._get_company_id(ticker)
        if not company_id:
            return None

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("""
                SELECT trend_classification, trend_value, period_start, period_end,
                       data_points, confidence_score, computed_at
                FROM growth_trends
                WHERE company_id = %s AND metric_type = %s
                ORDER BY computed_at DESC
                LIMIT 1
            """, (company_id, metric_type))

            row = cursor.fetchone()
            cursor.close()

            return dict(row) if row else None

        except Exception as e:
            print(f"⚠️  Error getting trend: {e}")
            return None

    # =========================================================================
    # FULL API RESPONSE CACHE
    # =========================================================================

    def cache_explorium_response(self, ticker: str, request_params: Dict,
                                 response_data: Dict) -> bool:
        """
        Cache full Explorium API response

        Args:
            ticker: Stock ticker symbol
            request_params: Parameters used for the API request
            response_data: Full API response to cache

        Returns:
            bool: True if cached successfully
        """
        conn = self._get_connection()
        if not conn:
            return False

        # Generate cache key from request params
        cache_key = hashlib.md5(json.dumps(request_params, sort_keys=True).encode()).hexdigest()

        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO growth_cache (ticker, cache_key, growth_data, expires_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (ticker, cache_key) DO UPDATE SET
                    growth_data = EXCLUDED.growth_data,
                    computed_at = CURRENT_TIMESTAMP,
                    expires_at = EXCLUDED.expires_at
            """, (
                ticker,
                cache_key,
                json.dumps(response_data),
                datetime.now() + timedelta(hours=self.cache_ttl_hours)
            ))

            conn.commit()
            cursor.close()
            print(f"💾 Cached Explorium response for {ticker}")
            return True

        except Exception as e:
            conn.rollback()
            print(f"⚠️  Error caching Explorium response: {e}")
            return False

    def get_cached_explorium_response(self, ticker: str, request_params: Dict) -> Optional[Dict]:
        """
        Get cached Explorium API response if not expired

        Args:
            ticker: Stock ticker symbol
            request_params: Parameters used for the API request

        Returns:
            Cached response or None
        """
        conn = self._get_connection()
        if not conn:
            return None

        cache_key = hashlib.md5(json.dumps(request_params, sort_keys=True).encode()).hexdigest()

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("""
                SELECT growth_data, computed_at
                FROM growth_cache
                WHERE ticker = %s AND cache_key = %s
                  AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
            """, (ticker, cache_key))

            row = cursor.fetchone()
            cursor.close()

            if row:
                print(f"✅ Cache HIT (RDS) for Explorium data: {ticker}")
                return row['growth_data']
            return None

        except Exception as e:
            print(f"⚠️  Error getting cached response: {e}")
            return None

    def invalidate(self, ticker: str = None):
        """
        Invalidate cache entries

        Args:
            ticker: If provided, only invalidate this ticker. Otherwise clear all.
        """
        conn = self._get_connection()
        if not conn:
            return

        try:
            cursor = conn.cursor()
            if ticker:
                cursor.execute("DELETE FROM growth_cache WHERE ticker = %s", (ticker,))
                print(f"🗑️  Cleared growth cache for {ticker}")
            else:
                cursor.execute("DELETE FROM growth_cache")
                print(f"🗑️  Cleared all growth cache")
            conn.commit()
            cursor.close()
        except Exception as e:
            print(f"⚠️  Error clearing growth cache: {e}")


# Global cache instance
growth_cache = GrowthCache()


# Helper function for LLM chat service
def get_cached_growth(ticker: str) -> Optional[Dict[str, Any]]:
    """
    Get growth metrics for a ticker from company_headcount_history and company_jobs_snapshot tables.
    Returns None if no data available.
    """
    conn = growth_cache._get_connection()
    if not conn:
        return None

    try:
        from psycopg2.extras import RealDictCursor
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Get latest jobs snapshot
        cursor.execute("""
            SELECT employee_count, total_jobs, hiring_intensity, jobs_by_function, jobs_by_seniority, snapshot_date
            FROM company_jobs_snapshot
            WHERE UPPER(ticker) = UPPER(%s)
            ORDER BY snapshot_date DESC
            LIMIT 1
        """, (ticker,))
        jobs_row = cursor.fetchone()

        # Get employee history for growth calculation
        cursor.execute("""
            SELECT employee_count, snapshot_date
            FROM company_headcount_history
            WHERE UPPER(ticker) = UPPER(%s)
            ORDER BY snapshot_date DESC
            LIMIT 12
        """, (ticker,))
        headcount_rows = cursor.fetchall()
        cursor.close()

        if not jobs_row and not headcount_rows:
            return None

        # Calculate growth rate from headcount history
        employee_growth_pct = None
        if len(headcount_rows) >= 2:
            latest = headcount_rows[0]['employee_count']
            oldest = headcount_rows[-1]['employee_count']
            if oldest and oldest > 0:
                employee_growth_pct = round(((latest - oldest) / oldest) * 100, 1)

        # Classify hiring intensity
        hiring_intensity_value = float(jobs_row['hiring_intensity']) if jobs_row and jobs_row.get('hiring_intensity') else 0
        if hiring_intensity_value > 15:
            intensity_class = 'high'
        elif hiring_intensity_value > 8:
            intensity_class = 'moderate'
        elif hiring_intensity_value > 3:
            intensity_class = 'low'
        else:
            intensity_class = 'minimal'

        return {
            'employee_count': jobs_row['employee_count'] if jobs_row else (headcount_rows[0]['employee_count'] if headcount_rows else None),
            'employee_growth_pct': employee_growth_pct,
            'hiring_intensity': intensity_class,
            'hiring_intensity_pct': hiring_intensity_value,
            'total_jobs': jobs_row['total_jobs'] if jobs_row else 0,
            'jobs_by_function': dict(jobs_row['jobs_by_function']) if jobs_row and jobs_row.get('jobs_by_function') else {},
            'jobs_by_seniority': dict(jobs_row['jobs_by_seniority']) if jobs_row and jobs_row.get('jobs_by_seniority') else {},
            'snapshot_date': jobs_row['snapshot_date'].isoformat() if jobs_row else None,
            'cached_at': datetime.now().isoformat()
        }

    except Exception as e:
        print(f"Error getting growth data for {ticker}: {e}")
        return None
