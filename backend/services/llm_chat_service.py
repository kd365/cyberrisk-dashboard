# =============================================================================
# LLM Chat Service - GraphRAG-Powered Assistant
# =============================================================================
#
# This service provides LLM-powered chat functionality.
#
# Two modes available (controlled by USE_LANGCHAIN env var):
#
# 1. Legacy Mode (USE_LANGCHAIN=false, default):
#    - Direct Bedrock API with Claude 3 Haiku
#    - Manual tool-calling loop
#    - Lower cost (~$25-35/month)
#
# 2. LangChain Mode (USE_LANGCHAIN=true):
#    - LangChain agent with Claude 3.5 Sonnet
#    - Automatic tool iteration
#    - Better reasoning, higher cost (~$100-150/month)
#
# =============================================================================

import os
import json
import logging
import re
from typing import Dict, List, Any, Optional
from datetime import datetime

import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)

# Feature flag for LangChain mode
USE_LANGCHAIN = os.environ.get("USE_LANGCHAIN", "false").lower() == "true"


class LLMChatService:
    """
    LLM-powered chat service using Claude via AWS Bedrock.

    Provides tool calling for database operations and GraphRAG
    for document-based intelligence.
    """

    # Bedrock inference profile ID for Claude 4.5 Haiku
    # (legacy claude-3-haiku-20240307 was deprecated by Bedrock in 2026)
    MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

    # System prompt loaded dynamically from shared prompts module
    # This ensures all companies from RDS are included
    _system_prompt = None

    @classmethod
    def get_system_prompt(cls):
        """Get system prompt (cached after first load)."""
        if cls._system_prompt is None:
            from services.prompts import get_system_prompt

            cls._system_prompt = get_system_prompt()
        return cls._system_prompt

    # Tool definitions for function calling
    TOOLS = [
        {
            "name": "list_companies",
            "description": "List all companies currently tracked in the dashboard with their basic info",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "get_company_info",
            "description": "Get detailed information about a specific company including current stock price",
            "input_schema": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol (e.g., CRWD, PANW)",
                    }
                },
                "required": ["ticker"],
            },
        },
        {
            "name": "get_sentiment",
            "description": "Get sentiment analysis results for a company based on SEC filings and earnings transcripts",
            "input_schema": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock ticker symbol"}
                },
                "required": ["ticker"],
            },
        },
        {
            "name": "get_forecast",
            "description": "Get stock price forecast for a company using Prophet or Chronos models",
            "input_schema": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock ticker symbol"},
                    "model": {
                        "type": "string",
                        "enum": ["prophet", "chronos"],
                        "description": "Forecasting model to use",
                    },
                    "days": {
                        "type": "integer",
                        "description": "Number of days to forecast (default: 30)",
                    },
                },
                "required": ["ticker"],
            },
        },
        {
            "name": "get_documents",
            "description": "List SEC filings and earnings transcripts available for a company",
            "input_schema": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock ticker symbol"}
                },
                "required": ["ticker"],
            },
        },
        {
            "name": "get_growth_metrics",
            "description": "Get company growth metrics including employee count and hiring data",
            "input_schema": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock ticker symbol"}
                },
                "required": ["ticker"],
            },
        },
        {
            "name": "add_company",
            "description": "Add a new company to track in the dashboard (requires authentication)",
            "input_schema": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock ticker symbol"},
                    "name": {"type": "string", "description": "Company name"},
                },
                "required": ["ticker", "name"],
            },
        },
        {
            "name": "remove_company",
            "description": "Remove a company from tracking (requires authentication)",
            "input_schema": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol to remove",
                    }
                },
                "required": ["ticker"],
            },
        },
        {
            "name": "query_knowledge_graph",
            "description": "Search the knowledge graph for information from SEC filings and documents. Use this for questions about specific topics, risks, people, or concepts mentioned in company filings.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language query to search for",
                    },
                    "ticker": {
                        "type": "string",
                        "description": "Optional: limit search to specific company",
                    },
                },
                "required": ["query"],
            },
        },
        {
            "name": "get_dashboard_help",
            "description": "Get information about dashboard features and capabilities",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "get_patents",
            "description": "Search for patents filed by a company or inventor. Use this when asked about patents, intellectual property, inventions, or patent filings.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol (e.g., CRWD, PANW) to search for company patents",
                    },
                    "inventor_name": {
                        "type": "string",
                        "description": "Name of an inventor to search for their patents",
                    },
                    "search_term": {
                        "type": "string",
                        "description": "General search term to find patents by title or content",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of patents to return (default: 10)",
                    },
                },
                "required": [],
            },
        },
    ]

    # Tools that require authentication
    PROTECTED_TOOLS = {"add_company", "remove_company"}

    def __init__(self):
        """Initialize the LLM chat service."""
        self.region = os.environ.get("AWS_REGION", "us-west-2")

        # Initialize Bedrock client
        config = Config(
            region_name=self.region, retries={"max_attempts": 3, "mode": "adaptive"}
        )
        self.bedrock = boto3.client("bedrock-runtime", config=config)

        # Service dependencies (lazy loaded)
        self._db_service = None
        self._neo4j_service = None
        self._memory_service = None
        self._cognito_service = None

    @property
    def db_service(self):
        """Lazy load database service."""
        if self._db_service is None:
            from services.database_service import db_service

            self._db_service = db_service
        return self._db_service

    @property
    def neo4j_service(self):
        """Lazy load Neo4j service."""
        if self._neo4j_service is None:
            try:
                from services.neo4j_service import get_neo4j_service

                self._neo4j_service = get_neo4j_service()
            except Exception as e:
                logger.warning(f"Neo4j service not available: {e}")
        return self._neo4j_service

    @property
    def memory_service(self):
        """Lazy load memory service."""
        if self._memory_service is None:
            from services.memory_service import get_memory_service

            self._memory_service = get_memory_service()
        return self._memory_service

    # =========================================================================
    # Main Chat Method
    # =========================================================================

    def chat(
        self,
        message: str,
        session_id: str,
        user_email: str = None,
        auth_token: str = None,
    ) -> Dict:
        """
        Process a chat message and return response.

        Args:
            message: User's message
            session_id: Conversation session ID
            user_email: Optional user email
            auth_token: Optional auth token for protected operations

        Returns:
            Response dict with message and metadata
        """
        try:
            # 1. Get conversation history
            history = self._get_conversation_context(session_id)

            # 2. Build messages for Claude
            messages = history + [{"role": "user", "content": message}]

            # 3. Call Claude with tools
            response = self._invoke_claude(messages, auth_token)

            # 4. Process response (may involve tool calls)
            final_response = self._process_response(response, messages, auth_token)

            # 5. Save messages to memory
            self._save_to_memory(session_id, message, final_response["content"])

            return {
                "response": final_response["content"],
                "session_id": session_id,
                "tools_used": final_response.get("tools_used", []),
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Chat error: {e}")
            return {
                "response": f"I apologize, but I encountered an error: {str(e)}. Please try again.",
                "session_id": session_id,
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }

    def _get_conversation_context(self, session_id: str) -> List[Dict]:
        """Get recent conversation history for context."""
        try:
            if self.memory_service:
                history = self.memory_service.get_context_for_llm(
                    session_id, max_messages=5
                )
                # Bedrock Converse API requires conversations to start with user message
                # Filter out any leading assistant messages
                while history and history[0].get("role") == "assistant":
                    history = history[1:]
                return history
        except Exception as e:
            logger.warning(f"Could not get conversation context: {e}")
        return []

    def _save_to_memory(self, session_id: str, user_msg: str, assistant_msg: str):
        """Save messages to conversation memory."""
        try:
            if self.memory_service:
                self.memory_service.add_message(session_id, "user", user_msg)
                self.memory_service.add_message(session_id, "assistant", assistant_msg)
        except Exception as e:
            logger.warning(f"Could not save to memory: {e}")

    # =========================================================================
    # Claude API Invocation
    # =========================================================================

    def _invoke_claude(self, messages: List[Dict], auth_token: str = None) -> Dict:
        """
        Invoke Claude via Bedrock Converse API.

        Args:
            messages: Conversation messages
            auth_token: Auth token for context

        Returns:
            Claude's response
        """
        # Build tool config
        tool_config = {
            "tools": [
                {
                    "toolSpec": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "inputSchema": {"json": tool["input_schema"]},
                    }
                }
                for tool in self.TOOLS
            ]
        }

        # Convert messages to Bedrock format
        bedrock_messages = []
        for msg in messages:
            bedrock_messages.append(
                {"role": msg["role"], "content": [{"text": msg["content"]}]}
            )

        try:
            response = self.bedrock.converse(
                modelId=self.MODEL_ID,
                messages=bedrock_messages,
                system=[{"text": self.get_system_prompt()}],
                toolConfig=tool_config,
                inferenceConfig={"maxTokens": 2048, "temperature": 0.7, "topP": 0.9},
            )

            return response

        except Exception as e:
            logger.error(f"Bedrock API error: {e}")
            raise

    def _process_response(
        self,
        response: Dict,
        messages: List[Dict],
        auth_token: str = None,
        max_iterations: int = 5,
    ) -> Dict:
        """
        Process Claude's response, handling tool calls iteratively.

        Args:
            response: Initial response from Claude
            messages: Current message history
            auth_token: Auth token for protected tools
            max_iterations: Max tool call iterations

        Returns:
            Final response with content and tools used
        """
        tools_used = []
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            output = response.get("output", {})
            message = output.get("message", {})
            content_blocks = message.get("content", [])

            # Check for tool use
            tool_uses = [b for b in content_blocks if "toolUse" in b]

            if not tool_uses:
                # No tool calls - extract text response
                text_content = ""
                for block in content_blocks:
                    if "text" in block:
                        text_content += block["text"]

                return {
                    "content": text_content or "I'm not sure how to respond to that.",
                    "tools_used": tools_used,
                }

            # Process tool calls
            tool_results = []
            for tool_block in tool_uses:
                tool_use = tool_block["toolUse"]
                tool_name = tool_use["name"]
                tool_id = tool_use["toolUseId"]
                tool_input = tool_use.get("input", {})

                logger.info(f"Executing tool: {tool_name} with input: {tool_input}")
                tools_used.append(tool_name)

                # Execute the tool
                result = self._execute_tool(tool_name, tool_input, auth_token)

                tool_results.append(
                    {
                        "toolResult": {
                            "toolUseId": tool_id,
                            "content": [{"json": result}],
                        }
                    }
                )

            # Continue conversation with tool results
            messages.append({"role": "assistant", "content": content_blocks})
            messages.append({"role": "user", "content": tool_results})

            # Build new Bedrock messages
            bedrock_messages = []
            for msg in messages:
                if isinstance(msg["content"], str):
                    bedrock_messages.append(
                        {"role": msg["role"], "content": [{"text": msg["content"]}]}
                    )
                else:
                    bedrock_messages.append(
                        {"role": msg["role"], "content": msg["content"]}
                    )

            # Call Claude again with tool results
            response = self.bedrock.converse(
                modelId=self.MODEL_ID,
                messages=bedrock_messages,
                system=[{"text": self.get_system_prompt()}],
                toolConfig={
                    "tools": [
                        {
                            "toolSpec": {
                                "name": tool["name"],
                                "description": tool["description"],
                                "inputSchema": {"json": tool["input_schema"]},
                            }
                        }
                        for tool in self.TOOLS
                    ]
                },
                inferenceConfig={"maxTokens": 2048, "temperature": 0.7, "topP": 0.9},
            )

        return {
            "content": "I've reached my limit of tool calls. Please try a simpler question.",
            "tools_used": tools_used,
        }

    # =========================================================================
    # Tool Execution
    # =========================================================================

    def _execute_tool(
        self, tool_name: str, params: Dict, auth_token: str = None
    ) -> Dict:
        """
        Execute a tool and return its result.

        Args:
            tool_name: Name of the tool to execute
            params: Tool parameters
            auth_token: Auth token for protected tools

        Returns:
            Tool execution result
        """
        # Check authentication for protected tools
        if tool_name in self.PROTECTED_TOOLS:
            if not auth_token:
                return {
                    "error": "authentication_required",
                    "message": "This action requires you to sign in. Please sign in first.",
                }

            from services.cognito_auth_service import cognito_auth

            claims = cognito_auth.verify_token(auth_token)
            if not claims:
                return {
                    "error": "invalid_token",
                    "message": "Your session has expired. Please sign in again.",
                }

        # Route to appropriate handler
        handlers = {
            "list_companies": self._tool_list_companies,
            "get_company_info": self._tool_get_company_info,
            "get_sentiment": self._tool_get_sentiment,
            "get_forecast": self._tool_get_forecast,
            "get_documents": self._tool_get_documents,
            "get_growth_metrics": self._tool_get_growth_metrics,
            "add_company": self._tool_add_company,
            "remove_company": self._tool_remove_company,
            "query_knowledge_graph": self._tool_query_knowledge_graph,
            "get_dashboard_help": self._tool_get_dashboard_help,
            "get_patents": self._tool_get_patents,
        }

        handler = handlers.get(tool_name)
        if not handler:
            return {"error": f"Unknown tool: {tool_name}"}

        try:
            return handler(params)
        except Exception as e:
            logger.error(f"Tool {tool_name} error: {e}")
            return {"error": str(e)}

    # =========================================================================
    # Tool Implementations
    # =========================================================================

    def _tool_list_companies(self, params: Dict) -> Dict:
        """List all tracked companies."""
        try:
            companies = self.db_service.get_all_companies()
            return {
                "companies": [
                    {
                        "ticker": c["ticker"],
                        "name": c["company_name"],
                        "sector": c.get("sector", "Cybersecurity"),
                    }
                    for c in companies
                ],
                "count": len(companies),
            }
        except Exception as e:
            return {"error": str(e)}

    def _tool_get_company_info(self, params: Dict) -> Dict:
        """Get company details."""
        ticker = params.get("ticker", "").upper()
        if not ticker:
            return {"error": "Ticker required"}

        try:
            company = self.db_service.get_company(ticker)
            if not company:
                return {"error": f"Company {ticker} not found"}

            # Get current stock price
            from services.forecast_cache import get_stock_data

            stock_data = get_stock_data(ticker)

            return {
                "ticker": ticker,
                "name": company.get("company_name"),
                "sector": company.get("sector", "Cybersecurity"),
                "description": company.get("description", ""),
                "current_price": (
                    stock_data.get("current_price") if stock_data else None
                ),
                "price_change_pct": (
                    stock_data.get("change_pct") if stock_data else None
                ),
            }
        except Exception as e:
            return {"error": str(e)}

    def _tool_get_sentiment(self, params: Dict) -> Dict:
        """Get sentiment analysis."""
        ticker = params.get("ticker", "").upper()
        if not ticker:
            return {"error": "Ticker required"}

        try:
            from services.sentiment_cache import get_cached_sentiment

            sentiment = get_cached_sentiment(ticker)

            if sentiment:
                return {
                    "ticker": ticker,
                    "overall_sentiment": sentiment.get("overall", {}),
                    "document_count": sentiment.get("document_count", 0),
                    "top_keywords": sentiment.get("wordFrequency", [])[:10],
                    "cached_at": sentiment.get("cached_at"),
                }
            return {"error": f"No sentiment data for {ticker}"}
        except Exception as e:
            return {"error": str(e)}

    def _tool_get_forecast(self, params: Dict) -> Dict:
        """Get stock forecast - prioritizes Chronos, falls back to Prophet."""
        ticker = params.get("ticker", "").upper()
        days = params.get("days", 30)

        if not ticker:
            return {"error": "Ticker required"}

        try:
            from services.forecast_cache import get_cached_forecast, forecast_cache

            # Check Chronos cache first (preferred model)
            forecast = get_cached_forecast(ticker, "chronos", days)
            if forecast:
                return {
                    "ticker": ticker,
                    "model": "chronos",
                    "forecast_days": days,
                    "current_price": forecast.get("current_price"),
                    "predicted_price": forecast.get("predicted_price"),
                    "expected_return_pct": forecast.get("expected_return_pct"),
                    "confidence": forecast.get(
                        "confidence_interval", forecast.get("confidence", {})
                    ),
                    "accuracy": forecast.get("accuracy", {}),
                    "computed_at": forecast.get(
                        "cached_at", forecast.get("computed_at")
                    ),
                }

            # Try to run Chronos forecast (primary model)
            logger.info(f"Running Chronos forecast for {ticker} ({days} days)")
            try:
                from models.chronos_forecaster import ChronosForecaster

                forecaster = ChronosForecaster(ticker, model_size="small")
                forecaster.fetch_stock_data(period="3y")
                results = forecaster.forecast(days_ahead=days)

                # Get accuracy metrics via backtesting
                accuracy_metrics = {}
                try:
                    eval_results = forecaster.evaluate(test_days=30)
                    accuracy_metrics = {
                        "mape": round(eval_results.get("mape", 0), 2),
                        "directional_accuracy": round(
                            eval_results.get("directional_accuracy", 0), 1
                        ),
                        "rmse": round(eval_results.get("rmse", 0), 2),
                    }
                except Exception as e:
                    logger.warning(f"Could not evaluate Chronos accuracy: {e}")

                response_data = {
                    "ticker": ticker,
                    "model": "chronos",
                    "current_price": float(results["current_price"]),
                    "predicted_price": float(results["predicted_price"]),
                    "expected_return_pct": float(results["expected_return_pct"]),
                    "confidence_interval": {
                        "lower": float(results["confidence_lower"]),
                        "upper": float(results["confidence_upper"]),
                    },
                    "accuracy": accuracy_metrics,
                }
                forecast_cache.set(ticker, days, response_data, "chronos")

                return {
                    "ticker": ticker,
                    "model": "chronos",
                    "forecast_days": days,
                    "current_price": response_data["current_price"],
                    "predicted_price": response_data["predicted_price"],
                    "expected_return_pct": response_data["expected_return_pct"],
                    "confidence": response_data["confidence_interval"],
                    "accuracy": accuracy_metrics,
                }
            except Exception as chronos_error:
                logger.warning(
                    f"Chronos forecast failed: {chronos_error}, falling back to Prophet"
                )

            # Fall back to Prophet if Chronos fails
            # Check Prophet cache
            forecast = get_cached_forecast(ticker, "prophet", days)
            if forecast:
                return {
                    "ticker": ticker,
                    "model": "prophet",
                    "model_note": "Chronos unavailable, using Prophet as backup",
                    "forecast_days": days,
                    "current_price": forecast.get("current_price"),
                    "predicted_price": forecast.get("predicted_price"),
                    "expected_return_pct": forecast.get("expected_return_pct"),
                    "confidence": forecast.get(
                        "confidence_interval", forecast.get("confidence", {})
                    ),
                    "accuracy": forecast.get("accuracy", {}),
                    "computed_at": forecast.get(
                        "cached_at", forecast.get("computed_at")
                    ),
                }

            # Run Prophet forecast as backup
            logger.info(f"Running Prophet forecast for {ticker} ({days} days)")
            try:
                from models.time_series_forecaster import CyberRiskForecaster

                forecaster = CyberRiskForecaster(ticker)
                forecaster.fetch_stock_data(period="2y")
                forecaster.add_cybersecurity_sentiment(mock=False)
                forecaster.add_volatility_regressor()
                forecaster.train()
                results = forecaster.forecast(days_ahead=days)

                # Get accuracy metrics via backtesting
                accuracy_metrics = {}
                try:
                    eval_results = forecaster.evaluate(test_days=30)
                    accuracy_metrics = {
                        "mape": round(eval_results.get("mape", 0), 2),
                        "directional_accuracy": round(
                            eval_results.get("directional_accuracy", 0), 1
                        ),
                        "rmse": round(eval_results.get("rmse", 0), 2),
                    }
                except Exception as e:
                    logger.warning(f"Could not evaluate Prophet accuracy: {e}")

                response_data = {
                    "ticker": ticker,
                    "model": "prophet",
                    "current_price": float(results["current_price"]),
                    "predicted_price": float(results["predicted_price"]),
                    "expected_return_pct": float(results["expected_return_pct"]),
                    "confidence_interval": {
                        "lower": float(results["confidence_lower"]),
                        "upper": float(results["confidence_upper"]),
                    },
                    "accuracy": accuracy_metrics,
                }
                forecast_cache.set(ticker, days, response_data, "prophet")

                return {
                    "ticker": ticker,
                    "model": "prophet",
                    "model_note": "Chronos unavailable, using Prophet as backup",
                    "forecast_days": days,
                    "current_price": response_data["current_price"],
                    "predicted_price": response_data["predicted_price"],
                    "expected_return_pct": response_data["expected_return_pct"],
                    "confidence": response_data["confidence_interval"],
                    "accuracy": accuracy_metrics,
                }
            except Exception as e:
                logger.error(f"Prophet forecast error: {e}")
                return {"error": f"Could not generate forecast: {str(e)}"}

        except Exception as e:
            logger.error(f"Forecast tool error: {e}")
            return {"error": str(e)}

    def _tool_get_documents(self, params: Dict) -> Dict:
        """List available documents."""
        ticker = params.get("ticker", "").upper()
        if not ticker:
            return {"error": "Ticker required"}

        try:
            artifacts = self.db_service.get_artifacts_by_ticker(ticker)
            return {
                "ticker": ticker,
                "documents": [
                    {
                        "type": a["artifact_type"],
                        "published_date": str(a.get("published_date", "")),
                        "s3_key": a["s3_key"],
                    }
                    for a in artifacts
                ],
                "count": len(artifacts),
            }
        except Exception as e:
            return {"error": str(e)}

    def _tool_get_growth_metrics(self, params: Dict) -> Dict:
        """Get company growth data from CoreSignal data."""
        ticker = params.get("ticker", "").upper()
        if not ticker:
            return {"error": "Ticker required"}

        try:
            from services.growth_cache import get_cached_growth

            growth = get_cached_growth(ticker)

            if growth:
                return {
                    "ticker": ticker,
                    "employee_count": growth.get("employee_count"),
                    "employee_growth_pct": growth.get("employee_growth_pct"),
                    "hiring_intensity": growth.get("hiring_intensity"),
                    "hiring_intensity_pct": growth.get("hiring_intensity_pct"),
                    "open_positions": growth.get("total_jobs"),
                    "jobs_by_function": growth.get("jobs_by_function", {}),
                    "jobs_by_seniority": growth.get("jobs_by_seniority", {}),
                    "snapshot_date": growth.get("snapshot_date"),
                    "cached_at": growth.get("cached_at"),
                }

            # No data for this company
            return {
                "ticker": ticker,
                "employee_count": None,
                "employee_growth_pct": None,
                "hiring_intensity": "data_unavailable",
                "open_positions": 0,
                "message": "Growth metrics are not available for this company.",
            }
        except Exception as e:
            return {"error": str(e)}

    def _tool_add_company(self, params: Dict) -> Dict:
        """Add a company to tracking."""
        ticker = params.get("ticker", "").upper()
        name = params.get("name", "")

        if not ticker or not name:
            return {"error": "Both ticker and name are required"}

        try:
            self.db_service.add_company(ticker, name)
            return {
                "success": True,
                "message": f"Added {name} ({ticker}) to tracked companies",
            }
        except Exception as e:
            return {"error": str(e)}

    def _tool_remove_company(self, params: Dict) -> Dict:
        """Remove a company from tracking."""
        ticker = params.get("ticker", "").upper()

        if not ticker:
            return {"error": "Ticker required"}

        try:
            self.db_service.remove_company(ticker)
            return {
                "success": True,
                "message": f"Removed {ticker} from tracked companies",
            }
        except Exception as e:
            return {"error": str(e)}

    def _tool_query_knowledge_graph(self, params: Dict) -> Dict:
        """Query the knowledge graph."""
        query = params.get("query", "")
        ticker = params.get("ticker")

        if not query:
            return {"error": "Query required"}

        if not self.neo4j_service:
            return {
                "error": "Knowledge graph not available",
                "message": "Neo4j service is not connected",
            }

        try:
            result = self.neo4j_service.semantic_query(query, ticker)
            return result
        except Exception as e:
            return {"error": str(e)}

    def _tool_get_dashboard_help(self, params: Dict) -> Dict:
        """Get dashboard help information."""
        return {
            "features": [
                {
                    "name": "Data Collection",
                    "description": "Collects SEC filings (10-K, 10-Q, 8-K) and earnings call transcripts",
                },
                {
                    "name": "Price Forecast",
                    "description": "Uses Prophet and Chronos models for stock price prediction",
                },
                {
                    "name": "Sentiment Analysis",
                    "description": "Analyzes sentiment from company documents using AWS Comprehend",
                },
                {
                    "name": "Company Growth",
                    "description": "Tracks employee counts and hiring trends from CoreSignal",
                },
                {
                    "name": "Knowledge Graph",
                    "description": "Visualizes entities and relationships from company documents",
                },
                {
                    "name": "AI Chat",
                    "description": "This chat interface - ask questions about any tracked company",
                },
            ],
            "tracked_companies": [
                "CRWD (CrowdStrike)",
                "PANW (Palo Alto Networks)",
                "ZS (Zscaler)",
                "FTNT (Fortinet)",
                "OKTA (Okta)",
                "NET (Cloudflare)",
                "S (SentinelOne)",
                "CYBR (CyberArk)",
                "TENB (Tenable)",
                "RPD (Rapid7)",
            ],
        }

    def _tool_get_patents(self, params: Dict) -> Dict:
        """Get patents from the knowledge graph."""
        ticker = params.get("ticker", "").upper() if params.get("ticker") else None
        inventor_name = params.get("inventor_name")
        search_term = params.get("search_term")
        limit = params.get("limit", 10)

        if not self.neo4j_service:
            return {
                "error": "Knowledge graph not available",
                "message": "Neo4j service is not connected",
            }

        try:
            result = self.neo4j_service.get_patents(
                ticker=ticker,
                inventor_name=inventor_name,
                search_term=search_term,
                limit=limit,
            )
            return result
        except Exception as e:
            logger.error(f"Patent query error: {e}")
            return {"error": str(e)}


# =============================================================================
# Singleton Instance with Feature Flag
# =============================================================================

_llm_chat_service = None


def get_llm_chat_service():
    """
    Get or create chat service singleton.

    Returns LangChainAgentService if USE_LANGCHAIN=true,
    otherwise returns legacy LLMChatService.
    """
    global _llm_chat_service
    if _llm_chat_service is None:
        if USE_LANGCHAIN:
            try:
                from services.langchain_agent import get_langchain_agent_service

                _llm_chat_service = get_langchain_agent_service()
                logger.info("Using LangChain agent with Claude 3.5 Sonnet")
            except ImportError as e:
                logger.warning(f"LangChain not available, falling back to legacy: {e}")
                _llm_chat_service = LLMChatService()
        else:
            _llm_chat_service = LLMChatService()
            logger.info("Using legacy Bedrock API with Claude 3 Haiku")
    return _llm_chat_service


# Convenience alias
llm_chat_service = None


def init_llm_chat_service():
    """Initialize the LLM chat service (call at app startup)."""
    global llm_chat_service
    try:
        llm_chat_service = get_llm_chat_service()
        mode = (
            "LangChain (Claude 3.5 Sonnet)"
            if USE_LANGCHAIN
            else "Legacy (Claude 3 Haiku)"
        )
        logger.info(f"LLM chat service initialized: {mode}")
    except Exception as e:
        logger.error(f"Failed to initialize LLM chat service: {e}")
        llm_chat_service = None
