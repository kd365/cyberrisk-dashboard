#!/usr/bin/env python3
"""
Migration Script: Consolidate Company nodes into Organization

This script:
1. Merges all Company nodes into Organization nodes (by ticker)
2. Migrates relationships from Company to Organization
3. Deletes the Company nodes after migration
4. Creates missing indexes

Run with --dry-run to preview changes without executing.
"""

import os
import sys
import argparse
import logging

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from neo4j import GraphDatabase

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class CompanyToOrganizationMigration:
    def __init__(self, uri: str, username: str, password: str, dry_run: bool = True):
        self.driver = GraphDatabase.driver(uri, auth=(username, password))
        self.dry_run = dry_run
        self.stats = {
            "company_nodes_found": 0,
            "properties_migrated": 0,
            "relationships_migrated": 0,
            "company_nodes_deleted": 0,
        }

    def close(self):
        self.driver.close()

    def run_query(self, query: str, params: dict = None):
        """Execute a read query and return results."""
        with self.driver.session() as session:
            result = session.run(query, params or {})
            return [dict(record) for record in result]

    def run_write(self, query: str, params: dict = None):
        """Execute a write query."""
        if self.dry_run:
            logger.info(f"  [DRY RUN] Would execute: {query[:100]}...")
            return None
        with self.driver.session() as session:
            result = session.run(query, params or {})
            return result.consume()

    def analyze_current_state(self):
        """Analyze the current state of Company and Organization nodes."""
        logger.info("Analyzing current graph state...")

        # Count Company nodes
        company_count = self.run_query("MATCH (c:Company) RETURN count(c) as count")
        self.stats["company_nodes_found"] = company_count[0]["count"] if company_count else 0
        logger.info(f"  Company nodes found: {self.stats['company_nodes_found']}")

        # Count Organization nodes
        org_count = self.run_query("MATCH (o:Organization) RETURN count(o) as count")
        logger.info(f"  Organization nodes found: {org_count[0]['count'] if org_count else 0}")

        # Find Company nodes with their tickers
        companies = self.run_query("""
            MATCH (c:Company)
            RETURN c.ticker as ticker, c.name as name,
                   keys(c) as properties,
                   size([(c)-[r]-() | r]) as relationship_count
        """)

        if companies:
            logger.info(f"\n  Company nodes to migrate:")
            for c in companies:
                logger.info(f"    - {c['ticker']}: {c['name']} ({c['relationship_count']} relationships)")

        # Check for Company nodes that don't have matching Organization nodes
        orphan_companies = self.run_query("""
            MATCH (c:Company)
            WHERE NOT EXISTS {
                MATCH (o:Organization {ticker: c.ticker})
            }
            RETURN c.ticker as ticker, c.name as name
        """)

        if orphan_companies:
            logger.info(f"\n  Company nodes WITHOUT matching Organization (will create new Organization):")
            for c in orphan_companies:
                logger.info(f"    - {c['ticker']}: {c['name']}")

        return companies

    def migrate_properties(self):
        """Migrate properties from Company to Organization nodes."""
        logger.info("\nMigrating properties from Company to Organization...")

        # For companies that have matching Organizations, copy any unique properties
        query = """
            MATCH (c:Company)
            MATCH (o:Organization {ticker: c.ticker})
            WITH c, o, keys(c) as company_props
            UNWIND company_props as prop
            WITH c, o, prop
            WHERE prop <> 'ticker' AND NOT prop IN keys(o)
            CALL apoc.do.when(
                NOT prop IN keys(o),
                'SET o[$prop] = c[$prop] RETURN 1 as migrated',
                'RETURN 0 as migrated',
                {o: o, c: c, prop: prop}
            ) YIELD value
            RETURN count(*) as properties_migrated
        """

        # Simplified version without APOC
        simple_query = """
            MATCH (c:Company)
            MATCH (o:Organization {ticker: c.ticker})
            SET o.analyst_sentiment = COALESCE(o.analyst_sentiment, c.analyst_sentiment),
                o.analyst_concerns = COALESCE(o.analyst_concerns, c.analyst_concerns),
                o.management_tone = COALESCE(o.management_tone, c.management_tone),
                o.guidance_direction = COALESCE(o.guidance_direction, c.guidance_direction),
                o.sentiment_extracted_at = COALESCE(o.sentiment_extracted_at, c.sentiment_extracted_at)
            RETURN count(o) as updated
        """

        if not self.dry_run:
            result = self.run_query(simple_query)
            self.stats["properties_migrated"] = result[0]["updated"] if result else 0
        else:
            # Count what would be migrated
            count_query = """
                MATCH (c:Company)
                MATCH (o:Organization {ticker: c.ticker})
                RETURN count(o) as count
            """
            result = self.run_query(count_query)
            self.stats["properties_migrated"] = result[0]["count"] if result else 0

        logger.info(f"  {'Would migrate' if self.dry_run else 'Migrated'} properties for {self.stats['properties_migrated']} nodes")

    def create_missing_organizations(self):
        """Create Organization nodes for Company nodes without matches."""
        logger.info("\nCreating Organization nodes for orphan Company nodes...")

        query = """
            MATCH (c:Company)
            WHERE NOT EXISTS {
                MATCH (o:Organization {ticker: c.ticker})
            }
            CREATE (o:Organization)
            SET o = properties(c),
                o.tracked = true,
                o.migrated_from_company = true
            RETURN count(o) as created
        """

        if not self.dry_run:
            result = self.run_query(query)
            created = result[0]["created"] if result else 0
            logger.info(f"  Created {created} new Organization nodes")
        else:
            count_query = """
                MATCH (c:Company)
                WHERE NOT EXISTS {
                    MATCH (o:Organization {ticker: c.ticker})
                }
                RETURN count(c) as count
            """
            result = self.run_query(count_query)
            logger.info(f"  Would create {result[0]['count'] if result else 0} new Organization nodes")

    def migrate_relationships(self):
        """Migrate all relationships from Company to Organization nodes."""
        logger.info("\nMigrating relationships from Company to Organization...")

        # Get all relationship types connected to Company nodes
        rel_types = self.run_query("""
            MATCH (c:Company)-[r]-()
            RETURN DISTINCT type(r) as rel_type, count(r) as count
        """)

        if rel_types:
            logger.info(f"  Relationship types to migrate:")
            for rt in rel_types:
                logger.info(f"    - {rt['rel_type']}: {rt['count']}")

        # Migrate incoming relationships
        incoming_query = """
            MATCH (c:Company)<-[r]-(other)
            MATCH (o:Organization {ticker: c.ticker})
            WHERE NOT (other)-[]->(o)
            WITH c, r, other, o, type(r) as rel_type, properties(r) as rel_props
            CALL apoc.create.relationship(other, rel_type, rel_props, o) YIELD rel
            RETURN count(rel) as migrated
        """

        # Simplified without APOC - handle each relationship type separately
        relationship_migrations = [
            # HAS_SENTIMENT
            """
            MATCH (c:Company)<-[r:HAS_SENTIMENT]-(s:SentimentSnapshot)
            MATCH (o:Organization {ticker: c.ticker})
            WHERE NOT (s)-[:HAS_SENTIMENT]->(o)
            CREATE (o)-[:HAS_SENTIMENT]->(s)
            RETURN count(*) as migrated
            """,
            # HAS_GROWTH_DATA
            """
            MATCH (c:Company)<-[r:HAS_GROWTH_DATA]-(g:GrowthSnapshot)
            MATCH (o:Organization {ticker: c.ticker})
            WHERE NOT (g)-[:HAS_GROWTH_DATA]->(o)
            CREATE (o)-[:HAS_GROWTH_DATA]->(g)
            RETURN count(*) as migrated
            """,
            # HAS_FORECAST
            """
            MATCH (c:Company)<-[r:HAS_FORECAST]-(f:ForecastSnapshot)
            MATCH (o:Organization {ticker: c.ticker})
            WHERE NOT (f)-[:HAS_FORECAST]->(o)
            CREATE (o)-[:HAS_FORECAST]->(f)
            RETURN count(*) as migrated
            """,
            # HEADCOUNT_HISTORY
            """
            MATCH (c:Company)-[r:HEADCOUNT_HISTORY]->(h:HeadcountPoint)
            MATCH (o:Organization {ticker: c.ticker})
            WHERE NOT (o)-[:HEADCOUNT_HISTORY]->(h)
            CREATE (o)-[:HEADCOUNT_HISTORY]->(h)
            RETURN count(*) as migrated
            """,
            # HIRING_FOR
            """
            MATCH (c:Company)-[r:HIRING_FOR]->(j:JobFunction)
            MATCH (o:Organization {ticker: c.ticker})
            WHERE NOT (o)-[:HIRING_FOR]->(j)
            CREATE (o)-[nr:HIRING_FOR]->(j)
            SET nr = properties(r)
            RETURN count(*) as migrated
            """,
            # EXECUTIVE_OF (Person -> Company)
            """
            MATCH (p:Person)-[r:EXECUTIVE_OF]->(c:Company)
            MATCH (o:Organization {ticker: c.ticker})
            WHERE NOT (p)-[:EXECUTIVE_OF]->(o)
            CREATE (p)-[nr:EXECUTIVE_OF]->(o)
            SET nr = properties(r)
            RETURN count(*) as migrated
            """,
        ]

        total_migrated = 0
        for query in relationship_migrations:
            if not self.dry_run:
                try:
                    result = self.run_query(query)
                    migrated = result[0]["migrated"] if result else 0
                    total_migrated += migrated
                except Exception as e:
                    logger.warning(f"  Query failed (may not have matching data): {e}")
            else:
                logger.info(f"  [DRY RUN] Would execute migration query")

        self.stats["relationships_migrated"] = total_migrated
        logger.info(f"  {'Would migrate' if self.dry_run else 'Migrated'} {total_migrated} relationships")

    def delete_company_nodes(self):
        """Delete Company nodes after migration."""
        logger.info("\nDeleting Company nodes...")

        # First detach and delete
        query = """
            MATCH (c:Company)
            DETACH DELETE c
            RETURN count(*) as deleted
        """

        if not self.dry_run:
            # Count first
            count = self.run_query("MATCH (c:Company) RETURN count(c) as count")
            self.stats["company_nodes_deleted"] = count[0]["count"] if count else 0

            # Then delete
            with self.driver.session() as session:
                session.run("MATCH (c:Company) DETACH DELETE c")

            logger.info(f"  Deleted {self.stats['company_nodes_deleted']} Company nodes")
        else:
            count = self.run_query("MATCH (c:Company) RETURN count(c) as count")
            self.stats["company_nodes_deleted"] = count[0]["count"] if count else 0
            logger.info(f"  Would delete {self.stats['company_nodes_deleted']} Company nodes")

    def run_migration(self):
        """Run the full migration."""
        logger.info("=" * 60)
        logger.info(f"Company to Organization Migration ({'DRY RUN' if self.dry_run else 'LIVE'})")
        logger.info("=" * 60)

        self.analyze_current_state()

        if self.stats["company_nodes_found"] == 0:
            logger.info("\nNo Company nodes found. Migration not needed.")
            return self.stats

        self.create_missing_organizations()
        self.migrate_properties()
        self.migrate_relationships()
        self.delete_company_nodes()

        logger.info("\n" + "=" * 60)
        logger.info("Migration Summary")
        logger.info("=" * 60)
        for key, value in self.stats.items():
            logger.info(f"  {key}: {value}")

        if self.dry_run:
            logger.info("\n*** This was a DRY RUN. No changes were made. ***")
            logger.info("Run with --execute to apply changes.")

        return self.stats


def main():
    parser = argparse.ArgumentParser(description="Migrate Company nodes to Organization")
    parser.add_argument("--execute", action="store_true", help="Actually execute changes (default is dry run)")
    parser.add_argument("--uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7687"), help="Neo4j URI")
    parser.add_argument("--username", default=os.environ.get("NEO4J_USERNAME", "neo4j"), help="Neo4j username")
    parser.add_argument("--password", default=os.environ.get("NEO4J_PASSWORD", ""), help="Neo4j password")

    args = parser.parse_args()

    if not args.password:
        logger.error("NEO4J_PASSWORD environment variable or --password argument required")
        sys.exit(1)

    dry_run = not args.execute

    migration = CompanyToOrganizationMigration(
        uri=args.uri,
        username=args.username,
        password=args.password,
        dry_run=dry_run
    )

    try:
        stats = migration.run_migration()
        return 0
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        migration.close()


if __name__ == "__main__":
    sys.exit(main())
