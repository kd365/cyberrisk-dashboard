"""
Cypher Generator — Text-to-Cypher for the CyberRisk Knowledge Graph.

Replaces brittle keyword routing in _call_graph_tools. The agent passes a
natural-language question; this module asks Claude Haiku to write a Cypher
query using the injected schema and few-shot examples, validates it as
read-only, and returns the structured results.

Architecture:
    question + ticker
        → schema-injected Haiku prompt
        → generated Cypher (validated read-only)
        → execute against Neo4j
        → return rows for synthesizer
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)


# =============================================================================
# Schema description — injected into the LLM prompt
# =============================================================================
# Hand-curated rather than auto-extracted from db.schema.visualization() because:
#   1. Property names need human-readable hints (e.g. "ticker is the stock symbol")
#   2. Some labels exist with different property availability per node
#   3. Keeping it in code lets us version-control the prompt surface

GRAPH_SCHEMA = """
Node labels and their key properties:

(:Organization)
    ticker: stock symbol (e.g. "CRWD"). Tracked companies have this set.
    name: company name (e.g. "CrowdStrike Holdings")
    tracked: true if it's one of the 30 actively-tracked cyber companies
    cyber_sector: primary sector (e.g. "Endpoint Security")
    cyber_focus: list of focus areas (e.g. ["EDR", "XDR"])
    market_positioning: leader|challenger|niche|emerging
    competitive_moat: technology|market_share|partnerships|data_scale|platform_breadth
    leadership_cyber_expertise, product_market_fit, innovation_intensity,
    customer_concentration_risk, regulatory_alignment, management_sentiment,
    growth_trajectory, risk_disclosure_quality, threat_landscape_awareness:
        each is a 0-4 integer score from LLM extraction of 10-K filings
    key_risks, key_opportunities: lists of strings extracted from 10-Ks
    risk_summary: 2-3 sentence summary

(:Document)
    title, date, filing_type ("10-K"|"10-Q"|"8-K"|"transcript"), source

(:MAEvent)                                       — from 8-K Item 1.01/2.01
    event_type: merger|acquisition|partnership|licensing|credit_agreement|other
    target_company: counterparty name (string, may not match an Organization node)
    counterparty: same as target_company in some events
    deal_value: dollar amount as string (may be null)
    effective_date, completion_date: YYYY-MM-DD strings
    summary: 1-2 sentence description

(:ExecutiveEvent)                                — from 8-K Item 5.02
    event_type: appointment|departure|retirement|resignation
    person_name, title
    effective_date: YYYY-MM-DD
    reason: nullable text

(:SecurityEvent)                                 — from 8-K Item 8.01 (rare)
    event_type: cybersecurity_incident|data_breach|vulnerability|ransomware
    severity: critical|high|medium|low
    discovery_date: YYYY-MM-DD
    summary

(:Vulnerability)                                 — from NVD CVE feed
    cve_id (e.g. "CVE-2024-12345"), severity, description, vendor

(:Patent)                                        — from USPTO
    number, title, filing_date, issued_date

(:Person)
    name, title, organization

(:Location)
    name, country_code

(:Concept)                                       — key phrases from documents
    name, normalized_name, frequency

(:Event)
    name, date, event_type

(:Regulation)                                    — from Federal Register
    title, agency (SEC|CISA|FTC|NIST|DHS), severity, effective_date

Relationships:

(Organization)-[:HAS_FILING]->(Document)
(Organization)-[:HAS_MA_EVENT]->(MAEvent)
(MAEvent)-[:INVOLVES_COMPANY]->(Organization)         — counterparty link
(Organization)-[:MA_RELATIONSHIP {type, date}]->(Organization)
(Organization)-[:HAS_EXECUTIVE_EVENT]->(ExecutiveEvent)
(Person)-[:INVOLVED_IN]->(ExecutiveEvent)
(Organization)-[:HAS_SECURITY_EVENT]->(SecurityEvent)
(Organization)-[:HAS_VULNERABILITY]->(Vulnerability)
(Organization)-[:FILED]->(Patent)
(Person)-[:INVENTED]->(Patent)
(Organization)-[:COMPETES_WITH]->(Organization)
(Organization)-[:OPERATES_IN]->(Location)
(Document)-[:DISCUSSES]->(Concept)
(Document)-[:MENTIONS]->(Organization|Person|Location|Event)
(Regulation)-[:IMPACTS {relevance_score, impact_level}]->(Organization)
"""


# =============================================================================
# Few-shot examples — calibrate the LLM on common query patterns
# =============================================================================

FEW_SHOT_EXAMPLES = """
Example 1:
Q: "Which companies has CSCO acquired?"
Cypher:
MATCH (o:Organization {ticker: 'CSCO'})-[:HAS_MA_EVENT]->(m:MAEvent)
WHERE m.event_type IN ['merger', 'acquisition', 'acquisition_completed']
RETURN m.target_company AS target, m.deal_value AS value,
       m.effective_date AS date, m.summary AS summary
ORDER BY m.effective_date DESC
LIMIT 25

Example 2:
Q: "Who left CrowdStrike's leadership?"
Cypher:
MATCH (o:Organization {ticker: 'CRWD'})-[:HAS_EXECUTIVE_EVENT]->(e:ExecutiveEvent)
WHERE e.event_type IN ['departure', 'resignation', 'retirement']
RETURN e.person_name AS person, e.title AS title,
       e.effective_date AS date, e.reason AS reason
ORDER BY e.effective_date DESC
LIMIT 25

Example 3:
Q: "What vulnerabilities affect Palo Alto Networks?"
Cypher:
MATCH (o:Organization {ticker: 'PANW'})-[:HAS_VULNERABILITY]->(v:Vulnerability)
RETURN v.cve_id AS cve, v.severity AS severity, v.description AS description
ORDER BY v.severity DESC
LIMIT 25

Example 4:
Q: "Which tracked companies have the highest cyber sector relevance?"
Cypher:
MATCH (o:Organization)
WHERE o.tracked = true AND o.cyber_sector_relevance IS NOT NULL
RETURN o.ticker AS ticker, o.name AS name,
       o.cyber_sector_relevance AS relevance,
       o.market_positioning AS positioning
ORDER BY o.cyber_sector_relevance DESC
LIMIT 25

Example 5:
Q: "Has anyone acquired Splunk?"
Cypher:
MATCH (acquirer:Organization)-[:HAS_MA_EVENT]->(m:MAEvent)
WHERE toLower(m.target_company) CONTAINS 'splunk'
   OR toLower(m.counterparty) CONTAINS 'splunk'
   OR toLower(m.summary) CONTAINS 'splunk'
RETURN acquirer.ticker AS acquirer_ticker, acquirer.name AS acquirer_name,
       m.event_type AS event_type, m.target_company AS target,
       m.effective_date AS date, m.summary AS summary
LIMIT 25

Example 6:
Q: "What patents has CRWD filed since 2024?"
Cypher:
MATCH (o:Organization {ticker: 'CRWD'})-[:FILED]->(p:Patent)
WHERE p.filing_date >= '2024-01-01'
RETURN p.number AS patent_number, p.title AS title,
       p.filing_date AS filed, p.issued_date AS issued
ORDER BY p.filing_date DESC
LIMIT 25

Example 7:
Q: "Show me the executive movements at FFIV"
Cypher:
MATCH (o:Organization {ticker: 'FFIV'})-[:HAS_EXECUTIVE_EVENT]->(e:ExecutiveEvent)
RETURN e.event_type AS type, e.person_name AS person, e.title AS title,
       e.effective_date AS date
ORDER BY e.effective_date DESC
LIMIT 25
"""


# =============================================================================
# Validator — block writes, enforce LIMIT
# =============================================================================

# Word-boundary keyword matching to avoid false positives like
# "DELETED" inside string literals.
WRITE_KEYWORD_RE = re.compile(
    r"\b(CREATE|MERGE|DELETE|REMOVE|SET|DETACH|DROP|FOREACH|LOAD\s+CSV)\b",
    re.IGNORECASE,
)

# Procedures that could write or escape sandbox
DANGEROUS_PROCEDURE_RE = re.compile(
    r"\bCALL\s+(?!db\.schema|db\.labels|db\.relationshipTypes|gds\.\w+\.stream)",
    re.IGNORECASE,
)


def validate_read_only(cypher: str) -> Optional[str]:
    """Return None if safe, error message string if not."""
    m = WRITE_KEYWORD_RE.search(cypher)
    if m:
        return f"Generated query contains write keyword: {m.group(0)}"
    m = DANGEROUS_PROCEDURE_RE.search(cypher)
    if m:
        return "Generated query uses a procedure that may write or escape sandbox"
    return None


def enforce_limit(cypher: str, max_limit: int = 100) -> str:
    """Append LIMIT if missing, cap if too high."""
    # Find existing LIMIT N
    m = re.search(r"\bLIMIT\s+(\d+)\b", cypher, re.IGNORECASE)
    if m:
        existing = int(m.group(1))
        if existing > max_limit:
            return cypher.replace(m.group(0), f"LIMIT {max_limit}")
        return cypher
    # No LIMIT — append. Strip trailing semicolons/whitespace first.
    return cypher.rstrip().rstrip(";") + f"\nLIMIT {max_limit}"


# =============================================================================
# Generator — Bedrock Haiku
# =============================================================================


class CypherGenerator:
    """LLM-backed text-to-Cypher generator with read-only enforcement."""

    MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    MAX_LIMIT = 100

    def __init__(self):
        region = os.environ.get("AWS_REGION", "us-west-2")
        config = Config(
            region_name=region, retries={"max_attempts": 3, "mode": "adaptive"}
        )
        self.bedrock = boto3.client("bedrock-runtime", config=config)
        self._neo4j = None

    @property
    def neo4j(self):
        if self._neo4j is None:
            from services.neo4j_service import get_neo4j_service

            self._neo4j = get_neo4j_service()
        return self._neo4j

    def _build_prompt(self, question: str, ticker: Optional[str]) -> str:
        ticker_hint = (
            f"\nThe user mentioned ticker: {ticker}. "
            f"Use this ticker in your query if relevant."
            if ticker
            else ""
        )
        return f"""You translate natural-language questions about a cybersecurity \
company knowledge graph into read-only Cypher queries.

GRAPH SCHEMA:
{GRAPH_SCHEMA}

EXAMPLES:
{FEW_SHOT_EXAMPLES}

RULES:
- Output ONLY the Cypher query, no explanation, no markdown fences.
- Use ONLY MATCH, WHERE, WITH, RETURN, ORDER BY, LIMIT, UNWIND, OPTIONAL MATCH.
- NEVER use CREATE, MERGE, DELETE, REMOVE, SET, DETACH, DROP, FOREACH, LOAD CSV.
- Always include a LIMIT clause (default LIMIT 25).
- Use exact property names from the schema. Do not invent fields.
- For string matching, prefer toLower(field) CONTAINS 'value' for fuzzy matching.
- If the user asks about a company by name (not ticker), match on toLower(o.name) CONTAINS.

QUESTION:{ticker_hint}
{question}

CYPHER:"""

    def generate(self, question: str, ticker: Optional[str] = None) -> Dict[str, Any]:
        """
        Translate a question to Cypher, execute it, return rows.

        Returns a dict with:
          - status: "ok" | "validation_error" | "execution_error"
          - cypher: the generated query (always present, even on error)
          - rows: list of result dicts (only on success)
          - error: error message (on failure)
        """
        prompt = self._build_prompt(question, ticker)

        try:
            response = self.bedrock.converse(
                modelId=self.MODEL_ID,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": 600, "temperature": 0},
            )
            cypher_raw = response["output"]["message"]["content"][0]["text"].strip()
        except Exception as e:
            logger.error(f"Cypher generation Bedrock call failed: {e}")
            return {"status": "generation_error", "error": str(e), "cypher": None}

        # Strip markdown fences if the model added them despite instructions
        cypher = re.sub(r"^```(?:cypher|sql)?\s*", "", cypher_raw)
        cypher = re.sub(r"\s*```$", "", cypher).strip()

        # Validate read-only
        violation = validate_read_only(cypher)
        if violation:
            logger.warning(f"Rejected unsafe Cypher: {violation}\nQuery: {cypher}")
            return {"status": "validation_error", "error": violation, "cypher": cypher}

        # Enforce row cap
        cypher = enforce_limit(cypher, self.MAX_LIMIT)

        # Execute
        try:
            rows = self.neo4j.execute_read(cypher, {})
        except Exception as e:
            logger.error(f"Cypher execution failed: {e}\nQuery: {cypher}")
            return {"status": "execution_error", "error": str(e), "cypher": cypher}

        return {
            "status": "ok",
            "cypher": cypher,
            "row_count": len(rows),
            "rows": rows[:25],  # Truncate further for synthesizer context
        }


_singleton: Optional[CypherGenerator] = None


def get_cypher_generator() -> CypherGenerator:
    global _singleton
    if _singleton is None:
        _singleton = CypherGenerator()
    return _singleton
