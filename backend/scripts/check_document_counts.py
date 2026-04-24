#!/usr/bin/env python3
"""
Check document counts between PostgreSQL artifacts and Neo4j Document nodes.
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.database_service import db_service
from services.neo4j_service import get_neo4j_service


def check_counts():
    """Compare document counts between PostgreSQL and Neo4j."""
    print("=" * 60)
    print("Document Count Comparison: PostgreSQL vs Neo4j")
    print("=" * 60)

    # PostgreSQL artifact count
    print("\n1. PostgreSQL Artifacts:")
    try:
        artifacts = db_service.get_all_artifacts()
        pg_total = len(artifacts)
        print(f"   Total artifacts: {pg_total}")

        # Count by type
        type_counts = {}
        for a in artifacts:
            atype = a.get("artifact_type", "unknown")
            type_counts[atype] = type_counts.get(atype, 0) + 1

        print("   By type:")
        for atype, count in sorted(type_counts.items()):
            print(f"     - {atype}: {count}")
    except Exception as e:
        print(f"   Error querying PostgreSQL: {e}")
        pg_total = 0

    # Neo4j document count
    print("\n2. Neo4j Document Nodes:")
    try:
        neo4j = get_neo4j_service()
        stats = neo4j.get_stats()
        neo4j_total = stats.get("documents", 0)
        print(f"   Total Document nodes: {neo4j_total}")

        # Get by type breakdown
        result = neo4j.execute_read("""
            MATCH (d:Document)
            RETURN d.type as type, count(d) as count
            ORDER BY count DESC
            """)
        if result:
            print("   By type:")
            for row in result:
                print(f"     - {row['type']}: {row['count']}")
    except Exception as e:
        print(f"   Error querying Neo4j: {e}")
        neo4j_total = 0

    # Comparison
    print("\n" + "=" * 60)
    print("COMPARISON:")
    print("=" * 60)
    print(f"   PostgreSQL artifacts: {pg_total}")
    print(f"   Neo4j Document nodes: {neo4j_total}")
    diff = pg_total - neo4j_total
    if diff > 0:
        print(f"   MISMATCH: {diff} artifacts NOT in Neo4j graph")
    elif diff < 0:
        print(f"   MISMATCH: {abs(diff)} extra nodes in Neo4j (orphaned?)")
    else:
        print("   MATCH: Counts are equal")

    return {"postgresql": pg_total, "neo4j": neo4j_total, "difference": diff}


if __name__ == "__main__":
    check_counts()
