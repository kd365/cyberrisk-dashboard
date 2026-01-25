# =============================================================================
# Graph Data Science (GDS) Service - Advanced Graph Analytics
# =============================================================================
#
# This service provides access to Neo4j GDS algorithms for competitive
# intelligence and risk analysis on the CyberRisk knowledge graph.
#
# Capabilities:
# - Centrality Analysis: PageRank, Betweenness, Degree
# - Community Detection: Louvain, Label Propagation, WCC
# - Similarity Analysis: Node Similarity, Jaccard
# - Path Finding: Shortest paths, influence chains
#
# =============================================================================

import os
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, ClientError

logger = logging.getLogger(__name__)


class GDSService:
    """
    Neo4j Graph Data Science service for CyberRisk analytics.

    Provides graph algorithms for competitive intelligence:
    - Market leaders (PageRank on COMPETES_WITH)
    - Acquisition targets (Betweenness centrality)
    - Market segments (Louvain community detection)
    - Similar companies (Node similarity)
    """

    def __init__(self, uri: str = None, username: str = None, password: str = None):
        """Initialize GDS service with Neo4j connection."""
        self.uri = uri or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        self.username = username or os.environ.get("NEO4J_USERNAME", "neo4j")
        self.password = password or os.environ.get("NEO4J_PASSWORD", "")
        self._driver = None

    @property
    def driver(self):
        """Lazy initialization of Neo4j driver."""
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                self.uri,
                auth=(self.username, self.password),
                max_connection_lifetime=3600,
            )
            self._driver.verify_connectivity()
            logger.info(f"GDS Service connected to Neo4j at {self.uri}")
        return self._driver

    def close(self):
        """Close the Neo4j driver connection."""
        if self._driver:
            self._driver.close()
            self._driver = None

    def get_gds_version(self) -> str:
        """Get the installed GDS version."""
        with self.driver.session() as session:
            result = session.run("RETURN gds.version() AS version")
            record = result.single()
            return record["version"] if record else "unknown"

    # =========================================================================
    # Graph Projection Management
    # =========================================================================

    def create_competition_graph(self) -> Dict[str, Any]:
        """
        Create a graph projection for competition analysis.

        Projects: Organization nodes with COMPETES_WITH relationships.
        Used for: PageRank, Betweenness, Community Detection.
        """
        graph_name = "competition_graph"

        # Drop existing projection if any
        self._drop_graph_if_exists(graph_name)

        # Simple native projection without boolean properties
        query = """
        CALL gds.graph.project(
            $graph_name,
            'Organization',
            {
                COMPETES_WITH: {
                    orientation: 'UNDIRECTED'
                }
            }
        )
        YIELD graphName, nodeCount, relationshipCount, projectMillis
        RETURN graphName, nodeCount, relationshipCount, projectMillis
        """

        with self.driver.session() as session:
            result = session.run(query, {"graph_name": graph_name})
            record = result.single()
            return {
                "graph_name": record["graphName"],
                "node_count": record["nodeCount"],
                "relationship_count": record["relationshipCount"],
                "project_millis": record["projectMillis"],
            }

    def create_patent_similarity_graph(self) -> Dict[str, Any]:
        """
        Create a graph projection for patent portfolio similarity.

        Projects: Organization nodes connected to Patent nodes via FILED.
        Used for: Node Similarity to find companies with similar IP portfolios.
        """
        graph_name = "patent_similarity_graph"

        self._drop_graph_if_exists(graph_name)

        query = """
        CALL gds.graph.project(
            $graph_name,
            ['Organization', 'Patent'],
            {
                FILED: {
                    orientation: 'NATURAL'
                }
            }
        )
        YIELD graphName, nodeCount, relationshipCount
        RETURN graphName, nodeCount, relationshipCount
        """

        with self.driver.session() as session:
            result = session.run(query, {"graph_name": graph_name})
            record = result.single()
            return {
                "graph_name": record["graphName"],
                "node_count": record["nodeCount"],
                "relationship_count": record["relationshipCount"],
            }

    def create_concept_similarity_graph(self) -> Dict[str, Any]:
        """
        Create a graph projection for concept/topic similarity.

        Projects: Organization -> Document -> Concept paths.
        Used for: Finding companies discussing similar topics.
        """
        graph_name = "concept_similarity_graph"

        self._drop_graph_if_exists(graph_name)

        # Create bipartite projection: Organization - Concept
        query = """
        CALL gds.graph.project.cypher(
            $graph_name,
            'MATCH (n) WHERE n:Organization OR n:Concept RETURN id(n) AS id, labels(n) AS labels',
            'MATCH (o:Organization)-[:HAS_FILING]->(:Document)-[:DISCUSSES]->(c:Concept)
             RETURN id(o) AS source, id(c) AS target'
        )
        YIELD graphName, nodeCount, relationshipCount
        RETURN graphName, nodeCount, relationshipCount
        """

        with self.driver.session() as session:
            result = session.run(query, {"graph_name": graph_name})
            record = result.single()
            return {
                "graph_name": record["graphName"],
                "node_count": record["nodeCount"],
                "relationship_count": record["relationshipCount"],
            }

    def _drop_graph_if_exists(self, graph_name: str):
        """Drop a graph projection if it exists."""
        query = """
        CALL gds.graph.exists($graph_name) YIELD exists
        WITH exists WHERE exists
        CALL gds.graph.drop($graph_name) YIELD graphName
        RETURN graphName
        """
        with self.driver.session() as session:
            try:
                session.run(query, {"graph_name": graph_name})
            except ClientError:
                pass  # Graph doesn't exist, that's fine

    def list_graphs(self) -> List[Dict[str, Any]]:
        """List all existing graph projections."""
        query = """
        CALL gds.graph.list()
        YIELD graphName, nodeCount, relationshipCount, creationTime
        RETURN graphName, nodeCount, relationshipCount, creationTime
        """
        with self.driver.session() as session:
            result = session.run(query)
            return [
                {
                    "name": r["graphName"],
                    "nodes": r["nodeCount"],
                    "relationships": r["relationshipCount"],
                    "created": (
                        r["creationTime"].isoformat() if r["creationTime"] else None
                    ),
                }
                for r in result
            ]

    # =========================================================================
    # Centrality Algorithms - Competitive Intelligence
    # =========================================================================

    def run_pagerank(
        self, graph_name: str = "competition_graph", limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Run PageRank on competition graph to find market leaders.

        High PageRank = Many competitors view this company as important.
        Interpretation: Market leaders, companies central to the industry.
        """
        # Ensure graph exists
        if not self._graph_exists(graph_name):
            self.create_competition_graph()

        query = """
        CALL gds.pageRank.stream($graph_name, {
            maxIterations: 20,
            dampingFactor: 0.85
        })
        YIELD nodeId, score
        WITH gds.util.asNode(nodeId) AS org, score
        WHERE org.tracked = true
        RETURN org.name AS company,
               org.ticker AS ticker,
               round(score * 1000) / 1000 AS pagerank_score
        ORDER BY score DESC
        LIMIT $limit
        """

        with self.driver.session() as session:
            result = session.run(query, {"graph_name": graph_name, "limit": limit})
            return [
                {
                    "company": r["company"],
                    "ticker": r["ticker"],
                    "pagerank_score": r["pagerank_score"],
                    "interpretation": (
                        "Market leader"
                        if r["pagerank_score"] > 0.1
                        else "Notable player"
                    ),
                }
                for r in result
            ]

    def run_betweenness_centrality(
        self, graph_name: str = "competition_graph", limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Run Betweenness Centrality to find strategic positions.

        High Betweenness = Company bridges different market segments.
        Interpretation: Acquisition targets, potential consolidation points.
        """
        if not self._graph_exists(graph_name):
            self.create_competition_graph()

        query = """
        CALL gds.betweenness.stream($graph_name)
        YIELD nodeId, score
        WITH gds.util.asNode(nodeId) AS org, score
        WHERE org.tracked = true
        RETURN org.name AS company,
               org.ticker AS ticker,
               round(score) AS betweenness_score
        ORDER BY score DESC
        LIMIT $limit
        """

        with self.driver.session() as session:
            result = session.run(query, {"graph_name": graph_name, "limit": limit})
            return [
                {
                    "company": r["company"],
                    "ticker": r["ticker"],
                    "betweenness_score": r["betweenness_score"],
                    "interpretation": (
                        "Strategic bridge"
                        if r["betweenness_score"] > 100
                        else "Standard position"
                    ),
                }
                for r in result
            ]

    def run_degree_centrality(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Calculate degree centrality directly (number of competitors).

        High Degree = Company competes with many others.
        Interpretation: Broad market player, diverse competition landscape.
        """
        query = """
        MATCH (o:Organization {tracked: true})-[r:COMPETES_WITH]-()
        WITH o, count(r) AS degree
        RETURN o.name AS company,
               o.ticker AS ticker,
               degree AS competitor_count
        ORDER BY degree DESC
        LIMIT $limit
        """

        with self.driver.session() as session:
            result = session.run(query, {"limit": limit})
            return [
                {
                    "company": r["company"],
                    "ticker": r["ticker"],
                    "competitor_count": r["competitor_count"],
                }
                for r in result
            ]

    # =========================================================================
    # Community Detection - Market Segmentation
    # =========================================================================

    def _get_segment_concepts(self, tickers: List[str]) -> List[str]:
        """
        Find distinctive concepts for a segment using TF-IDF style scoring.

        Rewards concepts that are popular within the cluster but rare globally.
        This automatically detects trends and filters out generic noise.
        """
        if not tickers or len(tickers) < 2:
            return []

        # TF-IDF style query:
        # 1. Calculate Local Frequency (in this cluster)
        # 2. Calculate Global Frequency (in the whole graph)
        # 3. Score = Local_Freq^2 * log(Total_Orgs / Global_Freq)
        query = """
        MATCH (o:Organization)
        WITH count(o) as total_orgs

        MATCH (o:Organization)-[:HAS_FILING]->(:Document)-[:DISCUSSES]->(c:Concept)
        WHERE o.ticker IN $tickers
        WITH c, count(DISTINCT o) as local_count, total_orgs
        WHERE local_count >= $min_companies

        // Look up global count for these specific concepts
        MATCH (other:Organization)-[:HAS_FILING]->(:Document)-[:DISCUSSES]->(c)
        WITH c, local_count, count(DISTINCT other) as global_count, total_orgs

        // Calculate Relevance Score
        // Square local_count to prioritize "sharedness" within the group
        WITH c,
             local_count,
             global_count,
             (toFloat(local_count) * toFloat(local_count) * log(toFloat(total_orgs) / toFloat(global_count))) as score

        // Filter out likely stop words (very high global count)
        WHERE global_count < (total_orgs * 0.8)

        RETURN c.name as concept, round(score * 100) / 100 as relevance_score
        ORDER BY score DESC
        LIMIT 5
        """

        min_companies = max(2, len(tickers) // 2)

        try:
            with self.driver.session() as session:
                result = session.run(
                    query, {"tickers": tickers, "min_companies": min_companies}
                )
                return [r["concept"] for r in result]
        except Exception as e:
            logger.warning(f"Error getting segment concepts: {e}")
            return []

    def run_louvain_communities(
        self, graph_name: str = "competition_graph"
    ) -> Dict[str, Any]:
        """
        Run Louvain community detection to find market segments.

        Groups companies that compete more closely with each other.
        Returns segments with distinctive concepts derived via TF-IDF scoring.
        """
        if not self._graph_exists(graph_name):
            self.create_competition_graph()

        query = """
        CALL gds.louvain.stream($graph_name)
        YIELD nodeId, communityId
        WITH gds.util.asNode(nodeId) AS org, communityId
        WHERE org.tracked = true
        WITH communityId, collect({
            company: org.name,
            ticker: org.ticker
        }) AS members
        RETURN communityId AS segment_id,
               size(members) AS company_count,
               members
        ORDER BY company_count DESC
        """

        with self.driver.session() as session:
            result = session.run(query, {"graph_name": graph_name})
            segments = []
            for r in result:
                companies = r["members"][:10]  # Limit to first 10 for display
                tickers = [c["ticker"] for c in companies if c.get("ticker")]

                # Get distinctive concepts for multi-company segments
                distinctive_concepts = []
                if len(companies) >= 2:
                    distinctive_concepts = self._get_segment_concepts(tickers)

                segments.append(
                    {
                        "segment_id": r["segment_id"],
                        "company_count": r["company_count"],
                        "companies": companies,
                        "distinctive_concepts": distinctive_concepts,
                    }
                )

            return {
                "total_segments": len(segments),
                "segments": segments[:10],  # Top 10 segments
            }

    def run_wcc(self, graph_name: str = "competition_graph") -> Dict[str, Any]:
        """
        Run Weakly Connected Components to find isolated groups.

        Finds disconnected competitive clusters.
        Interpretation: Separate market niches with no competitive overlap.
        """
        if not self._graph_exists(graph_name):
            self.create_competition_graph()

        query = """
        CALL gds.wcc.stream($graph_name)
        YIELD nodeId, componentId
        WITH gds.util.asNode(nodeId) AS org, componentId
        WHERE org.tracked = true
        WITH componentId, collect(org.name) AS companies
        RETURN componentId,
               size(companies) AS size,
               companies
        ORDER BY size DESC
        """

        with self.driver.session() as session:
            result = session.run(query, {"graph_name": graph_name})
            components = [
                {
                    "component_id": r["componentId"],
                    "size": r["size"],
                    "companies": r["companies"][:10],
                }
                for r in result
            ]
            return {"total_components": len(components), "components": components}

    # =========================================================================
    # Similarity Analysis - Finding Similar Companies
    # =========================================================================

    def run_node_similarity(
        self, graph_name: str = "patent_similarity_graph", top_k: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Run Node Similarity based on patent portfolios.

        Finds companies with similar IP strategies.
        Interpretation: Potential partners, acquisition synergies, or emerging competitors.
        """
        if not self._graph_exists(graph_name):
            self.create_patent_similarity_graph()

        query = """
        CALL gds.nodeSimilarity.stream($graph_name, {
            topK: $top_k,
            similarityCutoff: 0.1
        })
        YIELD node1, node2, similarity
        WITH gds.util.asNode(node1) AS org1, gds.util.asNode(node2) AS org2, similarity
        WHERE org1.tracked = true AND org2.tracked = true
        RETURN org1.name AS company1,
               org1.ticker AS ticker1,
               org2.name AS company2,
               org2.ticker AS ticker2,
               round(similarity * 100) / 100 AS similarity_score
        ORDER BY similarity DESC
        LIMIT 20
        """

        with self.driver.session() as session:
            result = session.run(query, {"graph_name": graph_name, "top_k": top_k})
            return [
                {
                    "company1": r["company1"],
                    "ticker1": r["ticker1"],
                    "company2": r["company2"],
                    "ticker2": r["ticker2"],
                    "similarity_score": r["similarity_score"],
                    "interpretation": (
                        "High IP overlap"
                        if r["similarity_score"] > 0.5
                        else "Some IP overlap"
                    ),
                }
                for r in result
            ]

    def find_similar_to_company(
        self, ticker: str, top_k: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Find companies most similar to a specific company based on multiple factors.

        Combines: Competition graph, patent portfolio, and concept similarity.
        """
        # Direct competitor overlap + shared concepts
        query = """
        MATCH (target:Organization {ticker: $ticker})

        // Find companies with shared competitors
        OPTIONAL MATCH (target)-[:COMPETES_WITH]-(shared:Organization)-[:COMPETES_WITH]-(similar:Organization)
        WHERE similar <> target AND similar.tracked = true
        WITH target, similar, count(DISTINCT shared) AS shared_competitors

        // Find companies discussing similar concepts
        OPTIONAL MATCH (target)-[:HAS_FILING]->(:Document)-[:DISCUSSES]->(c:Concept)<-[:DISCUSSES]-(:Document)<-[:HAS_FILING]-(similar)
        WITH similar, shared_competitors, count(DISTINCT c) AS shared_concepts

        WHERE shared_competitors > 0 OR shared_concepts > 0

        RETURN similar.name AS company,
               similar.ticker AS ticker,
               shared_competitors,
               shared_concepts,
               (shared_competitors * 2 + shared_concepts) AS similarity_score
        ORDER BY similarity_score DESC
        LIMIT $top_k
        """

        with self.driver.session() as session:
            result = session.run(query, {"ticker": ticker.upper(), "top_k": top_k})
            return [
                {
                    "company": r["company"],
                    "ticker": r["ticker"],
                    "shared_competitors": r["shared_competitors"],
                    "shared_concepts": r["shared_concepts"],
                    "similarity_score": r["similarity_score"],
                }
                for r in result
            ]

    # =========================================================================
    # Risk Analysis
    # =========================================================================

    def analyze_vulnerability_spread(self) -> Dict[str, Any]:
        """
        Analyze potential vulnerability spread patterns.

        Uses graph structure to identify companies that might be affected
        by supply chain or technology vulnerabilities.
        """
        query = """
        MATCH (o:Organization {tracked: true})-[:HAS_VULNERABILITY]->(v:Vulnerability)
        WITH o, count(v) AS vuln_count, collect(v.cve_id) AS cve_ids

        // Find connected companies through competition/partnerships
        OPTIONAL MATCH (o)-[:COMPETES_WITH|PARTNERS_WITH]-(connected:Organization {tracked: true})

        RETURN o.name AS company,
               o.ticker AS ticker,
               vuln_count AS vulnerability_count,
               cve_ids[0..5] AS sample_cves,
               count(connected) AS connected_companies
        ORDER BY vuln_count DESC
        LIMIT 20
        """

        with self.driver.session() as session:
            result = session.run(query)
            companies = [
                {
                    "company": r["company"],
                    "ticker": r["ticker"],
                    "vulnerability_count": r["vulnerability_count"],
                    "sample_cves": r["sample_cves"],
                    "connected_companies": r["connected_companies"],
                }
                for r in result
            ]

            return {
                "companies_with_vulnerabilities": len(companies),
                "companies": companies,
            }

    # =========================================================================
    # Executive Intelligence
    # =========================================================================

    def analyze_executive_network(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Analyze executive network and key personnel.

        Finds executives mentioned across multiple filings.
        """
        query = """
        MATCH (p:Person)-[:INVOLVED_IN]->(e:ExecutiveEvent)<-[:HAS_EXECUTIVE_EVENT]-(o:Organization {tracked: true})
        WITH p, collect(DISTINCT o.name) AS companies, count(DISTINCT e) AS events
        WHERE size(companies) >= 1
        RETURN p.name AS executive,
               companies,
               events AS executive_events
        ORDER BY events DESC
        LIMIT $limit
        """

        with self.driver.session() as session:
            result = session.run(query, {"limit": limit})
            return [
                {
                    "executive": r["executive"],
                    "companies": r["companies"],
                    "executive_events": r["executive_events"],
                }
                for r in result
            ]

    # =========================================================================
    # Helpers
    # =========================================================================

    def _graph_exists(self, graph_name: str) -> bool:
        """Check if a graph projection exists."""
        query = "CALL gds.graph.exists($graph_name) YIELD exists RETURN exists"
        with self.driver.session() as session:
            result = session.run(query, {"graph_name": graph_name})
            record = result.single()
            return record["exists"] if record else False

    def get_analytics_summary(self) -> Dict[str, Any]:
        """
        Get a summary of available GDS analytics capabilities and current state.
        """
        return {
            "gds_version": self.get_gds_version(),
            "graphs": self.list_graphs(),
            "available_analytics": {
                "centrality": ["pagerank", "betweenness", "degree"],
                "community": ["louvain", "wcc"],
                "similarity": ["node_similarity", "find_similar"],
                "risk": ["vulnerability_spread"],
                "executive": ["executive_network"],
            },
        }


# =============================================================================
# Module-level singleton
# =============================================================================

_gds_service: Optional[GDSService] = None


def get_gds_service() -> GDSService:
    """Get or create the singleton GDS service instance."""
    global _gds_service
    if _gds_service is None:
        _gds_service = GDSService()
    return _gds_service
