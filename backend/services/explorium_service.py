"""
Explorium API Service

Provides access to:
- Company data (employee counts, firmographics)
- Workforce trends by department
- Business events (hiring trends, funding, growth)

API Documentation: https://developers.explorium.ai/
"""

import os
import re
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
import json
import hashlib


class ExploriumCache:
    """Simple in-memory cache with TTL for Explorium API responses"""

    def __init__(self, ttl_seconds: int = 3600):
        self.ttl = ttl_seconds
        self._cache = {}
        self._timestamps = {}

    def _make_key(self, endpoint: str, data: Optional[Dict] = None) -> str:
        """Create a cache key from endpoint and query data"""
        key_str = endpoint
        if data:
            key_str += json.dumps(data, sort_keys=True)
        return hashlib.md5(key_str.encode()).hexdigest()

    def get(self, endpoint: str, data: Optional[Dict] = None) -> Optional[Any]:
        """Get cached response if valid"""
        key = self._make_key(endpoint, data)
        if key in self._cache:
            timestamp = self._timestamps.get(key, 0)
            if (datetime.now().timestamp() - timestamp) < self.ttl:
                print(f"  [Cache] Hit for {endpoint}")
                return self._cache[key]
            else:
                del self._cache[key]
                del self._timestamps[key]
        return None

    def set(self, endpoint: str, data: Optional[Dict], response: Any):
        """Cache a response"""
        key = self._make_key(endpoint, data)
        self._cache[key] = response
        self._timestamps[key] = datetime.now().timestamp()

    def clear(self):
        """Clear all cached data"""
        self._cache.clear()
        self._timestamps.clear()


class ExploriumService:
    """Service for interacting with Explorium APIs"""

    BASE_URL = "https://api.explorium.ai/v1"

    def __init__(self, api_key: Optional[str] = None, cache_ttl: int = 3600):
        """
        Initialize Explorium service

        Args:
            api_key: Explorium API key. If not provided, reads from
                     EXPLORIUM_API_KEY environment variable
            cache_ttl: Cache time-to-live in seconds (default 1 hour)
        """
        self.api_key = api_key or os.environ.get('EXPLORIUM_API_KEY')
        if not self.api_key:
            print("Warning: EXPLORIUM_API_KEY not set. Explorium features will be disabled.")

        self.headers = {
            'Content-Type': 'application/json',
            'api_key': self.api_key or ''
        }

        self._cache = ExploriumCache(ttl_seconds=cache_ttl)

    def _make_request(self, endpoint: str, method: str = 'POST',
                      data: Optional[Dict] = None,
                      params: Optional[Dict] = None,
                      use_cache: bool = True) -> Optional[Dict]:
        """Make an API request to Explorium with caching"""
        if not self.api_key:
            return None

        cache_key_data = data or params
        if use_cache:
            cached = self._cache.get(endpoint, cache_key_data)
            if cached is not None:
                return cached

        url = f"{self.BASE_URL}/{endpoint}"

        try:
            if method == 'GET':
                response = requests.get(url, headers=self.headers, params=params, timeout=30)
            elif method == 'POST':
                response = requests.post(url, headers=self.headers, json=data, timeout=30)
            else:
                raise ValueError(f"Unsupported method: {method}")

            response.raise_for_status()
            result = response.json()

            if use_cache and result:
                self._cache.set(endpoint, cache_key_data, result)

            return result

        except requests.exceptions.HTTPError as e:
            print(f"Explorium API error: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"   Response: {e.response.text[:500]}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"Request error: {e}")
            return None

    # =========================================================================
    # Company Match & Fetch APIs
    # =========================================================================

    def match_business(self, company_name: str = None, domain: str = None,
                       ticker: str = None) -> Optional[Dict]:
        """
        Match a business by name and domain to get Explorium ID

        Args:
            company_name: Company name (e.g., "CrowdStrike")
            domain: Company domain (e.g., "crowdstrike.com")
            ticker: Stock ticker - used to lookup domain from TICKER_TO_DOMAIN

        Returns:
            Matched business data with explorium_business_id
        """
        endpoint = "businesses/match"

        # Build business object for matching
        business_obj = {}

        # If ticker provided, try to get domain from our mapping
        if ticker and not domain:
            domain = TICKER_TO_DOMAIN.get(ticker.upper())

        if company_name:
            business_obj["name"] = company_name
        if domain:
            business_obj["domain"] = domain

        if not business_obj:
            print(f"  [Explorium] No matching criteria provided")
            return None

        data = {
            "businesses_to_match": [business_obj]
        }

        print(f"  [Explorium] Matching: {business_obj}")
        result = self._make_request(endpoint, method='POST', data=data)

        # Handle response format: {matched_businesses: [{input: {}, business_id: "..."}]}
        if result and result.get('matched_businesses'):
            matched = result['matched_businesses']
            if len(matched) > 0 and matched[0].get('business_id'):
                return {
                    'explorium_business_id': matched[0]['business_id'],
                    'domain': business_obj.get('domain'),
                    'name': business_obj.get('name')
                }

        if result and isinstance(result, list) and len(result) > 0:
            return result[0]
        if result and result.get('results') and len(result['results']) > 0:
            return result['results'][0]
        return None

    def fetch_business(self, explorium_id: str = None, domain: str = None,
                       ticker: str = None) -> Optional[Dict]:
        """
        Fetch detailed business data using firmographics/enrich endpoint

        Args:
            explorium_id: Explorium business ID
            domain: Company domain
            ticker: Stock ticker (used to lookup domain)

        Returns:
            Detailed business data including employee count, industry, etc.
        """
        # If we have explorium_id, use firmographics enrich
        if explorium_id:
            endpoint = "businesses/firmographics/enrich"
            data = {
                "business_id": explorium_id
            }

            print(f"  [Explorium] Enriching firmographics for: {explorium_id}")
            result = self._make_request(endpoint, method='POST', data=data)

            if result and result.get('data'):
                return result['data']

        # If no explorium_id, first match by domain then enrich
        if domain or ticker:
            if not domain and ticker:
                domain = TICKER_TO_DOMAIN.get(ticker.upper(), f"{ticker.lower()}.com")

            match = self.match_business(domain=domain)
            if match and match.get('explorium_business_id'):
                return self.fetch_business(explorium_id=match['explorium_business_id'])

        return None

    def get_business_by_ticker(self, ticker: str) -> Optional[Dict]:
        """
        Get business data by stock ticker

        Args:
            ticker: Stock ticker symbol (e.g., "CRWD")

        Returns:
            Business data dict
        """
        # Get domain from our mapping
        domain = TICKER_TO_DOMAIN.get(ticker.upper())

        if not domain:
            print(f"  [Explorium] No domain mapping for ticker: {ticker}")
            # Try guessing domain
            domain = f"{ticker.lower()}.com"

        # Try to match by domain
        match = self.match_business(domain=domain)
        if match:
            explorium_id = match.get('explorium_business_id')
            if explorium_id:
                business = self.fetch_business(explorium_id=explorium_id)
                if business:
                    return business

            # If match returned data directly, use it
            if match.get('company_name') or match.get('name'):
                return match

        # Fallback to direct fetch by domain
        return self.fetch_business(domain=domain)

    # =========================================================================
    # Workforce Trends API
    # =========================================================================

    def get_workforce_trends(self, explorium_id: str = None,
                             domain: str = None) -> Optional[Dict]:
        """
        Get workforce trends by department for a company

        Args:
            explorium_id: Explorium business ID
            domain: Company domain

        Returns:
            Workforce trends data including department breakdown
        """
        endpoint = "businesses/workforce_trends/enrich"

        # API expects business_id directly
        data = {}
        if explorium_id:
            data["business_id"] = explorium_id

        if not data:
            print("  [Explorium] No business_id for workforce trends")
            return None

        print(f"  [Explorium] Getting workforce trends for: {explorium_id}")
        result = self._make_request(endpoint, method='POST', data=data)

        # Response format: {data: {...}, entity_id: "...", response_context: {...}}
        if result and result.get('data'):
            return result['data']
        return None

    # =========================================================================
    # Business Events API
    # =========================================================================

    def get_business_events(self, explorium_id: str = None,
                            domain: str = None,
                            days_back: int = 90) -> Optional[List[Dict]]:
        """
        Get recent business events (hiring, funding, etc.)

        Args:
            explorium_id: Explorium business ID
            domain: Company domain
            days_back: How many days back to look (max 90)

        Returns:
            List of business events
        """
        endpoint = "businesses/events"

        if not explorium_id:
            print("  [Explorium] No business_id for events")
            return []

        # Event types to fetch - all hiring and growth related
        event_types = [
            "hiring_in_engineering_department",
            "hiring_in_sales_department",
            "hiring_in_marketing_department",
            "hiring_in_operations_department",
            "hiring_in_finance_department",
            "hiring_in_human_resources_department",
            "hiring_in_support_department",
            "increase_in_all_departments",
            "decrease_in_all_departments",
            "new_funding_round",
            "new_product",
            "new_office"
        ]

        data = {
            "business_ids": [explorium_id],
            "event_types": event_types
        }

        print(f"  [Explorium] Getting events for: {explorium_id}")
        result = self._make_request(endpoint, method='POST', data=data)

        # Response format: {output_events: [...], response_context: {...}}
        if result and result.get('output_events'):
            return result['output_events']
        return []

    # =========================================================================
    # Aggregated Company Growth Analysis
    # =========================================================================

    def get_company_growth_analysis(self, ticker: str) -> Dict[str, Any]:
        """
        Get comprehensive company growth analysis

        Args:
            ticker: Stock ticker symbol

        Returns:
            Comprehensive growth metrics
        """
        print(f"[Explorium] Fetching data for: {ticker}")

        result = {
            'company': None,
            'employee_count': None,
            'headcount_history': [],
            'job_velocity': {},
            'tenure_stats': {},
            'workforce_trends': {},
            'recent_events': [],
            'data_freshness': datetime.now().isoformat()
        }

        # Get company data
        business = self.get_business_by_ticker(ticker)
        if business:
            # Extract company info from firmographics response format
            city = business.get('city_name', '')
            region = business.get('region_name', '')
            country = business.get('country_name', '')
            headquarters = ', '.join(filter(None, [city, region, country]))

            result['company'] = {
                'name': business.get('name', business.get('company_name')),
                'industry': business.get('linkedin_industry_category', business.get('naics_description')),
                'founded': business.get('year_founded', business.get('founded_year')),
                'headquarters': headquarters if headquarters else business.get('headquarters'),
                'website': business.get('website', business.get('domain')),
                'description': (business.get('business_description', '') or '')[:500]
            }
            # Employee count comes as range like "10001+" or "1001-5000"
            emp_range = business.get('number_of_employees_range', '')
            if emp_range:
                # Extract first number from range
                match = re.search(r'(\d+)', emp_range.replace(',', ''))
                result['employee_count'] = int(match.group(1)) if match else None
            else:
                result['employee_count'] = business.get('number_of_employees',
                                                         business.get('employee_count'))

            explorium_id = business.get('business_id', business.get('explorium_business_id'))
            domain = business.get('website', business.get('domain'))
            if domain:
                # Clean up domain (remove https:// and www.)
                domain = domain.replace('https://', '').replace('http://', '').replace('www.', '').rstrip('/')

            # Get workforce trends
            if explorium_id:
                print(f"  [Explorium] Using business_id: {explorium_id}")

                workforce = self.get_workforce_trends(explorium_id=explorium_id)
                if workforce:
                    result['workforce_trends'] = workforce

                    # Extract department breakdown from workforce trends
                    # Fields are like: perc_engineering_roles, perc_sales_roles, etc.
                    dept_breakdown = {}
                    for key, value in workforce.items():
                        if key.startswith('perc_') and value is not None:
                            # Convert perc_engineering_roles -> Engineering
                            dept_name = key.replace('perc_', '').replace('_roles', '').replace('_', ' ').title()
                            dept_breakdown[dept_name] = value
                    if dept_breakdown:
                        result['job_velocity']['by_category'] = dept_breakdown

                # Get recent events (hiring trends, etc.)
                events = self.get_business_events(explorium_id=explorium_id, days_back=90)
                if events:
                    result['recent_events'] = events

                    # Count hiring events by type
                    hiring_by_dept = {}
                    for event in events:
                        event_name = event.get('event_name', '')
                        if 'hiring' in event_name:
                            # Extract department from event name
                            dept = event_name.replace('hiring_in_', '').replace('_department', '').replace('_', ' ').title()
                            event_data = event.get('data', {})
                            job_count = event_data.get('job_count', 1)
                            hiring_by_dept[dept] = hiring_by_dept.get(dept, 0) + job_count

                    total_jobs = sum(hiring_by_dept.values())
                    result['job_velocity']['total_postings'] = total_jobs
                    result['job_velocity']['postings_per_week'] = round(total_jobs / 13, 1) if total_jobs > 0 else 0
                    result['job_velocity']['by_department'] = hiring_by_dept

                    # Determine trend from increase/decrease events
                    increases = len([e for e in events if 'increase' in e.get('event_name', '')])
                    decreases = len([e for e in events if 'decrease' in e.get('event_name', '')])

                    if increases > decreases + 2:
                        result['job_velocity']['trend'] = 'accelerating'
                    elif decreases > increases + 2:
                        result['job_velocity']['trend'] = 'decelerating'
                    elif total_jobs > 0:
                        result['job_velocity']['trend'] = 'stable'
                    else:
                        result['job_velocity']['trend'] = 'unknown'
            else:
                print("  [Explorium] No business_id found, skipping trends/events")

        # Set defaults if no data
        if not result['job_velocity']:
            result['job_velocity'] = {
                'total_postings': 0,
                'postings_per_week': 0,
                'trend': 'unknown',
                'by_category': {}
            }

        if not result['tenure_stats']:
            result['tenure_stats'] = {
                'avg_tenure_months': None,
                'median_tenure_months': None,
                'sample_size': 0
            }

        return result


# Mapping of stock tickers to company domains (for fallback matching)
TICKER_TO_DOMAIN = {
    'CRWD': 'crowdstrike.com',
    'PANW': 'paloaltonetworks.com',
    'FTNT': 'fortinet.com',
    'ZS': 'zscaler.com',
    'OKTA': 'okta.com',
    'NET': 'cloudflare.com',
    'S': 'sentinelone.com',
    'CYBR': 'cyberark.com',
    'TENB': 'tenable.com',
    'VRNS': 'varonis.com',
    'RPD': 'rapid7.com',
    'QLYS': 'qualys.com',
    'MSFT': 'microsoft.com',
    'GOOGL': 'google.com',
    'AMZN': 'amazon.com',
    'META': 'meta.com',
    'AAPL': 'apple.com',
    'ATEN': 'a10networks.com',
    'CHKP': 'checkpoint.com',
    'FFIV': 'f5.com',
    'JNPR': 'juniper.net',
    'CSCO': 'cisco.com',
    'IBM': 'ibm.com',
    'AKAM': 'akamai.com',
    'SPLK': 'splunk.com',
    'DDOG': 'datadoghq.com',
}


def get_company_domain(ticker: str) -> str:
    """Get company domain for a ticker symbol"""
    return TICKER_TO_DOMAIN.get(ticker.upper(), f"{ticker.lower()}.com")
