# =============================================================================
# Graph Enrichment Service - RDS Data to Knowledge Graph
# =============================================================================
#
# This service enriches the Neo4j knowledge graph with data from existing
# RDS tables including:
# - Sentiment snapshots
# - Growth snapshots (CoreSignal)
# - Forecast snapshots
# - Headcount history
# - Job function data
#
# =============================================================================

import os
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class GraphEnrichmentService:
    """
    Enriches knowledge graph with RDS data.

    Pulls data from existing PostgreSQL tables and creates corresponding
    nodes and relationships in Neo4j for richer GraphRAG context.
    """

    def __init__(self):
        """Initialize the graph enrichment service."""
        # Service dependencies (lazy loaded)
        self._neo4j_service = None
        self._db_service = None

    @property
    def neo4j(self):
        """Lazy load Neo4j service."""
        if self._neo4j_service is None:
            from services.neo4j_service import get_neo4j_service
            self._neo4j_service = get_neo4j_service()
        return self._neo4j_service

    @property
    def db(self):
        """Lazy load database service."""
        if self._db_service is None:
            from services.database_service import db_service
            self._db_service = db_service
        return self._db_service

    # =========================================================================
    # Main Enrichment Pipeline
    # =========================================================================

    def enrich_graph_for_ticker(self, ticker: str) -> Dict:
        """
        Enrich knowledge graph with all RDS data for a ticker.

        Args:
            ticker: Company ticker symbol

        Returns:
            Summary of enrichment results
        """
        ticker = ticker.upper()
        logger.info(f"Enriching graph with RDS data for {ticker}")

        results = {
            'ticker': ticker,
            'sentiment_snapshots': 0,
            'growth_snapshots': 0,
            'forecast_snapshots': 0,
            'headcount_points': 0,
            'job_functions': 0,
            'errors': []
        }

        try:
            # 1. Ensure company node exists
            self._ensure_company_node(ticker)

            # 2. Add sentiment snapshots
            try:
                results['sentiment_snapshots'] = self._add_sentiment_snapshots(ticker)
            except Exception as e:
                logger.error(f"Error adding sentiment: {e}")
                results['errors'].append(f"sentiment: {str(e)}")

            # 3. Add growth snapshots
            try:
                results['growth_snapshots'] = self._add_growth_snapshots(ticker)
            except Exception as e:
                logger.error(f"Error adding growth: {e}")
                results['errors'].append(f"growth: {str(e)}")

            # 4. Add forecast snapshots
            try:
                results['forecast_snapshots'] = self._add_forecast_snapshots(ticker)
            except Exception as e:
                logger.error(f"Error adding forecasts: {e}")
                results['errors'].append(f"forecasts: {str(e)}")

            # 5. Add headcount history
            try:
                results['headcount_points'] = self._add_headcount_history(ticker)
            except Exception as e:
                logger.error(f"Error adding headcount: {e}")
                results['errors'].append(f"headcount: {str(e)}")

            # 6. Add job function data
            try:
                results['job_functions'] = self._add_job_functions(ticker)
            except Exception as e:
                logger.error(f"Error adding jobs: {e}")
                results['errors'].append(f"jobs: {str(e)}")

            logger.info(f"Graph enrichment complete for {ticker}: {results}")
            return results

        except Exception as e:
            logger.error(f"Error enriching graph for {ticker}: {e}")
            results['errors'].append(str(e))
            return results

    def enrich_all_tickers(self) -> Dict:
        """
        Enrich knowledge graph for all tracked companies.

        Returns:
            Summary of results per ticker
        """
        companies = self.db.get_all_companies()
        all_results = {}

        for company in companies:
            ticker = company.get('ticker', '').upper()
            if ticker:
                all_results[ticker] = self.enrich_graph_for_ticker(ticker)

        return all_results

    # =========================================================================
    # Individual Enrichment Methods
    # =========================================================================

    def _ensure_company_node(self, ticker: str):
        """Ensure company node exists in Neo4j."""
        company = self.db.get_company(ticker)
        if company:
            self.neo4j.create_company(
                ticker=ticker,
                name=company.get('company_name', ticker),
                sector=company.get('sector', 'Cybersecurity')
            )

    def _add_sentiment_snapshots(self, ticker: str) -> int:
        """
        Add sentiment cache data as SentimentSnapshot nodes.

        Returns:
            Number of snapshots added
        """
        conn = self.db._get_connection()
        cursor = conn.cursor()

        try:
            # Query sentiment_cache table
            cursor.execute("""
                SELECT cache_key, sentiment_data, cached_at
                FROM sentiment_cache
                WHERE cache_key LIKE %s
                ORDER BY cached_at DESC
                LIMIT 10
            """, (f"{ticker}_%",))

            rows = cursor.fetchall()
            count = 0

            for row in rows:
                cache_key, sentiment_data, cached_at = row

                if not sentiment_data:
                    continue

                # Parse sentiment data (assuming JSON)
                import json
                if isinstance(sentiment_data, str):
                    data = json.loads(sentiment_data)
                else:
                    data = sentiment_data

                overall = data.get('overall', {})

                # Create snapshot node
                query = """
                    MATCH (c:Company {ticker: $ticker})
                    MERGE (s:SentimentSnapshot {cache_key: $cache_key})
                    SET s.dominant_sentiment = $dominant,
                        s.confidence = $confidence,
                        s.positive = $positive,
                        s.negative = $negative,
                        s.neutral = $neutral,
                        s.mixed = $mixed,
                        s.cached_at = datetime($cached_at)
                    MERGE (c)-[:HAS_SENTIMENT]->(s)
                """

                self.neo4j.execute_write(query, {
                    'ticker': ticker,
                    'cache_key': cache_key,
                    'dominant': overall.get('dominant', 'NEUTRAL'),
                    'confidence': overall.get('confidence', 0),
                    'positive': overall.get('positive', 0),
                    'negative': overall.get('negative', 0),
                    'neutral': overall.get('neutral', 0),
                    'mixed': overall.get('mixed', 0),
                    'cached_at': cached_at.isoformat() if cached_at else datetime.now().isoformat()
                })

                count += 1

            return count

        finally:
            cursor.close()

    def _add_growth_snapshots(self, ticker: str) -> int:
        """
        Add growth cache data as GrowthSnapshot nodes.

        Returns:
            Number of snapshots added
        """
        conn = self.db._get_connection()
        cursor = conn.cursor()

        try:
            # Query growth_cache table
            cursor.execute("""
                SELECT ticker, snapshot_date, employee_count, hiring_intensity
                FROM growth_cache
                WHERE ticker = %s
                ORDER BY snapshot_date DESC
                LIMIT 10
            """, (ticker,))

            rows = cursor.fetchall()
            count = 0

            for row in rows:
                _, snapshot_date, employee_count, hiring_intensity = row

                if not snapshot_date:
                    continue

                date_str = snapshot_date.isoformat() if hasattr(snapshot_date, 'isoformat') else str(snapshot_date)

                # Create growth snapshot node
                query = """
                    MATCH (c:Company {ticker: $ticker})
                    MERGE (g:GrowthSnapshot {ticker: $ticker, date: date($date)})
                    SET g.employee_count = $employee_count,
                        g.hiring_intensity = $hiring_intensity
                    MERGE (c)-[:HAS_GROWTH_DATA]->(g)
                """

                self.neo4j.execute_write(query, {
                    'ticker': ticker,
                    'date': date_str[:10],  # YYYY-MM-DD
                    'employee_count': employee_count or 0,
                    'hiring_intensity': hiring_intensity or 0
                })

                count += 1

            return count

        finally:
            cursor.close()

    def _add_forecast_snapshots(self, ticker: str) -> int:
        """
        Add forecast cache data as ForecastSnapshot nodes.

        Returns:
            Number of snapshots added
        """
        conn = self.db._get_connection()
        cursor = conn.cursor()

        try:
            # Query forecast_cache table
            cursor.execute("""
                SELECT cache_key, forecast_data, cached_at
                FROM forecast_cache
                WHERE cache_key LIKE %s
                ORDER BY cached_at DESC
                LIMIT 5
            """, (f"{ticker}_%",))

            rows = cursor.fetchall()
            count = 0

            for row in rows:
                cache_key, forecast_data, cached_at = row

                if not forecast_data:
                    continue

                # Parse forecast data
                import json
                if isinstance(forecast_data, str):
                    data = json.loads(forecast_data)
                else:
                    data = forecast_data

                model = data.get('model', 'prophet')
                forecast_days = data.get('forecast_days', 30)

                # Create forecast snapshot node
                query = """
                    MATCH (c:Company {ticker: $ticker})
                    MERGE (f:ForecastSnapshot {cache_key: $cache_key})
                    SET f.ticker = $ticker,
                        f.model = $model,
                        f.forecast_days = $forecast_days,
                        f.current_price = $current_price,
                        f.predicted_price = $predicted_price,
                        f.expected_return_pct = $expected_return,
                        f.cached_at = datetime($cached_at)
                    MERGE (c)-[:HAS_FORECAST]->(f)
                """

                self.neo4j.execute_write(query, {
                    'ticker': ticker,
                    'cache_key': cache_key,
                    'model': model,
                    'forecast_days': forecast_days,
                    'current_price': data.get('current_price', 0),
                    'predicted_price': data.get('predicted_price', 0),
                    'expected_return': data.get('expected_return_pct', 0),
                    'cached_at': cached_at.isoformat() if cached_at else datetime.now().isoformat()
                })

                count += 1

            return count

        finally:
            cursor.close()

    def _add_headcount_history(self, ticker: str) -> int:
        """
        Add headcount history as HeadcountPoint nodes.

        Returns:
            Number of points added
        """
        conn = self.db._get_connection()
        cursor = conn.cursor()

        try:
            # Query headcount_history table (if exists)
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'headcount_history'
                )
            """)

            table_exists = cursor.fetchone()[0]

            if not table_exists:
                logger.info("headcount_history table does not exist")
                return 0

            cursor.execute("""
                SELECT ticker, snapshot_date, employee_count
                FROM headcount_history
                WHERE ticker = %s
                ORDER BY snapshot_date DESC
                LIMIT 50
            """, (ticker,))

            rows = cursor.fetchall()
            count = 0

            for row in rows:
                _, snapshot_date, employee_count = row

                if not snapshot_date or not employee_count:
                    continue

                date_str = snapshot_date.isoformat() if hasattr(snapshot_date, 'isoformat') else str(snapshot_date)

                # Create headcount point node
                query = """
                    MATCH (c:Company {ticker: $ticker})
                    MERGE (h:HeadcountPoint {ticker: $ticker, date: date($date)})
                    SET h.employee_count = $employee_count
                    MERGE (c)-[:HEADCOUNT_HISTORY]->(h)
                """

                self.neo4j.execute_write(query, {
                    'ticker': ticker,
                    'date': date_str[:10],
                    'employee_count': employee_count
                })

                count += 1

            return count

        finally:
            cursor.close()

    def _add_job_functions(self, ticker: str) -> int:
        """
        Add job function data from growth cache.

        Returns:
            Number of job functions added
        """
        conn = self.db._get_connection()
        cursor = conn.cursor()

        try:
            # Get latest growth data with jobs breakdown
            cursor.execute("""
                SELECT jobs_by_function, snapshot_date
                FROM growth_cache
                WHERE ticker = %s
                  AND jobs_by_function IS NOT NULL
                ORDER BY snapshot_date DESC
                LIMIT 1
            """, (ticker,))

            row = cursor.fetchone()

            if not row:
                return 0

            jobs_by_function, snapshot_date = row

            if not jobs_by_function:
                return 0

            # Parse jobs data
            import json
            if isinstance(jobs_by_function, str):
                jobs = json.loads(jobs_by_function)
            else:
                jobs = jobs_by_function

            count = 0
            date_str = snapshot_date.isoformat()[:10] if snapshot_date else datetime.now().isoformat()[:10]

            for function_name, open_positions in jobs.items():
                if not function_name or open_positions is None:
                    continue

                # Create job function node and relationship
                query = """
                    MATCH (c:Company {ticker: $ticker})
                    MERGE (j:JobFunction {name: $function_name})
                    MERGE (c)-[r:HIRING_FOR]->(j)
                    SET r.open_positions = $open_positions,
                        r.snapshot_date = date($date)
                """

                self.neo4j.execute_write(query, {
                    'ticker': ticker,
                    'function_name': function_name,
                    'open_positions': open_positions,
                    'date': date_str
                })

                count += 1

            return count

        finally:
            cursor.close()

    # =========================================================================
    # Full Sync
    # =========================================================================

    def full_sync(self, ticker: str = None) -> Dict:
        """
        Perform full sync of RDS data to knowledge graph.

        Args:
            ticker: Optional ticker to sync (all if None)

        Returns:
            Sync results
        """
        if ticker:
            return self.enrich_graph_for_ticker(ticker.upper())
        else:
            return self.enrich_all_tickers()


# =============================================================================
# Singleton Instance
# =============================================================================

_graph_enrichment_service = None


def get_graph_enrichment_service() -> GraphEnrichmentService:
    """Get or create graph enrichment service singleton."""
    global _graph_enrichment_service
    if _graph_enrichment_service is None:
        _graph_enrichment_service = GraphEnrichmentService()
    return _graph_enrichment_service
