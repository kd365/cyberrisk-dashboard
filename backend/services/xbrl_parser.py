"""
XBRL Parser for extracting financial data from SEC iXBRL filings

This parser extracts financial metrics directly from XBRL tags embedded in HTML filings,
which is more reliable than table scraping for structured financial data.
"""

import re
from bs4 import BeautifulSoup
from decimal import Decimal


class XBRLParser:
    """Parse XBRL/iXBRL data from SEC filings"""

    def __init__(self):
        # Common XBRL namespaces
        self.namespaces = {
            'us-gaap': 'http://fasb.org/us-gaap/',
            'dei': 'http://xbrl.sec.gov/dei/',
            'ix': 'http://www.xbrl.org/2013/inlineXBRL'
        }

        # Revenue-related XBRL tags to search for
        self.revenue_tags = [
            'Revenues',
            'RevenueFromContractWithCustomerExcludingAssessedTax',
            'RevenueFromContractWithCustomerIncludingAssessedTax',
            'SalesRevenueNet',
            'RevenueNotFromContractWithCustomer',
        ]

        # Subscription revenue tags (including common company-specific extensions)
        self.subscription_tags = [
            'RevenueFromSubscriptionServices',
            'SubscriptionRevenue',
            'SoftwareAsAServiceRevenue',
            'RecurringRevenue',
            'SubscriptionAndSupportRevenue',
            # CrowdStrike might use custom extension tags
        ]

    def parse_xbrl_contexts(self, html_content):
        """
        Parse XBRL context definitions from the filing

        Contexts define the dimensions/axes for facts, including:
        - Time periods (startDate, endDate, instant)
        - Entity identifiers
        - Segment dimensions (e.g., ProductOrServiceAxis with SubscriptionAndCirculationMember)

        Args:
            html_content: Raw HTML content from SEC filing

        Returns:
            dict: Mapping of context IDs to their metadata
        """
        soup = BeautifulSoup(html_content, 'lxml')
        contexts = {}

        # Find all context elements in the XBRL instance
        context_elements = soup.find_all('xbrli:context') or soup.find_all('context')

        for ctx in context_elements:
            ctx_id = ctx.get('id', '')
            if not ctx_id:
                continue

            context_info = {
                'id': ctx_id,
                'period': {},
                'entity': None,
                'dimensions': {}
            }

            # Parse period information
            period = ctx.find('xbrli:period') or ctx.find('period')
            if period:
                start_date = period.find('xbrli:startdate') or period.find('startdate')
                end_date = period.find('xbrli:enddate') or period.find('enddate')
                instant = period.find('xbrli:instant') or period.find('instant')

                if start_date and end_date:
                    context_info['period'] = {
                        'type': 'duration',
                        'start': start_date.get_text(strip=True),
                        'end': end_date.get_text(strip=True)
                    }
                elif instant:
                    context_info['period'] = {
                        'type': 'instant',
                        'date': instant.get_text(strip=True)
                    }

            # Parse segment dimensions (this is where SubscriptionAndCirculationMember lives)
            segment = ctx.find('xbrli:segment') or ctx.find('segment')
            if segment:
                # Find all explicit members (dimension values)
                members = segment.find_all('xbrldi:explicitmember') or segment.find_all('explicitmember')
                for member in members:
                    dimension = member.get('dimension', '')
                    member_value = member.get_text(strip=True)

                    # Extract local names
                    dim_local = dimension.split(':')[-1] if ':' in dimension else dimension
                    member_local = member_value.split(':')[-1] if ':' in member_value else member_value

                    context_info['dimensions'][dim_local] = member_local

            contexts[ctx_id] = context_info

        return contexts

    def extract_xbrl_facts(self, html_content):
        """
        Extract all XBRL facts from iXBRL HTML content

        Args:
            html_content: Raw HTML content from SEC filing

        Returns:
            dict: Extracted financial facts with contexts
        """
        soup = BeautifulSoup(html_content, 'lxml')

        facts = {
            'revenue': [],
            'subscription_revenue': [],
            'contexts': {},
            'units': {}
        }

        # Parse contexts first to understand dimensions
        contexts = self.parse_xbrl_contexts(html_content)
        facts['contexts'] = contexts

        # Find all inline XBRL elements (ix:nonFraction, ix:nonNumeric, etc.)
        # Modern SEC filings use inline XBRL tags
        xbrl_elements = soup.find_all(['ix:nonfraction', 'ix:nonnumeric', 'span', 'td', 'div'])

        for elem in xbrl_elements:
            # Check if element has XBRL attributes
            elem_name = elem.get('name', '')
            context_ref = elem.get('contextref', '')
            unit_ref = elem.get('unitref', '')
            decimals = elem.get('decimals', '')
            scale = elem.get('scale', '')

            if not elem_name:
                continue

            # Extract the local name (remove namespace prefix)
            local_name = elem_name.split(':')[-1] if ':' in elem_name else elem_name

            # Get the value
            value_text = elem.get_text(strip=True)
            if not value_text:
                continue

            # Try to parse as number
            try:
                # Remove formatting
                cleaned = value_text.replace(',', '').replace('$', '').replace(' ', '').strip()

                # Handle parentheses (negative)
                is_negative = False
                if cleaned.startswith('(') and cleaned.endswith(')'):
                    is_negative = True
                    cleaned = cleaned[1:-1]

                # Handle dashes
                if cleaned in ['-', '—', '–', '']:
                    value = 0
                else:
                    value = float(cleaned)
                    if is_negative:
                        value = -value

                # Apply scale if specified (e.g., scale="6" means millions)
                if scale:
                    try:
                        scale_factor = int(scale)
                        value = value * (10 ** scale_factor)
                    except ValueError:
                        pass

                # Get context information to check for subscription dimension
                context_info = contexts.get(context_ref, {})
                dimensions = context_info.get('dimensions', {})

                # Check if this fact has a subscription-related dimension
                is_subscription_dimension = any(
                    'subscription' in dim.lower() or 'subscription' in member.lower()
                    for dim, member in dimensions.items()
                )

                # Categorize by tag name and context dimensions
                if any(tag.lower() in local_name.lower() for tag in ['revenue', 'sales']):
                    fact_data = {
                        'name': local_name,
                        'value': value,
                        'context': context_ref,
                        'context_info': context_info,
                        'dimensions': dimensions,
                        'unit': unit_ref,
                        'scale': scale,
                        'element': elem_name
                    }

                    # If it has subscription dimension OR subscription in the tag name
                    if is_subscription_dimension or any(sub in local_name.lower() for sub in ['subscription', 'saas', 'recurring']):
                        facts['subscription_revenue'].append(fact_data)
                    else:
                        facts['revenue'].append(fact_data)

            except (ValueError, TypeError):
                continue

        return facts

    def find_subscription_revenue_by_segment(self, html_content, filing_date):
        """
        Find subscription revenue by analyzing segment/member data

        Many companies break down revenue by product/service type using segments.
        This looks for subscription-related segments.

        Args:
            html_content: Raw HTML from SEC filing
            filing_date: Date of filing

        Returns:
            float: Subscription revenue if found, None otherwise
        """
        soup = BeautifulSoup(html_content, 'lxml')

        # Look for revenue disaggregation tables
        # These often have segments like "Subscription" and "Professional Services"
        tables = soup.find_all('table')

        for table in tables:
            table_text = table.get_text().lower()

            # Check if this table discusses revenue disaggregation
            if 'subscription' in table_text and ('revenue' in table_text or 'sales' in table_text):
                rows = table.find_all('tr')

                for row in rows:
                    cells = row.find_all(['td', 'th'])
                    if len(cells) < 2:
                        continue

                    first_cell = cells[0].get_text(strip=True).lower()

                    # Look for subscription revenue row
                    # Check for exact matches to avoid "subscription cost"
                    if first_cell in ['subscription', 'subscription revenue', 'subscriptions']:
                        # Get the value from the first numeric column
                        for cell in cells[1:]:
                            # Check if cell has XBRL tags
                            xbrl_elem = cell.find(['ix:nonfraction', 'span', 'td'])
                            if xbrl_elem:
                                value_text = xbrl_elem.get_text(strip=True)
                                scale = xbrl_elem.get('scale', '')

                                try:
                                    cleaned = value_text.replace(',', '').replace('$', '').replace(' ', '').strip()

                                    # Handle negatives
                                    is_negative = False
                                    if cleaned.startswith('(') and cleaned.endswith(')'):
                                        is_negative = True
                                        cleaned = cleaned[1:-1]

                                    if cleaned in ['-', '—', '–', '']:
                                        continue

                                    value = float(cleaned)
                                    if is_negative:
                                        value = -value

                                    # Apply scale
                                    if scale:
                                        try:
                                            scale_factor = int(scale)
                                            value = value * (10 ** scale_factor)
                                        except ValueError:
                                            # Scale might be in thousands by default
                                            value = value * 1000
                                    else:
                                        # Most filings are in thousands
                                        if value < 1000000:
                                            value = value * 1000

                                    return value

                                except (ValueError, TypeError):
                                    continue

        return None

    def extract_financials_from_xbrl(self, html_content, filing_date):
        """
        Main method to extract financial metrics using XBRL parsing

        Args:
            html_content: Raw HTML from SEC filing
            filing_date: Date of filing

        Returns:
            dict: Financial metrics
        """
        print(f"  🔍 Parsing XBRL tags from filing...")

        financials = {
            'date': filing_date,
            'revenue': None,
            'subscription_revenue': None,
            'net_income': None,
            'operating_income': None,
            'eps': None,
        }

        # Try XBRL fact extraction
        facts = self.extract_xbrl_facts(html_content)

        # Filter facts to only include the most recent period
        # (SEC filings often include comparative periods - current quarter vs prior year)
        def filter_most_recent_period(fact_list):
            """Filter to facts from the most recent time period"""
            if not fact_list:
                return []

            # Get all unique periods
            periods = {}
            for fact in fact_list:
                context_info = fact.get('context_info', {})
                period = context_info.get('period', {})
                if period.get('type') == 'duration' and period.get('end'):
                    end_date = period['end']
                    if end_date not in periods:
                        periods[end_date] = []
                    periods[end_date].append(fact)

            if not periods:
                # If no period filtering possible, return all
                return fact_list

            # Get the most recent end date
            most_recent_date = max(periods.keys())
            return periods[most_recent_date]

        # Find total revenue (filter to most recent period)
        if facts['revenue']:
            recent_revenue_facts = filter_most_recent_period(facts['revenue'])

            # For total revenue, we want facts WITHOUT dimension breakdowns
            # (dimension breakdowns are for segments like subscription vs professional services)
            total_revenue_facts = [
                f for f in recent_revenue_facts
                if not f.get('dimensions', {})  # No dimensions = total revenue
            ]

            if total_revenue_facts:
                # Get the highest value (most likely to be total)
                revenue_facts = sorted(total_revenue_facts, key=lambda x: x['value'], reverse=True)
                financials['revenue'] = revenue_facts[0]['value']
                print(f"     ✅ Found total revenue from XBRL: ${financials['revenue']:,.0f}")
                print(f"        Context: {revenue_facts[0].get('context')}")

        # Find subscription revenue (filter to most recent period)
        if facts['subscription_revenue']:
            recent_sub_facts = filter_most_recent_period(facts['subscription_revenue'])

            if recent_sub_facts:
                # Get subscription revenue (should have dimension or tag indicating subscription)
                sub_facts = sorted(recent_sub_facts, key=lambda x: x['value'], reverse=True)
                financials['subscription_revenue'] = sub_facts[0]['value']

                dimensions = sub_facts[0].get('dimensions', {})
                dim_str = ', '.join([f"{k}={v}" for k, v in dimensions.items()]) if dimensions else "tag-based"

                print(f"     ✅ Found subscription revenue from XBRL: ${financials['subscription_revenue']:,.0f}")
                print(f"        Dimension: {dim_str}")
                print(f"        Context: {sub_facts[0].get('context')}")

        # If no subscription revenue found via tags, try segment analysis
        if not financials['subscription_revenue']:
            subscription_from_segment = self.find_subscription_revenue_by_segment(html_content, filing_date)
            if subscription_from_segment:
                financials['subscription_revenue'] = subscription_from_segment
                print(f"     ✅ Found subscription revenue from segment table: ${subscription_from_segment:,.0f}")

        return financials
