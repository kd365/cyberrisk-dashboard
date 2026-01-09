"""
Amazon Lex V2 Service
Provides integration with Amazon Lex chatbot for the CyberRisk Dashboard
"""

import boto3
import os
import uuid
from botocore.exceptions import ClientError


class LexService:
    """Service for interacting with Amazon Lex V2 chatbot"""

    def __init__(self, bot_id=None, bot_alias_id=None, locale_id="en_US"):
        """
        Initialize the Lex service

        Args:
            bot_id: The Lex bot ID (from Terraform output or env var)
            bot_alias_id: The Lex bot alias ID (from Terraform output or env var)
            locale_id: The locale for the bot (default: en_US)
        """
        self.bot_id = bot_id or os.environ.get("LEX_BOT_ID")
        self.bot_alias_id = bot_alias_id or os.environ.get("LEX_BOT_ALIAS_ID")
        self.locale_id = locale_id

        # Initialize the Lex Runtime V2 client
        self.client = boto3.client(
            "lexv2-runtime", region_name=os.environ.get("AWS_REGION", "us-west-2")
        )

    def send_message(self, message: str, session_id: str = None) -> dict:
        """
        Send a message to the Lex bot and get a response

        Args:
            message: The user's message text
            session_id: Optional session ID to maintain conversation context

        Returns:
            dict with 'message' (bot response) and 'session_id'
        """
        if not self.bot_id or not self.bot_alias_id:
            # Return fallback response if Lex is not configured
            return self._get_fallback_response(message, session_id)

        # Generate session ID if not provided
        if not session_id:
            session_id = str(uuid.uuid4())

        try:
            response = self.client.recognize_text(
                botId=self.bot_id,
                botAliasId=self.bot_alias_id,
                localeId=self.locale_id,
                sessionId=session_id,
                text=message,
            )

            # Extract the response message
            messages = response.get("messages", [])
            if messages:
                bot_message = " ".join([m.get("content", "") for m in messages])
            else:
                bot_message = (
                    "I'm sorry, I didn't understand that. Could you please rephrase?"
                )

            return {
                "message": bot_message,
                "session_id": session_id,
                "intent": response.get("sessionState", {})
                .get("intent", {})
                .get("name"),
                "slots": response.get("sessionState", {})
                .get("intent", {})
                .get("slots", {}),
            }

        except ClientError as e:
            print(f"Lex API error: {e}")
            return self._get_fallback_response(message, session_id)

        except Exception as e:
            print(f"Error communicating with Lex: {e}")
            return self._get_fallback_response(message, session_id)

    def _get_fallback_response(self, message: str, session_id: str = None) -> dict:
        """
        Provide fallback responses when Lex is not configured or unavailable

        This allows the chatbot to work even without Lex during development
        """
        if not session_id:
            session_id = str(uuid.uuid4())

        message_lower = message.lower()

        # Simple pattern matching for fallback responses
        if any(
            word in message_lower for word in ["hello", "hi", "hey", "help", "start"]
        ):
            response = """Welcome to the CyberRisk Dashboard Assistant! I can help you with:

- List available companies
- Get information about specific companies
- Check sentiment analysis results
- View forecast predictions
- Explain dashboard features

Just ask me something like "What companies are available?" or "Tell me about CrowdStrike"."""

        elif (
            "companies" in message_lower
            or "list" in message_lower
            or "tracked" in message_lower
        ):
            # Try to get companies from database
            try:
                import psycopg2

                db_host = os.environ.get("DB_HOST", "").split(":")[0]
                conn = psycopg2.connect(
                    host=db_host,
                    database=os.environ.get("DB_NAME"),
                    user=os.environ.get("DB_USER"),
                    password=os.environ.get("DB_PASSWORD"),
                    port=5432,
                )
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT company_name, ticker FROM companies ORDER BY company_name"
                )
                companies = cursor.fetchall()
                cursor.close()
                conn.close()

                if companies:
                    company_list = "\n".join([f"- {c[0]} ({c[1]})" for c in companies])
                    response = f"The dashboard tracks {len(companies)} cybersecurity companies:\n\n{company_list}\n\nAsk me about any of these companies for more details!"
                else:
                    response = (
                        "No companies are currently loaded. Please check the database."
                    )
            except Exception as e:
                print(f"Database error in fallback: {e}")
                # Fallback if database not available
                response = """The dashboard tracks cybersecurity companies including CrowdStrike, Palo Alto Networks, Fortinet, Zscaler, and many more.

Use the Companies list in the dashboard to see all available companies, or say "list companies" to try again."""

        elif "crowdstrike" in message_lower or "crwd" in message_lower:
            response = """CrowdStrike (CRWD) is a leading cybersecurity company specializing in endpoint protection.

The dashboard provides:
- SEC filings (10-K, 10-Q) analysis
- Earnings call transcripts with sentiment analysis
- Stock price forecasts using Prophet
- Company growth metrics

Navigate to the Sentiment Analysis tab to see how market sentiment has trended for CrowdStrike."""

        elif "palo alto" in message_lower or "panw" in message_lower:
            response = """Palo Alto Networks (PANW) is a multinational cybersecurity company.

The dashboard provides:
- SEC filings analysis
- Earnings call sentiment tracking
- Stock price forecasts
- Workforce growth trends

Check the Forecast tab to see price predictions for PANW."""

        elif "sentiment" in message_lower:
            response = """The Sentiment Analysis feature uses AWS Comprehend to analyze:

- SEC filings (10-K, 10-Q, 8-K reports)
- Earnings call transcripts

It provides:
- Overall sentiment scores (positive, negative, neutral)
- Key phrases extraction
- Word frequency analysis
- Sentiment trends over time

Visit the Sentiment Analysis tab and select a company to see detailed analysis."""

        elif "forecast" in message_lower or "predict" in message_lower:
            # Check if user specified a model
            use_chronos = "chronos" in message_lower
            use_prophet = "prophet" in message_lower

            if use_chronos or use_prophet:
                model_name = "Chronos-Bolt" if use_chronos else "Prophet"
                model_param = "chronos" if use_chronos else "prophet"

                # Try to get forecast data
                try:
                    import requests

                    ticker = "CRWD"  # Default ticker
                    for t in [
                        "CRWD",
                        "ZS",
                        "NET",
                        "PANW",
                        "FTNT",
                        "OKTA",
                        "CYBR",
                        "TENB",
                        "SPLK",
                    ]:
                        if t.lower() in message_lower:
                            ticker = t
                            break

                    resp = requests.get(
                        f"http://localhost:5000/api/forecast?ticker={ticker}&model={model_param}&days=30",
                        timeout=30,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        from_cache = data.get("from_cache", False)
                        cache_note = " (from cache)" if from_cache else ""

                        response = f"""Here's the {model_name} forecast for {ticker}{cache_note}:

**Current Price:** ${data.get('current_price', 0):.2f}
**Predicted Price (30 days):** ${data.get('predicted_price', 0):.2f}
**Expected Return:** {data.get('expected_return_pct', 0):+.2f}%
**Confidence Range:** ${data.get('confidence_interval', {}).get('lower', 0):.2f} - ${data.get('confidence_interval', {}).get('upper', 0):.2f}

Visit the Forecast tab to see the full chart and switch between models."""
                    else:
                        response = f"I couldn't retrieve the {model_name} forecast. Please try the Forecast tab directly."
                except Exception as e:
                    print(f"Forecast API error: {e}")
                    response = f"I couldn't retrieve the {model_name} forecast. Please try the Forecast tab directly."
            else:
                # Ask user which model they want
                response = """The Price Forecast feature supports two AI models:

**1. Prophet** - Facebook's time series model with cybersecurity sentiment regressors
**2. Chronos-Bolt** - Amazon's foundation model using log returns (zero-shot, no training)

Which model would you like to use? You can say:
- "Show me the Prophet forecast for CrowdStrike"
- "Use Chronos to predict Zscaler"

Note: Forecasts are for educational purposes and should not be considered financial advice."""

        elif (
            "growth" in message_lower
            or "hiring" in message_lower
            or "workforce" in message_lower
            or "employee" in message_lower
        ):
            # Company growth analysis - with full company names
            GROWTH_COMPANIES = {
                "CRWD": "CrowdStrike",
                "ZS": "Zscaler",
                "NET": "Cloudflare",
                "PANW": "Palo Alto Networks",
                "FTNT": "Fortinet",
                "OKTA": "Okta",
                "S": "SentinelOne",
                "CYBR": "CyberArk",
                "TENB": "Tenable",
                "SPLK": "Splunk",
            }

            # Check if user specified a company
            found_ticker = None
            for ticker, name in GROWTH_COMPANIES.items():
                if ticker.lower() in message_lower or name.lower() in message_lower:
                    found_ticker = ticker
                    break

            if found_ticker:
                # Try to get growth data
                try:
                    import requests

                    resp = requests.get(
                        f"http://localhost:5000/api/company-growth/{found_ticker}",
                        timeout=30,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        company_name = data.get("company", {}).get(
                            "name", GROWTH_COMPANIES[found_ticker]
                        )
                        employee_count = data.get("company", {}).get(
                            "employee_count", 0
                        )
                        total_jobs = data.get("total_jobs", 0)
                        hiring_intensity = data.get("hiring_intensity", 0)

                        # Get top hiring functions
                        jobs_by_function = data.get("jobs_by_function", {})
                        top_functions = sorted(
                            jobs_by_function.items(), key=lambda x: x[1], reverse=True
                        )[:3]
                        top_funcs_str = ", ".join(
                            [f"{f[0]} ({f[1]})" for f in top_functions]
                        )

                        response = f"""Here's the workforce analysis for **{company_name}** ({found_ticker}):

**Current Employees:** {employee_count:,}
**Active Job Postings:** {total_jobs:,}
**Hiring Intensity:** {hiring_intensity:.1f}% of workforce

**Top Hiring Areas:** {top_funcs_str}

Visit the Company Growth tab to see detailed charts comparing multiple companies."""
                    else:
                        response = f"I couldn't retrieve growth data for {GROWTH_COMPANIES[found_ticker]}. Please try the Company Growth tab directly."
                except Exception as e:
                    print(f"Growth API error: {e}")
                    response = f"I couldn't retrieve growth data. Please try the Company Growth tab directly."
            else:
                # Ask user to select a company using full names
                company_list = "\n".join(
                    [f"- {name}" for name in GROWTH_COMPANIES.values()]
                )
                response = f"""Company Growth analysis is available for these cybersecurity companies:

{company_list}

Which company would you like to analyze? You can say things like:
- "Show me CrowdStrike's growth"
- "How is Palo Alto Networks hiring?"
- "Compare Zscaler and Cloudflare workforce"

Visit the Company Growth tab to compare multiple companies side-by-side."""

        elif (
            "features" in message_lower
            or "dashboard" in message_lower
            or "tabs" in message_lower
        ):
            response = """The CyberRisk Dashboard has five main sections:

1. **Data Collection** - View and manage SEC filings and earnings transcripts

2. **Price Forecast** - AI stock price predictions using Prophet or Chronos-Bolt models

3. **Sentiment Analysis** - AWS Comprehend NLP analysis of company documents

4. **Company Growth** - Workforce and hiring trends from CoreSignal data (10 cybersecurity companies)

5. **AI Assistant** (You're using it now!) - Amazon Lex-powered chatbot

Navigate using the sidebar to explore each feature."""

        else:
            response = """I'm not sure I understood that. Here are some things you can ask me:

- "What companies are available?"
- "Tell me about CrowdStrike"
- "What is sentiment analysis?"
- "Show me the Prophet forecast for Zscaler"
- "Use Chronos to predict CrowdStrike"
- "How is Palo Alto Networks hiring?"
- "What features does the dashboard have?"

Or just say "help" to see all options."""

        return {
            "message": response,
            "session_id": session_id,
            "intent": "FallbackIntent",
            "slots": {},
        }

    def end_session(self, session_id: str) -> bool:
        """
        End a Lex conversation session

        Args:
            session_id: The session ID to end

        Returns:
            True if successful, False otherwise
        """
        if not self.bot_id or not self.bot_alias_id:
            return True

        try:
            self.client.delete_session(
                botId=self.bot_id,
                botAliasId=self.bot_alias_id,
                localeId=self.locale_id,
                sessionId=session_id,
            )
            return True
        except Exception as e:
            print(f"Error ending Lex session: {e}")
            return False
