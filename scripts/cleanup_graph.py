#!/usr/bin/env python3
"""
Comprehensive Neo4j Graph Cleanup Script

This script cleans up data quality issues in the knowledge graph:
1. Concept nodes with newlines (parsing artifacts)
2. Concept nodes with separator characters
3. Person nodes that are actually numbers
4. Person nodes that are actually organizations
5. Location nodes with bad data
6. Document type classification
7. Orphan Person nodes (optional)

Run with --dry-run to preview changes without executing.
"""

import os
import sys
import argparse
import logging
from typing import List, Dict, Tuple

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from neo4j import GraphDatabase

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class GraphCleaner:
    def __init__(self, uri: str, username: str, password: str, dry_run: bool = True):
        self.driver = GraphDatabase.driver(uri, auth=(username, password))
        self.dry_run = dry_run
        self.stats = {
            "concepts_with_newlines": 0,
            "concepts_with_separators": 0,
            "persons_as_numbers": 0,
            "persons_as_orgs": 0,
            "locations_bad": 0,
            "documents_updated": 0,
            "orphan_persons_deleted": 0,
            "orphan_orgs_deleted": 0,
            "duplicate_orgs_merged": 0,
        }

    def close(self):
        self.driver.close()

    def run_query(self, query: str, params: dict = None) -> List[Dict]:
        """Execute a read query and return results."""
        with self.driver.session() as session:
            result = session.run(query, params or {})
            return [dict(record) for record in result]

    def run_write(self, query: str, params: dict = None) -> int:
        """Execute a write query and return affected count."""
        if self.dry_run:
            # In dry run, just count what would be affected
            count_query = query.replace("DETACH DELETE", "RETURN count(n) as count")
            count_query = count_query.replace("DELETE", "RETURN count(n) as count")
            count_query = count_query.replace("SET", "RETURN count(n) as count //SET")
            with self.driver.session() as session:
                result = session.run(count_query, params or {})
                record = result.single()
                return record["count"] if record else 0
        else:
            with self.driver.session() as session:
                result = session.run(query, params or {})
                summary = result.consume()
                return summary.counters.nodes_deleted + summary.counters.properties_set

    def cleanup_concepts_with_newlines(self) -> int:
        """Delete Concept nodes that contain newline characters (parsing artifacts)."""
        logger.info("Cleaning up Concept nodes with newlines...")

        query = """
        MATCH (n:Concept)
        WHERE n.name CONTAINS '\n'
        DETACH DELETE n
        """

        if self.dry_run:
            count_query = "MATCH (n:Concept) WHERE n.name CONTAINS '\n' RETURN count(n) as count"
            result = self.run_query(count_query)
            count = result[0]["count"] if result else 0
        else:
            with self.driver.session() as session:
                result = session.run(query)
                summary = result.consume()
                count = summary.counters.nodes_deleted

        self.stats["concepts_with_newlines"] = count
        logger.info(f"  {'Would delete' if self.dry_run else 'Deleted'}: {count} concepts with newlines")
        return count

    def cleanup_concepts_with_separators(self) -> int:
        """Delete Concept nodes with separator characters or SEC EDGAR headers."""
        logger.info("Cleaning up Concept nodes with separators/headers...")

        query = """
        MATCH (n:Concept)
        WHERE n.name CONTAINS '----------------'
           OR n.name CONTAINS '========'
           OR n.name CONTAINS 'SEC EDGAR'
        DETACH DELETE n
        """

        if self.dry_run:
            count_query = """
            MATCH (n:Concept)
            WHERE n.name CONTAINS '----------------'
               OR n.name CONTAINS '========'
               OR n.name CONTAINS 'SEC EDGAR'
            RETURN count(n) as count
            """
            result = self.run_query(count_query)
            count = result[0]["count"] if result else 0
        else:
            with self.driver.session() as session:
                result = session.run(query)
                summary = result.consume()
                count = summary.counters.nodes_deleted

        self.stats["concepts_with_separators"] = count
        logger.info(f"  {'Would delete' if self.dry_run else 'Deleted'}: {count} concepts with separators")
        return count

    def cleanup_persons_as_numbers(self) -> int:
        """Delete Person nodes that are just numbers (patent IDs misclassified)."""
        logger.info("Cleaning up Person nodes that are numbers...")

        query = """
        MATCH (n:Person)
        WHERE n.name =~ '^[0-9,\\.]+$'
        DETACH DELETE n
        """

        if self.dry_run:
            count_query = "MATCH (n:Person) WHERE n.name =~ '^[0-9,\\\\.]+$' RETURN count(n) as count"
            result = self.run_query(count_query)
            count = result[0]["count"] if result else 0
        else:
            with self.driver.session() as session:
                result = session.run(query)
                summary = result.consume()
                count = summary.counters.nodes_deleted

        self.stats["persons_as_numbers"] = count
        logger.info(f"  {'Would delete' if self.dry_run else 'Deleted'}: {count} person nodes that are numbers")
        return count

    def cleanup_persons_as_orgs(self) -> int:
        """Convert Person nodes that are actually organizations."""
        logger.info("Converting Person nodes that are organizations...")

        # First, get the list of person nodes that should be organizations
        find_query = """
        MATCH (n:Person)
        WHERE n.name CONTAINS 'LLC'
           OR n.name CONTAINS 'Inc.'
           OR n.name CONTAINS 'Inc)'
           OR n.name CONTAINS 'Corporation'
           OR n.name CONTAINS 'ATTN'
           OR n.name CONTAINS 'Ltd.'
           OR n.name CONTAINS 'Ltd)'
           OR n.name CONTAINS 'LLP'
        RETURN n.name as name, id(n) as id
        """

        results = self.run_query(find_query)
        count = len(results)

        if not self.dry_run and count > 0:
            # Delete these nodes (they're usually orphans or duplicates of existing orgs)
            delete_query = """
            MATCH (n:Person)
            WHERE n.name CONTAINS 'LLC'
               OR n.name CONTAINS 'Inc.'
               OR n.name CONTAINS 'Inc)'
               OR n.name CONTAINS 'Corporation'
               OR n.name CONTAINS 'ATTN'
               OR n.name CONTAINS 'Ltd.'
               OR n.name CONTAINS 'Ltd)'
               OR n.name CONTAINS 'LLP'
            DETACH DELETE n
            """
            with self.driver.session() as session:
                result = session.run(delete_query)
                summary = result.consume()
                count = summary.counters.nodes_deleted

        self.stats["persons_as_orgs"] = count
        logger.info(f"  {'Would delete' if self.dry_run else 'Deleted'}: {count} person nodes that are organizations")
        return count

    def cleanup_bad_locations(self) -> int:
        """Delete Location nodes with obvious garbage data only.

        Keeps: Street addresses, geographic regions, cities, countries
        Deletes: Pure numbers, very short names, SEC metadata, incomplete phrases
        """
        logger.info("Cleaning up bad Location nodes...")

        # Valid 2-letter ISO country codes and US state abbreviations to preserve
        # ISO 3166-1 alpha-2 + US state codes
        iso_codes = [
            # Major countries
            "US", "UK", "GB", "CA", "MX", "FR", "DE", "IT", "ES", "PT", "NL", "BE",
            "CH", "AT", "SE", "NO", "DK", "FI", "PL", "CZ", "HU", "RO", "BG", "GR",
            "TR", "RU", "UA", "JP", "CN", "KR", "TW", "HK", "SG", "MY", "TH", "VN",
            "PH", "ID", "IN", "PK", "BD", "AU", "NZ", "ZA", "EG", "NG", "KE", "BR",
            "AR", "CL", "CO", "PE", "VE", "IE", "IL", "AE", "SA", "QA", "KW",
            # US States
            "AL", "AK", "AZ", "AR", "CO", "CT", "DC", "FL", "GA", "HI",
            "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT",
            "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA",
            "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"
        ]

        # Conservative garbage detection:
        # - Pure numbers (not locations)
        # - Very short names (< 3 chars) UNLESS they're valid ISO/state codes
        # - SEC filing metadata accidentally extracted as locations
        # - Incomplete phrases (ending with "and", starting with "a ")
        # - Company names misclassified as locations
        # - Names with embedded newlines (malformed extractions)
        query = """
        MATCH (n:Location)
        WHERE n.name =~ '^[0-9]+$'
           OR (size(n.name) < 3 AND NOT n.name IN $iso_codes)
           OR n.name CONTAINS 'Table of Contents'
           OR n.name CONTAINS 'Employer Identification'
           OR n.name CONTAINS 'Identification No'
           OR n.name CONTAINS 'Corporation '
           OR toLower(n.name) =~ '.* and$'
           OR toLower(n.name) =~ '^a [a-z]+$'
           OR toLower(n.name) = 'okta'
           OR n.name CONTAINS '\\n'
        DETACH DELETE n
        """

        if self.dry_run:
            count_query = """
            MATCH (n:Location)
            WHERE n.name =~ '^[0-9]+$'
               OR (size(n.name) < 3 AND NOT n.name IN $iso_codes)
               OR n.name CONTAINS 'Table of Contents'
               OR n.name CONTAINS 'Employer Identification'
               OR n.name CONTAINS 'Identification No'
               OR n.name CONTAINS 'Corporation '
               OR toLower(n.name) =~ '.* and$'
               OR toLower(n.name) =~ '^a [a-z]+$'
               OR toLower(n.name) = 'okta'
               OR n.name CONTAINS '\\n'
            RETURN count(n) as count
            """
            result = self.run_query(count_query, {"iso_codes": iso_codes})
            count = result[0]["count"] if result else 0
        else:
            with self.driver.session() as session:
                result = session.run(query, {"iso_codes": iso_codes})
                summary = result.consume()
                count = summary.counters.nodes_deleted

        self.stats["locations_bad"] = count
        logger.info(f"  {'Would delete' if self.dry_run else 'Deleted'}: {count} bad location nodes")
        return count

    def merge_duplicate_organizations(self) -> int:
        """Merge duplicate Organization nodes, keeping the tracked version.

        For each org name with duplicates:
        - If tracked version exists, move relationships from non-tracked to tracked
        - Delete non-tracked duplicates

        Handles common relationship types without requiring APOC.
        """
        logger.info("Merging duplicate Organization nodes...")

        # Find duplicates where one is tracked and one is not
        find_duplicates = """
        MATCH (o:Organization)
        WITH o.name AS name, collect(o) AS orgs
        WHERE size(orgs) > 1
        RETURN name
        """

        duplicates = self.run_query(find_duplicates)
        merged_count = 0

        # Common relationship types in the graph
        rel_types = [
            "COMPETES_WITH", "MENTIONS", "DISCUSSES", "FILED",
            "HAS_VULNERABILITY", "HAS_EXECUTIVE_EVENT", "HAS_EVENT",
            "LOCATED_IN", "EMPLOYS", "ACQUIRED", "PARTNERS_WITH"
        ]

        for dup in duplicates:
            name = dup.get("name")
            if not name:
                continue

            if self.dry_run:
                logger.info(f"    Would merge duplicates for: {name}")
                merged_count += 1
            else:
                try:
                    with self.driver.session() as session:
                        # For each relationship type, move from non-tracked to tracked
                        for rel_type in rel_types:
                            # Outgoing relationships
                            session.run(f"""
                                MATCH (tracked:Organization {{name: $name, tracked: true}})
                                MATCH (nonTracked:Organization {{name: $name}})
                                WHERE (nonTracked.tracked IS NULL OR nonTracked.tracked = false)
                                MATCH (nonTracked)-[r:{rel_type}]->(target)
                                MERGE (tracked)-[:{rel_type}]->(target)
                                DELETE r
                            """, {"name": name})

                            # Incoming relationships
                            session.run(f"""
                                MATCH (tracked:Organization {{name: $name, tracked: true}})
                                MATCH (nonTracked:Organization {{name: $name}})
                                WHERE (nonTracked.tracked IS NULL OR nonTracked.tracked = false)
                                MATCH (source)-[r:{rel_type}]->(nonTracked)
                                MERGE (source)-[:{rel_type}]->(tracked)
                                DELETE r
                            """, {"name": name})

                        # Delete the non-tracked duplicate(s)
                        session.run("""
                            MATCH (nonTracked:Organization {name: $name})
                            WHERE (nonTracked.tracked IS NULL OR nonTracked.tracked = false)
                            DETACH DELETE nonTracked
                        """, {"name": name})

                    merged_count += 1
                    logger.info(f"    Merged duplicates for: {name}")
                except Exception as e:
                    logger.warning(f"    Could not merge {name}: {e}")

        self.stats["duplicate_orgs_merged"] = merged_count
        logger.info(f"  {'Would merge' if self.dry_run else 'Merged'}: {merged_count} duplicate organizations")
        return merged_count

    def cleanup_orphan_organizations(self) -> int:
        """Delete orphan Organization nodes (no relationships)."""
        logger.info("Cleaning up orphan Organization nodes...")

        # Don't delete tracked organizations even if they have no relationships yet
        query = """
        MATCH (n:Organization)
        WHERE NOT (n)--()
          AND (n.tracked IS NULL OR n.tracked = false)
        DETACH DELETE n
        """

        if self.dry_run:
            count_query = """
            MATCH (n:Organization)
            WHERE NOT (n)--()
              AND (n.tracked IS NULL OR n.tracked = false)
            RETURN count(n) as count
            """
            result = self.run_query(count_query)
            count = result[0]["count"] if result else 0
        else:
            with self.driver.session() as session:
                result = session.run(query)
                summary = result.consume()
                count = summary.counters.nodes_deleted

        self.stats["orphan_orgs_deleted"] = count
        logger.info(f"  {'Would delete' if self.dry_run else 'Deleted'}: {count} orphan organization nodes")
        return count

    def update_document_types(self) -> int:
        """Update Document nodes with proper type based on their ID."""
        logger.info("Updating Document types...")

        updates = [
            # 10-K filings
            ("MATCH (d:Document) WHERE d.id CONTAINS '10K' AND (d.type IS NULL OR d.type = 'unknown') SET d.type = '10-K'", "10-K"),
            # 10-Q filings
            ("MATCH (d:Document) WHERE d.id CONTAINS '10Q' AND (d.type IS NULL OR d.type = 'unknown') SET d.type = '10-Q'", "10-Q"),
            # Transcripts
            ("MATCH (d:Document) WHERE d.id CONTAINS 'transcript' AND (d.type IS NULL OR d.type = 'unknown') SET d.type = 'transcript'", "transcript"),
            # 8-K filings
            ("MATCH (d:Document) WHERE d.id CONTAINS '8K' AND (d.type IS NULL OR d.type = 'unknown') SET d.type = '8-K'", "8-K"),
        ]

        total_count = 0
        for query, doc_type in updates:
            if self.dry_run:
                count_query = query.replace("SET d.type =", "RETURN count(d) as count //SET d.type =")
                result = self.run_query(count_query)
                count = result[0]["count"] if result else 0
            else:
                with self.driver.session() as session:
                    result = session.run(query)
                    summary = result.consume()
                    count = summary.counters.properties_set

            if count > 0:
                logger.info(f"    {doc_type}: {'Would update' if self.dry_run else 'Updated'} {count} documents")
            total_count += count

        self.stats["documents_updated"] = total_count
        logger.info(f"  Total documents {'would be' if self.dry_run else ''} updated: {total_count}")
        return total_count

    def cleanup_orphan_persons(self, delete: bool = False) -> int:
        """Handle orphan Person nodes (no relationships)."""
        logger.info("Checking orphan Person nodes...")

        count_query = """
        MATCH (n:Person)
        WHERE NOT (n)--()
        RETURN count(n) as count
        """

        result = self.run_query(count_query)
        count = result[0]["count"] if result else 0

        if delete and not self.dry_run and count > 0:
            delete_query = """
            MATCH (n:Person)
            WHERE NOT (n)--()
            DELETE n
            """
            with self.driver.session() as session:
                result = session.run(delete_query)
                summary = result.consume()
                count = summary.counters.nodes_deleted
            self.stats["orphan_persons_deleted"] = count
            logger.info(f"  Deleted: {count} orphan person nodes")
        else:
            logger.info(f"  Found {count} orphan person nodes (not deleting)")

        return count

    def run_cleanup(self, delete_orphans: bool = False) -> Dict:
        """Run all cleanup operations."""
        logger.info(f"\n{'='*60}")
        logger.info(f"Starting Graph Cleanup ({'DRY RUN' if self.dry_run else 'LIVE'})")
        logger.info(f"{'='*60}\n")

        self.cleanup_concepts_with_newlines()
        self.cleanup_concepts_with_separators()
        self.cleanup_persons_as_numbers()
        self.cleanup_persons_as_orgs()
        self.cleanup_bad_locations()
        self.merge_duplicate_organizations()  # Must run before orphan cleanup
        self.cleanup_orphan_organizations()
        self.update_document_types()
        self.cleanup_orphan_persons(delete=delete_orphans)

        logger.info(f"\n{'='*60}")
        logger.info("Cleanup Summary")
        logger.info(f"{'='*60}")

        total_deleted = (
            self.stats["concepts_with_newlines"] +
            self.stats["concepts_with_separators"] +
            self.stats["persons_as_numbers"] +
            self.stats["persons_as_orgs"] +
            self.stats["locations_bad"] +
            self.stats["orphan_orgs_deleted"] +
            self.stats["orphan_persons_deleted"]
        )

        for key, value in self.stats.items():
            logger.info(f"  {key}: {value}")

        logger.info(f"\nTotal nodes {'would be' if self.dry_run else ''} deleted: {total_deleted}")
        logger.info(f"Total documents {'would be' if self.dry_run else ''} updated: {self.stats['documents_updated']}")

        if self.dry_run:
            logger.info("\n*** This was a DRY RUN. No changes were made. ***")
            logger.info("Run with --execute to apply changes.")

        return self.stats


def main():
    parser = argparse.ArgumentParser(description="Clean up Neo4j knowledge graph data quality issues")
    parser.add_argument("--execute", action="store_true", help="Actually execute changes (default is dry run)")
    parser.add_argument("--delete-orphans", action="store_true", help="Also delete orphan Person nodes")
    parser.add_argument("--uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7687"), help="Neo4j URI")
    parser.add_argument("--username", default=os.environ.get("NEO4J_USERNAME", "neo4j"), help="Neo4j username")
    parser.add_argument("--password", default=os.environ.get("NEO4J_PASSWORD", ""), help="Neo4j password")

    args = parser.parse_args()

    if not args.password:
        logger.error("NEO4J_PASSWORD environment variable or --password argument required")
        sys.exit(1)

    dry_run = not args.execute

    cleaner = GraphCleaner(
        uri=args.uri,
        username=args.username,
        password=args.password,
        dry_run=dry_run
    )

    try:
        stats = cleaner.run_cleanup(delete_orphans=args.delete_orphans)
        return 0
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
        return 1
    finally:
        cleaner.close()


if __name__ == "__main__":
    sys.exit(main())
