"""
AWS Comprehend Service for NLP Analysis
Provides sentiment analysis, key phrase extraction, and word frequency analysis
"""

import boto3
import re
import io
import os
from collections import Counter
from datetime import datetime
from botocore.exceptions import ProfileNotFound

# Try to import PyPDF2 for PDF text extraction
try:
    from PyPDF2 import PdfReader

    PDF_AVAILABLE = True
except ImportError:
    print("Warning: PyPDF2 not installed. PDF text extraction will be limited.")
    PDF_AVAILABLE = False


class ComprehendService:
    def __init__(self):
        # Use profile locally, instance role on EC2
        profile = os.environ.get("AWS_PROFILE", "cyber-risk")
        try:
            session = boto3.Session(profile_name=profile)
            session.get_credentials()
            self.comprehend = session.client("comprehend", region_name="us-east-1")
            self.s3 = session.client("s3")
        except (ProfileNotFound, Exception):
            # On EC2, use instance role (no profile)
            self.comprehend = boto3.client("comprehend", region_name="us-east-1")
            self.s3 = boto3.client("s3")
        # Use ARTIFACTS_BUCKET env var, fallback to old bucket for local dev
        self.bucket = os.environ.get("ARTIFACTS_BUCKET", "cyber-risk-artifacts")

        # Stop words to filter out (expanded for financial/transcript documents)
        self.stop_words = set(
            [
                # Basic stop words
                "the",
                "a",
                "an",
                "and",
                "or",
                "but",
                "in",
                "on",
                "at",
                "to",
                "for",
                "of",
                "with",
                "by",
                "from",
                "as",
                "is",
                "was",
                "are",
                "were",
                "been",
                "be",
                "have",
                "has",
                "had",
                "do",
                "does",
                "did",
                "will",
                "would",
                "could",
                "should",
                "may",
                "might",
                "must",
                "can",
                "this",
                "that",
                "these",
                "those",
                "i",
                "you",
                "he",
                "she",
                "it",
                "we",
                "they",
                "what",
                "which",
                "who",
                "when",
                "where",
                "why",
                "how",
                "all",
                "each",
                "every",
                "both",
                "few",
                "more",
                "most",
                "other",
                "some",
                "such",
                # PDF metadata artifacts (from malformed PDF extraction)
                "obj",
                "endobj",
                "stream",
                "endstream",
                "filter",
                "flatedecode",
                "length",
                "objstm",
                "xref",
                "trailer",
                "startxref",
                "eof",
                "page",
                "contents",
                "resources",
                "mediabox",
                "parent",
                "kids",
                "count",
                "procset",
                "pdf",
                "text",
                "imageb",
                "imagec",
                "imagei",
                "font",
                "xobject",
                "colorspace",
                "devicergb",
                "devicegray",
                "devicecmyk",
                # SEC SGML/HTML/CSS artifacts
                "style",
                "bbb",
                "hhhh",
                "fasb",
                "org",
                "xmlns",
                "xbrli",
                "iso",
                "xsi",
                "dei",
                "link",
                "href",
                "arcrole",
                "role",
                "label",
                "calculation",
                "presentation",
                "definition",
                "false",
                "true",
                "duration",
                "instant",
                "pure",
                "usd",
                "ary",
                "string",
                "member",
                "axis",
                "domain",
                "table",
                "abstract",
                "line",
                "item",
                "items",
                "class",
                "span",
                "div",
                "pre",
                "html",
                "body",
                "head",
                "meta",
                "script",
                "noscript",
                "img",
                "alt",
                # CSS styling terms
                "align",
                "color",
                "padding",
                "bottom",
                "vertical",
                "background",
                "height",
                "size",
                "weight",
                "family",
                "serif",
                "roman",
                "sans",
                "right",
                "border",
                "top",
                "width",
                "solid",
                "left",
                "center",
                "middle",
                "font",
                "margin",
                # HTML table artifacts
                "rowspan",
                "colspan",
                "cellpadding",
                "cellspacing",
                "valign",
                "nowrap",
                "thead",
                "tbody",
                "tfoot",
                "caption",
                "colgroup",
                "col",
                "scope",
                # XBRL/Accounting taxonomy
                "xbrl",
                "paragraph",
                "topic",
                "colspan",
                "standards",
                "asc",
                "uri",
                "codification",
                "subtopic",
                "subparagraph",
                "disclosureref",
                "reference",
                "cceeff",
                "nsuri",
                "localname",
                "contextref",
                "decimals",
                "unitref",
                "xbrltype",
                "prefix",
                "namespace",
                "display",
                "terselabel",
                "monetaryitemtype",
                "legacyref",
                "commonpracticeref",
                "oid",
                "extlink",
                "loc",
                "verboselabel",
                "documentation",
                "references",
                "ref",
                "double",
                "deferred",
                "disclosure",
                "common",
                "term",
                "any",
                "not",
                "under",
                "options",
                "contract",
                "performance",
                "amount",
                "credit",
                "loss",
                "payment",
                "interest",
                "tax",
                "compensation",
                "ffffff",
                "none",
                "january",
                "number",
                "policy",
                "business",
                "investments",
                "exampleref",
                "crdr",
                "nskm",
                "stringitemtype",
                "xox",
                "mhh",
                "auv",
                "debit",
                "outstanding",
                "non",
                "average",
                "its",
                "one",
                "order",
                "increase",
                "recognized",
                "financing",
                "future",
                "property",
                "equipment",
                "rate",
                "weighted",
                "gov",
                "years",
                "results",
                "entity",
                "subject",
                "acquired",
                "sheet",
                "reporting",
                "july",
                "thousands",
                "time",
                "use",
                "sales",
                "taxes",
                "market",
                "stockholders",
                # Web/URL terms
                "http",
                "https",
                "www",
                "com",
                "net",
                "lang",
                "utf",
                "charset",
                "xml",
                # Document structure terms
                "section",
                "publisher",
                "details",
                "times",
                "new",
                "based",
                # Generic document terms
                "document",
                "type",
                "ticker",
                "date",
                "content",
                "replace",
                "actual",
                "aten",
                "mock",
                "sec",
                # Alpha Vantage transcript format terms
                "speaker",
                "title",
                "sentiment",
                "operator",
                "thank",
                "question",
                "answer",
                "over",
                "their",
                "about",
                "than",
                "them",
                "your",
                "there",
                # Motley Fool platform terms
                "motley",
                "fool",
                "motleyfool",
                "accessibility",
                "menu",
                "services",
                "advisor",
                "epic",
                "portfolios",
                "podcasts",
                "foundation",
                "trending",
                "newsletter",
                "subscribe",
                "premium",
                "membership",
                # Generic financial terms (too common to be meaningful)
                "our",
                "million",
                "billion",
                "quarter",
                "year",
                "fiscal",
                "ended",
                "months",
                "three",
                "six",
                "nine",
                "twelve",
                "first",
                "second",
                "third",
                "fourth",
                "financial",
                "statement",
                "statements",
                "operating",
                "total",
                "net",
                "cash",
                "stock",
                "share",
                "shares",
                "inc",
                "company",
                "per",
                "basis",
                "information",
                "including",
                "related",
                "certain",
                "see",
                "notes",
                "note",
                "refer",
                "following",
                "also",
                "included",
                "june",
                "september",
                "december",
                "march",
                "period",
                "periods",
                "respective",
                # Very generic terms
                "name",
                "accounting",
                "htm",
                "indent",
                "during",
                "available",
                "expected",
                "current",
                "plan",
                "arrangement",
                "consolidated",
                "purchase",
                "debt",
                "lease",
                "price",
                "award",
                "attributable",
                "acquisition",
                "securities",
                "operations",
                "may",
                "used",
                "within",
                "through",
                "without",
                "various",
                # Accounting/metrics terms (too generic)
                "gaap",
                "arr",
                "revenue",
                "income",
                "expense",
                "expenses",
                "cost",
                "costs",
                "assets",
                "liabilities",
                "equity",
                "balance",
                "retained",
                "earnings",
                "comprehensive",
                "accumulated",
                "derivative",
                "fair",
                "value",
                "goodwill",
                "intangible",
                "amortization",
                "depreciation",
                "siem",
                "saas",
                "ebitda",
                "capex",
                "opex",
                "cogs",
                "eps",
                "roi",
                # Company-specific (ticker and name components)
                "crowdstrike",
                "crwd",
                "holdings",
                # Navigation/UI terms
                "arrow",
                "thin",
                "down",
                "up",
                "click",
                "here",
                "read",
                "view",
                "show",
                "hide",
                "menu",
                "search",
                "home",
                "back",
                "next",
                "previous",
            ]
        )

    def _clean_transcript_text(self, text):
        """
        Clean Motley Fool website navigation and boilerplate from transcript text

        Args:
            text: Raw text extracted from PDF

        Returns:
            str: Cleaned text with website structure removed
        """
        if not text:
            return text

        lines = text.split("\n")
        cleaned_lines = []
        skip_until_content = True

        # Indicators that actual transcript content has started
        content_indicators = [
            "operator",
            "prepared remarks",
            "earnings call",
            "conference call",
            "good morning",
            "good afternoon",
            "thank you for standing by",
            "welcome to the",
        ]

        # Patterns to skip (Motley Fool website structure)
        skip_patterns = [
            "accessibility",
            "stock advisor",
            "epic plus",
            "fool portfolios",
            "market movers",
            "tech stock news",
            "crypto news",
            "biggest stock gainers",
            "biggest stock losers",
            "terms of use",
            "privacy policy",
            "disclosure policy",
            "copyright, trademark",
            "do not sell my personal",
            "motley fool asset management",
            "motley fool wealth management",
            "become an affiliate",
            "arrow-thin-",
            "+0.",  # Stock price changes
            "-0.",
            "nasdaq",
            "bitcoin",
            "aapl",
            "amzn",
            "goog",
            "meta",
        ]

        for line in lines:
            line_lower = line.lower().strip()

            # Skip empty lines
            if not line_lower:
                continue

            # Check if we've hit actual content
            if skip_until_content:
                if any(indicator in line_lower for indicator in content_indicators):
                    skip_until_content = False
                    cleaned_lines.append(line)
                continue

            # Skip lines with Motley Fool boilerplate
            if any(pattern in line_lower for pattern in skip_patterns):
                continue

            # Skip very short lines (likely navigation)
            if len(line.strip()) < 10:
                continue

            # Skip lines that are all caps (likely headers)
            if line.strip().isupper() and len(line.strip()) < 50:
                continue

            cleaned_lines.append(line)

        return "\n".join(cleaned_lines)

    def get_document_text(self, s3_key):
        """
        Retrieve text content from S3 document (with PDF support)

        Args:
            s3_key: S3 object key

        Returns:
            str: Document text content
        """
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=s3_key)

            # Extract text from PDF
            if PDF_AVAILABLE and s3_key.endswith(".pdf"):
                pdf_content = response["Body"].read()
                pdf_file = io.BytesIO(pdf_content)

                try:
                    reader = PdfReader(pdf_file)
                    text = ""
                    for page in reader.pages:
                        text += page.extract_text() + "\n"

                    # Clean transcript text if it's from Motley Fool
                    if "transcript" in s3_key.lower():
                        text = self._clean_transcript_text(text)

                    return text.strip()
                except Exception as pdf_error:
                    print(f"❌ Error extracting text from PDF {s3_key}: {pdf_error}")
                    return ""
            else:
                # For non-PDF files, try reading as text
                content = response["Body"].read()
                try:
                    return content.decode("utf-8")
                except:
                    return content.decode("latin-1", errors="ignore")

        except Exception as e:
            print(f"❌ Error reading document from S3: {e}")
            return ""

    def extract_alphavantage_sentiment(self, s3_key):
        """
        Extract Alpha Vantage sentiment scores from transcript text

        Alpha Vantage provides sentiment scores (0.0-1.0) for each speaker segment
        This extracts those scores and calculates aggregate metrics

        Args:
            s3_key: S3 key for transcript file

        Returns:
            dict: Sentiment analysis with scores by speaker and overall metrics
        """
        try:
            text = self.get_document_text(s3_key)
            if not text:
                return None

            # Parse sentiment scores from the formatted text
            # Format: "Sentiment: 0.7" on its own line
            sentiment_scores = []
            speaker_sentiments = {}
            current_speaker = None

            lines = text.split("\n")
            for i, line in enumerate(lines):
                # Extract speaker name
                if line.startswith("Speaker: "):
                    current_speaker = line.replace("Speaker: ", "").strip()
                    if current_speaker not in speaker_sentiments:
                        speaker_sentiments[current_speaker] = []

                # Extract sentiment score
                if line.startswith("Sentiment: "):
                    try:
                        score = float(line.replace("Sentiment: ", "").strip())
                        sentiment_scores.append(score)

                        if current_speaker:
                            speaker_sentiments[current_speaker].append(score)
                    except ValueError:
                        continue

            if not sentiment_scores:
                return None

            # Calculate aggregate metrics
            avg_sentiment = sum(sentiment_scores) / len(sentiment_scores)

            # Calculate by speaker
            speaker_averages = {}
            for speaker, scores in speaker_sentiments.items():
                if scores:
                    speaker_averages[speaker] = {
                        "average": sum(scores) / len(scores),
                        "count": len(scores),
                        "min": min(scores),
                        "max": max(scores),
                    }

            # Categorize sentiment (Alpha Vantage scale: 0.0 = neutral/negative, 1.0 = very positive)
            positive_count = sum(1 for s in sentiment_scores if s >= 0.6)
            neutral_count = sum(1 for s in sentiment_scores if 0.3 <= s < 0.6)
            negative_count = sum(1 for s in sentiment_scores if s < 0.3)

            return {
                "overall_score": avg_sentiment,
                "total_segments": len(sentiment_scores),
                "score_distribution": {
                    "positive": positive_count / len(sentiment_scores),
                    "neutral": neutral_count / len(sentiment_scores),
                    "negative": negative_count / len(sentiment_scores),
                },
                "by_speaker": speaker_averages,
                "min_score": min(sentiment_scores),
                "max_score": max(sentiment_scores),
            }

        except Exception as e:
            print(f"❌ Error extracting Alpha Vantage sentiment from {s3_key}: {e}")
            return None

    def analyze_sentiment(self, text):
        """
        Analyze sentiment of text using AWS Comprehend

        Args:
            text: Text to analyze (max 5000 bytes for Comprehend)

        Returns:
            dict: Sentiment scores
        """
        if not text or len(text.strip()) == 0:
            return {
                "Sentiment": "NEUTRAL",
                "SentimentScore": {
                    "Positive": 0.0,
                    "Negative": 0.0,
                    "Neutral": 1.0,
                    "Mixed": 0.0,
                },
            }

        # Truncate to max bytes for Comprehend (5000 UTF-8 bytes)
        text_bytes = text.encode("utf-8")[:5000]
        text = text_bytes.decode("utf-8", errors="ignore")

        try:
            response = self.comprehend.detect_sentiment(Text=text, LanguageCode="en")
            return response
        except Exception as e:
            print(f"Error analyzing sentiment: {e}")
            return {
                "Sentiment": "NEUTRAL",
                "SentimentScore": {
                    "Positive": 0.0,
                    "Negative": 0.0,
                    "Neutral": 1.0,
                    "Mixed": 0.0,
                },
            }

    def analyze_document_sentiment(self, s3_key):
        """
        Analyze sentiment of entire document by chunking

        Args:
            s3_key: S3 key for document

        Returns:
            dict: Average sentiment across all chunks
        """
        text = self.get_document_text(s3_key)

        if not text:
            return {"Positive": 0.0, "Negative": 0.0, "Neutral": 1.0, "Mixed": 0.0}

        # Split into chunks (5000 bytes each for Comprehend)
        chunks = self._chunk_text(text, max_bytes=5000)

        sentiments = []
        for chunk in chunks[:10]:  # Limit to first 10 chunks for performance
            result = self.analyze_sentiment(chunk)
            sentiments.append(result["SentimentScore"])

        # Average sentiment scores
        if not sentiments:
            return {"Positive": 0.0, "Negative": 0.0, "Neutral": 1.0, "Mixed": 0.0}

        avg_sentiment = {
            "Positive": sum(s["Positive"] for s in sentiments) / len(sentiments),
            "Negative": sum(s["Negative"] for s in sentiments) / len(sentiments),
            "Neutral": sum(s["Neutral"] for s in sentiments) / len(sentiments),
            "Mixed": sum(s["Mixed"] for s in sentiments) / len(sentiments),
        }

        return avg_sentiment

    def extract_key_phrases(self, text):
        """
        Extract key phrases using AWS Comprehend

        Args:
            text: Text to analyze

        Returns:
            list: Key phrases with scores
        """
        if not text or len(text.strip()) == 0:
            return []

        # Truncate to max bytes
        text_bytes = text.encode("utf-8")[:5000]
        text = text_bytes.decode("utf-8", errors="ignore")

        try:
            response = self.comprehend.detect_key_phrases(Text=text, LanguageCode="en")
            return response.get("KeyPhrases", [])
        except Exception as e:
            print(f"Error extracting key phrases: {e}")
            return []

    def extract_word_frequency(self, text, top_n=50):
        """
        Extract word frequency from text with cybersecurity focus

        Args:
            text: Text to analyze
            top_n: Number of top words to return

        Returns:
            list: List of dicts with {text, count, category}
        """
        if not text:
            return []

        # Cybersecurity-relevant keywords (boost their importance by 3x)
        security_keywords = {
            # Threat types
            "breach",
            "attack",
            "malware",
            "ransomware",
            "phishing",
            "vulnerability",
            "exploit",
            "threat",
            "intrusion",
            "ddos",
            "zero-day",
            "backdoor",
            "botnet",
            "trojan",
            "worm",
            "spyware",
            "adware",
            # Security concepts
            "encryption",
            "authentication",
            "authorization",
            "firewall",
            "endpoint",
            "detection",
            "prevention",
            "response",
            "incident",
            "compliance",
            "privacy",
            "gdpr",
            "hipaa",
            "soc2",
            "penetration",
            "forensics",
            "security",
            "cybersecurity",
            "defense",
            "protection",
            "safeguard",
            # Cloud/Infrastructure security
            "cloud",
            "infrastructure",
            "network",
            "perimeter",
            "siem",
            "soar",
            "xdr",
            "edr",
            "ndr",
            "identity",
            "access",
            "iam",
            "zero-trust",
            "vpn",
            "proxy",
            "gateway",
            "appliance",
            "load-balancer",
            # Security operations
            "monitoring",
            "alerting",
            "remediation",
            "patching",
            "hardening",
            "segmentation",
            "isolation",
            "sandbox",
            "quarantine",
            "visibility",
            "analytics",
            "intelligence",
            "telemetry",
            # Business/Risk terms
            "risk",
            "exposure",
            "assessment",
            "audit",
            "governance",
            "policy",
            "regulation",
            "certification",
            # Application/Platform
            "application",
            "platform",
            "service",
            "solution",
            "deployment",
            "implementation",
            "integration",
            "automation",
        }

        # Clean and tokenize
        text = text.lower()
        words = re.findall(r"\b[a-z]{3,}\b", text)  # Words with 3+ letters

        # Filter stop words
        words = [w for w in words if w not in self.stop_words]

        # Count frequencies
        word_counts = Counter(words)

        # Boost security-relevant keywords (multiply count by 3)
        boosted_counts = {}
        for word, count in word_counts.items():
            if word in security_keywords:
                boosted_counts[word] = {
                    "count": count,
                    "boosted_score": count * 3,
                    "category": "security",
                }
            else:
                boosted_counts[word] = {
                    "count": count,
                    "boosted_score": count,
                    "category": "general",
                }

        # Sort by boosted score
        sorted_words = sorted(
            boosted_counts.items(), key=lambda x: x[1]["boosted_score"], reverse=True
        )

        # Return top N with category labels
        return [
            {"text": word, "count": data["count"], "category": data["category"]}
            for word, data in sorted_words[:top_n]
        ]

    def extract_entities(self, text):
        """
        Extract named entities using AWS Comprehend

        Args:
            text: Text to analyze

        Returns:
            list: Named entities with types and scores
        """
        if not text or len(text.strip()) == 0:
            return []

        # Truncate to max bytes
        text_bytes = text.encode("utf-8")[:5000]
        text = text_bytes.decode("utf-8", errors="ignore")

        try:
            response = self.comprehend.detect_entities(Text=text, LanguageCode="en")
            return response.get("Entities", [])
        except Exception as e:
            print(f"Error extracting entities: {e}")
            return []

    def detect_targeted_sentiment(self, text):
        """
        Detect sentiment for specific entities in the text using AWS Comprehend Targeted Sentiment

        This identifies entities and determines sentiment toward each one.
        More granular than overall sentiment analysis.

        Args:
            text: Text to analyze (max 5000 bytes)

        Returns:
            list: Entities with their targeted sentiment scores
        """
        if not text or len(text.strip()) == 0:
            return []

        # Truncate to max bytes
        text_bytes = text.encode("utf-8")[:5000]
        text = text_bytes.decode("utf-8", errors="ignore")

        try:
            response = self.comprehend.detect_targeted_sentiment(
                Text=text, LanguageCode="en"
            )
            return response.get("Entities", [])
        except Exception as e:
            print(f"Error detecting targeted sentiment: {e}")
            return []

    def analyze_ticker_sentiment(self, ticker, artifacts, include_entities=True):
        """
        Comprehensive sentiment analysis for a ticker

        Args:
            ticker: Stock ticker symbol
            artifacts: List of artifact dicts with s3_key, type, date
            include_entities: Whether to extract entities (more expensive)

        Returns:
            dict: Complete sentiment analysis results
        """
        # Filter artifacts for this ticker
        ticker_artifacts = [a for a in artifacts if a.get("ticker") == ticker]

        print(f"📊 Found {len(ticker_artifacts)} artifacts for {ticker}")

        if not ticker_artifacts:
            print(f"❌ No artifacts found for {ticker}")
            return None

        # Overall sentiment analysis
        all_sentiments = []
        all_text = ""

        # Timeline data
        timeline = []

        # Document type separation
        sec_docs = []
        transcript_docs = []

        # Entity tracking
        all_entities = []
        all_targeted_entities = []  # For targeted sentiment analysis

        for artifact in ticker_artifacts:
            s3_key = artifact.get("s3_key") or artifact.get("document_link")
            doc_type = artifact.get("type", "")
            doc_date = artifact.get("date", "")

            print(f"  📄 Processing: {s3_key} ({doc_type})")

            if not s3_key:
                print(f"    ⚠️  Skipping - no s3_key")
                continue

            # Get document text
            text = self.get_document_text(s3_key)

            if not text:
                print(f"    ❌ Failed to extract text from {s3_key}")
                continue

            text_len = len(text.strip())
            print(f"    ✅ Extracted {text_len} characters")

            if text_len < 100:
                print(f"    ⚠️  Skipping - text too short ({text_len} chars)")
                continue

            all_text += " " + text

            # Analyze sentiment for this document
            sentiment = self.analyze_document_sentiment(s3_key)
            all_sentiments.append(sentiment)

            # Extract entities and targeted sentiment (first 5000 chars to save cost)
            # Limit to transcripts for better quality (SEC PDFs have too much XBRL noise)
            if include_entities and len(all_targeted_entities) < 100:  # Limit API calls
                sample_text = text[:5000]

                # Only analyze transcripts for targeted sentiment (cleaner text)
                if "transcript" in doc_type.lower() and s3_key.endswith(".txt"):
                    entities = self.extract_entities(sample_text)
                    all_entities.extend(entities)

                    # Targeted sentiment - identifies sentiment toward specific entities
                    targeted_entities = self.detect_targeted_sentiment(sample_text)
                    all_targeted_entities.extend(targeted_entities)

            # Add to timeline
            timeline.append(
                {"date": doc_date, "type": doc_type, "sentiment": sentiment}
            )

            # Categorize by document type
            if "10-K" in doc_type or "10-Q" in doc_type:
                sec_docs.append(
                    {
                        "text": text,
                        "sentiment": sentiment,
                        "date": doc_date,
                        "type": doc_type,
                    }
                )
            elif "transcript" in doc_type.lower():
                transcript_docs.append(
                    {
                        "text": text,
                        "sentiment": sentiment,
                        "date": doc_date,
                        "type": doc_type,
                    }
                )

        # Calculate overall average sentiment
        if not all_sentiments:
            print(f"❌ No valid sentiments extracted for {ticker}")
            return None

        print(f"✅ Successfully analyzed {len(all_sentiments)} documents for {ticker}")

        overall_sentiment = {
            "Positive": sum(s["Positive"] for s in all_sentiments)
            / len(all_sentiments),
            "Negative": sum(s["Negative"] for s in all_sentiments)
            / len(all_sentiments),
            "Neutral": sum(s["Neutral"] for s in all_sentiments) / len(all_sentiments),
            "Mixed": sum(s["Mixed"] for s in all_sentiments) / len(all_sentiments),
        }

        # Word frequency analysis
        word_frequency = self.extract_word_frequency(all_text, top_n=50)

        # Process entities
        entity_summary = self._summarize_entities(all_entities)

        # Process targeted sentiment - entity-specific sentiment analysis
        targeted_sentiment_summary = self._summarize_targeted_sentiment(
            all_targeted_entities
        )

        # Document comparison
        sec_sentiment = self._calculate_average_sentiment(sec_docs)
        transcript_sentiment = self._calculate_average_sentiment(transcript_docs)

        # Generate insights
        insights = self._generate_comparison_insights(
            sec_sentiment, transcript_sentiment, len(sec_docs), len(transcript_docs)
        )

        # Sort timeline by date
        timeline.sort(key=lambda x: x["date"])

        # Get date range
        dates = [t["date"] for t in timeline if t["date"]]
        date_range = None
        if dates:
            date_range = {"start": min(dates), "end": max(dates)}

        return {
            "ticker": ticker,
            "overall": {
                "sentiment": overall_sentiment,
                "documentCount": len(ticker_artifacts),
                "dateRange": date_range,
            },
            "wordFrequency": word_frequency,
            "entities": entity_summary,
            "targetedSentiment": targeted_sentiment_summary,  # Entity-specific sentiment
            "documentComparison": {
                "sec": {
                    "sentiment": sec_sentiment,
                    "documentCount": len(sec_docs),
                    "topWords": self._get_top_words_for_docs(sec_docs, top_n=10),
                },
                "transcripts": {
                    "sentiment": transcript_sentiment,
                    "documentCount": len(transcript_docs),
                    "topWords": self._get_top_words_for_docs(transcript_docs, top_n=10),
                },
                "insights": insights,
            },
            "timeline": timeline,
        }

    def _chunk_text(self, text, max_bytes=5000):
        """Split text into chunks that fit Comprehend's byte limit"""
        chunks = []
        current_chunk = ""

        sentences = text.split(".")

        for sentence in sentences:
            sentence_with_period = sentence + "."
            sentence_bytes = len(sentence_with_period.encode("utf-8"))

            # If single sentence exceeds limit, truncate it
            if sentence_bytes > max_bytes:
                if current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = ""
                # Truncate the sentence to fit
                truncated = sentence_with_period.encode("utf-8")[:max_bytes]
                chunks.append(truncated.decode("utf-8", errors="ignore"))
                continue

            test_chunk = current_chunk + sentence_with_period
            if len(test_chunk.encode("utf-8")) > max_bytes:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = sentence_with_period
            else:
                current_chunk = test_chunk

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def _calculate_average_sentiment(self, docs):
        """Calculate average sentiment for a list of documents"""
        if not docs:
            return {"Positive": 0.0, "Negative": 0.0, "Neutral": 1.0, "Mixed": 0.0}

        sentiments = [d["sentiment"] for d in docs]

        return {
            "Positive": sum(s["Positive"] for s in sentiments) / len(sentiments),
            "Negative": sum(s["Negative"] for s in sentiments) / len(sentiments),
            "Neutral": sum(s["Neutral"] for s in sentiments) / len(sentiments),
            "Mixed": sum(s["Mixed"] for s in sentiments) / len(sentiments),
        }

    def _get_top_words_for_docs(self, docs, top_n=10):
        """Extract top words from a collection of documents"""
        if not docs:
            return []

        combined_text = " ".join([d["text"] for d in docs])
        return self.extract_word_frequency(combined_text, top_n=top_n)

    def _generate_comparison_insights(
        self, sec_sentiment, transcript_sentiment, sec_count, transcript_count
    ):
        """Generate insights comparing SEC docs vs transcripts"""
        insights = []

        if sec_count == 0 and transcript_count == 0:
            return ["No documents available for analysis"]

        if sec_count == 0:
            insights.append(
                "Only earnings transcripts available - SEC filings needed for comparison"
            )
            return insights

        if transcript_count == 0:
            insights.append(
                "Only SEC filings available - earnings transcripts needed for comparison"
            )
            return insights

        # Compare positive sentiment
        pos_diff = sec_sentiment["Positive"] - transcript_sentiment["Positive"]
        if abs(pos_diff) > 0.1:
            if pos_diff > 0:
                insights.append(
                    f"SEC filings are {abs(pos_diff)*100:.1f}% more positive than earnings calls"
                )
            else:
                insights.append(
                    f"Earnings calls are {abs(pos_diff)*100:.1f}% more positive than SEC filings"
                )
        else:
            insights.append(
                "Sentiment tone is consistent between SEC filings and earnings calls"
            )

        # Compare negative sentiment
        neg_diff = sec_sentiment["Negative"] - transcript_sentiment["Negative"]
        if abs(neg_diff) > 0.1:
            if neg_diff > 0:
                insights.append(
                    f"SEC filings contain {abs(neg_diff)*100:.1f}% more negative language"
                )
            else:
                insights.append(
                    f"Earnings calls contain {abs(neg_diff)*100:.1f}% more negative language"
                )

        # Check for mixed sentiment
        if sec_sentiment["Mixed"] > 0.15 or transcript_sentiment["Mixed"] > 0.15:
            insights.append(
                "High mixed sentiment detected - documents contain both positive and negative themes"
            )

        return insights

    def _summarize_entities(self, entities):
        """
        Summarize extracted entities by type, filtering out noise

        Args:
            entities: List of entity dicts from Comprehend

        Returns:
            dict: Summarized entities by type
        """
        if not entities:
            return {
                "organizations": [],
                "people": [],
                "locations": [],
                "commercialItems": [],
                "other": [],
            }

        # Entities to filter out (Motley Fool platform and generic terms)
        filter_entities = {
            "motley fool",
            "the motley fool",
            "fool",
            "epic",
            "plus",
            "epic plus",
            "stock advisor",
            "rule breaker",
            "warren buffett",
            "chatgpt",
            "spacex",
            "openai",
            "accessibility",
            "services",
            "foundation",
            "ventures",
            "asset management",
            "wealth management",
            "nasdaq",
            "nyse",
            "sec",
            "s&p",
            "dow jones",
            "apple",
            "amazon",
            "google",
            "meta",
            "microsoft",
            "tesla",
            "nvidia",  # Filter out unless they're actually being discussed
        }

        # Group by type
        by_type = {
            "ORGANIZATION": [],
            "PERSON": [],
            "LOCATION": [],
            "COMMERCIAL_ITEM": [],
            "OTHER": [],
        }

        for entity in entities:
            entity_type = entity.get("Type", "OTHER")
            text = entity.get("Text", "")
            score = entity.get("Score", 0.0)

            # Filter out noise entities
            if text.lower() in filter_entities:
                continue

            # Filter out very short entities (likely errors)
            if len(text) < 2:
                continue

            # Filter out entities that are all caps and very short (likely acronyms from navigation)
            if text.isupper() and len(text) <= 3:
                continue

            # Filter out entities with newlines or multiple spaces (malformed PDF extraction)
            if "\n" in text or "  " in text:
                continue

            # Filter out entities that contain "Table" or "Contents" (TOC artifacts)
            if any(
                word in text
                for word in ["Table", "Contents", "of Contents", "as reported"]
            ):
                continue

            # Filter out single letter entities
            if len(text.strip()) == 1:
                continue

            # Filter out entities that are mostly numbers/special chars
            alpha_chars = sum(c.isalpha() for c in text)
            if alpha_chars < len(text) * 0.5:  # Less than 50% letters
                continue

            # Filter out entities with "x" patterns (like "1x", "2x") - table headers
            if re.match(r"^\d+x$", text.strip().lower()):
                continue

            if entity_type not in by_type:
                by_type[entity_type] = []

            by_type[entity_type].append({"text": text, "score": score})

        # Count occurrences and get top entities
        def get_top_entities(entity_list, top_n=10):
            from collections import Counter

            entity_texts = [e["text"] for e in entity_list]
            counts = Counter(entity_texts)

            return [
                {
                    "text": text,
                    "count": count,
                    "score": next(e["score"] for e in entity_list if e["text"] == text),
                }
                for text, count in counts.most_common(top_n)
            ]

        return {
            "organizations": get_top_entities(by_type.get("ORGANIZATION", []), 15),
            "people": get_top_entities(by_type.get("PERSON", []), 10),
            "locations": get_top_entities(by_type.get("LOCATION", []), 10),
            "commercialItems": get_top_entities(by_type.get("COMMERCIAL_ITEM", []), 10),
            "other": get_top_entities(by_type.get("OTHER", []), 5),
        }

    def _summarize_targeted_sentiment(self, targeted_entities):
        """
        Summarize targeted sentiment entities by aggregating mentions and sentiment

        Args:
            targeted_entities: List of entities from detect_targeted_sentiment
                              Each entity has a 'Mentions' array with text and sentiment

        Returns:
            dict: Top entities with aggregated sentiment scores
        """
        if not targeted_entities:
            return []

        from collections import defaultdict

        # Filter out non-meaningful entities
        skip_terms = {
            # Pronouns
            "i",
            "you",
            "he",
            "she",
            "it",
            "we",
            "they",
            "our",
            "your",
            "their",
            "us",
            "them",
            "my",
            "mine",
            "yours",
            "his",
            "hers",
            "its",
            "ours",
            "theirs",
            "me",
            "him",
            "her",
            # Generic time terms
            "today",
            "tomorrow",
            "yesterday",
            "now",
            "then",
            "later",
            "soon",
            "this",
            "that",
            "these",
            "those",
            "annual",
            "quarter",
            "fiscal",
            "for",
            "quarterly",
            "of 1995",
            "as of the date",
            "at this",
            # Generic quantifiers
            "all",
            "some",
            "any",
            "many",
            "few",
            "several",
            "more",
            "most",
            "both",
            # Generic business terms
            "company",
            "business",
            "industry",
            "market",
            "sector",
            "margin",
            "margins",
            "revenue",
            "schedule",
            "growth",
            "expenses",
            "customer",
            "customers",
            "platform",
            "service",
            "services",
            "results",
            "result",
            "offices",
            "office",
            "cost",
            "costs",
            "profitability",
            "profit",
            "profile",
            "scale",
            "public company",
            "organization",
            "organizations",
            "cybersecurity",
            "security",
            "ecosystem",
            "earnings",
            "outlook",
            "filings",
            "data",
            "partner",
            "partners",
            "others",
            "world",
            "board",
            "logo",
            "next-gen",
            # Document structure
            "statements",
            "statement",
            "title",
            "section",
            "paragraph",
            "press release",
            "website",
            # Transcript/conference terms
            "speaker",
            "operator",
            "participants",
            "participant",
            "conference",
            "call",
            "question",
            "answer",
            "thank",
            "thanks",
            "speakers'",
            "speakers",
            # SEC filing terms
            "sec",
            "form",
            "filing",
            "report",
            "securities",
            "reform act",
            "form 8",
            "form 10",
            "exchange act",
            "form 8-k",
            "act",
            # Generic roles/titles
            "of investor relations",
            "investor relations",
            "president and",
            "chief executive officer",
            "chief financial officer",
            "co-founder",
            "ceo",
            "cfo",
            "coo",
            "cto",
            "vice president",
            "vice-president",
            "vice-president of",
            # Very generic
            "one",
            "two",
            "three",
            "four",
            "five",
            "first",
            "second",
            "third",
            "other",
            "another",
            "since",
            "while",
            "during",
            "before",
            "after",
            "you all",
            "everyone",
            "everybody",
        }

        # Aggregate by entity text
        # Note: AWS Targeted Sentiment returns entities with a 'Mentions' array
        # Each mention has 'Text', 'Type', and 'MentionSentiment'
        entity_sentiments = defaultdict(
            lambda: {"mentions": [], "sentiment_scores": [], "types": set()}
        )

        for entity in targeted_entities:
            # Get all mentions for this entity
            mentions = entity.get("Mentions", [])

            for mention in mentions:
                text = mention.get("Text", "").strip()
                if not text or len(text) < 2:
                    continue

                # Skip entities with newlines (parsing errors)
                if "\n" in text or "\r" in text:
                    continue

                # Skip URLs
                if (
                    ".com" in text.lower()
                    or ".org" in text.lower()
                    or text.startswith("http")
                ):
                    continue

                # Skip monetary values (e.g., "$188.7 million", "$2.9 billion")
                if (
                    "$" in text
                    or "million" in text.lower()
                    or "billion" in text.lower()
                ):
                    continue

                # Skip very long entities (likely full sentences or dates)
                if len(text) > 40:
                    continue

                # Skip generic/non-meaningful terms
                if text.lower() in skip_terms:
                    continue

                # Skip single characters and pure numbers
                if len(text) == 1 or text.isdigit():
                    continue

                # Skip pure numeric values (e.g., "0.9", "123.45")
                try:
                    float(text.replace(",", ""))
                    continue
                except ValueError:
                    pass  # Not a number, keep processing

                # Get entity type and sentiment
                entity_type = mention.get("Type", "UNKNOWN")

                # Skip QUANTITY entities entirely (numbers, "eight or more", etc.)
                if entity_type == "QUANTITY":
                    continue

                # Skip DATE entities that are generic time references
                # (e.g., "First Quarter 2024", "fiscal year 2024", "the second half of the year")
                if entity_type == "DATE":
                    # Skip all date entities - they're usually generic time references in transcripts
                    continue

                mention_sentiment = mention.get("MentionSentiment", {})
                sentiment_score = mention_sentiment.get("SentimentScore", {})

                if sentiment_score:
                    entity_sentiments[text]["mentions"].append(mention)
                    entity_sentiments[text]["sentiment_scores"].append(sentiment_score)
                    entity_sentiments[text]["types"].add(entity_type)

        # Calculate average sentiment for each entity
        results = []
        for entity_text, data in entity_sentiments.items():
            if not data["sentiment_scores"]:
                continue

            # Average sentiment across all mentions
            avg_sentiment = {
                "Positive": sum(s.get("Positive", 0) for s in data["sentiment_scores"])
                / len(data["sentiment_scores"]),
                "Negative": sum(s.get("Negative", 0) for s in data["sentiment_scores"])
                / len(data["sentiment_scores"]),
                "Neutral": sum(s.get("Neutral", 0) for s in data["sentiment_scores"])
                / len(data["sentiment_scores"]),
                "Mixed": sum(s.get("Mixed", 0) for s in data["sentiment_scores"])
                / len(data["sentiment_scores"]),
            }

            # Determine dominant sentiment
            dominant = max(avg_sentiment.items(), key=lambda x: x[1])[0]

            results.append(
                {
                    "entity": entity_text,
                    "types": list(
                        data["types"]
                    ),  # Convert set to list for JSON serialization
                    "mention_count": len(data["mentions"]),
                    "sentiment": avg_sentiment,
                    "dominant_sentiment": dominant,
                    "sentiment_score": avg_sentiment.get(dominant, 0),
                }
            )

        # Filter out low-quality entities with only 1 mention
        # Keep only entities with 2+ mentions OR entities with 1 mention that are high-quality types
        high_quality_results = []
        for entity in results:
            mention_count = entity["mention_count"]
            entity_types = entity["types"]
            entity_text = entity["entity"]

            # Keep entities with 2+ mentions
            if mention_count >= 2:
                high_quality_results.append(entity)
            # For entities with only 1 mention, only keep high-quality types with sufficient length
            elif mention_count == 1:
                # Skip very short entities with 1 mention (likely parsing errors)
                if len(entity_text) < 3:
                    continue
                # Skip if it's generic OTHER or ATTRIBUTE type with 1 mention
                if any(
                    t
                    in [
                        "PERSON",
                        "ORGANIZATION",
                        "BRAND",
                        "COMMERCIAL_ITEM",
                        "SOFTWARE",
                        "EVENT",
                    ]
                    for t in entity_types
                ):
                    high_quality_results.append(entity)

        # Deduplicate entities where one is a substring of another (e.g., "George" vs "George Kurtz")
        # Keep the longer, more specific version
        deduplicated_results = []
        sorted_entities = sorted(
            high_quality_results, key=lambda x: len(x["entity"]), reverse=True
        )

        for entity in sorted_entities:
            entity_text = entity["entity"]

            # Check if this entity is a substring of any already added entity
            is_substring = False
            for added_entity in deduplicated_results:
                added_text = added_entity["entity"]

                # If current entity is a single word that appears in a longer entity, skip it
                # e.g., "George" appears in "George Kurtz"
                if " " not in entity_text and entity_text in added_text.split():
                    is_substring = True
                    break

            if not is_substring:
                deduplicated_results.append(entity)

        # Sort by mention count (most mentioned first)
        deduplicated_results.sort(key=lambda x: x["mention_count"], reverse=True)

        return deduplicated_results[:20]  # Top 20 entities

    def _summarize_key_phrases(self, key_phrases):
        """
        Summarize key phrases by frequency, filtering out website navigation

        Args:
            key_phrases: List of key phrase dicts from Comprehend

        Returns:
            list: Top key phrases with counts
        """
        if not key_phrases:
            return []

        from collections import Counter

        # Phrases to filter out (Motley Fool website structure + financial boilerplate)
        filter_phrases = {
            # Motley Fool platform
            "accessibility menu",
            "stock advisor",
            "epic plus",
            "fool portfolios",
            "motley fool money",
            "rule breaker investing",
            "the motley fool foundation",
            "stock market news",
            "market movers",
            "tech stock news",
            "market trends",
            "crypto news",
            "stock market indexes",
            "biggest stock gainers",
            "biggest stock losers",
            "largest market cap companies",
            "market research",
            "breakfast news",
            "top stocks",
            "best etfs",
            "all services",
            "our services",
            "today",
            "stocks",
            "a company",
            "accessibility",
            "podcasts home",
            "consumer stock news",
            "terms of use",
            "privacy policy",
            "disclosure policy",
            # Financial/PR boilerplate
            "the press release",
            "press release",
            "a non-gaap basis",
            "non-gaap basis",
            "the company",
            "the call",
            "this call",
            "our company",
            "the quarter",
            "the year",
            "the period",
            "fiscal year",
            "current price",
            "price price",
            "angle-down",
            "change angle",
            "investor relations",
            "earnings call",
            "conference call",
            "prepared remarks",
            "question and answer",
            # SEC form boilerplate
            "the registrant",
            "check mark",
            "by check mark",
            "such shorter period",
            "the preceding",
            "the act",
            "ended july",
            "ended january",
            "ended april",
            "ended october",
            "such date",
            "the commission",
            "the securities",
            "exchange act",
            "securities act",
            "the rules",
            "item 1a",
        }

        # Extract phrase texts with score threshold
        phrase_texts = []
        for kp in key_phrases:
            text = kp.get("Text", "")
            score = kp.get("Score", 0)

            # Higher score threshold
            if score <= 0.85:
                continue

            # Filter out noise phrases
            if text.lower() in filter_phrases:
                continue

            # Filter out very short phrases
            if len(text.split()) < 2:
                continue

            # Filter out phrases with numbers/percentages (likely stock prices)
            if any(char in text for char in ["%", "+", "-", "$"]) and any(
                char.isdigit() for char in text
            ):
                continue

            # Filter out phrases with newlines (malformed multi-line extraction)
            if "\n" in text:
                continue

            # Filter out phrases with "UNITED STATES", "WASHINGTON", "COMMISSION" (SEC headers)
            sec_headers = [
                "united states",
                "washington",
                "commission file",
                "exchange commission",
                "mark one",
                "exact name",
                "state of incorporation",
                "file number",
            ]
            if any(header in text.lower() for header in sec_headers):
                continue

            # Filter out phrases that are mostly caps (likely headers/forms)
            words_in_phrase = text.split()
            caps_words = sum(1 for w in words_in_phrase if w.isupper() and len(w) > 1)
            if caps_words > len(words_in_phrase) * 0.5:  # More than 50% all-caps words
                continue

            # Filter out phrases with unusual unicode characters (like Â)
            if any(ord(c) > 127 for c in text):
                continue

            phrase_texts.append(text)

        # Count frequencies
        phrase_counts = Counter(phrase_texts)

        # Return top 20
        return [
            {"text": phrase, "count": count}
            for phrase, count in phrase_counts.most_common(20)
        ]
