# =============================================================================
# OCR Service - Enhanced PDF Text Extraction
# =============================================================================
#
# This service provides high-quality text extraction from PDF documents
# using Unstructured.io for OCR processing. Based on the municipal-ai
# project's proven approach.
#
# Features:
#   - OCR-based extraction for scanned/image PDFs
#   - Fast extraction mode for text-based PDFs
#   - Text cleaning to remove common OCR artifacts
#   - S3 integration for document retrieval
#   - Caching to avoid re-processing
#
# =============================================================================

import os
import re
import logging
import tempfile
import hashlib
from typing import Optional, Dict, Tuple
from datetime import datetime

import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)


class OCRService:
    """
    Enhanced PDF text extraction service using Unstructured.io.

    Provides both OCR-based extraction (for scanned documents) and
    fast extraction (for text-based PDFs). Includes comprehensive
    text cleaning to improve downstream NLP quality.
    """

    # Common artifacts to filter from extracted text
    PDF_ARTIFACTS = {
        # PDF internal structure
        "obj", "endobj", "stream", "endstream", "xref", "trailer",
        "startxref", "flatedecode", "devicergb", "devicegray", "devicecmyk",
        # XBRL/SEC artifacts
        "xmlns", "xbrli", "xsi", "dei", "fasb", "us-gaap", "gaap",
        "iso4217", "srt", "country",
        # HTML/CSS artifacts
        "colspan", "rowspan", "thead", "tbody", "cellpadding", "cellspacing",
        "bgcolor", "valign", "nowrap",
    }

    # Patterns that indicate garbage text (often from malformed extraction)
    GARBAGE_PATTERNS = [
        r'^[A-Fa-f0-9]{32,}$',  # Long hex strings
        r'^\d+\s+\d+\s+obj$',    # PDF object references
        r'^<<.*>>$',             # PDF dictionary markers
        r'^\s*[<>]+\s*$',        # Lone angle brackets
    ]

    def __init__(self):
        """Initialize the OCR service."""
        self.region = os.environ.get("AWS_REGION", "us-west-2")
        self.bucket = os.environ.get("ARTIFACTS_BUCKET", "cyber-risk-artifacts")

        # Initialize S3 client
        config = Config(
            region_name=self.region,
            retries={"max_attempts": 3, "mode": "adaptive"}
        )
        self.s3 = boto3.client("s3", config=config)

        # Cache directory for processed documents
        self.cache_dir = os.environ.get("OCR_CACHE_DIR", "/tmp/ocr_cache")
        os.makedirs(self.cache_dir, exist_ok=True)

        # Track if unstructured is available
        self._unstructured_available = None
        self._pymupdf_available = None

    @property
    def unstructured_available(self) -> bool:
        """Check if unstructured library is available."""
        if self._unstructured_available is None:
            try:
                from unstructured.partition.pdf import partition_pdf
                self._unstructured_available = True
            except ImportError:
                logger.warning("unstructured library not available - OCR will be limited")
                self._unstructured_available = False
        return self._unstructured_available

    @property
    def pymupdf_available(self) -> bool:
        """Check if PyMuPDF (fitz) is available for fast extraction."""
        if self._pymupdf_available is None:
            try:
                import fitz
                self._pymupdf_available = True
            except ImportError:
                logger.info("PyMuPDF not available - using fallback extraction")
                self._pymupdf_available = False
        return self._pymupdf_available

    # =========================================================================
    # Main Extraction Methods
    # =========================================================================

    def extract_text_from_s3(
        self,
        s3_key: str,
        use_ocr: bool = True,
        use_cache: bool = True
    ) -> Optional[str]:
        """
        Extract text from a PDF stored in S3.

        Args:
            s3_key: S3 key of the PDF document
            use_ocr: Whether to use OCR (slower but better for scanned docs)
            use_cache: Whether to use/update the local cache

        Returns:
            Extracted and cleaned text, or None if extraction fails
        """
        # Check cache first
        if use_cache:
            cached = self._get_cached_text(s3_key)
            if cached:
                logger.info(f"Using cached text for {s3_key}")
                return cached

        # Download from S3 to temp file
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp_path = tmp.name
                logger.info(f"Downloading {s3_key} from S3...")
                self.s3.download_file(self.bucket, s3_key, tmp_path)
        except Exception as e:
            logger.error(f"Failed to download {s3_key} from S3: {e}")
            return None

        try:
            # Extract text
            if use_ocr and self.unstructured_available:
                text = self._extract_with_unstructured(tmp_path)
            elif self.pymupdf_available:
                text = self._extract_with_pymupdf(tmp_path)
            else:
                text = self._extract_with_pypdf2(tmp_path)

            if text:
                # Clean the extracted text
                text = self.clean_text(text)

                # Cache the result
                if use_cache and text:
                    self._cache_text(s3_key, text)

            return text

        finally:
            # Cleanup temp file
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    def extract_text_from_file(
        self,
        file_path: str,
        use_ocr: bool = True
    ) -> Optional[str]:
        """
        Extract text from a local PDF file.

        Args:
            file_path: Path to the PDF file
            use_ocr: Whether to use OCR extraction

        Returns:
            Extracted and cleaned text
        """
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            return None

        if use_ocr and self.unstructured_available:
            text = self._extract_with_unstructured(file_path)
        elif self.pymupdf_available:
            text = self._extract_with_pymupdf(file_path)
        else:
            text = self._extract_with_pypdf2(file_path)

        if text:
            text = self.clean_text(text)

        return text

    # =========================================================================
    # Extraction Implementations
    # =========================================================================

    def _extract_with_unstructured(self, file_path: str) -> Optional[str]:
        """
        Extract text using Unstructured.io with OCR.

        This is the highest quality extraction method, especially for
        scanned documents or PDFs with complex layouts.
        """
        try:
            from unstructured.partition.pdf import partition_pdf

            logger.info(f"Extracting with Unstructured OCR: {file_path}")

            # Use OCR strategy for best results
            elements = partition_pdf(
                filename=file_path,
                strategy="ocr_only"
            )

            # Join all elements with double newlines to preserve structure
            text = "\n\n".join([str(el) for el in elements])

            logger.info(f"Unstructured extracted {len(text):,} characters")
            return text

        except Exception as e:
            logger.error(f"Unstructured extraction failed: {e}")
            return None

    def _extract_with_pymupdf(self, file_path: str) -> Optional[str]:
        """
        Fast text extraction using PyMuPDF (fitz).

        Best for text-based PDFs where OCR is not needed.
        """
        try:
            import fitz

            logger.info(f"Extracting with PyMuPDF: {file_path}")

            doc = fitz.open(file_path)
            text_parts = []

            for page_num in range(len(doc)):
                page = doc[page_num]
                text_parts.append(page.get_text())

            doc.close()

            text = "\n\n".join(text_parts)
            logger.info(f"PyMuPDF extracted {len(text):,} characters")
            return text

        except Exception as e:
            logger.error(f"PyMuPDF extraction failed: {e}")
            return None

    def _extract_with_pypdf2(self, file_path: str) -> Optional[str]:
        """
        Fallback extraction using PyPDF2.

        Less reliable but has no additional dependencies.
        """
        try:
            from PyPDF2 import PdfReader

            logger.info(f"Extracting with PyPDF2: {file_path}")

            reader = PdfReader(file_path)
            text_parts = []

            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)

            text = "\n\n".join(text_parts)
            logger.info(f"PyPDF2 extracted {len(text):,} characters")
            return text

        except Exception as e:
            logger.error(f"PyPDF2 extraction failed: {e}")
            return None

    # =========================================================================
    # Text Cleaning
    # =========================================================================

    def clean_text(self, text: str) -> str:
        """
        Clean extracted text to improve NLP quality.

        Removes common OCR artifacts, fixes spacing issues, and
        filters out garbage content.

        Args:
            text: Raw extracted text

        Returns:
            Cleaned text
        """
        if not text:
            return ""

        # Step 1: Fix hyphenated words across line breaks
        # Example: "cyber-\nsecurity" -> "cybersecurity"
        text = re.sub(r'(\w)-\s*\n\s*(\w)', r'\1\2', text)

        # Step 2: Fix missing spaces between CamelCase words
        # Example: "CrowdStrikeAnnounces" -> "CrowdStrike Announces"
        text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)

        # Step 3: Fix spacing around section numbers
        # Example: "9.52.180Code" -> "9.52.180 Code"
        text = re.sub(r'(\d+\.\d+\.?\d*)([A-Za-z])', r'\1 \2', text)

        # Step 4: Remove PDF artifact keywords
        for artifact in self.PDF_ARTIFACTS:
            # Case-insensitive removal of standalone artifacts
            text = re.sub(rf'\b{artifact}\b', '', text, flags=re.IGNORECASE)

        # Step 5: Remove garbage lines matching patterns
        lines = text.split('\n')
        clean_lines = []
        for line in lines:
            line_stripped = line.strip()

            # Skip empty lines (we'll normalize spacing later)
            if not line_stripped:
                clean_lines.append('')
                continue

            # Skip garbage pattern matches
            is_garbage = False
            for pattern in self.GARBAGE_PATTERNS:
                if re.match(pattern, line_stripped):
                    is_garbage = True
                    break

            if not is_garbage:
                clean_lines.append(line)

        text = '\n'.join(clean_lines)

        # Step 6: Normalize whitespace
        # Replace multiple spaces with single space
        text = re.sub(r'[ \t]+', ' ', text)
        # Replace 3+ newlines with double newline (preserve paragraph breaks)
        text = re.sub(r'\n{3,}', '\n\n', text)

        # Step 7: Remove lines that are just numbers or punctuation
        lines = text.split('\n')
        clean_lines = [
            line for line in lines
            if not re.match(r'^[\d\s\-\.\,\;\:]+$', line.strip())
            or len(line.strip()) > 20  # Keep if it's a substantial number line
        ]
        text = '\n'.join(clean_lines)

        # Final trim
        text = text.strip()

        return text

    def clean_for_comprehend(self, text: str, max_bytes: int = 4900) -> str:
        """
        Additional cleaning optimized for AWS Comprehend.

        Comprehend has specific requirements:
        - Max 5000 bytes per request (we use 4900 for safety)
        - Works best with clean, natural language text

        Args:
            text: Pre-cleaned text
            max_bytes: Maximum byte size

        Returns:
            Comprehend-optimized text chunk
        """
        # Remove any remaining XBRL-style tags
        text = re.sub(r'<[^>]+>', ' ', text)

        # Remove URLs (often noisy in SEC filings)
        text = re.sub(r'https?://\S+', '', text)

        # Remove email addresses
        text = re.sub(r'\S+@\S+\.\S+', '', text)

        # Collapse whitespace again after removals
        text = re.sub(r'\s+', ' ', text).strip()

        # Truncate to max bytes if needed
        if len(text.encode('utf-8')) > max_bytes:
            # Encode, truncate, decode safely
            encoded = text.encode('utf-8')[:max_bytes]
            text = encoded.decode('utf-8', errors='ignore')
            # Try to end at a sentence boundary
            last_period = text.rfind('.')
            if last_period > max_bytes * 0.8:  # At least 80% of content
                text = text[:last_period + 1]

        return text

    # =========================================================================
    # Caching
    # =========================================================================

    def _get_cache_key(self, s3_key: str) -> str:
        """Generate a cache filename from S3 key."""
        # Use hash to create safe filename
        key_hash = hashlib.md5(s3_key.encode()).hexdigest()
        return os.path.join(self.cache_dir, f"{key_hash}.txt")

    def _get_cached_text(self, s3_key: str) -> Optional[str]:
        """Retrieve cached text if available."""
        cache_path = self._get_cache_key(s3_key)

        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception as e:
                logger.warning(f"Cache read failed: {e}")

        return None

    def _cache_text(self, s3_key: str, text: str) -> None:
        """Save extracted text to cache."""
        cache_path = self._get_cache_key(s3_key)

        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                f.write(text)
            logger.debug(f"Cached text for {s3_key}")
        except Exception as e:
            logger.warning(f"Cache write failed: {e}")

    def clear_cache(self, s3_key: Optional[str] = None) -> int:
        """
        Clear cached extractions.

        Args:
            s3_key: If provided, clear only this document's cache.
                   If None, clear entire cache.

        Returns:
            Number of cache files removed
        """
        count = 0

        if s3_key:
            cache_path = self._get_cache_key(s3_key)
            if os.path.exists(cache_path):
                os.unlink(cache_path)
                count = 1
        else:
            for filename in os.listdir(self.cache_dir):
                if filename.endswith('.txt'):
                    os.unlink(os.path.join(self.cache_dir, filename))
                    count += 1

        logger.info(f"Cleared {count} cached files")
        return count

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def get_extraction_stats(self, text: str) -> Dict:
        """
        Get statistics about extracted text quality.

        Useful for monitoring extraction quality.
        """
        if not text:
            return {"error": "No text provided"}

        lines = text.split('\n')
        words = text.split()

        # Count potential issues
        short_lines = sum(1 for line in lines if 0 < len(line.strip()) < 10)
        numeric_lines = sum(
            1 for line in lines
            if line.strip() and re.match(r'^[\d\s\-\.\,]+$', line.strip())
        )

        return {
            "total_characters": len(text),
            "total_words": len(words),
            "total_lines": len(lines),
            "non_empty_lines": sum(1 for line in lines if line.strip()),
            "short_lines": short_lines,
            "numeric_only_lines": numeric_lines,
            "avg_line_length": len(text) / max(len(lines), 1),
            "avg_word_length": sum(len(w) for w in words) / max(len(words), 1),
        }

    def is_text_quality_acceptable(
        self,
        text: str,
        min_words: int = 100,
        max_short_line_ratio: float = 0.5
    ) -> Tuple[bool, str]:
        """
        Check if extracted text meets quality thresholds.

        Args:
            text: Extracted text to check
            min_words: Minimum word count
            max_short_line_ratio: Maximum ratio of short lines

        Returns:
            Tuple of (is_acceptable, reason)
        """
        stats = self.get_extraction_stats(text)

        if stats.get("error"):
            return False, stats["error"]

        if stats["total_words"] < min_words:
            return False, f"Too few words: {stats['total_words']} < {min_words}"

        non_empty = stats["non_empty_lines"]
        if non_empty > 0:
            short_ratio = stats["short_lines"] / non_empty
            if short_ratio > max_short_line_ratio:
                return False, f"Too many short lines: {short_ratio:.1%} > {max_short_line_ratio:.1%}"

        return True, "OK"


# =============================================================================
# Singleton Instance
# =============================================================================

_ocr_service = None


def get_ocr_service() -> OCRService:
    """Get or create OCR service singleton."""
    global _ocr_service
    if _ocr_service is None:
        _ocr_service = OCRService()
    return _ocr_service
