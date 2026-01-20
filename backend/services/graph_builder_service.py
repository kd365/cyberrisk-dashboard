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

    # Concept categories for classification - enhanced for cybersecurity domain
    CONCEPT_CATEGORIES = {
        "RISK": [
            "risk", "threat", "vulnerability", "breach", "attack", "exposure",
            "ransomware", "malware", "phishing", "cyber attack", "data loss",
            "security incident", "intrusion", "exploit", "compromise", "hacker",
            "cyberattack", "apt", "threat actor", "nation-state", "insider threat",
        ],
        "TECHNOLOGY": [
            "ai", "artificial intelligence", "machine learning", "cloud", "platform",
            "saas", "endpoint", "zero trust", "xdr", "edr", "siem", "soar",
            "automation", "orchestration", "devsecops", "container", "kubernetes",
            "api security", "identity", "iam", "mfa", "sso", "encryption",
            "firewall", "network security", "cloud security", "data protection",
        ],
        "PRODUCT": [
            "product", "solution", "module", "service", "offering", "suite",
            "falcon", "cortex", "chronicle", "sentinel", "defender", "crowdstrike",
            "prisma", "cloudflare", "zscaler", "okta", "cyberark", "sailpoint",
        ],
        "MARKET": [
            "market", "competition", "industry", "sector", "demand", "tam",
            "market share", "addressable market", "enterprise", "smb", "mid-market",
            "customer", "partner", "channel", "go-to-market", "land and expand",
        ],
        "COMPETITOR": [
            "competitor", "competition", "market leader", "rival", "alternative",
            "competitive", "differentiation", "positioning",
        ],
        "OPPORTUNITY": [
            "growth", "opportunity", "expansion", "innovation", "potential",
            "partnership", "acquisition", "merger", "new product", "launch",
            "international", "geographic expansion", "upsell", "cross-sell",
        ],
        "FINANCIAL": [
            "revenue", "margin", "arr", "earnings", "profit", "cost",
            "subscription", "recurring", "billings", "backlog", "guidance",
            "gross margin", "operating margin", "free cash flow", "ebitda",
        ],
    }

    # Entity blocklist - filter out common noise from extraction
    ENTITY_BLOCKLIST = {
        # XBRL/PDF artifacts
        "xbrl", "xmlns", "fasb", "dei", "gaap", "us-gaap", "iso4217",
        "devicergb", "flatedecode", "endobj", "xref", "srt",
        # Generic terms that aren't useful entities
        "the company", "our company", "the period", "fiscal year",
        "quarter", "the registrant", "the board", "the securities",
        "the exchange", "the commission", "annual report", "form 10-k",
        # Website/navigation artifacts
        "motley fool", "fool.com", "arrow-thin-down", "click here",
        "read more", "sign up", "log in", "subscribe",
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
        self._ocr_service = None

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

    @property
    def ocr_service(self):
        """Lazy load OCR service for enhanced PDF extraction."""
        if self._ocr_service is None:
            from services.ocr_service import get_ocr_service

            self._ocr_service = get_ocr_service()
        return self._ocr_service

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
        # First, ensure all tracked company nodes exist (source of truth)
        logger.info("Ensuring all tracked company nodes exist...")
        self.ensure_all_tracked_companies()

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
        """
        Get document text from S3 using enhanced OCR extraction.

        Uses the OCR service for PDF files to get clean, high-quality text.
        Falls back to direct text read for .txt files.
        """
        try:
            # Check if it's a PDF - use OCR service
            if s3_key.lower().endswith('.pdf'):
                logger.info(f"Using OCR extraction for PDF: {s3_key}")
                text = self.ocr_service.extract_text_from_s3(
                    s3_key=s3_key,
                    use_ocr=True,
                    use_cache=True
                )
                if text:
                    # Validate quality
                    is_ok, reason = self.ocr_service.is_text_quality_acceptable(text)
                    if not is_ok:
                        logger.warning(f"Low quality extraction for {s3_key}: {reason}")
                return text

            # For text files, read directly
            bucket = os.environ.get("ARTIFACTS_BUCKET", "cyber-risk-artifacts")
            response = self.s3.get_object(Bucket=bucket, Key=s3_key)
            content = response["Body"].read()

            # Try to decode as text
            try:
                return content.decode("utf-8")
            except UnicodeDecodeError:
                # Binary file that's not PDF - try OCR as fallback
                logger.warning(f"Binary file detected, attempting OCR: {s3_key}")
                return self.ocr_service.extract_text_from_s3(s3_key)

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

    def ensure_all_tracked_companies(self) -> int:
        """
        Ensure all tracked companies from database exist in Neo4j.

        This should be called before processing documents to ensure
        canonical company nodes exist for entity resolution.

        Primary source is the RDS database (companies table with taxonomy columns).
        Falls back to hardcoded taxonomy for companies not yet in database.

        Returns:
            Number of companies created/updated
        """
        from data.taxonomy import TRACKED_COMPANIES

        count = 0

        # Primary source: Database companies with taxonomy
        companies = self.db_service.get_all_companies()
        db_tickers = set()

        for company in companies:
            ticker = company.get("ticker", "").upper()
            if not ticker:
                continue

            db_tickers.add(ticker)

            # Get taxonomy from database columns (new approach)
            cyber_sector = company.get("cyber_sector")
            cyber_focus = company.get("cyber_focus") or []
            gics_sector = company.get("gics_sector")
            gics_industry = company.get("gics_industry")

            # Fallback to hardcoded taxonomy if DB columns not populated
            if not cyber_sector and ticker in TRACKED_COMPANIES:
                taxonomy = TRACKED_COMPANIES[ticker]
                cyber_sector = taxonomy.get("cyber_sector")
                cyber_focus = taxonomy.get("cyber_focus", [])
                gics_sector = taxonomy.get("gics_sector")
                gics_industry = taxonomy.get("gics_industry")

            # Parse alternate_names (may be stored as JSON string or array)
            alternate_names = company.get("alternate_names") or []
            if isinstance(alternate_names, str):
                try:
                    import json
                    alternate_names = json.loads(alternate_names)
                except (json.JSONDecodeError, TypeError):
                    alternate_names = []

            self.neo4j.create_organization(
                name=company.get("company_name", ticker),
                ticker=ticker,
                tracked=True,
                gics_sector=gics_sector or "Information Technology",
                gics_industry=gics_industry or "Systems Software",
                cyber_sector=cyber_sector or "cybersecurity",
                cyber_focus=cyber_focus if isinstance(cyber_focus, list) else [],
                description=company.get("description"),
                exchange=company.get("exchange"),
                location=company.get("location"),
                domain=company.get("domain"),
                alternate_names=alternate_names if isinstance(alternate_names, list) else [],
            )
            count += 1
            logger.debug(f"Ensured tracked company node: {ticker}")

        # Fallback: Also ensure hardcoded taxonomy companies exist
        for ticker, taxonomy in TRACKED_COMPANIES.items():
            if ticker not in db_tickers:
                self.neo4j.create_organization(
                    name=taxonomy.get("name", ticker),
                    ticker=ticker,
                    tracked=True,
                    gics_sector=taxonomy.get("gics_sector"),
                    gics_industry=taxonomy.get("gics_industry"),
                    cyber_sector=taxonomy.get("cyber_sector"),
                    cyber_focus=taxonomy.get("cyber_focus", []),
                    description=taxonomy.get("description"),
                )
                count += 1
                logger.debug(f"Ensured tracked company node from taxonomy: {ticker}")

        logger.info(f"Ensured {count} tracked company nodes in Neo4j")
        return count

    def _ensure_company_node(self, ticker: str):
        """
        Ensure tracked organization node exists in Neo4j with taxonomy.

        Priority: Database taxonomy > Hardcoded taxonomy > Basic defaults
        """
        from data.taxonomy import get_company_taxonomy

        company = self.db_service.get_company(ticker)
        taxonomy = get_company_taxonomy(ticker)

        if company:
            # Primary: Use database company record with taxonomy columns
            cyber_sector = company.get("cyber_sector")
            cyber_focus = company.get("cyber_focus") or []
            gics_sector = company.get("gics_sector")
            gics_industry = company.get("gics_industry")

            # Fallback to hardcoded taxonomy if DB columns empty
            if not cyber_sector and taxonomy:
                cyber_sector = taxonomy.get("cyber_sector")
                cyber_focus = taxonomy.get("cyber_focus", [])
                gics_sector = taxonomy.get("gics_sector")
                gics_industry = taxonomy.get("gics_industry")

            # Parse alternate_names
            alternate_names = company.get("alternate_names") or []
            if isinstance(alternate_names, str):
                try:
                    import json
                    alternate_names = json.loads(alternate_names)
                except (json.JSONDecodeError, TypeError):
                    alternate_names = []

            self.neo4j.create_organization(
                name=company.get("company_name", ticker),
                ticker=ticker,
                tracked=True,
                gics_sector=gics_sector or "Information Technology",
                gics_industry=gics_industry or "Systems Software",
                cyber_sector=cyber_sector or "cybersecurity",
                cyber_focus=cyber_focus if isinstance(cyber_focus, list) else [],
                description=company.get("description"),
                exchange=company.get("exchange"),
                location=company.get("location"),
                domain=company.get("domain"),
                alternate_names=alternate_names if isinstance(alternate_names, list) else [],
            )
        elif taxonomy:
            # Fallback: Use hardcoded taxonomy (for companies not in DB)
            self.neo4j.create_organization(
                name=taxonomy.get("name", ticker),
                ticker=ticker,
                tracked=True,
                gics_sector=taxonomy.get("gics_sector"),
                gics_industry=taxonomy.get("gics_industry"),
                cyber_sector=taxonomy.get("cyber_sector"),
                cyber_focus=taxonomy.get("cyber_focus", []),
                description=taxonomy.get("description"),
            )
        else:
            # Last resort: Create minimal node
            self.neo4j.create_organization(
                name=ticker,
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

            # Skip low confidence or very short entities (raised threshold from 0.7)
            if score < 0.85 or len(entity_text) < 3:
                continue

            # Skip numeric-only entities
            if entity_text.replace(",", "").replace(".", "").replace("-", "").replace(" ", "").isdigit():
                continue

            # Skip entities with too few alphabetic characters
            alpha_chars = sum(1 for c in entity_text if c.isalpha())
            if alpha_chars < 2:
                continue

            # Normalize entity name
            normalized = self._normalize_entity_name(entity_text)

            # Skip duplicates in this document
            if normalized in seen_entities:
                continue

            # Skip blocklisted entities (noise filtering)
            if entity_text.lower() in self.ENTITY_BLOCKLIST or normalized in self.ENTITY_BLOCKLIST:
                continue

            seen_entities.add(normalized)

            # Skip DATE and QUANTITY - these become attributes, not nodes
            if entity_type in ["DATE", "QUANTITY"]:
                continue

            # Map Comprehend types to our schema
            if entity_type == "ORGANIZATION":
                # Check if this is a tracked company (resolve aliases)
                resolved = self._resolve_organization(entity_text)

                if resolved and resolved.get("is_tracked"):
                    # This is a tracked company - use canonical name/ticker
                    canonical_name = resolved.get("name")
                    canonical_ticker = resolved.get("ticker")
                    canonical_normalized = self._normalize_entity_name(canonical_name)

                    # Link to the existing tracked company node (don't create duplicate)
                    self.neo4j.link_document_organization(
                        doc_id=doc_id,
                        org_normalized=canonical_normalized,
                        count=1
                    )
                    logger.debug(f"Linked '{entity_text}' to tracked company {canonical_ticker}")
                else:
                    # Not a tracked company - create as mentioned organization
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

            # Skip low confidence or very short phrases (raised threshold from 0.8)
            if score < 0.9 or len(phrase_text) < 4:
                continue

            # Skip numeric-only phrases (dates, amounts, page numbers, etc.)
            if phrase_text.replace(",", "").replace(".", "").replace("-", "").replace(" ", "").isdigit():
                continue

            # Skip phrases that are mostly numbers (e.g., "2024", "$1.5 million")
            alpha_chars = sum(1 for c in phrase_text if c.isalpha())
            if alpha_chars < 3:
                continue

            # Skip blocklisted phrases
            if phrase_text.lower() in self.ENTITY_BLOCKLIST:
                continue

            # Normalize
            normalized = self._normalize_entity_name(phrase_text)

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

    def _resolve_organization(self, name: str) -> Optional[Dict]:
        """
        Resolve an organization name to its canonical tracked company info.

        Uses the taxonomy alias lookup to match extracted entity names
        to our tracked companies, ensuring proper deduplication.

        Args:
            name: Organization name as extracted from text

        Returns:
            dict with ticker, name, is_tracked, taxonomy if found, else None
        """
        from data.taxonomy import resolve_company_name

        return resolve_company_name(name)

    def _normalize_entity_name(self, name: str) -> str:
        """
        Improved entity name normalization for better deduplication.

        Handles common variations in company names and entity references.
        """
        # Lowercase and strip
        name = name.lower().strip()

        # Remove common corporate suffixes
        suffixes = [
            ", inc.", ", inc", " inc.", " inc",
            ", llc", " llc", ", l.l.c.", " l.l.c.",
            ", corp.", " corp.", ", corporation", " corporation",
            ", ltd.", " ltd.", ", limited", " limited",
            ", co.", " co.", ", company", " company",
            ", plc", " plc", ", n.v.", " n.v.",
        ]
        for suffix in suffixes:
            if name.endswith(suffix):
                name = name[:-len(suffix)]

        # Remove common prefixes
        prefixes = ["the ", "a ", "an "]
        for prefix in prefixes:
            if name.startswith(prefix):
                name = name[len(prefix):]

        # Replace special characters with underscore
        name = re.sub(r'[^a-z0-9]+', '_', name)

        # Remove leading/trailing underscores
        name = name.strip('_')

        # Collapse multiple underscores
        name = re.sub(r'_+', '_', name)

        return name

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
            // Threshold raised from 2 to 5 to reduce false relationships
            MATCH (d:Document)-[:MENTIONS]->(o1:Organization)
            MATCH (d)-[:MENTIONS]->(o2:Organization)
            WHERE o1 <> o2
              AND ($ticker IS NULL OR d.ticker = $ticker)
            WITH o1, o2, count(d) as cooccurrences
            WHERE cooccurrences >= 5
            MERGE (o1)-[r:RELATED_TO]-(o2)
            SET r.strength = cooccurrences,
                r.relationship_type = 'co_occurrence'
            RETURN count(r) as relationships_created
        """

        result = self.neo4j.execute_read(query, {"ticker": ticker})
        count = result[0]["relationships_created"] if result else 0

        logger.info(f"Created {count} co-occurrence relationships")
        return count

    def infer_concept_relationships(self, ticker: str = None) -> int:
        """
        Infer relationships between concepts based on co-occurrence in documents.

        Creates RELATED_TO relationships between concepts that appear together
        in the same documents, enabling queries like:
        - "What technologies are discussed alongside risks?"
        - "What market terms co-occur with competitor mentions?"

        Args:
            ticker: Optional ticker to limit to specific company's documents

        Returns:
            Number of concept relationships created
        """
        logger.info("Inferring concept relationships from co-occurrence...")

        query = """
            // Find concepts that co-occur in same documents
            MATCH (d:Document)-[:DISCUSSES]->(c1:Concept)
            MATCH (d)-[:DISCUSSES]->(c2:Concept)
            WHERE c1 <> c2
              AND id(c1) < id(c2)  // Avoid duplicate pairs
              AND ($ticker IS NULL OR d.ticker = $ticker)
            WITH c1, c2, count(DISTINCT d) as cooccurrences
            WHERE cooccurrences >= 3  // Minimum threshold
            MERGE (c1)-[r:RELATED_TO]-(c2)
            SET r.strength = cooccurrences,
                r.relationship_type = 'co_occurrence',
                r.updated_at = datetime()
            RETURN count(r) as relationships_created
        """

        result = self.neo4j.execute_read(query, {"ticker": ticker})
        count = result[0]["relationships_created"] if result else 0

        logger.info(f"Created {count} concept co-occurrence relationships")
        return count

    def create_company_concept_associations(self, ticker: str = None) -> int:
        """
        Create ASSOCIATED_WITH relationships between companies and concepts.

        Tracks which concepts are frequently discussed in each company's filings,
        with frequency counts and source tracking. This enables queries like:
        - "What risks does CrowdStrike discuss most frequently?"
        - "Which companies discuss cloud security the most?"

        Args:
            ticker: Optional ticker to limit to specific company

        Returns:
            Number of associations created/updated
        """
        logger.info("Creating company-concept associations...")

        query = """
            // Aggregate concept mentions per company
            MATCH (c:Company)-[:FILED]->(d:Document)-[disc:DISCUSSES]->(concept:Concept)
            WHERE $ticker IS NULL OR c.ticker = $ticker
            WITH c, concept,
                 count(DISTINCT d) as doc_count,
                 sum(disc.count) as total_mentions,
                 collect(DISTINCT d.type) as source_doc_types
            WHERE doc_count >= 2  // Must appear in at least 2 documents
            MERGE (c)-[r:ASSOCIATED_WITH]->(concept)
            SET r.frequency = total_mentions,
                r.document_count = doc_count,
                r.source = source_doc_types,
                r.updated_at = datetime()
            RETURN count(r) as associations_created
        """

        result = self.neo4j.execute_read(query, {"ticker": ticker})
        count = result[0]["associations_created"] if result else 0

        logger.info(f"Created/updated {count} company-concept associations")
        return count

    def build_full_graph_with_relationships(
        self, ticker: str = None, rebuild: bool = False
    ) -> Dict:
        """
        Build complete knowledge graph including all relationship inference.

        This is the full pipeline that:
        1. Builds base graph (documents, entities, concepts)
        2. Infers entity (organization) relationships
        3. Infers concept relationships
        4. Creates company-concept associations

        Args:
            ticker: Optional ticker to build for (None = all companies)
            rebuild: If True, clear existing graph first

        Returns:
            Summary of all graph building operations
        """
        results = {
            "documents_processed": 0,
            "entities_created": 0,
            "concepts_created": 0,
            "entity_relationships": 0,
            "concept_relationships": 0,
            "company_concept_associations": 0,
        }

        if ticker:
            # Build for single ticker
            logger.info(f"Building full graph for {ticker}")
            build_result = self.build_graph_for_ticker(ticker)
            results["documents_processed"] = build_result.get("documents_processed", 0)
            results["entities_created"] = sum(
                d.get("entities", 0) for d in build_result.get("documents", [])
            )
            results["concepts_created"] = sum(
                d.get("concepts", 0) for d in build_result.get("documents", [])
            )
        else:
            # Build for all companies
            logger.info("Building full graph for all companies")
            all_result = self.build_graph_for_all_companies()
            results["documents_processed"] = all_result.get("total_documents", 0)

        # Infer relationships
        results["entity_relationships"] = self.infer_entity_relationships(ticker)
        results["concept_relationships"] = self.infer_concept_relationships(ticker)
        results["company_concept_associations"] = self.create_company_concept_associations(ticker)

        logger.info(f"Full graph build complete: {results}")
        return results


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
