# =============================================================================
# Neo4j Service - Knowledge Graph Operations
# =============================================================================
#
# This service handles all Neo4j graph database operations for the CyberRisk
# knowledge graph. Supports:
# - CRUD operations for graph nodes and relationships
# - Cypher query execution (with security filters)
# - Graph statistics and visualization data
# - Semantic queries for GraphRAG
#
# Graph Schema (v2):
# ------------------
# Node Labels:
#   :Organization  - Companies and organizations (tracked and mentioned)
#                    Properties: name, ticker, tracked, gics_sector, gics_industry,
#                                cyber_sector, cyber_focus[], description
#   :Location      - Geographic locations mentioned in documents
#   :Event         - Events with date attribute
#   :Person        - People mentioned in documents
#   :Concept       - Key phrases and concepts
#   :Document      - SEC filings, transcripts with date attribute
#   :News          - News articles with date attribute
#
# Relationships:
#   (Organization)-[:FILED]->(Document)
#   (Document)-[:MENTIONS]->(Organization|Location|Person|Event)
#   (Document)-[:DISCUSSES]->(Concept)
#   (Organization)-[:COMPETES_WITH]->(Organization)
#   (Organization)-[:PARTNERS_WITH]->(Organization)
#   (Person)-[:WORKS_FOR]->(Organization)
#
# =============================================================================

import os
import logging
from typing import Dict, List, Any, Optional
from contextlib import contextmanager
from datetime import datetime, date

from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, AuthError
from neo4j.time import DateTime as Neo4jDateTime, Date as Neo4jDate

logger = logging.getLogger(__name__)


def _serialize_neo4j_value(value):
    """Convert Neo4j types to JSON-serializable Python types."""
    from neo4j.graph import Node, Relationship

    if isinstance(value, Node):
        # Convert Neo4j Node to dict with labels and properties
        return {
            "labels": list(value.labels),
            "properties": _serialize_neo4j_value(dict(value)),
        }
    elif isinstance(value, Relationship):
        # Convert Neo4j Relationship to dict
        return {"type": value.type, "properties": _serialize_neo4j_value(dict(value))}
    elif isinstance(value, (Neo4jDateTime, Neo4jDate)):
        return value.iso_format()
    elif isinstance(value, (datetime, date)):
        return value.isoformat()
    elif isinstance(value, list):
        return [_serialize_neo4j_value(v) for v in value]
    elif isinstance(value, dict):
        return {k: _serialize_neo4j_value(v) for k, v in value.items()}
    return value


class Neo4jService:
    """
    Neo4j graph database service for CyberRisk knowledge graph.

    Manages connections and provides methods for querying and updating
    the knowledge graph containing companies, documents, entities, and
    their relationships.
    """

    # Keywords blocked in public Cypher queries (prevent destructive operations)
    DANGEROUS_KEYWORDS = [
        "DELETE",
        "REMOVE",
        "DROP",
        "CREATE",
        "SET",
        "MERGE",
        "DETACH",
        "CALL",
        "LOAD",
        "FOREACH",
    ]

    def __init__(self, uri: str = None, username: str = None, password: str = None):
        """
        Initialize Neo4j connection.

        Args:
            uri: Neo4j Bolt URI (default from environment)
            username: Neo4j username (default: neo4j)
            password: Neo4j password (from environment)
        """
        self.uri = uri or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        self.username = username or os.environ.get("NEO4J_USERNAME", "neo4j")
        self.password = password or os.environ.get("NEO4J_PASSWORD", "")

        self._driver = None
        self._connected = False

    @property
    def driver(self):
        """Lazy initialization of Neo4j driver."""
        if self._driver is None:
            try:
                self._driver = GraphDatabase.driver(
                    self.uri,
                    auth=(self.username, self.password),
                    max_connection_lifetime=3600,
                    max_connection_pool_size=50,
                    connection_acquisition_timeout=60,
                )
                # Verify connectivity
                self._driver.verify_connectivity()
                self._connected = True
                logger.info(f"Connected to Neo4j at {self.uri}")
            except (ServiceUnavailable, AuthError) as e:
                logger.error(f"Failed to connect to Neo4j: {e}")
                self._connected = False
                raise
        return self._driver

    def close(self):
        """Close the Neo4j driver connection."""
        if self._driver:
            self._driver.close()
            self._driver = None
            self._connected = False

    @contextmanager
    def session(self):
        """Context manager for Neo4j sessions."""
        session = self.driver.session()
        try:
            yield session
        finally:
            session.close()

    def is_connected(self) -> bool:
        """Check if connected to Neo4j."""
        try:
            # Access driver property to trigger lazy initialization
            driver = self.driver
            driver.verify_connectivity()
            return True
        except Exception as e:
            logger.debug(f"Neo4j connection check failed: {e}")
            return False

    # =========================================================================
    # Query Execution
    # =========================================================================

    def execute_read(self, query: str, parameters: Dict = None) -> List[Dict]:
        """
        Execute a read-only Cypher query.

        Args:
            query: Cypher query string
            parameters: Query parameters

        Returns:
            List of result records as dictionaries
        """
        with self.session() as session:
            result = session.run(query, parameters or {})
            return [dict(record) for record in result]

    def execute_write(self, query: str, parameters: Dict = None) -> Dict:
        """
        Execute a write Cypher query.

        Args:
            query: Cypher query string
            parameters: Query parameters

        Returns:
            Summary of the operation
        """
        with self.session() as session:
            result = session.run(query, parameters or {})
            summary = result.consume()
            return {
                "nodes_created": summary.counters.nodes_created,
                "nodes_deleted": summary.counters.nodes_deleted,
                "relationships_created": summary.counters.relationships_created,
                "relationships_deleted": summary.counters.relationships_deleted,
                "properties_set": summary.counters.properties_set,
            }

    def execute_cypher_safe(self, query: str) -> Dict:
        """
        Execute a Cypher query with security filters (for public console).

        Blocks destructive operations like DELETE, CREATE, etc.

        Args:
            query: Cypher query from user

        Returns:
            Query results or error
        """
        # Security check - block dangerous keywords
        query_upper = query.upper()
        for keyword in self.DANGEROUS_KEYWORDS:
            if keyword in query_upper:
                return {
                    "error": f'Operation "{keyword}" not allowed in console',
                    "allowed_operations": [
                        "MATCH",
                        "RETURN",
                        "WHERE",
                        "WITH",
                        "ORDER BY",
                        "LIMIT",
                    ],
                }

        try:
            with self.session() as session:
                result = session.run(query)
                records = list(result)

                if not records:
                    return {"columns": [], "records": [], "count": 0}

                # Extract column names from first record
                columns = list(records[0].keys()) if records else []

                # Convert records to serializable format
                data = []
                for record in records:
                    row = {}
                    for key in columns:
                        value = record[key]
                        row[key] = self._serialize_value(value)
                    data.append(row)

                return {"columns": columns, "records": data, "count": len(data)}

        except Exception as e:
            logger.error(f"Cypher execution error: {e}")
            return {"error": str(e)}

    def _serialize_value(self, value: Any) -> Any:
        """Convert Neo4j values to JSON-serializable format."""
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool)):
            return value
        # Handle Neo4j DateTime and Date objects
        if isinstance(value, (Neo4jDateTime, Neo4jDate)):
            return value.iso_format()
        # Handle Python datetime and date objects
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, list):
            return [self._serialize_value(v) for v in value]
        if isinstance(value, dict):
            return {k: self._serialize_value(v) for k, v in value.items()}
        # Handle Neo4j Node objects
        if hasattr(value, "labels") and hasattr(value, "items"):
            # Recursively serialize properties to handle DateTime values
            props = {
                k: self._serialize_value(v) for k, v in dict(value.items()).items()
            }
            return {"_type": "node", "labels": list(value.labels), "properties": props}
        # Handle Neo4j Relationship objects
        if hasattr(value, "type") and hasattr(value, "start_node"):
            # Recursively serialize properties to handle DateTime values
            props = {
                k: self._serialize_value(v) for k, v in dict(value.items()).items()
            }
            return {"_type": "relationship", "type": value.type, "properties": props}
        # Fallback
        return str(value)

    # =========================================================================
    # Graph Statistics
    # =========================================================================

    def get_stats(self) -> Dict:
        """Get knowledge graph statistics."""
        query = """
            CALL {
                MATCH (o:Organization) RETURN count(o) as organizations
            }
            CALL {
                MATCH (o:Organization {tracked: true}) RETURN count(o) as tracked_companies
            }
            CALL {
                MATCH (d:Document) RETURN count(d) as documents
            }
            CALL {
                MATCH (l:Location) RETURN count(l) as locations
            }
            CALL {
                MATCH (e:Event) RETURN count(e) as events
            }
            CALL {
                MATCH (p:Person) RETURN count(p) as persons
            }
            CALL {
                MATCH (con:Concept) RETURN count(con) as concepts
            }
            CALL {
                MATCH (n:News) RETURN count(n) as news
            }
            CALL {
                MATCH (pat:Patent) RETURN count(pat) as patents
            }
            CALL {
                MATCH ()-[r]->() RETURN count(r) as relationships
            }
            RETURN organizations, tracked_companies, documents, locations, events,
                   persons, concepts, news, patents, relationships
        """

        try:
            results = self.execute_read(query)
            if results:
                return results[0]
            return {
                "organizations": 0,
                "tracked_companies": 0,
                "documents": 0,
                "locations": 0,
                "events": 0,
                "persons": 0,
                "concepts": 0,
                "news": 0,
                "patents": 0,
                "relationships": 0,
            }
        except Exception as e:
            logger.error(f"Error getting graph stats: {e}")
            return {"error": str(e)}

    # =========================================================================
    # Company Graph Visualization
    # =========================================================================

    def get_company_graph(
        self,
        ticker: str,
        depth: int = 2,
        include_organizations: bool = True,
        include_locations: bool = True,
        include_concepts: bool = True,
        include_documents: bool = False,
        limit: int = 100,
    ) -> Dict:
        """
        Get graph data for visualization centered on a company.

        Since tracked organizations (with tickers) don't have direct relationships,
        we find organization entities by name that match the tracked company.

        Args:
            ticker: Company ticker symbol
            depth: How many relationship hops to include
            include_organizations: Include other Organization nodes
            include_locations: Include Location nodes
            include_concepts: Include Concept nodes
            include_documents: Include Document nodes
            limit: Maximum nodes to return

        Returns:
            Graph data with nodes and links for visualization
        """
        # Build node type filter
        node_types = ["Organization", "Person", "Event", "Patent"]
        if include_locations:
            node_types.append("Location")
        if include_concepts:
            node_types.append("Concept")
        if include_documents:
            node_types.append("Document")

        # First get the tracked company's name
        name_query = """
            MATCH (o:Organization {ticker: $ticker, tracked: true})
            RETURN o.name as name
        """
        name_result = self.execute_read(name_query, {"ticker": ticker.upper()})
        if not name_result:
            return {"nodes": [], "links": [], "ticker": ticker}

        company_name = name_result[0]["name"]
        # Extract core company name (e.g., "CrowdStrike" from "CrowdStrike Holdings")
        core_name = company_name.split()[0] if company_name else ticker

        # Query to find entities related to this company via documents and patents
        query = f"""
            // Find organization entities that match the company name
            MATCH (o:Organization)
            WHERE o.name CONTAINS $core_name OR o.ticker = $ticker
            WITH collect(DISTINCT o) as startOrgs

            // Find documents that mention these orgs
            UNWIND startOrgs as startOrg
            OPTIONAL MATCH (d:Document)-[:MENTIONS]->(startOrg)
            OPTIONAL MATCH (d)-[:MENTIONS]->(entity)
            WHERE entity <> startOrg

            // Also find patents filed by matching orgs
            OPTIONAL MATCH (startOrg)-[:FILED]->(patent:Patent)
            OPTIONAL MATCH (inventor:Person)-[:INVENTED]->(patent)

            // Collect all nodes
            WITH startOrgs + collect(DISTINCT d) + collect(DISTINCT entity) +
                 collect(DISTINCT patent) + collect(DISTINCT inventor) as allNodes

            // Filter out nulls and limit
            UNWIND allNodes as n
            WITH n WHERE n IS NOT NULL
            WITH collect(DISTINCT n)[0..$limit] as nodes

            // Get relationships between collected nodes
            UNWIND nodes as n1
            UNWIND nodes as n2
            OPTIONAL MATCH (n1)-[r]-(n2)
            WHERE n1 <> n2

            WITH nodes, collect(DISTINCT r) as relationships

            RETURN nodes, [r IN relationships WHERE r IS NOT NULL] as relationships
        """

        # Simpler fallback without complex path traversal
        fallback_query = """
            // Find organizations matching the company
            MATCH (o:Organization)
            WHERE o.name CONTAINS $core_name OR o.ticker = $ticker

            // Get documents mentioning these orgs and their mentioned entities
            OPTIONAL MATCH (d:Document)-[:MENTIONS]->(o)
            OPTIONAL MATCH (d)-[r2:MENTIONS]->(e)

            // Get patents filed by matching orgs
            OPTIONAL MATCH (o)-[:FILED]->(p:Patent)
            OPTIONAL MATCH (inv:Person)-[:INVENTED]->(p)

            // Collect distinct nodes
            WITH collect(DISTINCT o) + collect(DISTINCT d)[0..20] +
                 collect(DISTINCT e)[0..30] + collect(DISTINCT p)[0..20] +
                 collect(DISTINCT inv)[0..20] as allNodes

            // Filter nulls and limit
            UNWIND allNodes as n
            WITH n WHERE n IS NOT NULL
            WITH collect(DISTINCT n)[0..$limit] as nodes

            // Get relationships
            UNWIND nodes as n1
            UNWIND nodes as n2
            OPTIONAL MATCH (n1)-[r]-(n2)
            WHERE id(n1) < id(n2)

            WITH nodes, collect(DISTINCT r) as rels
            RETURN nodes, [r IN rels WHERE r IS NOT NULL] as relationships
        """

        try:
            results = self.execute_read(
                fallback_query,
                {"ticker": ticker.upper(), "core_name": core_name, "limit": limit},
            )
        except Exception as e:
            logger.error(f"Graph query failed: {e}")
            return {"nodes": [], "links": [], "ticker": ticker}

        if not results:
            return {"nodes": [], "links": []}

        result = results[0]
        nodes_data = result.get("nodes", [])
        rels_data = result.get("relationships", [])

        # Convert to visualization format
        nodes = []
        node_ids = set()

        for node in nodes_data:
            if node is None:
                continue
            node_id = node.element_id if hasattr(node, "element_id") else str(id(node))
            if node_id in node_ids:
                continue
            node_ids.add(node_id)

            labels = list(node.labels) if hasattr(node, "labels") else ["Unknown"]
            props = dict(node.items()) if hasattr(node, "items") else {}
            # Serialize Neo4j types to JSON-compatible values
            props = _serialize_neo4j_value(props)

            nodes.append(
                {
                    "id": node_id,
                    "labels": labels,
                    "name": props.get("name")
                    or props.get("ticker")
                    or props.get("headline", "Unknown"),
                    "type": labels[0] if labels else "Unknown",
                    "properties": props,
                }
            )

        links = []
        for rel in rels_data:
            if rel is None:
                continue
            try:
                rel_props = dict(rel.items()) if hasattr(rel, "items") else {}
                links.append(
                    {
                        "source": rel.start_node.element_id,
                        "target": rel.end_node.element_id,
                        "type": rel.type,
                        "properties": _serialize_neo4j_value(rel_props),
                    }
                )
            except Exception:
                pass

        return {"nodes": nodes, "links": links}

    # =========================================================================
    # Semantic Query for GraphRAG
    # =========================================================================

    def semantic_query(self, query: str, ticker: str = None) -> Dict:
        """
        Natural language query over knowledge graph (for GraphRAG).

        This is a simplified pattern matching approach. In production,
        you'd use embeddings and vector similarity.

        Args:
            query: Natural language query
            ticker: Optional ticker to filter by

        Returns:
            Relevant graph context
        """
        # Extract potential entity mentions from query
        keywords = [w.strip().lower() for w in query.split() if len(w) > 2]

        # Build Cypher query to find relevant nodes
        cypher = """
            // Find matching organizations, locations, concepts, persons, patents
            MATCH (n)
            WHERE any(label IN labels(n) WHERE label IN ['Organization', 'Location', 'Concept', 'Person', 'Event', 'Patent'])
              AND any(kw IN $keywords WHERE toLower(n.name) CONTAINS kw
                                         OR toLower(n.normalized_name) CONTAINS kw
                                         OR toLower(n.title) CONTAINS kw)
            WITH n LIMIT 10

            // Get connected context
            OPTIONAL MATCH (n)-[r]-(connected)
            WHERE connected:Organization OR connected:Document

            RETURN n as entity,
                   collect(DISTINCT {
                       node: connected,
                       relationship: type(r)
                   })[0..5] as context
        """

        if ticker:
            cypher = """
                MATCH (o:Organization {ticker: $ticker})
                MATCH (o)-[:FILED|HAS_FILING]->(d:Document)
                OPTIONAL MATCH (d)-[:MENTIONS|DISCUSSES]->(n)
                WHERE any(kw IN $keywords WHERE toLower(n.name) CONTAINS kw)
                WITH o, n, d
                RETURN n as entity,
                       collect(DISTINCT {document: d.type, date: d.date})[0..5] as mentions
                LIMIT 10
            """

        try:
            results = self.execute_read(
                cypher,
                {"keywords": keywords, "ticker": ticker.upper() if ticker else None},
            )

            # Serialize Neo4j Node/Relationship objects to JSON-serializable dicts
            serialized_results = _serialize_neo4j_value(results)

            return {
                "query": query,
                "ticker": ticker,
                "results": serialized_results,
                "keywords_extracted": keywords,
            }
        except Exception as e:
            logger.error(f"Semantic query error: {e}")
            return {"error": str(e)}

    def get_patents(
        self,
        ticker: str = None,
        inventor_name: str = None,
        search_term: str = None,
        limit: int = 10,
    ) -> Dict:
        """
        Query patents from the knowledge graph.

        Args:
            ticker: Stock ticker to get patents for a company
            inventor_name: Name of inventor to search
            search_term: General search term for patent title
            limit: Maximum number of patents to return

        Returns:
            Dict with patents and metadata
        """
        try:
            if ticker:
                # Get patents filed by a specific company
                query = """
                    MATCH (o:Organization)-[:FILED]->(p:Patent)
                    WHERE o.ticker = $ticker OR toLower(o.name) CONTAINS toLower($ticker)
                    OPTIONAL MATCH (inventor:Person)-[:INVENTED]->(p)
                    RETURN p.patent_number as patent_number,
                           p.title as title,
                           p.filing_date as filing_date,
                           p.grant_date as grant_date,
                           p.patent_url as patent_url,
                           o.name as assignee,
                           collect(DISTINCT inventor.name) as inventors
                    ORDER BY p.filing_date DESC
                    LIMIT $limit
                """
                results = self.execute_read(
                    query, {"ticker": ticker.upper(), "limit": limit}
                )

            elif inventor_name:
                # Get patents by inventor
                query = """
                    MATCH (inventor:Person)-[:INVENTED]->(p:Patent)
                    WHERE toLower(inventor.name) CONTAINS toLower($inventor_name)
                    OPTIONAL MATCH (o:Organization)-[:FILED]->(p)
                    RETURN p.patent_number as patent_number,
                           p.title as title,
                           p.filing_date as filing_date,
                           p.grant_date as grant_date,
                           p.patent_url as patent_url,
                           collect(DISTINCT o.name) as assignees,
                           inventor.name as inventor
                    ORDER BY p.filing_date DESC
                    LIMIT $limit
                """
                results = self.execute_read(
                    query, {"inventor_name": inventor_name, "limit": limit}
                )

            elif search_term:
                # Search patents by title
                keywords = [
                    w.strip().lower() for w in search_term.split() if len(w) > 2
                ]
                query = """
                    MATCH (p:Patent)
                    WHERE any(kw IN $keywords WHERE toLower(p.title) CONTAINS kw)
                    OPTIONAL MATCH (o:Organization)-[:FILED]->(p)
                    OPTIONAL MATCH (inventor:Person)-[:INVENTED]->(p)
                    RETURN p.patent_number as patent_number,
                           p.title as title,
                           p.filing_date as filing_date,
                           p.grant_date as grant_date,
                           p.patent_url as patent_url,
                           collect(DISTINCT o.name) as assignees,
                           collect(DISTINCT inventor.name) as inventors
                    ORDER BY p.filing_date DESC
                    LIMIT $limit
                """
                results = self.execute_read(
                    query, {"keywords": keywords, "limit": limit}
                )

            else:
                # Get recent patents
                query = """
                    MATCH (p:Patent)
                    OPTIONAL MATCH (o:Organization)-[:FILED]->(p)
                    OPTIONAL MATCH (inventor:Person)-[:INVENTED]->(p)
                    RETURN p.patent_number as patent_number,
                           p.title as title,
                           p.filing_date as filing_date,
                           p.grant_date as grant_date,
                           p.patent_url as patent_url,
                           collect(DISTINCT o.name) as assignees,
                           collect(DISTINCT inventor.name) as inventors
                    ORDER BY p.filing_date DESC
                    LIMIT $limit
                """
                results = self.execute_read(query, {"limit": limit})

            # Get total patent count
            count_query = "MATCH (p:Patent) RETURN count(p) as total"
            count_result = self.execute_read(count_query)
            total_patents = count_result[0]["total"] if count_result else 0

            # Serialize results
            serialized_results = _serialize_neo4j_value(results)

            return {
                "patents": serialized_results,
                "count": len(serialized_results),
                "total_patents_in_graph": total_patents,
                "query_params": {
                    "ticker": ticker,
                    "inventor_name": inventor_name,
                    "search_term": search_term,
                },
            }

        except Exception as e:
            logger.error(f"Patent query error: {e}")
            return {"error": str(e), "patents": []}

    # =========================================================================
    # Node CRUD Operations
    # =========================================================================

    def create_organization(
        self,
        name: str,
        ticker: str = None,
        tracked: bool = False,
        gics_sector: str = None,
        gics_industry: str = None,
        cyber_sector: str = None,
        cyber_focus: list = None,
        description: str = None,
        exchange: str = None,
        location: str = None,
        domain: str = None,
        alternate_names: list = None,
        **properties,
    ) -> Dict:
        """
        Create or update an Organization node.

        For tracked companies (our analysis targets), set tracked=True and provide ticker.
        For mentioned organizations, set tracked=False.

        Args:
            alternate_names: List of aliases for entity resolution (e.g., ["Palo Alto", "PANW", "PAN"])
        """
        if ticker:
            # Tracked company - merge on ticker
            query = """
                MERGE (o:Organization {ticker: $ticker})
                SET o.name = $name,
                    o.tracked = $tracked,
                    o.gics_sector = $gics_sector,
                    o.gics_industry = $gics_industry,
                    o.cyber_sector = $cyber_sector,
                    o.cyber_focus = $cyber_focus,
                    o.description = $description,
                    o.exchange = $exchange,
                    o.location = $location,
                    o.domain = $domain,
                    o.alternate_names = $alternate_names,
                    o.updated_at = datetime()
                SET o += $properties
                RETURN o
            """
        else:
            # Mentioned organization - merge on normalized name
            normalized = name.lower().replace(" ", "_")
            query = """
                MERGE (o:Organization {normalized_name: $normalized})
                ON CREATE SET o.name = $name,
                              o.tracked = false,
                              o.first_mentioned = date(),
                              o.mention_count = 1
                ON MATCH SET o.mention_count = o.mention_count + 1
                RETURN o
            """
            return self.execute_write(query, {"name": name, "normalized": normalized})

        return self.execute_write(
            query,
            {
                "name": name,
                "ticker": ticker.upper() if ticker else None,
                "tracked": tracked,
                "gics_sector": gics_sector,
                "gics_industry": gics_industry,
                "cyber_sector": cyber_sector,
                "cyber_focus": cyber_focus or [],
                "description": description,
                "exchange": exchange,
                "location": location,
                "domain": domain,
                "alternate_names": alternate_names or [],
                "properties": properties,
            },
        )

    def create_document(
        self,
        doc_id: str,
        ticker: str,
        doc_type: str,
        s3_key: str,
        date: str = None,
        **properties,
    ) -> Dict:
        """Create a Document node linked to a tracked Organization."""
        query = """
            MATCH (o:Organization {ticker: $ticker, tracked: true})
            MERGE (d:Document {id: $doc_id})
            SET d.type = $doc_type,
                d.s3_key = $s3_key,
                d.ticker = $ticker,
                d.date = $date,
                d.created_at = datetime()
            SET d += $properties
            MERGE (o)-[:FILED]->(d)
            RETURN d
        """
        return self.execute_write(
            query,
            {
                "doc_id": doc_id,
                "ticker": ticker.upper(),
                "doc_type": doc_type,
                "s3_key": s3_key,
                "date": date,
                "properties": properties,
            },
        )

    def create_location(
        self, name: str, normalized_name: str = None, location_type: str = None
    ) -> Dict:
        """Create a Location node."""
        if not normalized_name:
            normalized_name = name.lower().replace(" ", "_")

        query = """
            MERGE (l:Location {normalized_name: $normalized})
            ON CREATE SET l.name = $name,
                          l.type = $type,
                          l.first_mentioned = date(),
                          l.mention_count = 1
            ON MATCH SET l.mention_count = l.mention_count + 1
            RETURN l
        """
        return self.execute_write(
            query, {"name": name, "normalized": normalized_name, "type": location_type}
        )

    def create_event(
        self,
        name: str,
        date: str = None,
        normalized_name: str = None,
        event_type: str = None,
    ) -> Dict:
        """Create an Event node."""
        if not normalized_name:
            normalized_name = name.lower().replace(" ", "_")

        query = """
            MERGE (e:Event {normalized_name: $normalized})
            ON CREATE SET e.name = $name,
                          e.date = $date,
                          e.type = $type,
                          e.first_mentioned = date(),
                          e.mention_count = 1
            ON MATCH SET e.mention_count = e.mention_count + 1
            RETURN e
        """
        return self.execute_write(
            query,
            {
                "name": name,
                "date": date,
                "normalized": normalized_name,
                "type": event_type,
            },
        )

    def create_person(
        self, name: str, title: str = None, normalized_name: str = None, **properties
    ) -> Dict:
        """Create a Person node."""
        if not normalized_name:
            normalized_name = name.lower().replace(" ", "_")

        query = """
            MERGE (p:Person {normalized_name: $normalized})
            ON CREATE SET p.name = $name,
                          p.title = $title,
                          p.first_mentioned = date()
            SET p += $properties
            RETURN p
        """
        return self.execute_write(
            query,
            {
                "name": name,
                "title": title,
                "normalized": normalized_name,
                "properties": properties,
            },
        )

    def create_concept(self, name: str, normalized_name: str = None) -> Dict:
        """Create a Concept node (key phrase)."""
        if not normalized_name:
            normalized_name = name.lower().replace(" ", "_")

        query = """
            MERGE (c:Concept {normalized_name: $normalized})
            ON CREATE SET c.name = $name,
                          c.first_mentioned = date(),
                          c.mention_count = 1
            ON MATCH SET c.mention_count = c.mention_count + 1
            RETURN c
        """
        return self.execute_write(query, {"name": name, "normalized": normalized_name})

    def link_document_organization(
        self, doc_id: str, org_normalized: str, count: int = 1, sentiment: float = 0.0
    ) -> Dict:
        """Create MENTIONS relationship between Document and Organization."""
        query = """
            MATCH (d:Document {id: $doc_id})
            MATCH (o:Organization {normalized_name: $org})
            MERGE (d)-[r:MENTIONS]->(o)
            SET r.count = $count,
                r.sentiment = $sentiment
            RETURN r
        """
        return self.execute_write(
            query,
            {
                "doc_id": doc_id,
                "org": org_normalized,
                "count": count,
                "sentiment": sentiment,
            },
        )

    def link_document_location(
        self, doc_id: str, loc_normalized: str, count: int = 1
    ) -> Dict:
        """Create MENTIONS relationship between Document and Location."""
        query = """
            MATCH (d:Document {id: $doc_id})
            MATCH (l:Location {normalized_name: $loc})
            MERGE (d)-[r:MENTIONS]->(l)
            SET r.count = $count
            RETURN r
        """
        return self.execute_write(
            query, {"doc_id": doc_id, "loc": loc_normalized, "count": count}
        )

    def link_document_concept(
        self,
        doc_id: str,
        concept_normalized: str,
        count: int = 1,
        relevance: float = 0.0,
    ) -> Dict:
        """Create DISCUSSES relationship between Document and Concept."""
        query = """
            MATCH (d:Document {id: $doc_id})
            MATCH (c:Concept {normalized_name: $concept})
            MERGE (d)-[r:DISCUSSES]->(c)
            SET r.count = $count,
                r.relevance = $relevance
            RETURN r
        """
        return self.execute_write(
            query,
            {
                "doc_id": doc_id,
                "concept": concept_normalized,
                "count": count,
                "relevance": relevance,
            },
        )

    def link_person_organization(
        self, person_normalized: str, org_normalized: str, role: str = None
    ) -> Dict:
        """Create WORKS_FOR relationship between Person and Organization."""
        query = """
            MATCH (p:Person {normalized_name: $person})
            MATCH (o:Organization {normalized_name: $org})
            MERGE (p)-[r:WORKS_FOR]->(o)
            SET r.role = $role
            RETURN r
        """
        return self.execute_write(
            query, {"person": person_normalized, "org": org_normalized, "role": role}
        )

    # =========================================================================
    # Graph Management
    # =========================================================================

    def clear_graph(self) -> Dict:
        """
        Clear all nodes and relationships from the graph.

        WARNING: This is destructive and cannot be undone.
        """
        query = """
            MATCH (n)
            DETACH DELETE n
        """
        return self.execute_write(query)

    def create_indexes(self) -> Dict:
        """Create indexes for common query patterns."""
        indexes = [
            "CREATE INDEX org_ticker IF NOT EXISTS FOR (o:Organization) ON (o.ticker)",
            "CREATE INDEX org_normalized IF NOT EXISTS FOR (o:Organization) ON (o.normalized_name)",
            "CREATE INDEX org_tracked IF NOT EXISTS FOR (o:Organization) ON (o.tracked)",
            "CREATE INDEX doc_id IF NOT EXISTS FOR (d:Document) ON (d.id)",
            "CREATE INDEX doc_ticker IF NOT EXISTS FOR (d:Document) ON (d.ticker)",
            "CREATE INDEX person_normalized IF NOT EXISTS FOR (p:Person) ON (p.normalized_name)",
            "CREATE INDEX location_normalized IF NOT EXISTS FOR (l:Location) ON (l.normalized_name)",
            "CREATE INDEX event_normalized IF NOT EXISTS FOR (e:Event) ON (e.normalized_name)",
            "CREATE INDEX concept_normalized IF NOT EXISTS FOR (c:Concept) ON (c.normalized_name)",
        ]

        results = []
        for idx_query in indexes:
            try:
                self.execute_write(idx_query)
                results.append({"query": idx_query, "status": "success"})
            except Exception as e:
                results.append({"query": idx_query, "status": "error", "error": str(e)})

        return {"indexes_created": results}

    def get_schema_info(self) -> Dict:
        """Get information about the graph schema."""
        return {
            "version": "2.0",
            "node_labels": {
                "Organization": "Companies and organizations (tracked and mentioned)",
                "Location": "Geographic locations mentioned in documents",
                "Event": "Events with date attribute",
                "Person": "People mentioned in documents",
                "Concept": "Key phrases and concepts",
                "Document": "SEC filings, transcripts with date attribute",
                "News": "News articles with date attribute",
            },
            "relationships": {
                "FILED": "(Organization)-[:FILED]->(Document)",
                "MENTIONS": "(Document)-[:MENTIONS]->(Organization|Location|Person|Event)",
                "DISCUSSES": "(Document)-[:DISCUSSES]->(Concept)",
                "COMPETES_WITH": "(Organization)-[:COMPETES_WITH]->(Organization)",
                "PARTNERS_WITH": "(Organization)-[:PARTNERS_WITH]->(Organization)",
                "WORKS_FOR": "(Person)-[:WORKS_FOR]->(Organization)",
            },
            "taxonomy": {
                "gics": "Global Industry Classification Standard (Sector, Industry)",
                "cyber_sector": "CyberRisk custom cybersecurity sector classification",
            },
        }


# =============================================================================
# Singleton Instance
# =============================================================================

_neo4j_service = None


def get_neo4j_service() -> Neo4jService:
    """Get or create Neo4j service singleton."""
    global _neo4j_service
    if _neo4j_service is None:
        _neo4j_service = Neo4jService()
    return _neo4j_service


# Convenience alias
neo4j_service = None


def init_neo4j_service():
    """Initialize the Neo4j service (call at app startup)."""
    global neo4j_service
    try:
        neo4j_service = get_neo4j_service()
        if neo4j_service.is_connected():
            logger.info("Neo4j service initialized successfully")
        else:
            logger.warning("Neo4j service created but not connected")
    except Exception as e:
        logger.error(f"Failed to initialize Neo4j service: {e}")
        neo4j_service = None
