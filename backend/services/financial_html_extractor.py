"""
Financial Data Extractor for SEC iXBRL/HTML Filings

Modern SEC filings use iXBRL (inline XBRL) format embedded in HTML.
This extractor parses HTML filings to extract financial metrics.

More reliable than PDF extraction for post-2019 filings.
"""

import boto3
import os
import re
from bs4 import BeautifulSoup
from collections import defaultdict
from botocore.exceptions import ProfileNotFound
from .xbrl_parser import XBRLParser

class FinancialHtmlExtractor:
    """Extract financial metrics from SEC HTML filings"""

    def __init__(self, aws_profile=None):
        """Initialize S3 client and XBRL parser"""
        # Use profile locally, instance role on EC2
        profile = aws_profile or os.environ.get('AWS_PROFILE', 'cyber-risk')
        try:
            session = boto3.Session(profile_name=profile)
            session.get_credentials()
            self.s3 = session.client('s3', region_name='us-east-1')
        except (ProfileNotFound, Exception):
            self.s3 = boto3.client('s3', region_name='us-east-1')
        # Use ARTIFACTS_BUCKET env var, fallback to old bucket for local dev
        self.bucket = os.environ.get('ARTIFACTS_BUCKET', 'cyber-risk-artifacts')
        self.xbrl_parser = XBRLParser()

    def extract_financials_from_html_filing(self, s3_key, filing_date=None):
        """
        Extract financial metrics from HTML SEC filing

        Args:
            s3_key: S3 key to the SEC filing (HTML or PDF)
            filing_date: Date of the filing

        Returns:
            dict: Financial metrics
        """
        print(f"📊 Extracting financials from HTML: {s3_key}")

        try:
            # Download file from S3
            response = self.s3.get_object(Bucket=self.bucket, Key=s3_key)
            content = response['Body'].read()

            # Try to decode as text
            try:
                if content.startswith(b'%PDF'):
                    print(f"  ℹ️  PDF file detected, using text extraction")
                    return self._extract_from_pdf_text(s3_key, filing_date)
                else:
                    html = content.decode('utf-8', errors='ignore')
            except Exception as e:
                print(f"  ❌ Could not decode file: {e}")
                return None

            # Parse HTML
            soup = BeautifulSoup(html, 'lxml')

            # Try XBRL parsing first (more reliable for modern SEC filings)
            print(f"  🔍 Attempting XBRL tag extraction...")
            xbrl_financials = self.xbrl_parser.extract_financials_from_xbrl(html, filing_date)

            # Extract financial data from HTML tables (fallback/supplement)
            print(f"  📊 Extracting from HTML tables...")
            table_financials = self._parse_financial_from_html(soup, filing_date)

            # Merge results: prefer XBRL data when available, use table data as fallback
            financials = {
                'date': filing_date,
                'revenue': xbrl_financials.get('revenue') or table_financials.get('revenue'),
                'subscription_revenue': xbrl_financials.get('subscription_revenue') or table_financials.get('subscription_revenue'),
                'recurring_revenue': table_financials.get('recurring_revenue'),
                'net_income': xbrl_financials.get('net_income') or table_financials.get('net_income'),
                'operating_income': xbrl_financials.get('operating_income') or table_financials.get('operating_income'),
                'eps': xbrl_financials.get('eps') or table_financials.get('eps'),
                'arr': table_financials.get('arr'),
            }

            print(f"  ✅ Extracted financials (XBRL + HTML tables)")
            if financials['subscription_revenue']:
                print(f"     💡 Subscription revenue: ${financials['subscription_revenue']:,.0f}")
            return financials

        except Exception as e:
            print(f"  ❌ Error extracting financials: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _extract_from_pdf_text(self, s3_key, filing_date):
        """
        For PDF files, download and extract text using existing method
        This is a placeholder - would integrate with PDF text extraction
        """
        print(f"  ⚠️  PDF extraction not yet implemented, returning None")
        return None

    def _parse_financial_from_html(self, soup, filing_date):
        """
        Parse financial metrics from HTML soup

        Modern SEC filings have tables with financial data.
        Look for:
        - Condensed Consolidated Statements of Operations
        - Revenue tables
        """
        financials = {
            'date': filing_date,
            'revenue': None,
            'subscription_revenue': None,
            'recurring_revenue': None,
            'net_income': None,
            'operating_income': None,
            'eps': None,
            'arr': None,
        }

        # Try text-based extraction first (for filings with formatted text instead of tables)
        html_text = soup.get_text()
        text_financials = self._extract_from_text(html_text, filing_date)
        if text_financials:
            financials.update(text_financials)

        # Find all tables
        tables = soup.find_all('table')
        print(f"  ℹ️  Found {len(tables)} tables in filing")

        # Try to detect if values are in thousands or millions from table headers
        in_thousands = False
        in_millions = False

        for table in tables:
            # Check table caption/headers for scaling info
            table_text = table.get_text().lower()
            if 'in thousands' in table_text or 'except per share' in table_text:
                in_thousands = True
            if 'in millions' in table_text:
                in_millions = True

        for table in tables:
            # Extract text from table rows
            rows = table.find_all('tr')

            for row in rows:
                cells = row.find_all(['td', 'th'])
                if len(cells) < 2:
                    continue

                # First cell is usually the metric name
                metric_text = cells[0].get_text(strip=True).lower()

                # Get values from subsequent cells (usually current period is first data column)
                values = [c.get_text(strip=True) for c in cells[1:]]

                # Revenue patterns
                if any(pattern in metric_text for pattern in [
                    'total revenue', 'total net revenue', 'revenues, net',
                    'revenue:', 'total revenues'
                ]) and financials['revenue'] is None:
                    financials['revenue'] = self._parse_financial_value(values, in_thousands=in_thousands, in_millions=in_millions)

                # Subscription revenue patterns
                # IMPORTANT: Exclude "cost" rows - we want revenue, not expenses
                # Match exact "subscription" row (not "subscription cost", etc.)
                # CrowdStrike labels it as just "Subscription" in the revenue section
                if financials['subscription_revenue'] is None:
                    # Check if this is a subscription revenue row
                    is_subscription_row = (
                        metric_text in ['subscription', 'subscription revenue', 'subscription and support', 'saas revenue', 'recurring revenue']
                        or (metric_text.startswith('subscription') and 'cost' not in metric_text and 'expense' not in metric_text and 'defer' not in metric_text)
                    )

                    if is_subscription_row:
                        parsed_value = self._parse_financial_value(values, in_thousands=in_thousands, in_millions=in_millions)
                        if parsed_value and parsed_value > 0:
                            print(f"  ✅ Found subscription revenue: '{metric_text}' = ${parsed_value:,.0f}")
                            financials['subscription_revenue'] = parsed_value

                # ARR
                if any(pattern in metric_text for pattern in [
                    'annual recurring revenue', 'arr'
                ]) and financials['arr'] is None:
                    financials['arr'] = self._parse_financial_value(values, in_thousands=in_thousands, in_millions=in_millions)

                # Net Income
                if any(pattern in metric_text for pattern in [
                    'net income', 'net loss', 'net income (loss)'
                ]) and 'attributable' not in metric_text and financials['net_income'] is None:
                    financials['net_income'] = self._parse_financial_value(values, in_thousands=in_thousands, in_millions=in_millions)

                # Operating Income
                if any(pattern in metric_text for pattern in [
                    'income from operations', 'operating income (loss)',
                    'income (loss) from operations'
                ]) and financials['operating_income'] is None:
                    financials['operating_income'] = self._parse_financial_value(values, in_thousands=in_thousands, in_millions=in_millions)

                # EPS (prefer diluted)
                if any(pattern in metric_text for pattern in [
                    'diluted earnings per share', 'diluted (loss) per share',
                    'diluted net income per share', 'diluted net loss per share'
                ]) and financials['eps'] is None:
                    financials['eps'] = self._parse_financial_value(values, is_per_share=True, in_thousands=in_thousands, in_millions=in_millions)

        # NOTE: If subscription revenue wasn't found but we have total revenue,
        # some companies (like CrowdStrike) may not report it as a separate line item
        # in the condensed income statement tables in their 10-Q/10-K filings.
        # They discuss the breakdown in MD&A narrative sections.
        # For CrowdStrike specifically, subscription typically represents 94-96% of total revenue.
        # We leave it as None to indicate missing data rather than estimating.

        return financials

    def _extract_from_text(self, text, filing_date):
        """
        Extract financial data from formatted text in SEC filings

        Many modern filings have financial statements as formatted text rather than HTML tables.
        This method uses regex to find patterns like:

        Revenue
        Subscription $ 1,168,705 $ 962,735
        Professional services 65,539 47,443
        Total revenue 1,234,244 1,010,178
        """
        import re

        financials = {}

        # Look for "Revenue" section followed by "Subscription" line
        # Pattern: Revenue \n Subscription $ 1,168,705
        revenue_section_match = re.search(
            r'Revenue\s+Subscription\s+\$?\s*([\d,]+)',
            text,
            re.IGNORECASE | re.MULTILINE
        )

        if revenue_section_match:
            subscription_value_str = revenue_section_match.group(1).replace(',', '')
            try:
                subscription_value = float(subscription_value_str)
                # Values in SEC filings are typically in thousands
                subscription_value = subscription_value * 1000
                financials['subscription_revenue'] = subscription_value
                print(f"  ✅ Found subscription revenue from text: ${subscription_value:,.0f}")
            except (ValueError, TypeError):
                pass

        # Also look for total revenue
        total_revenue_match = re.search(
            r'Total revenue\s+\$?\s*([\d,]+)',
            text,
            re.IGNORECASE
        )

        if total_revenue_match:
            total_revenue_str = total_revenue_match.group(1).replace(',', '')
            try:
                total_revenue = float(total_revenue_str)
                # Values in SEC filings are typically in thousands
                total_revenue = total_revenue * 1000
                financials['revenue'] = total_revenue
            except (ValueError, TypeError):
                pass

        return financials if financials else None

    def _parse_financial_value(self, values, is_per_share=False, in_thousands=False, in_millions=False):
        """
        Parse a financial value from table cells

        Handles:
        - Dollar signs, commas, parentheses
        - Thousands/millions notation from table headers
        - Per share values

        Args:
            values: List of cell values to parse
            is_per_share: True if this is a per-share value (EPS)
            in_thousands: True if table header indicates "in thousands"
            in_millions: True if table header indicates "in millions"
        """
        if not values:
            return None

        for val in values:
            if not val:
                continue

            val = val.strip()

            # Skip headers and text
            if any(skip in val.lower() for skip in [
                'year ended', 'three months', 'six months', 'nine months',
                'december', 'january', 'february', 'march', 'april', 'may',
                'june', 'july', 'august', 'september', 'october', 'november',
                '$', 'in thousands', 'in millions'
            ]):
                # Only skip if it's purely text (no numbers)
                if not re.search(r'\d', val):
                    continue

            # Try to parse as number
            try:
                # Remove $, commas, and whitespace
                cleaned = val.replace('$', '').replace(',', '').replace(' ', '').strip()

                # Handle parentheses (negative)
                is_negative = False
                if cleaned.startswith('(') and cleaned.endswith(')'):
                    is_negative = True
                    cleaned = cleaned[1:-1]

                # Handle dash for zero
                if cleaned in ['-', '—', '–', '']:
                    return 0

                # Try to convert to float
                num = float(cleaned)

                if is_negative:
                    num = -num

                # For per-share values, return as-is (no scaling)
                if is_per_share:
                    # Per-share values are typically small (< 100)
                    # If num is very large, it's likely in thousandths
                    if num > 100:
                        return num / 1000  # Convert from thousandths to dollars
                    return num

                # Apply scaling based on table header information
                # If we detected "in thousands" or "in millions" in the table
                if in_thousands:
                    # Values are stated in thousands, multiply by 1000 to get dollars
                    return num * 1000
                elif in_millions:
                    # Values are stated in millions, multiply by 1,000,000 to get dollars
                    return num * 1000000
                else:
                    # Fallback heuristic if no table header info found
                    # - If num > 1,000,000: already in dollars (e.g., 1,234,567,000)
                    # - If num is between 100 and 1,000,000: in thousands (e.g., 1,234 = $1,234,000)
                    # - If num < 100: likely in millions (e.g., 1.5 = $1,500,000)
                    if num > 1000000:
                        return num
                    elif num >= 100:
                        return num * 1000
                    else:
                        return num * 1000000

            except (ValueError, TypeError):
                continue

        return None

    def extract_all_financials_for_ticker(self, ticker, artifacts):
        """
        Extract financial data from all SEC HTML filings for a ticker

        Args:
            ticker: Stock ticker
            artifacts: List of artifact dicts from S3

        Returns:
            list: Financial data points sorted by date
        """
        print(f"\n💰 Extracting Financial Data for {ticker} (HTML Method)")
        print("=" * 70)

        # Filter for SEC filings only
        sec_filings = [
            a for a in artifacts
            if a.get('ticker') == ticker
            and a.get('type') in ['10-K', '10-Q']
        ]

        if not sec_filings:
            print(f"  ⚠️  No SEC filings found for {ticker}")
            return []

        print(f"  📄 Found {len(sec_filings)} SEC filings")

        # Sort by date descending to get most recent filings first
        sec_filings.sort(key=lambda x: x.get('date', ''), reverse=True)

        # Extract financials from each filing
        financials_timeline = []

        for filing in sec_filings[:12]:  # Limit to most recent 12 filings (3 years of quarterly)
            s3_key = filing.get('s3_key')
            filing_date = filing.get('date')
            filing_type = filing.get('type')

            print(f"\n  📊 Processing {filing_type} from {filing_date}")

            # Extract financials
            financials = self.extract_financials_from_html_filing(s3_key, filing_date)

            if financials and any(financials.get(k) for k in ['revenue', 'net_income', 'operating_income']):
                financials['type'] = filing_type
                financials['s3_key'] = s3_key
                financials_timeline.append(financials)
            else:
                print(f"  ⚠️  No financial data extracted from {s3_key}")

        # Sort by date
        financials_timeline.sort(key=lambda x: x.get('date', ''), reverse=False)

        print(f"\n✅ Extracted financials from {len(financials_timeline)} filings")

        return financials_timeline

    def calculate_rolling_averages(self, financials_timeline, window=4):
        """
        Calculate rolling averages for financial metrics

        Args:
            financials_timeline: List of financial data points
            window: Number of quarters for rolling average (default 4 = 1 year)

        Returns:
            list: Financial data with rolling averages added
        """
        if len(financials_timeline) < window:
            print(f"  ⚠️  Not enough data for {window}-quarter rolling average")
            return financials_timeline

        metrics = ['revenue', 'subscription_revenue', 'net_income', 'operating_income']

        for i in range(window - 1, len(financials_timeline)):
            # Get last 'window' quarters
            window_data = financials_timeline[i - window + 1:i + 1]

            # Calculate rolling averages
            for metric in metrics:
                values = [d.get(metric) for d in window_data if d.get(metric) is not None]

                if values and len(values) == window:
                    avg = sum(values) / len(values)
                    financials_timeline[i][f'{metric}_rolling_avg'] = avg

        return financials_timeline
