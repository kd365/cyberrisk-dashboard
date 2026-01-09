# =============================================================================
# Graph Builder Service - Knowledge Graph Construction from Documents
# =============================================================================
#
# This service builds the Neo4j knowledge graph from SEC filings and
# earnings transcripts using AWS Comprehend for entity extraction.
#
# Pipeline:
#   S3 Documents -> Comprehend Analysis -> Entity Resolution -> Neo4j Graph
#
# Schema v2:
#   - Organization (tracked companies + mentioned orgs)
#   - Location (geographic mentions)
#   - Event (with date attribute)
#   - Person, Concept, Document
#
# =============================================================================

import os
import re
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)


class GraphBuilderService:
    """
    Builds knowledge graph from SEC filings and transcripts.

    Uses AWS Comprehend for NLP extraction and creates nodes/relationships
    in Neo4j for the GraphRAG system.
    """

    # Concept categories for classification
    CONCEPT_CATEGORIES = {
        "RISK": ["risk", "threat", "vulnerability", "breach", "attack", "exposure"],
        "OPPORTUNITY": [
            "growth",
            "opportunity",
            "expansion",
            "innovation",
            "potential",
        ],
        "TECHNOLOGY": [
            "ai",
            "cloud",
            "platform",
            "saas",
            "endpoint",
            "zero trust",
            "xdr",
        ],
        "MARKET": ["market", "competition", "industry", "sector", "demand"],
        "FINANCIAL": ["revenue", "margin", "arr", "earnings", "profit", "cost"],
    }

    def __init__(self):
        """Initialize the graph builder service."""
        self.region = os.environ.get("AWS_REGION", "us-west-2")

        # Initialize AWS clients
        config = Config(
            region_name=self.region, retries={"max_attempts": 3, "mode": "adaptive"}
        )
        self.comprehend = boto3.client("comprehend", config=config)
        self.s3 = boto3.client("s3", config=config)

        # Service dependencies (lazy loaded)
        self._neo4j_service = None
        self._s3_service = None
        self._db_service = None

    @property
    def neo4j(self):
        """Lazy load Neo4j service."""
        if self._neo4j_service is None:
            from services.neo4j_service import get_neo4j_service

            self._neo4j_service = get_neo4j_service()
        return self._neo4j_service

    @property
    def s3_service(self):
        """Lazy load S3 service."""
        if self._s3_service is None:
            from services.s3_service import S3ArtifactService

            self._s3_service = S3ArtifactService()
        return self._s3_service

    @property
    def db_service(self):
        """Lazy load database service."""
        if self._db_service is None:
            from services.database_service import db_service

            self._db_service = db_service
        return self._db_service

    # =========================================================================
    # Main Build Pipeline
    # =========================================================================

    def build_graph_for_ticker(
        self,
        ticker: str,
        include_entities: bool = True,
        include_concepts: bool = True,
        include_key_phrases: bool = True,
    ) -> Dict:
        """
        Build knowledge graph for a single company.

        Args:
            ticker: Company ticker symbol
            include_entities: Extract and add entities
            include_concepts: Extract and add concepts
            include_key_phrases: Extract and add key phrases

        Returns:
            Summary of graph building results
        """
        ticker = ticker.upper()
        logger.info(f"Building knowledge graph for {ticker}")

        results = {
            "ticker": ticker,
            "documents_processed": 0,
            "entities_created": 0,
            "concepts_created": 0,
            "relationships_created": 0,
            "errors": [],
        }

        try:
            # 1. Ensure company node exists
            self._ensure_company_node(ticker)

            # 2. Get all artifacts for this ticker
            artifacts = self.db_service.get_artifacts_by_ticker(ticker)

            if not artifacts:
                logger.warning(f"No artifacts found for {ticker}")
                results["errors"].append("No documents found")
                return results

            # 3. Process each document
            for artifact in artifacts:
                try:
                    doc_results = self._process_document(
                        artifact,
                        include_entities=include_entities,
                        include_concepts=include_concepts,
                        include_key_phrases=include_key_phrases,
                    )

                    results["documents_processed"] += 1
                    results["entities_created"] += doc_results.get("entities", 0)
                    results["concepts_created"] += doc_results.get("concepts", 0)
                    results["relationships_created"] += doc_results.get(
                        "relationships", 0
                    )

                except Exception as e:
                    logger.error(
                        f"Error processing document {artifact.get('s3_key')}: {e}"
                    )
                    results["errors"].append(str(e))

            logger.info(f"Graph build complete for {ticker}: {results}")
            return results

        except Exception as e:
            logger.error(f"Error building graph for {ticker}: {e}")
            results["errors"].append(str(e))
            return results

    def build_graph_all_tickers(self) -> Dict:
        """
        Build knowledge graph for all tracked companies.

        Returns:
            Summary of results per ticker
        """
        companies = self.db_service.get_all_companies()
        all_results = {}

        for company in companies:
            ticker = company.get("ticker", "").upper()
            if ticker:
                all_results[ticker] = self.build_graph_for_ticker(ticker)

        return all_results

    # =========================================================================
    # Document Processing
    # =========================================================================

    def _process_document(
        self,
        artifact: Dict,
        include_entities: bool = True,
        include_concepts: bool = True,
        include_key_phrases: bool = True,
    ) -> Dict:
        """
        Process a single document and add to graph.

        Args:
            artifact: Artifact metadata from database
            include_entities: Extract entities
            include_concepts: Extract concepts
            include_key_phrases: Extract key phrases

        Returns:
            Processing results
        """
        s3_key = artifact.get("s3_key")
        ticker = artifact.get("ticker", "").upper()
        doc_type = artifact.get("artifact_type", "unknown")
        published_date = artifact.get("published_date")

        if not s3_key:
            return {"error": "No S3 key"}

        logger.info(f"Processing document: {s3_key}")

        results = {"entities": 0, "concepts": 0, "relationships": 0}

        # 1. Get document text
        text = self._get_document_text(s3_key)
        if not text or len(text) < 100:
            logger.warning(f"Document too short or empty: {s3_key}")
            return results

        # 2. Create document node
        doc_id = self._create_document_id(s3_key)
        self._create_document_node(doc_id, ticker, doc_type, s3_key, published_date)

        # 3. Run Comprehend analysis (chunks up to 10 sections of ~5KB each)
        analysis = self._analyze_text(text, max_chunks=10)

        # 4. Process entities
        if include_entities and analysis.get("entities"):
            entity_count = self._process_entities(doc_id, ticker, analysis["entities"])
            results["entities"] = entity_count

        # 5. Process key phrases as concepts
        if include_concepts and analysis.get("key_phrases"):
            concept_count = self._process_key_phrases(
                doc_id, ticker, analysis["key_phrases"]
            )
            results["concepts"] = concept_count

        # 6. Process sentiment
        if analysis.get("sentiment"):
            self._update_document_sentiment(doc_id, analysis["sentiment"])

        results["relationships"] = results["entities"] + results["concepts"]

        return results

    def _get_document_text(self, s3_key: str) -> Optional[str]:
        """Get document text from S3."""
        try:
            # Get bucket name from environment
            bucket = os.environ.get("ARTIFACTS_BUCKET", "cyber-risk-artifacts")

            response = self.s3.get_object(Bucket=bucket, Key=s3_key)
            content = response["Body"].read()

            # Try to decode as text
            try:
                return content.decode("utf-8")
            except UnicodeDecodeError:
                # Might be PDF - skip binary files
                logger.warning(f"Cannot read binary file: {s3_key}")
                return None

        except Exception as e:
            logger.error(f"Error reading document {s3_key}: {e}")
            return None

    def _chunk_text(self, text: str, max_bytes: int = 4900) -> List[str]:
        """
        Split text into chunks that fit within Comprehend's byte limit.

        AWS Comprehend has a 5000 byte limit. We use 4900 to have margin.
        Attempts to split on sentence boundaries when possible.
        """
        chunks = []
        current_chunk = ""

        # Split on sentences (simple heuristic)
        sentences = re.split(r"(?<=[.!?])\s+", text)

        for sentence in sentences:
            # Check if adding this sentence would exceed limit
            test_chunk = current_chunk + " " + sentence if current_chunk else sentence
            if len(test_chunk.encode("utf-8")) <= max_bytes:
                current_chunk = test_chunk
            else:
                # Save current chunk if it has content
                if current_chunk:
                    chunks.append(current_chunk)

                # If single sentence exceeds limit, truncate it
                if len(sentence.encode("utf-8")) > max_bytes:
                    encoded = sentence.encode("utf-8")[:max_bytes]
                    sentence = encoded.decode("utf-8", errors="ignore")

                current_chunk = sentence

        # Don't forget the last chunk
        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def _analyze_text(self, text: str, max_chunks: int = 10) -> Dict:
        """
        Run AWS Comprehend analysis on text, chunking if necessary.

        Args:
            text: Full document text
            max_chunks: Maximum number of chunks to analyze (cost control)

        Returns:
            Merged analysis results from all chunks
        """
        results = {"entities": [], "key_phrases": [], "sentiment": None}

        # Split into chunks
        chunks = self._chunk_text(text)

        # Limit chunks to control costs
        chunks = chunks[:max_chunks]

        # Track sentiment scores for averaging
        sentiment_scores = {"Positive": [], "Negative": [], "Neutral": [], "Mixed": []}

        for i, chunk in enumerate(chunks):
            try:
                # Detect entities
                entity_response = self.comprehend.detect_entities(
                    Text=chunk, LanguageCode="en"
                )
                results["entities"].extend(entity_response.get("Entities", []))

                # Detect key phrases
                phrase_response = self.comprehend.detect_key_phrases(
                    Text=chunk, LanguageCode="en"
                )
                results["key_phrases"].extend(phrase_response.get("KeyPhrases", []))

                # Detect sentiment (average across chunks)
                sentiment_response = self.comprehend.detect_sentiment(
                    Text=chunk, LanguageCode="en"
                )
                scores = sentiment_response.get("SentimentScore", {})
                for key in sentiment_scores:
                    if key in scores:
                        sentiment_scores[key].append(scores[key])

            except Exception as e:
                logger.error(f"Comprehend analysis error on chunk {i}: {e}")

        # Average sentiment scores
        if any(sentiment_scores["Positive"]):
            avg_scores = {
                key: sum(vals) / len(vals) if vals else 0
                for key, vals in sentiment_scores.items()
            }
            # Determine overall sentiment from highest average score
            overall = max(avg_scores, key=avg_scores.get)
            results["sentiment"] = {"sentiment": overall.upper(), "scores": avg_scores}

        return results

    # =========================================================================
    # Neo4j Node Creation
    # =========================================================================

    def _ensure_company_node(self, ticker: str):
        """Ensure tracked organization node exists in Neo4j with taxonomy."""
        from data.taxonomy import get_company_taxonomy

        company = self.db_service.get_company(ticker)
        taxonomy = get_company_taxonomy(ticker)

        if company:
            # Use taxonomy data if available, otherwise fall back to database
            if taxonomy:
                self.neo4j.create_organization(
                    name=taxonomy.get("name", company.get("company_name", ticker)),
                    ticker=ticker,
                    tracked=True,
                    gics_sector=taxonomy.get("gics_sector"),
                    gics_industry=taxonomy.get("gics_industry"),
                    cyber_sector=taxonomy.get("cyber_sector"),
                    cyber_focus=taxonomy.get("cyber_focus", []),
                    description=taxonomy.get("description"),
                )
            else:
                self.neo4j.create_organization(
                    name=company.get("company_name", ticker),
                    ticker=ticker,
                    tracked=True,
                    cyber_sector="cybersecurity",
                )

    def _create_document_id(self, s3_key: str) -> str:
        """Generate document ID from S3 key."""
        # Use last part of path as ID
        return s3_key.split("/")[-1].replace(".txt", "").replace(".pdf", "")

    def _create_document_node(
        self, doc_id: str, ticker: str, doc_type: str, s3_key: str, published_date: Any
    ):
        """Create document node in Neo4j."""
        date_str = None
        if published_date:
            if hasattr(published_date, "isoformat"):
                date_str = published_date.isoformat()
            else:
                date_str = str(published_date)

        self.neo4j.create_document(
            doc_id=doc_id,
            ticker=ticker,
            doc_type=doc_type,
            s3_key=s3_key,
            date=date_str,  # Changed from published_date to date
        )

    def _process_entities(self, doc_id: str, ticker: str, entities: List[Dict]) -> int:
        """
        Process Comprehend entities and add to graph.

        Maps Comprehend entity types to our schema:
        - ORGANIZATION -> Organization node
        - LOCATION -> Location node
        - EVENT -> Event node
        - PERSON -> Person node
        - DATE, QUANTITY -> Skipped (captured as attributes elsewhere)

        Args:
            doc_id: Document ID
            ticker: Company ticker
            entities: Comprehend entity list

        Returns:
            Number of entities created
        """
        count = 0
        seen_entities = set()

        for entity in entities:
            entity_text = entity.get("Text", "").strip()
            entity_type = entity.get("Type", "OTHER")
            score = entity.get("Score", 0)

            # Skip low confidence or very short entities
            if score < 0.7 or len(entity_text) < 2:
                continue

            # Normalize entity name
            normalized = entity_text.lower().replace(" ", "_")

            # Skip duplicates in this document
            if normalized in seen_entities:
                continue
            seen_entities.add(normalized)

            # Skip DATE and QUANTITY - these become attributes, not nodes
            if entity_type in ["DATE", "QUANTITY"]:
                continue

            # Map Comprehend types to our schema
            if entity_type == "ORGANIZATION":
                # Create Organization node (mentioned, not tracked)
                self.neo4j.create_organization(name=entity_text)
                self.neo4j.link_document_organization(
                    doc_id=doc_id, org_normalized=normalized, count=1
                )
                count += 1

            elif entity_type == "LOCATION":
                # Create Location node
                self.neo4j.create_location(name=entity_text, normalized_name=normalized)
                self.neo4j.link_document_location(
                    doc_id=doc_id, loc_normalized=normalized, count=1
                )
                count += 1

            elif entity_type == "EVENT":
                # Create Event node
                self.neo4j.create_event(name=entity_text, normalized_name=normalized)
                # Link via MENTIONS
                query = """
                    MATCH (d:Document {id: $doc_id})
                    MATCH (e:Event {normalized_name: $event})
                    MERGE (d)-[r:MENTIONS]->(e)
                    SET r.count = 1
                """
                self.neo4j.execute_write(query, {"doc_id": doc_id, "event": normalized})
                count += 1

            elif entity_type == "PERSON":
                # Create Person node
                self.neo4j.create_person(name=entity_text, normalized_name=normalized)
                # Link via MENTIONS
                query = """
                    MATCH (d:Document {id: $doc_id})
                    MATCH (p:Person {normalized_name: $person})
                    MERGE (d)-[r:MENTIONS]->(p)
                    SET r.count = 1
                """
                self.neo4j.execute_write(
                    query, {"doc_id": doc_id, "person": normalized}
                )
                count += 1

            # Skip OTHER, COMMERCIAL_ITEM, TITLE, etc.

        return count

    def _process_key_phrases(
        self, doc_id: str, ticker: str, key_phrases: List[Dict]
    ) -> int:
        """
        Process key phrases as concepts and add to graph.

        Args:
            doc_id: Document ID
            ticker: Company ticker
            key_phrases: Comprehend key phrases

        Returns:
            Number of concepts created
        """
        count = 0
        seen_concepts = set()

        for phrase in key_phrases:
            phrase_text = phrase.get("Text", "").strip()
            score = phrase.get("Score", 0)

            # Skip low confidence or very short phrases
            if score < 0.8 or len(phrase_text) < 3:
                continue

            # Normalize
            normalized = phrase_text.lower().replace(" ", "_")

            # Skip duplicates
            if normalized in seen_concepts:
                continue
            seen_concepts.add(normalized)

            # Categorize concept
            category = self._categorize_concept(phrase_text)

            # Create concept node
            query = """
                MERGE (c:Concept {normalized_name: $normalized})
                ON CREATE SET c.name = $name,
                              c.category = $category,
                              c.mention_count = 1
                ON MATCH SET c.mention_count = c.mention_count + 1
            """
            self.neo4j.execute_write(
                query,
                {"normalized": normalized, "name": phrase_text, "category": category},
            )

            # Link document to concept
            query = """
                MATCH (d:Document {id: $doc_id})
                MATCH (c:Concept {normalized_name: $concept})
                MERGE (d)-[r:DISCUSSES]->(c)
                ON CREATE SET r.count = 1
                ON MATCH SET r.count = r.count + 1
            """
            self.neo4j.execute_write(query, {"doc_id": doc_id, "concept": normalized})

            count += 1

        return count

    def _categorize_concept(self, phrase: str) -> str:
        """Categorize a concept based on keywords."""
        phrase_lower = phrase.lower()

        for category, keywords in self.CONCEPT_CATEGORIES.items():
            if any(kw in phrase_lower for kw in keywords):
                return category

        return "GENERAL"

    def _update_document_sentiment(self, doc_id: str, sentiment: Dict):
        """Update document node with sentiment data."""
        query = """
            MATCH (d:Document {id: $doc_id})
            SET d.overall_sentiment = $sentiment,
                d.sentiment_positive = $positive,
                d.sentiment_negative = $negative,
                d.sentiment_neutral = $neutral,
                d.sentiment_mixed = $mixed
        """
        scores = sentiment.get("scores", {})
        self.neo4j.execute_write(
            query,
            {
                "doc_id": doc_id,
                "sentiment": sentiment.get("sentiment", "NEUTRAL"),
                "positive": scores.get("Positive", 0),
                "negative": scores.get("Negative", 0),
                "neutral": scores.get("Neutral", 0),
                "mixed": scores.get("Mixed", 0),
            },
        )

    # =========================================================================
    # Relationship Inference
    # =========================================================================

    def infer_entity_relationships(self, ticker: str = None):
        """
        Infer relationships between organizations based on co-occurrence.

        Creates RELATED_TO relationships between organizations that appear
        together in documents.
        """
        logger.info("Inferring organization relationships from co-occurrence...")

        query = """
            // Find organizations that co-occur in same documents
            MATCH (d:Document)-[:MENTIONS]->(o1:Organization)
            MATCH (d)-[:MENTIONS]->(o2:Organization)
            WHERE o1 <> o2
              AND ($ticker IS NULL OR d.ticker = $ticker)
            WITH o1, o2, count(d) as cooccurrences
            WHERE cooccurrences >= 2
            MERGE (o1)-[r:RELATED_TO]-(o2)
            SET r.strength = cooccurrences,
                r.relationship_type = 'co_occurrence'
            RETURN count(r) as relationships_created
        """

        result = self.neo4j.execute_read(query, {"ticker": ticker})
        count = result[0]["relationships_created"] if result else 0

        logger.info(f"Created {count} co-occurrence relationships")
        return count


# =============================================================================
# Singleton Instance
# =============================================================================

_graph_builder_service = None


def get_graph_builder_service() -> GraphBuilderService:
    """Get or create graph builder service singleton."""
    global _graph_builder_service
    if _graph_builder_service is None:
        _graph_builder_service = GraphBuilderService()
    return _graph_builder_service
