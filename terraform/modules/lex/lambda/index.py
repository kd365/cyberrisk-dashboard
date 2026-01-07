"""
Lambda function for Lex V2 fulfillment - Cyber Risk Dashboard Assistant
Supports company CRUD operations via conversational interface
"""

import json
import os
import re
import psycopg2
from psycopg2.extras import RealDictCursor
import urllib.request
import urllib.error

# Database connection parameters from environment
DB_CONFIG = {
    'host': os.environ.get('DB_HOST'),
    'database': os.environ.get('DB_NAME'),
    'user': os.environ.get('DB_USER'),
    'password': os.environ.get('DB_PASSWORD'),
    'port': int(os.environ.get('DB_PORT', 5432))
}

# API endpoint for triggering analysis
API_BASE_URL = os.environ.get('API_BASE_URL', 'http://internal-cyberrisk-dev-kh-alb-1840593498.us-west-2.elb.amazonaws.com:5000')

# Known company mappings for entity extraction
KNOWN_COMPANIES = {
    'crowdstrike': ('CrowdStrike Holdings', 'CRWD'),
    'crwd': ('CrowdStrike Holdings', 'CRWD'),
    'palo alto': ('Palo Alto Networks', 'PANW'),
    'palo alto networks': ('Palo Alto Networks', 'PANW'),
    'panw': ('Palo Alto Networks', 'PANW'),
    'fortinet': ('Fortinet Inc', 'FTNT'),
    'ftnt': ('Fortinet Inc', 'FTNT'),
    'zscaler': ('Zscaler Inc', 'ZS'),
    'zs': ('Zscaler Inc', 'ZS'),
    'sentinelone': ('SentinelOne Inc', 'S'),
    'sentinel one': ('SentinelOne Inc', 'S'),
    'microsoft': ('Microsoft Corporation', 'MSFT'),
    'msft': ('Microsoft Corporation', 'MSFT'),
    'cisco': ('Cisco Systems', 'CSCO'),
    'csco': ('Cisco Systems', 'CSCO'),
    'okta': ('Okta Inc', 'OKTA'),
    'cloudflare': ('Cloudflare Inc', 'NET'),
    'net': ('Cloudflare Inc', 'NET'),
    'cyberark': ('CyberArk Software', 'CYBR'),
    'cybr': ('CyberArk Software', 'CYBR'),
    'qualys': ('Qualys Inc', 'QLYS'),
    'qlys': ('Qualys Inc', 'QLYS'),
}

def get_db_connection():
    """Create database connection"""
    return psycopg2.connect(**DB_CONFIG)

def call_api(endpoint, timeout=60):
    """Call the backend API and return JSON response"""
    try:
        url = f"{API_BASE_URL}{endpoint}"
        print(f"Calling API: {url}")
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode('utf-8'))
            return data
    except urllib.error.HTTPError as e:
        print(f"API HTTP Error: {e.code} - {e.reason}")
        return None
    except urllib.error.URLError as e:
        print(f"API URL Error: {e.reason}")
        return None
    except Exception as e:
        print(f"API Error: {str(e)}")
        return None

def extract_company_from_utterance(utterance):
    """
    Extract company name/ticker from user utterance
    Returns (company_name, ticker) tuple or (None, None) if not found
    """
    utterance_lower = utterance.lower()

    # Check for known companies
    for keyword, (company_name, ticker) in KNOWN_COMPANIES.items():
        if keyword in utterance_lower:
            return (company_name, ticker)

    # Try to extract ticker pattern (2-5 uppercase letters)
    ticker_match = re.search(r'\b([A-Z]{2,5})\b', utterance)
    if ticker_match:
        ticker = ticker_match.group(1)
        # Return just the ticker, caller can look up company name
        return (None, ticker)

    return (None, None)


def find_company_by_alias(search_term):
    """
    Find company by any alias using database lookup
    Returns (company_id, ticker, company_name) or (None, None, None)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # First try direct match on companies table
        cursor.execute("""
            SELECT id, ticker, company_name
            FROM companies
            WHERE LOWER(ticker) = LOWER(%s)
               OR LOWER(company_name) LIKE LOWER(%s)
        """, (search_term, f'%{search_term}%'))

        row = cursor.fetchone()
        if row:
            cursor.close()
            conn.close()
            return (row['id'], row['ticker'], row['company_name'])

        # Try alternate_names column
        cursor.execute("""
            SELECT id, ticker, company_name
            FROM companies
            WHERE LOWER(alternate_names) LIKE LOWER(%s)
        """, (f'%{search_term}%',))

        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if row:
            return (row['id'], row['ticker'], row['company_name'])
        return (None, None, None)

    except Exception as e:
        print(f"Error finding company by alias: {e}")
        return (None, None, None)

def close_response(session_attributes, fulfillment_state, message, intent_name=None):
    """Build Lex V2 response"""
    intent_obj = {
        'state': fulfillment_state
    }
    # Lex V2 requires intent name in the response
    if intent_name:
        intent_obj['name'] = intent_name

    return {
        'sessionState': {
            'sessionAttributes': session_attributes,
            'dialogAction': {
                'type': 'Close'
            },
            'intent': intent_obj
        },
        'messages': [
            {
                'contentType': 'PlainText',
                'content': message
            }
        ]
    }

def handle_welcome(event):
    """Handle welcome/help intent"""
    message = """Welcome to the Cyber Risk Dashboard Assistant! I can help you with:

- List available companies
- Get information about specific companies
- Check sentiment analysis results
- View forecast predictions
- Check document inventory (SEC filings, transcripts)
- View growth metrics and hiring trends
- Add or remove companies
- Explain dashboard features

Just ask me something like:
- "What companies are available?"
- "Tell me about CrowdStrike"
- "What documents do I have for CRWD?"
- "Show growth metrics for Palo Alto"

Tip: I understand variations like "crowdstrike", "CRWD", "crowd strike" - all map to the same company!"""

    return close_response({}, 'Fulfilled', message)

def handle_list_companies(event):
    """List all companies in the database"""
    try:
        # Check if user is asking for a count
        utterance = event.get('inputTranscript', '').lower()
        is_count_query = 'how many' in utterance or 'count' in utterance or 'number of' in utterance

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            SELECT DISTINCT company_name, ticker
            FROM companies
            ORDER BY company_name
        """)
        companies = cursor.fetchall()
        cursor.close()
        conn.close()

        if companies:
            count = len(companies)
            if is_count_query:
                message = f"The dashboard currently tracks {count} cybersecurity companies.\n\nSay 'list companies' to see the full list, or ask about a specific company like 'Tell me about CrowdStrike'."
            else:
                company_list = "\n".join([f"- {c['company_name']} ({c['ticker']})" for c in companies])
                message = f"Here are the {count} companies available in the dashboard:\n\n{company_list}\n\nAsk me about any of these companies for more details!"
        else:
            message = "No companies are currently loaded in the database. Please check the data migration status."

    except Exception as e:
        message = f"I'm having trouble accessing the database. The dashboard may still be initializing. Error: {str(e)}"

    return close_response({}, 'Fulfilled', message)

def handle_company_info(event):
    """Get information about a specific company"""
    slots = event['sessionState']['intent']['slots']
    company_name = slots.get('CompanyName', {}).get('value', {}).get('interpretedValue', '')

    if not company_name:
        return close_response({}, 'Failed', "I didn't catch the company name. Could you please specify which company you'd like information about?")

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Get company info
        cursor.execute("""
            SELECT c.company_name, c.ticker, c.sector,
                   COUNT(DISTINCT a.id) as artifact_count,
                   MIN(a.published_date) as earliest_date,
                   MAX(a.published_date) as latest_date
            FROM companies c
            LEFT JOIN artifacts a ON c.id = a.company_id
            WHERE LOWER(c.company_name) LIKE LOWER(%s)
               OR LOWER(c.ticker) = LOWER(%s)
            GROUP BY c.id, c.company_name, c.ticker, c.sector
        """, (f'%{company_name}%', company_name))

        company = cursor.fetchone()
        cursor.close()
        conn.close()

        if company:
            message = f"""Here's what I know about {company['company_name']} ({company['ticker']}):

Sector: {company['sector'] or 'Cybersecurity'}
Total Documents: {company['artifact_count']}
Data Range: {company['earliest_date']} to {company['latest_date']}

You can view detailed analysis on the dashboard including:
- SEC filings and earnings call transcripts
- Sentiment analysis using AWS Comprehend
- Stock price forecasts using Prophet

Would you like to know about sentiment or forecasts for this company?"""
        else:
            message = f"I couldn't find a company matching '{company_name}'. Try asking me to list all available companies."

    except Exception as e:
        message = f"I encountered an error looking up that company: {str(e)}"

    return close_response({}, 'Fulfilled', message)

def handle_sentiment_analysis(event):
    """Get sentiment analysis for a company - triggers analysis via API if not cached"""
    # Try to get company from slots first
    slots = event['sessionState']['intent']['slots'] or {}
    company_name = None
    ticker = None

    if slots.get('CompanyName'):
        company_name = slots['CompanyName'].get('value', {}).get('interpretedValue', '')

    # If no slot, extract from utterance
    if not company_name:
        utterance = event.get('inputTranscript', '')
        extracted_name, extracted_ticker = extract_company_from_utterance(utterance)
        if extracted_ticker:
            company_name = extracted_ticker
            ticker = extracted_ticker
        elif extracted_name:
            company_name = extracted_name

    if not company_name:
        return close_response({}, 'Failed', "Which company would you like sentiment analysis for? Try saying 'sentiment for CrowdStrike' or 'sentiment for CRWD'.")

    # Look up the ticker if we don't have it
    if not ticker:
        company_id, db_ticker, db_company_name = find_company_by_alias(company_name)
        if db_ticker:
            ticker = db_ticker
            company_name = db_company_name
        else:
            # Use the company name as ticker (might work for some)
            ticker = company_name.upper()

    # Call the sentiment API - this will trigger analysis if not cached
    print(f"Fetching sentiment for ticker: {ticker}")
    sentiment_data = call_api(f"/api/sentiment/{ticker}")

    if sentiment_data and 'error' not in sentiment_data:
        # Successfully got sentiment data - parse actual API response structure
        overall = sentiment_data.get('overall', {})
        overall_sentiment = overall.get('sentiment', {})

        # Determine dominant sentiment
        sentiment_scores = {
            'Positive': overall_sentiment.get('Positive', 0),
            'Negative': overall_sentiment.get('Negative', 0),
            'Neutral': overall_sentiment.get('Neutral', 0),
            'Mixed': overall_sentiment.get('Mixed', 0)
        }
        sentiment_label = max(sentiment_scores, key=sentiment_scores.get)
        confidence = sentiment_scores[sentiment_label]

        # Get document breakdown from documentComparison
        doc_comparison = sentiment_data.get('documentComparison', {})
        sec_data = doc_comparison.get('sec', {})
        transcript_data = doc_comparison.get('transcripts', {})

        sec_count = sec_data.get('documentCount', 0)
        transcript_count = transcript_data.get('documentCount', 0)

        # Get SEC sentiment label
        sec_sentiment_scores = sec_data.get('sentiment', {})
        sec_label = max(sec_sentiment_scores, key=sec_sentiment_scores.get) if sec_sentiment_scores else 'N/A'

        # Get transcript sentiment label
        transcript_sentiment_scores = transcript_data.get('sentiment', {})
        transcript_label = max(transcript_sentiment_scores, key=transcript_sentiment_scores.get) if transcript_sentiment_scores else 'N/A'

        from_cache = sentiment_data.get('from_cache', False)
        cache_status = "(from cache)" if from_cache else "(freshly analyzed)"

        # Get top words instead of key_phrases
        top_words = sentiment_data.get('wordFrequency', [])[:5]
        top_words_str = chr(10).join([f"- {w.get('text', '')} ({w.get('count', 0)} occurrences)" for w in top_words])

        # Get insights if available
        insights = doc_comparison.get('insights', [])
        insights_str = ""
        if insights:
            insights_str = f"\n\nInsights:\n" + chr(10).join([f"- {i}" for i in insights])

        message = f"""Sentiment Analysis for {ticker} {cache_status}:

Overall Sentiment: {sentiment_label} (confidence: {confidence:.1%})

SEC Filings: {sec_label} ({sec_count} documents)
Earnings Transcripts: {transcript_label} ({transcript_count} documents)

Top Keywords:
{top_words_str}{insights_str}

This analysis is powered by AWS Comprehend, which examines SEC filings and earnings call transcripts."""

    elif sentiment_data and 'error' in sentiment_data:
        # API returned an error
        error_msg = sentiment_data.get('error', 'Unknown error')
        if 'No documents found' in error_msg:
            message = f"I don't have any documents for {ticker} to analyze yet. Please scrape some SEC filings or earnings transcripts first using the dashboard."
        else:
            message = f"I couldn't analyze sentiment for {ticker}: {error_msg}"
    else:
        # API call failed completely
        message = f"I'm having trouble connecting to the analysis service. Please try again in a moment or check the dashboard directly for {ticker} sentiment."

    return close_response({}, 'Fulfilled', message)

def handle_forecast(event):
    """
    Handle forecast intent with multi-model support and conversational flow

    Flow:
    1. Check cache for both models
    2. If cached, present summary and ask for preference
    3. Handle model selection and refresh requests
    """
    slots = event['sessionState']['intent']['slots'] or {}
    session_attributes = event.get('sessionState', {}).get('sessionAttributes', {}) or {}
    utterance = event.get('inputTranscript', '').lower()

    # Debug logging
    print(f"[ForecastIntent] utterance: {utterance}")
    print(f"[ForecastIntent] session_attributes: {session_attributes}")

    # Extract company/ticker
    company_name = None
    ticker = None

    if slots.get('CompanyName'):
        company_name = slots['CompanyName'].get('value', {}).get('interpretedValue', '')

    if not company_name:
        extracted_name, extracted_ticker = extract_company_from_utterance(utterance)
        if extracted_ticker:
            ticker = extracted_ticker
        elif extracted_name:
            company_name = extracted_name

    # Check session for stored ticker from previous turn
    if not ticker and not company_name:
        ticker = session_attributes.get('forecast_ticker')
        print(f"[ForecastIntent] Using stored ticker from session: {ticker}")

    if company_name and not ticker:
        company_id, db_ticker, db_company_name = find_company_by_alias(company_name)
        if db_ticker:
            ticker = db_ticker
            company_name = db_company_name
        else:
            ticker = company_name.upper()

    print(f"[ForecastIntent] Final ticker: {ticker}")

    if not ticker:
        return close_response({}, 'Failed', "Which company would you like a forecast for?")

    # Check for explicit model selection in utterance
    wants_chronos = 'chronos' in utterance
    wants_prophet = 'prophet' in utterance
    wants_refresh = 'refresh' in utterance or 'new' in utterance or 'update' in utterance or 'fresh' in utterance

    # Check for follow-up responses (yes/recommended/better -> use chronos)
    pending_action = session_attributes.get('forecast_pending_action')
    print(f"[ForecastIntent] pending_action: {pending_action}")

    if pending_action == 'awaiting_model_selection':
        if wants_chronos or 'recommend' in utterance or 'better' in utterance or 'yes' in utterance or 'first' in utterance:
            selected_model = 'chronos'
        elif wants_prophet or 'second' in utterance:
            selected_model = 'prophet'
        else:
            # Default to recommended
            selected_model = 'chronos'

        print(f"[ForecastIntent] Follow-up detected! Selected model: {selected_model}")
        # Clear pending action and fetch the selected model
        return _fetch_and_format_forecast(ticker, selected_model, wants_refresh)

    # Explicit model selection - go directly to that model
    if wants_chronos:
        return _fetch_and_format_forecast(ticker, 'chronos', wants_refresh)
    if wants_prophet:
        return _fetch_and_format_forecast(ticker, 'prophet', wants_refresh)

    # No explicit model - check cache for both and present comparison
    compare_data = call_api(f"/api/forecast/compare?ticker={ticker}&days=30", timeout=30)

    if not compare_data or 'error' in compare_data:
        # Fallback to just fetching chronos (recommended)
        return _fetch_and_format_forecast(ticker, 'chronos', False)

    has_cached = compare_data.get('has_cached_data', False)
    models = compare_data.get('models', {})
    recommended = compare_data.get('recommended_model', 'chronos')
    recommendation_reason = compare_data.get('recommendation_reason', '')

    # If user wants refresh, generate new forecast with recommended model
    if wants_refresh:
        return _fetch_and_format_forecast(ticker, recommended, True)

    # Build comparison summary
    prophet_info = models.get('prophet', {})
    chronos_info = models.get('chronos', {})

    if has_cached:
        # Present summary of cached forecasts
        summary_parts = [f"I have forecast data for {ticker}:\n"]

        if chronos_info.get('cached'):
            chronos_return = chronos_info.get('expected_return_pct', 0)
            chronos_mape = chronos_info.get('mape', 8.75)
            chronos_price = chronos_info.get('current_price', 0)
            chronos_time = chronos_info.get('cache_time_display', 'today')
            summary_parts.append(f"**Chronos (RECOMMENDED)**: {chronos_return:+.1f}% return, {100-chronos_mape:.1f}% accuracy")
            summary_parts.append(f"   Current price (as of {chronos_time}): ${chronos_price:.2f}")
        else:
            summary_parts.append(f"**Chronos**: Not yet generated (~91% accuracy)")

        if prophet_info.get('cached'):
            prophet_return = prophet_info.get('expected_return_pct', 0)
            prophet_mape = prophet_info.get('mape', 23.0)
            summary_parts.append(f"**Prophet**: {prophet_return:+.1f}% return, {100-prophet_mape:.1f}% accuracy")
        else:
            summary_parts.append(f"**Prophet**: Not yet generated (~77% accuracy)")

        summary_parts.append(f"\n{recommendation_reason}")
        summary_parts.append("\nSay:")
        summary_parts.append("- \"Yes\" or \"Chronos\" for the recommended model")
        summary_parts.append("- \"Prophet\" for the Prophet model")
        summary_parts.append("- \"Refresh\" to generate a fresh forecast")

        # Store session state for follow-up
        new_session_attrs = dict(session_attributes)
        new_session_attrs['forecast_pending_action'] = 'awaiting_model_selection'
        new_session_attrs['forecast_ticker'] = ticker

        return elicit_response(new_session_attrs, 'ForecastIntent', '\n'.join(summary_parts))

    else:
        # No cached data - generate with recommended model
        return _fetch_and_format_forecast(ticker, recommended, False)


def _fetch_and_format_forecast(ticker, model_type, refresh=False):
    """Helper to fetch forecast and format response"""
    from datetime import datetime

    refresh_param = '&refresh=true' if refresh else ''
    forecast_data = call_api(
        f"/api/forecast?ticker={ticker}&days=30&model={model_type}{refresh_param}",
        timeout=120  # Longer timeout for model training
    )

    if forecast_data and 'error' not in forecast_data:
        current_price = forecast_data.get('current_price', 0)
        predicted_price = forecast_data.get('predicted_price', 0)
        expected_return = forecast_data.get('expected_return_pct', 0)
        confidence = forecast_data.get('confidence_interval', {})
        from_cache = forecast_data.get('from_cache', False)
        model_name = forecast_data.get('model', model_type)

        # Get timestamp for current price
        try:
            now = datetime.utcnow()
            price_time = now.strftime('%H:%M %m/%d/%y')
        except:
            price_time = 'now'

        # Determine trend
        if expected_return > 5:
            trend = "strong upward trend"
        elif expected_return > 0:
            trend = "slight upward trend"
        elif expected_return > -5:
            trend = "slight downward trend"
        else:
            trend = "strong downward trend"

        # Get MAPE from metrics
        metrics = forecast_data.get('model_metrics', {})
        mape = metrics.get('mape', 8.75 if 'chronos' in model_type else 23.0)
        accuracy = 100 - mape

        model_display = "Chronos" if 'chronos' in model_type.lower() else "Prophet"
        status = "(from cache)" if from_cache else "(freshly generated)"

        message = f"""{model_display} Forecast for {ticker} {status}:

The model predicts a {trend} over the next 30 days.

Current Price (as of {price_time}): ${current_price:.2f}
Predicted Price (30 days): ${predicted_price:.2f}
Expected Return: {expected_return:+.1f}%

Confidence Range: ${confidence.get('lower', 0):.2f} - ${confidence.get('upper', 0):.2f}
Model Accuracy: {accuracy:.1f}% (MAPE: {mape:.1f}%)

Other options:
- "Chronos forecast for {ticker}" - Use Chronos model (better accuracy)
- "Prophet forecast for {ticker}" - Use Prophet model
- "Refresh forecast for {ticker}" - Generate fresh prediction

Note: Forecasts are for educational purposes only, not financial advice."""

    elif forecast_data and 'error' in forecast_data:
        message = f"I couldn't generate a forecast for {ticker}: {forecast_data.get('error', 'Unknown error')}\n\nTry asking about sentiment or documents instead."
    else:
        message = f"""I'm having trouble generating a forecast for {ticker} right now.

You can view the forecast chart directly on the dashboard's Forecast tab.

Try:
- "Sentiment for {ticker}" - Get NLP analysis
- "Documents for {ticker}" - See available data"""

    return close_response({}, 'Fulfilled', message)


def handle_dashboard_features(event):
    """Explain dashboard features"""
    message = """The Cyber Risk Dashboard has four main sections:

1. **Company Overview** - View company metrics, stock prices, and key statistics

2. **Sentiment Analysis** - AWS Comprehend analyzes SEC filings and earnings calls to determine market sentiment, showing positive/negative/neutral trends and key phrases

3. **Forecast** - Prophet-based stock price predictions with 30-day forecasts and confidence intervals

4. **AI Assistant** (You're using it now!) - Amazon Lex-powered chatbot to help navigate the dashboard

Data Sources:
- SEC EDGAR filings (10-K, 10-Q, 8-K)
- Earnings call transcripts
- Historical stock prices

The dashboard focuses on cybersecurity companies: CrowdStrike, Palo Alto Networks, Fortinet, Zscaler, and SentinelOne."""

    return close_response({}, 'Fulfilled', message)

def handle_add_company(event):
    """Handle adding a new company to the database"""
    utterance = event.get('inputTranscript', '')
    session_attributes = event.get('sessionState', {}).get('sessionAttributes', {})

    pending_action = session_attributes.get('pending_action')

    if pending_action == 'add_company_name':
        company_name = utterance.strip()
        session_attributes['company_name'] = company_name
        session_attributes['pending_action'] = 'add_company_ticker'
        return elicit_response(session_attributes, "AddCompanyIntent",
            f"Got it! The company name is '{company_name}'. What is the stock ticker symbol? (e.g., CRWD, PANW)")

    elif pending_action == 'add_company_ticker':
        ticker = utterance.strip().upper()
        company_name = session_attributes.get('company_name', 'Unknown')

        session_attributes.pop('pending_action', None)
        session_attributes.pop('company_name', None)

        try:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            cursor.execute("SELECT * FROM companies WHERE ticker = %s", (ticker,))
            existing = cursor.fetchone()

            if existing:
                cursor.close()
                conn.close()
                return close_response(session_attributes, 'Fulfilled',
                    f"The company {ticker} already exists in the database as '{existing['company_name']}'.")

            cursor.execute("""
                INSERT INTO companies (company_name, ticker, sector)
                VALUES (%s, %s, 'Cybersecurity')
                RETURNING id, company_name, ticker
            """, (company_name, ticker))

            new_company = cursor.fetchone()
            conn.commit()
            cursor.close()
            conn.close()

            message = f"""Successfully added {new_company['company_name']} ({new_company['ticker']}) to the dashboard!

You can now:
- Ask for sentiment analysis: "What is the sentiment for {ticker}?"
- View forecasts: "Show forecast for {ticker}"
- Get company info: "Tell me about {ticker}"

Note: You'll need to scrape SEC filings and earnings transcripts before full analysis is available."""

            return close_response(session_attributes, 'Fulfilled', message)

        except Exception as e:
            return close_response(session_attributes, 'Failed',
                f"Sorry, I couldn't add the company. Error: {str(e)}")

    company_name, ticker = extract_company_from_utterance(utterance)

    if company_name and ticker:
        try:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            cursor.execute("SELECT * FROM companies WHERE ticker = %s", (ticker,))
            existing = cursor.fetchone()

            if existing:
                cursor.close()
                conn.close()
                return close_response(session_attributes, 'Fulfilled',
                    f"Good news! {company_name} ({ticker}) is already in the dashboard. You can start analyzing it right away!")

            cursor.execute("""
                INSERT INTO companies (company_name, ticker, sector)
                VALUES (%s, %s, 'Cybersecurity')
                RETURNING id, company_name, ticker
            """, (company_name, ticker))

            new_company = cursor.fetchone()
            conn.commit()
            cursor.close()
            conn.close()

            message = f"""Successfully added {new_company['company_name']} ({new_company['ticker']}) to the dashboard!

You can now ask me about this company's sentiment analysis or forecasts."""

            return close_response(session_attributes, 'Fulfilled', message)

        except Exception as e:
            return close_response(session_attributes, 'Failed',
                f"Sorry, I couldn't add the company. Error: {str(e)}")

    elif ticker:
        session_attributes['pending_action'] = 'add_company_ticker'
        session_attributes['company_name'] = f"Company {ticker}"
        return elicit_response(session_attributes, "AddCompanyIntent",
            f"I found the ticker {ticker}. What is the full company name?")

    else:
        session_attributes['pending_action'] = 'add_company_name'
        return elicit_response(session_attributes, "AddCompanyIntent",
            "I'd be happy to help you add a new company! What is the company name?")


def handle_remove_company(event):
    """Handle removing a company from the database"""
    utterance = event.get('inputTranscript', '')
    session_attributes = event.get('sessionState', {}).get('sessionAttributes', {})

    pending_action = session_attributes.get('pending_action')

    if pending_action == 'confirm_remove':
        ticker = session_attributes.get('remove_ticker', '')
        company_name = session_attributes.get('remove_company_name', '')

        session_attributes.pop('pending_action', None)
        session_attributes.pop('remove_ticker', None)
        session_attributes.pop('remove_company_name', None)

        if any(word in utterance.lower() for word in ['yes', 'confirm', 'delete', 'remove', 'ok', 'sure']):
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("DELETE FROM companies WHERE ticker = %s", (ticker,))
                deleted = cursor.rowcount > 0
                conn.commit()
                cursor.close()
                conn.close()

                if deleted:
                    return close_response(session_attributes, 'Fulfilled',
                        f"Done! {company_name} ({ticker}) has been removed from the dashboard.")
                else:
                    return close_response(session_attributes, 'Fulfilled',
                        f"Hmm, I couldn't find {ticker} in the database. It may have already been removed.")

            except Exception as e:
                return close_response(session_attributes, 'Failed',
                    f"Sorry, I couldn't remove the company. Error: {str(e)}")
        else:
            return close_response(session_attributes, 'Fulfilled',
                f"OK, I won't remove {company_name}. The company will remain in the dashboard.")

    company_name, ticker = extract_company_from_utterance(utterance)

    if ticker:
        try:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT * FROM companies WHERE ticker = %s", (ticker,))
            company = cursor.fetchone()
            cursor.close()
            conn.close()

            if company:
                session_attributes['pending_action'] = 'confirm_remove'
                session_attributes['remove_ticker'] = ticker
                session_attributes['remove_company_name'] = company['company_name']
                return elicit_response(session_attributes, "RemoveCompanyIntent",
                    f"Are you sure you want to remove {company['company_name']} ({ticker}) from the dashboard? This will delete any cached data. Reply 'yes' to confirm or 'no' to cancel.")
            else:
                return close_response(session_attributes, 'Fulfilled',
                    f"I couldn't find a company with ticker {ticker} in the database. Use 'list companies' to see available companies.")

        except Exception as e:
            return close_response(session_attributes, 'Failed',
                f"Sorry, I encountered an error: {str(e)}")

    else:
        return elicit_response(session_attributes, "RemoveCompanyIntent",
            "Which company would you like to remove? Please provide the company name or ticker symbol.")


def elicit_response(session_attributes, intent_name, message):
    """Build Lex V2 response that elicits more information"""
    return {
        'sessionState': {
            'sessionAttributes': session_attributes,
            'dialogAction': {
                'type': 'ElicitIntent'
            }
        },
        'messages': [
            {
                'contentType': 'PlainText',
                'content': message
            }
        ]
    }


def handle_document_inventory(event):
    """Handle document inventory queries"""
    session_attributes = event.get('sessionState', {}).get('sessionAttributes', {})
    slots = event['sessionState']['intent']['slots'] or {}
    company_name = None
    ticker = None

    # Try to get company from slots first
    if slots.get('CompanyName'):
        company_name = slots['CompanyName'].get('value', {}).get('interpretedValue', '')

    # If no slot, extract from utterance
    if not company_name:
        utterance = event.get('inputTranscript', '')
        extracted_name, extracted_ticker = extract_company_from_utterance(utterance)
        if extracted_ticker:
            company_name = extracted_ticker
            ticker = extracted_ticker
        elif extracted_name:
            company_name = extracted_name

    # Look up the ticker if we don't have it
    if company_name and not ticker:
        company_id, db_ticker, db_company_name = find_company_by_alias(company_name)
        if db_ticker:
            ticker = db_ticker
            company_name = db_company_name
        else:
            ticker = company_name.upper()

    if not ticker:
        return elicit_response(session_attributes, "DocumentInventoryIntent",
            "Which company would you like to see the document inventory for? Please provide the company name or ticker.")

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            SELECT
                artifact_type,
                COUNT(*) as doc_count,
                MIN(published_date) as earliest_date,
                MAX(published_date) as latest_date
            FROM artifacts a
            JOIN companies c ON a.company_id = c.id
            WHERE LOWER(c.ticker) = LOWER(%s)
            GROUP BY artifact_type
            ORDER BY doc_count DESC
        """, (ticker,))

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        if rows:
            doc_list = []
            total_docs = 0
            for row in rows:
                doc_type = row['artifact_type']
                count = row['doc_count']
                total_docs += count
                earliest = row['earliest_date'].strftime('%Y-%m-%d') if row['earliest_date'] else 'N/A'
                latest = row['latest_date'].strftime('%Y-%m-%d') if row['latest_date'] else 'N/A'
                doc_list.append(f"- {doc_type}: {count} documents ({earliest} to {latest})")

            message = f"""Document Inventory for {company_name} ({ticker}):

Total Documents: {total_docs}

{chr(10).join(doc_list)}

You can analyze sentiment on these documents by asking "What is the sentiment for {ticker}?" """
        else:
            message = f"""I don't have any documents for {company_name} ({ticker}) in the database yet.

To add documents, use the "Start Scraping" button on the dashboard to fetch SEC filings and earnings transcripts.

Would you like to add a different company instead?"""

        return close_response(session_attributes, 'Fulfilled', message)

    except Exception as e:
        return close_response(session_attributes, 'Failed',
            f"Sorry, I couldn't retrieve the document inventory. Error: {str(e)}")


def handle_growth_metrics(event):
    """Handle growth metrics queries - calls the API for fresh data"""
    session_attributes = event.get('sessionState', {}).get('sessionAttributes', {})
    slots = event['sessionState']['intent']['slots'] or {}
    company_name = None
    ticker = None

    # Try to get company from slots first
    if slots.get('CompanyName'):
        company_name = slots['CompanyName'].get('value', {}).get('interpretedValue', '')

    # If no slot, extract from utterance
    if not company_name:
        utterance = event.get('inputTranscript', '')
        extracted_name, extracted_ticker = extract_company_from_utterance(utterance)
        if extracted_ticker:
            company_name = extracted_ticker
            ticker = extracted_ticker
        elif extracted_name:
            company_name = extracted_name

    # Look up the ticker if we don't have it
    if company_name and not ticker:
        company_id, db_ticker, db_company_name = find_company_by_alias(company_name)
        if db_ticker:
            ticker = db_ticker
            company_name = db_company_name
        else:
            ticker = company_name.upper()

    if not ticker:
        return elicit_response(session_attributes, "GrowthMetricsIntent",
            "Which company would you like to see growth metrics for? Please provide the company name or ticker.")

    # Call the growth API
    print(f"Fetching growth metrics for ticker: {ticker}")
    growth_data = call_api(f"/api/company-growth/{ticker}")

    if growth_data and 'error' not in growth_data:
        company_info = growth_data.get('company', {})
        emp_count = growth_data.get('employee_count', 'N/A')
        job_velocity = growth_data.get('job_velocity', {})
        tenure_stats = growth_data.get('tenure_stats', {})
        from_cache = growth_data.get('from_cache', False)

        cache_status = "(from cache)" if from_cache else "(freshly fetched)"

        message = f"""Growth Metrics for {company_name or ticker} {cache_status}:

Employee Count: {emp_count:,} employees
Job Velocity: {job_velocity.get('monthly_average', 'N/A')} postings/month
Average Tenure: {tenure_stats.get('average_months', 'N/A')} months

Hiring Trend: {job_velocity.get('trend', 'N/A')}

This data is sourced from Explorium and provides insights into company growth patterns."""

    elif growth_data and 'error' in growth_data:
        message = f"I couldn't fetch growth metrics for {ticker}: {growth_data.get('error', 'Unknown error')}"
    else:
        message = f"I'm having trouble fetching growth data for {ticker}. Please try the Company Growth tab on the dashboard."

    return close_response(session_attributes, 'Fulfilled', message)


def handle_fallback(event):
    """Handle fallback when no intent is matched - use company context if available"""
    utterance = event.get('inputTranscript', '').lower()

    # Try to extract company from utterance for context
    company_name, ticker = extract_company_from_utterance(utterance)

    if ticker:
        # User mentioned a company - provide helpful context
        message = f"""{company_name or ticker} is a cybersecurity company tracked in the dashboard.

You can ask me:
- "What is the sentiment for {ticker}?" - Analyze SEC filings and transcripts
- "Show forecast for {ticker}" - Get 30-day price predictions
- "What documents do I have for {ticker}?" - See available filings
- "Growth metrics for {ticker}" - View employee and hiring trends

Or try "list companies" to see all available companies."""
    else:
        message = """I'm sorry, I didn't understand that. Could you please rephrase?

Here are some things you can ask me:
- "List companies" - Show all available companies
- "Sentiment for CrowdStrike" - Get sentiment analysis
- "Forecast for PANW" - Get price predictions
- "What documents do I have for Zscaler?" - See document inventory
- "Growth metrics for CRWD" - View hiring trends
- "Help" - See all available commands"""

    return close_response({}, 'Fulfilled', message)


def delegate_to_lex(event):
    """Delegate control back to Lex for dialog management"""
    return {
        'sessionState': {
            'sessionAttributes': event.get('sessionState', {}).get('sessionAttributes', {}),
            'dialogAction': {
                'type': 'Delegate'
            },
            'intent': event['sessionState']['intent']
        }
    }


def handler(event, context):
    """Main Lambda handler for Lex V2"""
    print(f"Received event: {json.dumps(event)}")

    intent_name = event['sessionState']['intent']['name']
    invocation_source = event.get('invocationSource', 'FulfillmentCodeHook')

    print(f"Intent: {intent_name}, Invocation: {invocation_source}")

    # For DialogCodeHook, check if we have all required slots
    # If so, handle immediately; otherwise delegate to Lex
    if invocation_source == 'DialogCodeHook':
        slots = event['sessionState']['intent'].get('slots', {})

        # For intents that need a company name, check if slot is filled
        intents_needing_company = ['ForecastIntent', 'SentimentAnalysisIntent',
                                   'GrowthMetricsIntent', 'DocumentInventoryIntent',
                                   'AddCompanyIntent', 'RemoveCompanyIntent', 'CompanyInfoIntent']

        if intent_name in intents_needing_company:
            company_slot = slots.get('CompanyName', {})
            if company_slot and company_slot.get('value', {}).get('interpretedValue'):
                # Slot is filled - handle the request now
                print(f"Slot filled, handling {intent_name} directly")
                pass  # Continue to handler
            else:
                # Slot not filled - delegate to Lex to elicit
                print(f"Slot not filled, delegating to Lex")
                return delegate_to_lex(event)
        elif intent_name in ['WelcomeIntent', 'ListCompaniesIntent', 'DashboardFeaturesIntent', 'FallbackIntent']:
            # These don't need slots - handle immediately
            pass
        else:
            # Unknown intent - delegate
            return delegate_to_lex(event)

    handlers = {
        'WelcomeIntent': handle_welcome,
        'ListCompaniesIntent': handle_list_companies,
        'CompanyInfoIntent': handle_company_info,
        'SentimentAnalysisIntent': handle_sentiment_analysis,
        'ForecastIntent': handle_forecast,
        'DashboardFeaturesIntent': handle_dashboard_features,
        'AddCompanyIntent': handle_add_company,
        'RemoveCompanyIntent': handle_remove_company,
        'DocumentInventoryIntent': handle_document_inventory,
        'GrowthMetricsIntent': handle_growth_metrics,
        'FallbackIntent': handle_fallback,
    }

    handler_func = handlers.get(intent_name, handle_fallback)
    result = handler_func(event)

    # Ensure intent name is included in response (Lex V2 requirement)
    if 'sessionState' in result and 'intent' in result['sessionState']:
        if 'name' not in result['sessionState']['intent']:
            result['sessionState']['intent']['name'] = intent_name

    print(f"Returning: {json.dumps(result)}")
    return result
