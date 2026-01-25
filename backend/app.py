from flask import Flask, jsonify, request, redirect
from flask_cors import CORS
import sys
import os

# Add parent directory to path so we can import backend modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.s3_service import S3ArtifactService
from services.comprehend_service import ComprehendService
from services.sentiment_cache import SentimentCache
from services.forecast_cache import ForecastCache
from services.growth_cache import GrowthCache
from services.coresignal_service import CoreSignalService, CORESIGNAL_COMPANIES
from services.lex_service import LexService
from services.database_service import db_service
from services.regulatory_service import regulatory_service
from services.scraper import SecTranscriptScraper
from services.cognito_auth_service import require_cognito_auth, optional_cognito_auth
from models.time_series_forecaster import CyberRiskForecaster
import traceback
import threading

# Lazy load Chronos (may not be installed)
ChronosForecaster = None
CHRONOS_AVAILABLE = False


def _load_chronos_forecaster():
    """Lazy load Chronos forecaster"""
    global ChronosForecaster, CHRONOS_AVAILABLE
    if ChronosForecaster is not None:
        return CHRONOS_AVAILABLE
    try:
        from models.chronos_forecaster import ChronosForecaster as CF

        ChronosForecaster = CF
        CHRONOS_AVAILABLE = True
        print("✅ Chronos forecaster available")
    except ImportError as e:
        print(f"⚠️  Chronos forecaster not available: {e}")
        CHRONOS_AVAILABLE = False
    return CHRONOS_AVAILABLE


app = Flask(__name__)
CORS(app)

# Initialize services
s3_service = S3ArtifactService()
comprehend_service = ComprehendService()
sentiment_cache = SentimentCache(ttl_seconds=86400)  # 24 hour cache (now RDS-backed)
forecast_cache = ForecastCache()  # RDS-backed forecast cache
growth_cache = GrowthCache(cache_ttl_hours=24)  # RDS-backed growth cache
coresignal_service = CoreSignalService()  # API key from CORESIGNAL_API_KEY env var
lex_service = LexService()  # Bot ID/Alias from env vars or Terraform outputs
forecasters = {}  # Prophet forecasters
chronos_forecasters = {}  # Chronos forecasters


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy", "service": "cyber-risk-api"})


# ============================================================================
# ARTIFACT PROXY - Allow frontend to access S3 documents
# ============================================================================


@app.route("/api/artifact-proxy", methods=["GET"])
def artifact_proxy():
    """Proxy for accessing S3 documents with presigned URLs"""
    try:
        url = request.args.get("url")
        if not url:
            return jsonify({"error": "No URL provided"}), 400

        # If it's already a full S3 URL, redirect to it
        if url.startswith("http"):
            return redirect(url, code=302)

        # Otherwise, it might be an S3 key - get presigned URL
        presigned = s3_service.get_presigned_url(url)
        if presigned:
            return redirect(presigned, code=302)
        else:
            return jsonify({"error": "Could not generate presigned URL"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/artifact-url", methods=["GET"])
def artifact_url():
    """Get presigned S3 URL as JSON (for frontend to handle redirect)"""
    try:
        s3_key = request.args.get("key")
        if not s3_key:
            return jsonify({"error": "No S3 key provided"}), 400

        # Generate presigned URL
        presigned = s3_service.get_presigned_url(s3_key)
        if presigned:
            return jsonify({"url": presigned})
        else:
            return jsonify({"error": "Could not generate presigned URL"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# ARTIFACT ENDPOINTS
# ============================================================================


@app.route("/api/artifacts", methods=["GET"])
def get_artifacts():
    """Get all artifacts from database (with S3 fallback)"""
    try:
        # Try database first
        artifacts = db_service.get_all_artifacts()
        if artifacts:
            return jsonify(artifacts)

        # Fallback to S3 if database is empty
        artifacts = s3_service.get_artifacts_table()
        return jsonify(artifacts)
    except Exception as e:
        print(f"Error getting artifacts: {e}")
        traceback.print_exc()
        # Fallback to S3 on any error
        try:
            artifacts = s3_service.get_artifacts_table()
            return jsonify(artifacts)
        except:
            return jsonify({"error": str(e)}), 500


@app.route("/api/companies", methods=["GET"])
def get_companies():
    """Get company list from database (with S3 fallback)"""
    try:
        # Try database first (includes dynamically added companies)
        db_companies = db_service.get_all_companies()
        if db_companies:
            # Transform to frontend format (use 'name' instead of 'company_name')
            companies = []
            for db_c in db_companies:
                company = {
                    "name": db_c.get("company_name"),
                    "ticker": db_c.get("ticker", "").upper(),
                    "description": db_c.get("description", ""),
                    "exchange": db_c.get("exchange", ""),
                    "location": db_c.get("location", ""),
                    "sector": db_c.get("sector", "Cybersecurity"),
                    "alternate_names": db_c.get("alternate_names", ""),
                }
                companies.append(company)

            return jsonify(companies)

        # Fallback to S3 if database is empty
        companies = s3_service.get_companies()
        return jsonify(companies)
    except Exception as e:
        print(f"Error getting companies: {e}")
        traceback.print_exc()
        # Fallback to S3 on any error
        try:
            companies = s3_service.get_companies()
            return jsonify(companies)
        except:
            return jsonify({"error": str(e)}), 500


# ============================================================================
# COMPANY CRUD ENDPOINTS (Database-backed)
# ============================================================================


@app.route("/api/companies/db", methods=["GET"])
def get_companies_db():
    """Get all companies from database"""
    try:
        companies = db_service.get_all_companies()
        return jsonify(companies)
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/companies/db/<ticker>", methods=["GET"])
def get_company_db(ticker):
    """Get a specific company by ticker from database"""
    try:
        company = db_service.get_company(ticker.upper())
        if company:
            return jsonify(company)
        else:
            return jsonify({"error": f"Company not found: {ticker}"}), 404
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/companies/db", methods=["POST"])
def create_company():
    """
    Create a new company in the database

    Request body:
        {
            "company_name": "Company Full Name",
            "ticker": "TICK",
            "sector": "Cybersecurity"  (optional)
        }

    Returns:
        Created company or error
    """
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Request body required"}), 400

        company_name = data.get("company_name")
        ticker = data.get("ticker")
        sector = data.get("sector", "Cybersecurity")

        if not company_name or not ticker:
            return jsonify({"error": "company_name and ticker are required"}), 400

        # Check if company already exists
        if db_service.company_exists(ticker):
            return jsonify({"error": f"Company already exists: {ticker}"}), 409

        company = db_service.create_company(company_name, ticker, sector)
        if company:
            return (
                jsonify(
                    {
                        "status": "success",
                        "message": f"Company {ticker} created successfully",
                        "company": company,
                    }
                ),
                201,
            )
        else:
            return jsonify({"error": "Failed to create company"}), 500

    except Exception as e:
        print(f"Error creating company: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/companies/db/<ticker>", methods=["PUT"])
def update_company(ticker):
    """
    Update a company in the database

    Request body:
        {
            "company_name": "New Name",  (optional)
            "sector": "New Sector"  (optional)
        }

    Returns:
        Updated company or error
    """
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Request body required"}), 400

        company_name = data.get("company_name")
        sector = data.get("sector")

        company = db_service.update_company(ticker, company_name, sector)
        if company:
            return jsonify(
                {
                    "status": "success",
                    "message": f"Company {ticker} updated successfully",
                    "company": company,
                }
            )
        else:
            return jsonify({"error": f"Company not found: {ticker}"}), 404

    except Exception as e:
        print(f"Error updating company: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/companies/db/<ticker>", methods=["DELETE"])
def delete_company(ticker):
    """Delete a company from the database"""
    try:
        deleted = db_service.delete_company(ticker)
        if deleted:
            return jsonify(
                {
                    "status": "success",
                    "message": f"Company {ticker} deleted successfully",
                }
            )
        else:
            return jsonify({"error": f"Company not found: {ticker}"}), 404

    except Exception as e:
        print(f"Error deleting company: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/all-artifacts", methods=["GET"])
def get_all_artifacts():
    """Get all artifacts from all companies (database with S3 fallback)"""
    try:
        # Try database first
        artifacts = db_service.get_all_artifacts()
        if artifacts:
            return jsonify(artifacts)

        # Fallback to S3
        artifacts = s3_service.get_artifacts_table()
        return jsonify(artifacts)
    except Exception as e:
        print(f"Error getting all artifacts: {e}")
        try:
            artifacts = s3_service.get_artifacts_table()
            return jsonify(artifacts)
        except:
            return jsonify({"error": str(e)}), 500


@app.route("/api/artifacts/<ticker>", methods=["GET"])
def get_company_artifacts(ticker):
    """Get artifacts for specific company (database with S3 fallback)"""
    try:
        # Try database first
        artifacts = db_service.get_artifacts_by_ticker(ticker.upper())
        if artifacts:
            return jsonify(artifacts)

        # Fallback to S3
        artifacts = s3_service.get_artifacts_by_ticker(ticker.upper())
        return jsonify(artifacts)
    except Exception as e:
        print(f"Error getting artifacts for {ticker}: {e}")
        try:
            artifacts = s3_service.get_artifacts_by_ticker(ticker.upper())
            return jsonify(artifacts)
        except:
            return jsonify({"error": str(e)}), 500


@app.route("/api/artifacts/status/<ticker>", methods=["GET"])
def get_artifact_status(ticker):
    """Get status of what documents exist for a ticker"""
    try:
        status = s3_service.check_existing_documents(ticker.upper())
        needed = s3_service.get_documents_to_fetch(ticker.upper())

        return jsonify({"status": status, "to_fetch": needed})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/document/<path:filename>", methods=["GET"])
def get_document(filename):
    """Get presigned URL for document"""
    try:
        # Determine if SEC or transcript based on filename
        if "_10-K_" in filename or "_10-Q_" in filename:
            s3_key = f"raw/sec/{filename}"
        else:
            s3_key = f"raw/transcripts/{filename}"

        url = s3_service.get_presigned_url(s3_key)

        if url:
            return jsonify({"url": url, "filename": filename})
        else:
            return jsonify({"error": "Document not found"}), 404

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# FORECAST ENDPOINTS
# ============================================================================


@app.route("/api/forecast", methods=["GET"])
def get_forecast():
    """
    Get forecast for a ticker using Prophet or Chronos-Bolt

    Query params:
        ticker: Stock ticker symbol (default: MSFT)
        days: Forecast horizon in days (default: 30)
        model: 'prophet' or 'chronos' (default: prophet)
        refresh: If 'true', force recomputation (bypass cache)
    """
    ticker = request.args.get("ticker", "MSFT").upper()
    days = int(request.args.get("days", 30))
    model_type = request.args.get("model", "prophet").lower()
    refresh = request.args.get("refresh", "false").lower() == "true"

    # Validate model type
    if model_type not in ["prophet", "chronos"]:
        return (
            jsonify(
                {
                    "error": f"Invalid model type: {model_type}. Use 'prophet' or 'chronos'"
                }
            ),
            400,
        )

    try:
        # Check cache first (unless refresh is requested)
        if not refresh:
            cached_data = forecast_cache.get(ticker, days, model_type)
            if cached_data:
                cached_data["from_cache"] = True
                return jsonify(cached_data)

        # If refresh requested, invalidate cache for this ticker/model
        if refresh:
            forecast_cache.invalidate(ticker, model_type)
            # Also clear in-memory model to force retrain
            if model_type == "prophet" and ticker in forecasters:
                del forecasters[ticker]
            elif model_type == "chronos" and ticker in chronos_forecasters:
                del chronos_forecasters[ticker]

        import datetime

        today = datetime.date.today().isoformat()

        if model_type == "chronos":
            # Use Chronos-Bolt forecaster
            if not _load_chronos_forecaster():
                return (
                    jsonify(
                        {
                            "error": "Chronos model not available. Install with: pip install chronos-forecasting torch"
                        }
                    ),
                    503,
                )

            # Initialize Chronos forecaster if needed
            if ticker not in chronos_forecasters:
                print(f"Initializing Chronos-Bolt for {ticker}...")
                chronos_forecasters[ticker] = ChronosForecaster(
                    ticker, model_size="small"
                )
                chronos_forecasters[ticker].fetch_stock_data(
                    period="3y"
                )  # More context for Chronos
                print(f"Chronos ready for {ticker}")

            results = chronos_forecasters[ticker].forecast(days_ahead=days)

            # Convert forecast DataFrame to list
            forecast_data = results["forecast_df"][
                ["ds", "yhat", "yhat_lower", "yhat_upper"]
            ].to_dict("records")

            # Convert historical DataFrame to list
            historical_data = results["historical_df"].to_dict("records")

            response_data = {
                "ticker": ticker,
                "model": "chronos-bolt",
                "current_price": float(results["current_price"]),
                "predicted_price": float(results["predicted_price"]),
                "expected_return_pct": float(results["expected_return_pct"]),
                "confidence_interval": {
                    "lower": float(results["confidence_lower"]),
                    "upper": float(results["confidence_upper"]),
                },
                "expected_volatility_pct": float(
                    results.get("expected_volatility_pct", 0)
                ),
                "forecast": forecast_data,
                "historical": historical_data,
                "today": today,
                "from_cache": False,
                "notes": "Using log returns with P10/P50/P90 quantiles",
            }

        else:
            # Use Prophet forecaster (default)
            if ticker not in forecasters:
                print(f"Training Prophet model for {ticker}...")
                forecasters[ticker] = CyberRiskForecaster(ticker)
                forecasters[ticker].fetch_stock_data(period="2y")
                forecasters[ticker].add_cybersecurity_sentiment(mock=False)
                forecasters[ticker].add_volatility_regressor()
                forecasters[ticker].train()
                print(f"Prophet model ready for {ticker}")

            results = forecasters[ticker].forecast(days_ahead=days)

            # Convert forecast DataFrame to list
            forecast_data = results["forecast_df"][
                ["ds", "yhat", "yhat_lower", "yhat_upper"]
            ].to_dict("records")

            # Convert historical DataFrame to list
            historical_data = results["historical_df"].to_dict("records")

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
                "forecast": forecast_data,
                "historical": historical_data,
                "today": today,
                "from_cache": False,
            }

        # Cache the results with model type
        forecast_cache.set(ticker, days, response_data, model_type)

        return jsonify(response_data)

    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/forecast/models", methods=["GET"])
def get_available_models():
    """Get list of available forecast models"""
    models = [
        {
            "id": "prophet",
            "name": "Prophet",
            "description": "Facebook Prophet with cybersecurity sentiment regressors",
            "available": True,
        },
        {
            "id": "chronos",
            "name": "Chronos-Bolt",
            "description": "Amazon foundation model using log returns (zero-shot, no training)",
            "available": _load_chronos_forecaster(),
        },
    ]
    return jsonify({"models": models})


@app.route("/api/forecast/compare", methods=["GET"])
def get_forecast_comparison():
    """
    Get comparative forecast summary for both Prophet and Chronos models

    Query params:
        ticker: Stock ticker symbol (required)
        days: Forecast horizon in days (default: 30)

    Returns:
        - Summary of both models if cached
        - Recommendation for best model
        - Prompt for user to request refresh or select model
    """
    ticker = request.args.get("ticker", "").upper()
    days = int(request.args.get("days", 30))

    if not ticker:
        return jsonify({"error": "Ticker is required"}), 400

    import datetime as dt

    # Check cache for BOTH models
    cached_forecasts = forecast_cache.get_all_models(ticker, days)

    prophet_data = cached_forecasts.get("prophet")
    chronos_data = cached_forecasts.get("chronos")

    response = {
        "ticker": ticker,
        "forecast_days": days,
        "models": {},
        "has_cached_data": False,
        "recommended_model": "chronos",  # Chronos is better (8.75% MAPE vs ~23%)
        "recommendation_reason": "Chronos has better accuracy (MAPE: 8.75% vs ~23% for Prophet)",
    }

    # Build model summaries
    if prophet_data:
        cached_at = prophet_data.get("cached_at", "")
        # Parse cached_at to get readable time
        try:
            cached_dt = dt.datetime.fromisoformat(cached_at.replace("Z", "+00:00"))
            cache_time_str = cached_dt.strftime("%H:%M %m/%d/%y")
        except:
            cache_time_str = "today"

        response["models"]["prophet"] = {
            "available": True,
            "cached": True,
            "cached_at": cached_at,
            "cache_time_display": cache_time_str,
            "current_price": prophet_data.get("current_price"),
            "predicted_price": prophet_data.get("predicted_price"),
            "expected_return_pct": prophet_data.get("expected_return_pct"),
            "confidence_interval": prophet_data.get("confidence_interval"),
            "mape": prophet_data.get("model_metrics", {}).get("mape", 23.0),
        }
        response["has_cached_data"] = True
    else:
        response["models"]["prophet"] = {
            "available": True,
            "cached": False,
            "mape": 23.0,  # Historical average MAPE for Prophet
        }

    if chronos_data:
        cached_at = chronos_data.get("cached_at", "")
        try:
            cached_dt = dt.datetime.fromisoformat(cached_at.replace("Z", "+00:00"))
            cache_time_str = cached_dt.strftime("%H:%M %m/%d/%y")
        except:
            cache_time_str = "today"

        response["models"]["chronos"] = {
            "available": _load_chronos_forecaster(),
            "cached": True,
            "cached_at": cached_at,
            "cache_time_display": cache_time_str,
            "current_price": chronos_data.get("current_price"),
            "predicted_price": chronos_data.get("predicted_price"),
            "expected_return_pct": chronos_data.get("expected_return_pct"),
            "confidence_interval": chronos_data.get("confidence_interval"),
            "mape": chronos_data.get("model_metrics", {}).get("mape", 8.75),
        }
        response["has_cached_data"] = True
    else:
        response["models"]["chronos"] = {
            "available": _load_chronos_forecaster(),
            "cached": False,
            "mape": 8.75,  # Historical average MAPE for Chronos
        }

    # Determine recommendation based on actual MAPE if available
    prophet_mape = response["models"]["prophet"].get("mape", 23.0)
    chronos_mape = response["models"]["chronos"].get("mape", 8.75)

    if chronos_mape < prophet_mape:
        response["recommended_model"] = "chronos"
        response["recommendation_reason"] = (
            f"Chronos has better accuracy (MAPE: {chronos_mape:.1f}% vs {prophet_mape:.1f}% for Prophet)"
        )
    else:
        response["recommended_model"] = "prophet"
        response["recommendation_reason"] = (
            f"Prophet has better accuracy (MAPE: {prophet_mape:.1f}% vs {chronos_mape:.1f}% for Chronos)"
        )

    return jsonify(response)


@app.route("/api/evaluate/<ticker>", methods=["GET"])
def evaluate_model(ticker):
    """
    Get model evaluation metrics

    Query params:
        model: 'prophet' or 'chronos' (default: prophet)
    """
    ticker = ticker.upper()
    model_type = request.args.get("model", "prophet").lower()

    try:
        if model_type == "chronos":
            if ticker not in chronos_forecasters:
                return (
                    jsonify(
                        {
                            "error": "Chronos model not loaded yet. Call /api/forecast?model=chronos first."
                        }
                    ),
                    404,
                )

            evaluation = chronos_forecasters[ticker].evaluate(test_days=30)

            return jsonify(
                {
                    "ticker": ticker,
                    "model": "chronos-bolt",
                    "mape": float(evaluation["mape"]),
                    "rmse": float(evaluation["rmse"]),
                    "mae": float(evaluation["mae"]),
                    "directional_accuracy": float(evaluation["directional_accuracy"]),
                    "test_days": evaluation["test_days"],
                    "model_variant": evaluation.get("model_variant", "small"),
                }
            )
        else:
            # Prophet evaluation
            if ticker not in forecasters:
                return (
                    jsonify(
                        {
                            "error": "Prophet model not trained yet. Call /api/forecast first."
                        }
                    ),
                    404,
                )

            evaluation = forecasters[ticker].evaluate(test_days=30)

            return jsonify(
                {
                    "ticker": ticker,
                    "model": "prophet",
                    "mape": float(evaluation["mape"]),
                    "rmse": float(evaluation["rmse"]),
                    "mae": float(evaluation["mae"]),
                    "directional_accuracy": float(evaluation["directional_accuracy"]),
                    "test_days": evaluation["test_days"],
                }
            )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# SCRAPING ENDPOINTS
# ============================================================================

# Global scraping state
scraping_status = {
    "running": False,
    "progress": 0,
    "message": "Ready",
    "current_company": None,
    "results": [],
    "enrichment": None,  # Will contain event extraction results after scraping
}


def run_scraping_task(companies, scrape_type, include_8k=False):
    """Background task to scrape companies

    Args:
        companies: List of ticker symbols to scrape
        scrape_type: 'all', 'sec', 'transcripts', or '8k'
        include_8k: Whether to include 8-K filings (current reports)
    """
    scraping_status["running"] = True
    scraping_status["progress"] = 0
    scraping_status["results"] = []

    scraper = SecTranscriptScraper()
    total = len(companies)

    for i, ticker in enumerate(companies):
        try:
            scraping_status["current_company"] = ticker
            scraping_status["message"] = f"Scraping {ticker} ({i+1}/{total})..."
            scraping_status["progress"] = int((i / total) * 100)

            result = {
                "ticker": ticker,
                "sec_filings": 0,
                "eightk_filings": 0,
                "transcripts": 0,
                "errors": [],
            }

            # Scrape SEC filings (10-K, 10-Q)
            if scrape_type in ["all", "sec"]:
                try:
                    filings = scraper.scrape_sec_filings(
                        ticker, num_filings=5, include_8k=include_8k, num_8k=10
                    )
                    if filings:
                        # Separate 8-K from other filings for reporting
                        regular_filings = [f for f in filings if f["form"] != "8-K"]
                        eightk_filings = [f for f in filings if f["form"] == "8-K"]

                        if regular_filings:
                            saved = scraper.save_raw_pdf_files(regular_filings)
                            result["sec_filings"] = len(saved)

                        if eightk_filings:
                            saved_8k = scraper.save_raw_pdf_files(eightk_filings)
                            result["eightk_filings"] = len(saved_8k)
                except Exception as e:
                    result["errors"].append(f"SEC: {str(e)}")

            # Scrape only 8-K filings
            if scrape_type == "8k":
                try:
                    filings = scraper.scrape_sec_filings(
                        ticker, num_filings=0, include_8k=True, num_8k=10
                    )
                    eightk_filings = [f for f in filings if f["form"] == "8-K"]
                    if eightk_filings:
                        saved = scraper.save_raw_pdf_files(eightk_filings)
                        result["eightk_filings"] = len(saved)
                except Exception as e:
                    result["errors"].append(f"8-K: {str(e)}")

            # Scrape transcripts
            if scrape_type in ["all", "transcripts"]:
                try:
                    transcripts = scraper.scrape_earnings_transcripts(
                        ticker, num_quarters=4
                    )
                    result["transcripts"] = len(transcripts)
                except Exception as e:
                    result["errors"].append(f"Transcripts: {str(e)}")

            scraping_status["results"].append(result)

        except Exception as e:
            scraping_status["results"].append(
                {
                    "ticker": ticker,
                    "sec_filings": 0,
                    "eightk_filings": 0,
                    "transcripts": 0,
                    "errors": [str(e)],
                }
            )

    # === AUTO-ENRICHMENT AFTER SCRAPING ===
    # Track which companies got which types of new files
    companies_with_8k = [
        r["ticker"]
        for r in scraping_status["results"]
        if r.get("eightk_filings", 0) > 0
    ]
    companies_with_sec = [
        r["ticker"] for r in scraping_status["results"] if r.get("sec_filings", 0) > 0
    ]
    companies_with_transcripts = [
        r["ticker"] for r in scraping_status["results"] if r.get("transcripts", 0) > 0
    ]
    # Any company with new documents needs graph building
    companies_with_new_docs = list(
        set(companies_with_8k + companies_with_sec + companies_with_transcripts)
    )

    enrichment_results = {
        # 8-K event extraction
        "executive_events": 0,
        "ma_events": 0,
        "security_events": 0,
        "restructuring_events": 0,
        # Graph building (entities, concepts, risks)
        "entities_created": 0,
        "concepts_created": 0,
        "documents_processed": 0,
        # Summary
        "companies_enriched": len(companies_with_new_docs),
    }

    # 1. Extract 8-K events (executive changes, M&A, security incidents) - uses LLM
    if companies_with_8k:
        scraping_status["message"] = (
            f"Extracting 8-K events from {len(companies_with_8k)} companies..."
        )
        try:
            from services.data_enrichment_service import SEC8KEventExtractor

            extractor = SEC8KEventExtractor()

            for i, ticker in enumerate(companies_with_8k):
                scraping_status["message"] = (
                    f"Extracting 8-K events for {ticker} ({i+1}/{len(companies_with_8k)})..."
                )
                try:
                    result = extractor.create_all_events(ticker)
                    enrichment_results["executive_events"] += result.get(
                        "executive_events", 0
                    )
                    enrichment_results["ma_events"] += result.get("ma_events", 0)
                    enrichment_results["security_events"] += result.get(
                        "security_events", 0
                    )
                    enrichment_results["restructuring_events"] += result.get(
                        "restructuring_events", 0
                    )
                except Exception as e:
                    print(f"8-K enrichment error for {ticker}: {e}")

            print(f"8-K event extraction complete: {enrichment_results}")
        except Exception as e:
            print(f"8-K auto-enrichment failed: {e}")
            scraping_status["enrichment_error"] = str(e)

    # 2. Build knowledge graph (entities, concepts, risks, key phrases) - uses AWS Comprehend
    if companies_with_new_docs:
        scraping_status["message"] = (
            f"Building knowledge graph for {len(companies_with_new_docs)} companies..."
        )
        try:
            from services.graph_builder_service import GraphBuilderService

            graph_builder = GraphBuilderService()

            for i, ticker in enumerate(companies_with_new_docs):
                scraping_status["message"] = (
                    f"Building graph for {ticker} ({i+1}/{len(companies_with_new_docs)})..."
                )
                try:
                    result = graph_builder.build_graph_for_ticker(
                        ticker,
                        include_entities=True,
                        include_concepts=True,  # RISK, TECHNOLOGY, FINANCIAL, etc.
                        include_key_phrases=True,
                    )
                    enrichment_results["entities_created"] += result.get(
                        "entities_created", 0
                    )
                    enrichment_results["concepts_created"] += result.get(
                        "concepts_created", 0
                    )
                    enrichment_results["documents_processed"] += result.get(
                        "documents_processed", 0
                    )
                except Exception as e:
                    print(f"Graph building error for {ticker}: {e}")

            print(
                f"Graph building complete: {enrichment_results['entities_created']} entities, {enrichment_results['concepts_created']} concepts"
            )
        except Exception as e:
            print(f"Graph building failed: {e}")

    scraping_status["enrichment"] = enrichment_results

    # Build summary message
    scraping_status["running"] = False
    scraping_status["progress"] = 100
    scraping_status["current_company"] = None
    scraping_status["message"] = f"Completed scraping {total} companies" + (
        f", enriched {len(companies_with_new_docs)}" if companies_with_new_docs else ""
    )


@app.route("/api/scraping/status", methods=["GET"])
def get_scraping_status():
    """Get scraping progress status"""
    return jsonify(scraping_status)


@app.route("/api/scraping/start", methods=["POST"])
def start_scraping():
    """Start scraping process in background

    Request body:
        type: 'all', 'sec', 'transcripts', or '8k'
        companies: List of ticker symbols
        include_8k: Whether to include 8-K filings when type is 'all' or 'sec'
    """
    if scraping_status["running"]:
        return (
            jsonify({"status": "error", "message": "Scraping already in progress"}),
            400,
        )

    data = request.json or {}
    scrape_type = data.get("type", "all")
    companies = data.get("companies", [])
    include_8k = data.get("include_8k", False)

    if not companies:
        return jsonify({"status": "error", "message": "No companies specified"}), 400

    # Start scraping in background thread
    thread = threading.Thread(
        target=run_scraping_task, args=(companies, scrape_type, include_8k)
    )
    thread.daemon = True
    thread.start()

    return jsonify(
        {
            "status": "started",
            "type": scrape_type,
            "include_8k": include_8k,
            "companies": companies,
            "message": f"Started scraping {len(companies)} companies",
        }
    )


# ============================================================================
# SENTIMENT ANALYSIS ENDPOINTS (AWS Comprehend NLP)
# ============================================================================


@app.route("/api/sentiment/<ticker>", methods=["GET"])
def get_sentiment_analysis(ticker):
    """
    Get comprehensive sentiment analysis for a ticker using AWS Comprehend

    Query params:
        include_entities: Include entity recognition (default: true)
        refresh: If 'true', force recomputation (bypass cache)

    Returns:
        - Overall sentiment across all documents
        - Word frequency analysis
        - Entity recognition (organizations, people, products)
        - Key phrases
        - SEC vs Transcript comparison
        - Sentiment timeline
    """
    try:
        ticker = ticker.upper()
        refresh = request.args.get("refresh", "false").lower() == "true"

        # Get all artifacts for this ticker
        artifacts = s3_service.get_artifacts_table()

        # If refresh requested, invalidate cache for this ticker
        if refresh:
            sentiment_cache.invalidate(ticker)

        # Check cache first (unless refresh is requested)
        if not refresh:
            cached_data = sentiment_cache.get(ticker, artifacts)
            if cached_data:
                cached_data["from_cache"] = True
                return jsonify(cached_data)

        # Perform comprehensive sentiment analysis
        print(f"Analyzing sentiment for {ticker}...")

        # Check if entities should be included
        include_entities = (
            request.args.get("include_entities", "true").lower() == "true"
        )

        sentiment_data = comprehend_service.analyze_ticker_sentiment(
            ticker, artifacts, include_entities=include_entities
        )

        if not sentiment_data:
            return (
                jsonify(
                    {
                        "error": "No documents found for sentiment analysis",
                        "ticker": ticker,
                    }
                ),
                404,
            )

        sentiment_data["from_cache"] = False

        # Cache the results
        sentiment_cache.set(ticker, artifacts, sentiment_data)

        print(f"Sentiment analysis complete for {ticker}")
        return jsonify(sentiment_data)

    except Exception as e:
        print(f"Error analyzing sentiment: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/sentiment/<ticker>/timeline", methods=["GET"])
def get_sentiment_timeline(ticker):
    """Get sentiment timeline for a specific ticker"""
    try:
        ticker = ticker.upper()
        artifacts = s3_service.get_artifacts_table()

        sentiment_data = comprehend_service.analyze_ticker_sentiment(ticker, artifacts)

        if not sentiment_data:
            return jsonify({"error": "No documents found"}), 404

        return jsonify(
            {"ticker": ticker, "timeline": sentiment_data.get("timeline", [])}
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/sentiment/<ticker>/words", methods=["GET"])
def get_word_frequency(ticker):
    """Get word frequency analysis for a ticker"""
    try:
        ticker = ticker.upper()
        top_n = int(request.args.get("top_n", 50))

        artifacts = s3_service.get_artifacts_table()
        sentiment_data = comprehend_service.analyze_ticker_sentiment(ticker, artifacts)

        if not sentiment_data:
            return jsonify({"error": "No documents found"}), 404

        return jsonify(
            {"ticker": ticker, "words": sentiment_data.get("wordFrequency", [])[:top_n]}
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/sentiment/<ticker>/targeted", methods=["GET"])
def get_targeted_sentiment(ticker):
    """
    Get AWS Comprehend Targeted Sentiment Analysis

    Identifies specific entities (people, products, organizations) and
    determines sentiment toward each one

    Returns:
        Entity-specific sentiment analysis
    """
    try:
        ticker = ticker.upper()
        artifacts = s3_service.get_artifacts_table()

        # Filter for transcripts only (better quality text than SEC PDFs)
        ticker_artifacts = [
            a
            for a in artifacts
            if a.get("ticker") == ticker
            and "transcript" in a.get("type", "").lower()
            and a.get("s3_key", "").endswith(".txt")  # Alpha Vantage transcripts only
        ]

        if not ticker_artifacts:
            return (
                jsonify(
                    {
                        "error": "No Alpha Vantage transcripts found for targeted sentiment",
                        "ticker": ticker,
                    }
                ),
                404,
            )

        print(f"Running targeted sentiment analysis for {ticker}...")

        all_targeted_entities = []
        docs_analyzed = 0

        # Analyze a sample of transcripts (targeted sentiment is more expensive)
        for artifact in ticker_artifacts[:5]:  # Limit to 5 docs for cost
            s3_key = artifact.get("s3_key")
            doc_type = artifact.get("type", "")

            if not s3_key:
                continue

            print(f"  Analyzing: {s3_key}")

            text = comprehend_service.get_document_text(s3_key)
            if not text or len(text) < 100:
                continue

            # Analyze first 5000 chars
            sample_text = text[:5000]
            targeted_entities = comprehend_service.detect_targeted_sentiment(
                sample_text
            )

            if targeted_entities:
                all_targeted_entities.extend(targeted_entities)
                docs_analyzed += 1

        if not all_targeted_entities:
            return (
                jsonify(
                    {"error": "No targeted sentiment data extracted", "ticker": ticker}
                ),
                404,
            )

        # Summarize targeted sentiment
        entity_sentiments = comprehend_service._summarize_targeted_sentiment(
            all_targeted_entities
        )

        print(f"Extracted targeted sentiment for {len(entity_sentiments)} entities")

        return jsonify(
            {
                "ticker": ticker,
                "documents_analyzed": docs_analyzed,
                "entity_count": len(entity_sentiments),
                "entities": entity_sentiments,
            }
        )

    except Exception as e:
        print(f"Error in targeted sentiment: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/sentiment/<ticker>/alphavantage", methods=["GET"])
def get_alphavantage_sentiment(ticker):
    """
    Get Alpha Vantage sentiment scores over time for earnings call transcripts

    Returns:
        Timeline of sentiment scores from Alpha Vantage API embedded in transcripts
    """
    try:
        ticker = ticker.upper()
        artifacts = s3_service.get_artifacts_table()

        # Filter for Alpha Vantage transcripts (.txt files)
        transcript_artifacts = [
            a
            for a in artifacts
            if a.get("ticker") == ticker
            and "transcript" in a.get("type", "").lower()
            and a.get("s3_key", "").endswith(".txt")  # Alpha Vantage transcripts
        ]

        if not transcript_artifacts:
            return (
                jsonify(
                    {"error": "No Alpha Vantage transcripts found", "ticker": ticker}
                ),
                404,
            )

        timeline = []

        for artifact in transcript_artifacts:
            s3_key = artifact.get("s3_key")
            date = artifact.get("date")

            print(f"  Extracting Alpha Vantage sentiment from {s3_key}")

            sentiment_data = comprehend_service.extract_alphavantage_sentiment(s3_key)

            if sentiment_data:
                timeline.append(
                    {
                        "date": date,
                        "s3_key": s3_key,
                        "quarter": s3_key.split("_")[1]
                        .replace("transcript.txt", "")
                        .strip("_"),
                        "sentiment": sentiment_data,
                    }
                )

        if not timeline:
            return (
                jsonify(
                    {
                        "error": "Could not extract sentiment from transcripts",
                        "ticker": ticker,
                    }
                ),
                404,
            )

        # Sort by date
        timeline.sort(key=lambda x: x["date"])

        # Calculate overall statistics
        overall_scores = [t["sentiment"]["overall_score"] for t in timeline]

        return jsonify(
            {
                "ticker": ticker,
                "timeline": timeline,
                "overall": {
                    "average_score": sum(overall_scores) / len(overall_scores),
                    "min_score": min(overall_scores),
                    "max_score": max(overall_scores),
                    "transcript_count": len(timeline),
                },
            }
        )

    except Exception as e:
        print(f"Error extracting Alpha Vantage sentiment: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/sentiment/cache/stats", methods=["GET"])
def get_cache_stats():
    """Get sentiment cache statistics"""
    try:
        stats = sentiment_cache.get_cache_stats()
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/sentiment/cache/clear", methods=["POST"])
def clear_cache():
    """Clear sentiment cache (optional: specific ticker)"""
    try:
        ticker = request.args.get("ticker")
        sentiment_cache.invalidate(ticker)

        return jsonify(
            {
                "status": "success",
                "message": (
                    f"Cache cleared for {ticker}" if ticker else "All cache cleared"
                ),
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# FINANCIAL DATA ENDPOINTS (AWS Textract SEC Filing Extraction)
# ============================================================================


@app.route("/api/financials/<ticker>", methods=["GET"])
def get_financials(ticker):
    """
    Extract financial metrics from SEC filings using AWS Textract

    Returns:
        - Revenue, Subscription Revenue, ARR, Net Income, Operating Income, EPS
        - 4-quarter rolling averages for key metrics
        - Timeline of financial data from 10-K and 10-Q filings
    """
    try:
        ticker = ticker.upper()

        # Get all artifacts for this ticker
        artifacts = s3_service.get_artifacts_table()

        # Import and initialize financial extractor
        # Using HTML extractor for modern iXBRL filings (more reliable than Textract)
        from services.financial_html_extractor import FinancialHtmlExtractor

        extractor = FinancialHtmlExtractor()

        print(f"Extracting financial data for {ticker}...")

        # Extract financial data from SEC filings
        financials = extractor.extract_all_financials_for_ticker(ticker, artifacts)

        if not financials:
            return (
                jsonify(
                    {
                        "error": "No financial data extracted",
                        "ticker": ticker,
                        "message": "No SEC filings found or extraction failed",
                    }
                ),
                404,
            )

        # Calculate rolling averages
        financials_with_avg = extractor.calculate_rolling_averages(financials, window=4)

        # Calculate summary statistics
        latest = financials_with_avg[-1] if financials_with_avg else {}

        summary = {
            "ticker": ticker,
            "latest_filing": {
                "date": latest.get("date"),
                "type": latest.get("type"),
                "revenue": latest.get("revenue"),
                "subscription_revenue": latest.get("subscription_revenue"),
                "arr": latest.get("arr"),
                "net_income": latest.get("net_income"),
                "operating_income": latest.get("operating_income"),
                "eps": latest.get("eps"),
            },
            "rolling_averages": {
                "revenue_4q_avg": latest.get("revenue_rolling_avg"),
                "subscription_revenue_4q_avg": latest.get(
                    "subscription_revenue_rolling_avg"
                ),
                "net_income_4q_avg": latest.get("net_income_rolling_avg"),
                "operating_income_4q_avg": latest.get("operating_income_rolling_avg"),
            },
            "timeline": financials_with_avg,
            "filing_count": len(financials_with_avg),
        }

        print(f"Extracted {len(financials_with_avg)} financial data points")

        return jsonify(summary)

    except Exception as e:
        print(f"Error extracting financials: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ============================================================================
# COMPANY GROWTH ENDPOINTS (CoreSignal API)
# ============================================================================


@app.route("/api/company-growth/available", methods=["GET"])
def get_available_growth_companies():
    """
    Get list of companies available for growth metrics

    Returns:
        List of curated companies with CoreSignal data
    """
    try:
        companies = coresignal_service.get_available_companies()
        return jsonify({"companies": companies, "count": len(companies)})
    except Exception as e:
        print(f"Error getting available companies: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/company-growth/<ticker>", methods=["GET"])
def get_company_growth(ticker):
    """
    Get company growth metrics from CoreSignal (with RDS storage)

    Query params:
        - refresh: Set to 'true' to bypass cache and fetch fresh data

    Returns:
        - Employee count and headcount history
        - Active jobs by function and seniority
        - Hiring intensity metrics
        - from_cache: Boolean indicating if data came from cache
    """
    try:
        ticker = ticker.upper()

        # Check if ticker is in our curated list
        if not coresignal_service.is_valid_ticker(ticker):
            return (
                jsonify(
                    {
                        "error": f"Company {ticker} not in curated list",
                        "ticker": ticker,
                        "available": list(CORESIGNAL_COMPANIES.keys()),
                    }
                ),
                404,
            )

        print(f"Fetching CoreSignal growth data for {ticker}...")

        # Get company info
        company_info = CORESIGNAL_COMPANIES.get(ticker, {})

        # Get headcount history from RDS
        headcount_history = coresignal_service.get_headcount_history(ticker)

        # Get latest jobs data
        jobs_data = coresignal_service.get_latest_jobs(ticker)

        # Build response
        latest_employee_count = None
        if headcount_history:
            latest_employee_count = headcount_history[-1].get("employee_count")
        elif jobs_data:
            latest_employee_count = jobs_data.get("employee_count")

        response_data = {
            "ticker": ticker,
            "company": {
                "name": company_info.get("name", ticker),
                "domain": company_info.get("domain"),
                "coresignal_id": company_info.get("id"),
            },
            "employee_count": latest_employee_count,
            "headcount_history": headcount_history,
            "jobs_by_function": (
                jobs_data.get("jobs_by_function", {}) if jobs_data else {}
            ),
            "jobs_by_seniority": (
                jobs_data.get("jobs_by_seniority", {}) if jobs_data else {}
            ),
            "total_jobs": jobs_data.get("total_jobs", 0) if jobs_data else 0,
            "hiring_intensity": (
                jobs_data.get("hiring_intensity", 0) if jobs_data else 0
            ),
            "data_freshness": jobs_data.get("snapshot_date") if jobs_data else None,
            "from_cache": jobs_data.get("from_cache", False) if jobs_data else False,
        }

        return jsonify(response_data)

    except Exception as e:
        print(f"Error fetching company growth: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/company-growth/compare", methods=["GET"])
def compare_companies():
    """
    Compare growth metrics for multiple companies

    Query params:
        - tickers: Comma-separated list of tickers (max 3)

    Returns:
        Comprehensive comparison data for visualizations
    """
    try:
        tickers_param = request.args.get("tickers", "")
        if not tickers_param:
            return (
                jsonify(
                    {
                        "error": "tickers parameter required",
                        "example": "/api/company-growth/compare?tickers=CRWD,ZS,NET",
                    }
                ),
                400,
            )

        tickers = [t.strip().upper() for t in tickers_param.split(",")][:3]

        # Validate all tickers
        invalid = [t for t in tickers if not coresignal_service.is_valid_ticker(t)]
        if invalid:
            return (
                jsonify(
                    {
                        "error": f"Invalid tickers: {invalid}",
                        "available": list(CORESIGNAL_COMPANIES.keys()),
                    }
                ),
                400,
            )

        print(f"Comparing companies: {tickers}")

        # Get comparison data
        comparison_data = coresignal_service.get_comparison_data(tickers)

        return jsonify({"tickers": tickers, **comparison_data})

    except Exception as e:
        print(f"Error comparing companies: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/company-growth/<ticker>/jobs", methods=["GET"])
def get_company_jobs(ticker):
    """
    Get current job postings breakdown for a company

    Returns:
        - Jobs by function (Engineering, Sales, IT, etc.)
        - Jobs by seniority (Entry, Mid-Senior, Director, etc.)
        - Hiring intensity metrics
    """
    try:
        ticker = ticker.upper()

        if not coresignal_service.is_valid_ticker(ticker):
            return (
                jsonify(
                    {
                        "error": f"Company {ticker} not in curated list",
                        "available": list(CORESIGNAL_COMPANIES.keys()),
                    }
                ),
                404,
            )

        company_info = CORESIGNAL_COMPANIES.get(ticker, {})
        jobs_data = coresignal_service.get_latest_jobs(ticker)

        if not jobs_data:
            return jsonify({"error": "No jobs data available", "ticker": ticker}), 404

        return jsonify(
            {
                "ticker": ticker,
                "company_name": company_info.get("name", ticker),
                "jobs_by_function": jobs_data.get("jobs_by_function", {}),
                "jobs_by_seniority": jobs_data.get("jobs_by_seniority", {}),
                "total_jobs": jobs_data.get("total_jobs", 0),
                "employee_count": jobs_data.get("employee_count"),
                "hiring_intensity": jobs_data.get("hiring_intensity", 0),
                "snapshot_date": jobs_data.get("snapshot_date"),
                "from_cache": jobs_data.get("from_cache", False),
            }
        )

    except Exception as e:
        print(f"Error fetching jobs: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/company-growth/<ticker>/headcount", methods=["GET"])
def get_company_headcount(ticker):
    """
    Get headcount history for a company

    Query params:
        - limit: Max records to return (default: 100)

    Returns:
        List of headcount records over time
    """
    try:
        ticker = ticker.upper()
        limit = int(request.args.get("limit", 100))

        if not coresignal_service.is_valid_ticker(ticker):
            return (
                jsonify(
                    {
                        "error": f"Company {ticker} not in curated list",
                        "available": list(CORESIGNAL_COMPANIES.keys()),
                    }
                ),
                404,
            )

        company_info = CORESIGNAL_COMPANIES.get(ticker, {})
        headcount_history = coresignal_service.get_headcount_history(
            ticker, limit=limit
        )

        return jsonify(
            {
                "ticker": ticker,
                "company_name": company_info.get("name", ticker),
                "headcount_history": headcount_history,
                "count": len(headcount_history),
            }
        )

    except Exception as e:
        print(f"Error fetching headcount: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ============================================================================
# LEX CHATBOT ENDPOINTS (Amazon Lex V2 Integration)
# ============================================================================


@app.route("/api/lex/message", methods=["POST"])
def lex_message():
    """
    Send a message to the Lex chatbot and get a response

    Request body:
        {
            "message": "user's message text",
            "sessionId": "optional session ID for conversation context"
        }

    Returns:
        {
            "message": "bot's response",
            "sessionId": "session ID for follow-up messages",
            "intent": "detected intent name",
            "slots": {}
        }
    """
    try:
        data = request.json
        message = data.get("message", "")
        session_id = data.get("sessionId")

        if not message:
            return jsonify({"error": "Message is required"}), 400

        response = lex_service.send_message(message, session_id)
        return jsonify(response)

    except Exception as e:
        print(f"Error in Lex message: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/lex/session", methods=["DELETE"])
def lex_end_session():
    """End a Lex conversation session"""
    try:
        session_id = request.args.get("sessionId")
        if not session_id:
            return jsonify({"error": "sessionId is required"}), 400

        success = lex_service.end_session(session_id)
        return jsonify(
            {
                "success": success,
                "message": "Session ended" if success else "Failed to end session",
            }
        )

    except Exception as e:
        print(f"Error ending Lex session: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================================
# LLM CHAT ENDPOINTS (GraphRAG-Powered Assistant)
# ============================================================================

# Lazy-loaded services for LLM chat
_llm_chat_service = None
_memory_service = None
_neo4j_service = None


def get_llm_chat():
    """
    Lazy load LLM chat service.

    Uses USE_LANGCHAIN env var to determine which service to use:
    - USE_LANGCHAIN=true: LangChain agent with Claude 3.5 Sonnet (better reasoning)
    - USE_LANGCHAIN=false (default): Legacy service with Claude 3 Haiku (lower cost)

    For assessment, set USE_LANGCHAIN=true to demonstrate LangChain integration.
    """
    global _llm_chat_service
    if _llm_chat_service is None:
        try:
            from services.llm_chat_service import get_llm_chat_service

            _llm_chat_service = get_llm_chat_service()
            print("✅ LLM chat service initialized")
        except Exception as e:
            print(f"⚠️  LLM chat service not available: {e}")
    return _llm_chat_service


def get_memory():
    """Lazy load memory service"""
    global _memory_service
    if _memory_service is None:
        try:
            from services.memory_service import MemoryService

            _memory_service = MemoryService()
            _memory_service.init_schema()
            print("✅ Memory service initialized")
        except Exception as e:
            print(f"⚠️  Memory service not available: {e}")
    return _memory_service


def get_neo4j():
    """Lazy load Neo4j service"""
    global _neo4j_service
    if _neo4j_service is None:
        try:
            from services.neo4j_service import Neo4jService

            _neo4j_service = Neo4jService()
            if _neo4j_service.is_connected():
                print("✅ Neo4j service connected")
            else:
                print("⚠️  Neo4j service initialized but not connected")
        except Exception as e:
            print(f"⚠️  Neo4j service not available: {e}")
    return _neo4j_service


@app.route("/api/chat", methods=["POST"])
def chat():
    """
    Main chat endpoint for GraphRAG-powered LLM assistant

    Request body:
        {
            "message": "user's message",
            "session_id": "optional session ID",
            "user_email": "optional email for tracking"
        }

    Headers:
        Authorization: Bearer <token> (optional, for protected operations)

    Returns:
        {
            "response": "assistant's response",
            "session_id": "session ID for follow-up",
            "tools_used": ["list of tools used"],
            "timestamp": "ISO timestamp"
        }
    """
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Request body required"}), 400

        message = data.get("message", "").strip()
        if not message:
            return jsonify({"error": "Message is required"}), 400

        session_id = data.get("session_id")
        user_email = data.get("user_email")

        # Get auth token if present
        auth_header = request.headers.get("Authorization", "")
        auth_token = None
        if auth_header.startswith("Bearer "):
            auth_token = auth_header.split(" ", 1)[1]

        # Get LLM service
        llm_service = get_llm_chat()
        if not llm_service:
            return (
                jsonify(
                    {
                        "error": "LLM service not available",
                        "message": "The AI assistant is currently unavailable. Please try again later.",
                    }
                ),
                503,
            )

        # Generate session ID if not provided
        if not session_id:
            import uuid

            session_id = str(uuid.uuid4())

        # Process chat message
        response = llm_service.chat(
            message=message,
            session_id=session_id,
            user_email=user_email,
            auth_token=auth_token,
        )

        return jsonify(response)

    except Exception as e:
        print(f"Error in chat: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/chat/history/<session_id>", methods=["GET"])
def get_chat_history(session_id):
    """
    Get conversation history for a session

    Returns:
        List of messages with role, content, and timestamp
    """
    try:
        limit = int(request.args.get("limit", 50))

        memory = get_memory()
        if not memory:
            return jsonify({"error": "Memory service not available"}), 503

        messages = memory.get_session_history(session_id, limit=limit)

        return jsonify(
            {"session_id": session_id, "messages": messages, "count": len(messages)}
        )

    except Exception as e:
        print(f"Error getting chat history: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/chat/session/<session_id>", methods=["DELETE"])
def delete_chat_session(session_id):
    """Delete a chat session and its history"""
    try:
        memory = get_memory()
        if not memory:
            return jsonify({"error": "Memory service not available"}), 503

        memory.delete_session(session_id)

        return jsonify({"success": True, "message": f"Session {session_id} deleted"})

    except Exception as e:
        print(f"Error deleting chat session: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================================
# KNOWLEDGE GRAPH ENDPOINTS (Neo4j)
# ============================================================================


@app.route("/api/knowledge-graph/<ticker>", methods=["GET"])
def get_knowledge_graph(ticker):
    """
    Get knowledge graph data for visualization

    Query params:
        depth: How many hops from company (default: 2)
        include_entities: Include Entity nodes (default: true)
        include_concepts: Include Concept nodes (default: true)
        include_documents: Include Document nodes (default: false)
        limit: Max nodes (default: 100)

    Returns:
        Graph data with nodes and links for visualization
    """
    try:
        ticker = ticker.upper()

        neo4j = get_neo4j()
        if not neo4j or not neo4j.is_connected():
            return (
                jsonify(
                    {
                        "error": "Knowledge graph not available",
                        "message": "Neo4j service is not connected",
                    }
                ),
                503,
            )

        depth = int(request.args.get("depth", 2))
        include_organizations = (
            request.args.get("include_organizations", "true").lower() == "true"
        )
        include_locations = (
            request.args.get("include_locations", "true").lower() == "true"
        )
        include_concepts = (
            request.args.get("include_concepts", "true").lower() == "true"
        )
        include_documents = (
            request.args.get("include_documents", "false").lower() == "true"
        )
        limit = int(request.args.get("limit", 100))

        graph_data = neo4j.get_company_graph(
            ticker=ticker,
            depth=depth,
            include_organizations=include_organizations,
            include_locations=include_locations,
            include_concepts=include_concepts,
            include_documents=include_documents,
            limit=limit,
        )

        return jsonify({"ticker": ticker, **graph_data})

    except Exception as e:
        print(f"Error getting knowledge graph: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/knowledge-graph/query", methods=["POST"])
def query_knowledge_graph():
    """
    Natural language query over knowledge graph

    Request body:
        {
            "query": "natural language query",
            "ticker": "optional ticker to filter"
        }

    Returns:
        Query results with relevant entities and context
    """
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Request body required"}), 400

        query = data.get("query", "").strip()
        if not query:
            return jsonify({"error": "Query is required"}), 400

        ticker = data.get("ticker")

        neo4j = get_neo4j()
        if not neo4j or not neo4j.is_connected():
            return (
                jsonify(
                    {
                        "error": "Knowledge graph not available",
                        "message": "Neo4j service is not connected",
                    }
                ),
                503,
            )

        results = neo4j.semantic_query(query, ticker)

        return jsonify(results)

    except Exception as e:
        print(f"Error in knowledge graph query: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/knowledge-graph/stats", methods=["GET"])
def get_knowledge_graph_stats():
    """Get knowledge graph statistics"""
    try:
        neo4j = get_neo4j()
        if not neo4j or not neo4j.is_connected():
            return (
                jsonify({"error": "Knowledge graph not available", "connected": False}),
                503,
            )

        stats = neo4j.get_stats()

        return jsonify({"connected": True, **stats})

    except Exception as e:
        print(f"Error getting graph stats: {e}")
        return jsonify({"error": str(e), "connected": False}), 500


@app.route("/api/cypher/query", methods=["POST"])
def execute_cypher():
    """
    Execute a Cypher query (read-only, for Cypher Console)

    Request body:
        {
            "query": "MATCH (o:Organization) RETURN o LIMIT 10"
        }

    Returns:
        Query results with columns and records
    """
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Request body required"}), 400

        query = data.get("query", "").strip()
        if not query:
            return jsonify({"error": "Query is required"}), 400

        neo4j = get_neo4j()
        if not neo4j or not neo4j.is_connected():
            return (
                jsonify(
                    {
                        "error": "Knowledge graph not available",
                        "message": "Neo4j service is not connected",
                    }
                ),
                503,
            )

        # Execute with security filtering (blocks write operations)
        results = neo4j.execute_cypher_safe(query)

        if "error" in results:
            return jsonify(results), 400

        return jsonify(results)

    except Exception as e:
        print(f"Error executing Cypher: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ============================================================================
# RAG (Retrieval-Augmented Generation) ENDPOINTS
# ============================================================================

# Lazy-loaded RAG service
_rag_service = None


def get_rag():
    """Lazy load RAG service"""
    global _rag_service
    if _rag_service is None:
        try:
            from services.rag_service import RAGService

            _rag_service = RAGService()
            print("✅ RAG service initialized")
        except Exception as e:
            print(f"⚠️  RAG service not available: {e}")
    return _rag_service


@app.route("/api/rag/search", methods=["POST"])
def rag_search():
    """
    Search indexed documents using semantic similarity

    Request body:
        {
            "query": "natural language query",
            "ticker": "optional ticker to filter",
            "top_k": 5
        }

    Returns:
        List of relevant document chunks with metadata
    """
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Request body required"}), 400

        query = data.get("query", "").strip()
        if not query:
            return jsonify({"error": "Query is required"}), 400

        ticker = data.get("ticker")
        top_k = int(data.get("top_k", 5))

        rag = get_rag()
        if not rag:
            return (
                jsonify(
                    {
                        "error": "RAG service not available",
                        "message": "Document search is not connected",
                    }
                ),
                503,
            )

        if ticker:
            ticker = ticker.upper()

        results = rag.search(query, ticker=ticker, top_k=top_k)

        return jsonify(
            {
                "query": query,
                "ticker": ticker,
                "results": results,
                "count": len(results),
            }
        )

    except Exception as e:
        print(f"Error in RAG search: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/rag/index", methods=["POST"])
@require_cognito_auth
def rag_index_document():
    """
    Index a document from S3 for RAG retrieval

    Request body:
        {
            "s3_key": "raw/sec/CRWD_10-K_2024.pdf",
            "ticker": "CRWD",
            "document_type": "10-K"
        }

    Returns:
        Indexing result with chunk count
    """
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Request body required"}), 400

        s3_key = data.get("s3_key", "").strip()
        if not s3_key:
            return jsonify({"error": "s3_key is required"}), 400

        ticker = data.get("ticker", "").upper()
        document_type = data.get("document_type", "")

        rag = get_rag()
        if not rag:
            return (
                jsonify(
                    {
                        "error": "RAG service not available",
                        "message": "Document indexing is not connected",
                    }
                ),
                503,
            )

        # Import and use OCR service to extract text
        from services.rag_service import index_s3_document

        result = index_s3_document(s3_key, ticker, document_type)

        return jsonify(result)

    except Exception as e:
        print(f"Error indexing document: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/rag/index-ticker/<ticker>", methods=["POST"])
@require_cognito_auth
def rag_index_ticker(ticker):
    """
    Index all documents for a ticker from S3

    Query params:
        document_types: Comma-separated list (e.g., "10-K,10-Q,transcript")
        limit: Max documents to index (default: 50)

    Returns:
        Summary of indexed documents
    """
    try:
        ticker = ticker.upper()
        document_types = request.args.get("document_types", "").split(",")
        document_types = [dt.strip() for dt in document_types if dt.strip()]
        limit = int(request.args.get("limit", 50))

        rag = get_rag()
        if not rag:
            return (
                jsonify(
                    {
                        "error": "RAG service not available",
                        "message": "Document indexing is not connected",
                    }
                ),
                503,
            )

        # Get artifacts for this ticker
        artifacts = db_service.get_artifacts_by_ticker(ticker)
        if not artifacts:
            artifacts = s3_service.get_artifacts_by_ticker(ticker)

        if not artifacts:
            return (
                jsonify(
                    {"error": f"No artifacts found for {ticker}", "ticker": ticker}
                ),
                404,
            )

        # Filter by document type if specified
        if document_types:
            artifacts = [
                a
                for a in artifacts
                if any(dt in a.get("artifact_type", "") for dt in document_types)
            ]

        # Limit documents
        artifacts = artifacts[:limit]

        from services.rag_service import index_s3_document

        results = []
        for artifact in artifacts:
            s3_key = artifact.get("s3_key", "")
            doc_type = artifact.get("artifact_type", "")
            if s3_key:
                try:
                    result = index_s3_document(s3_key, ticker, doc_type)
                    results.append({"s3_key": s3_key, "status": "success", **result})
                except Exception as e:
                    results.append(
                        {"s3_key": s3_key, "status": "error", "error": str(e)}
                    )

        success_count = sum(1 for r in results if r["status"] == "success")

        return jsonify(
            {
                "ticker": ticker,
                "documents_indexed": success_count,
                "total_attempted": len(results),
                "results": results,
            }
        )

    except Exception as e:
        print(f"Error indexing ticker documents: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/rag/stats", methods=["GET"])
def rag_stats():
    """
    Get RAG index statistics

    Query params:
        ticker: Optional ticker to filter stats

    Returns:
        Document and chunk counts
    """
    try:
        ticker = request.args.get("ticker")

        rag = get_rag()
        if not rag:
            return (
                jsonify(
                    {
                        "error": "RAG service not available",
                        "message": "RAG statistics not available",
                    }
                ),
                503,
            )

        if ticker:
            ticker = ticker.upper()

        stats = rag.get_stats(ticker=ticker)

        return jsonify(stats)

    except Exception as e:
        print(f"Error getting RAG stats: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================================
# AUTHENTICATION ENDPOINTS (Cognito)
# ============================================================================


@app.route("/api/auth/status", methods=["GET"])
def auth_status():
    """
    Check current authentication status

    Headers:
        Authorization: Bearer <token>

    Returns:
        Authentication status and user info if authenticated
    """
    try:
        from services.cognito_auth_service import get_auth_status

        status = get_auth_status()
        return jsonify(status)
    except Exception as e:
        print(f"Error checking auth status: {e}")
        return jsonify({"authenticated": False, "error": str(e)})


@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    """
    Authenticate user with Cognito.

    Request body:
        {
            "email": "user@example.com",
            "password": "password123"
        }

    Returns:
        JWT tokens if successful, error otherwise
    """
    import boto3

    try:
        data = request.json
        if not data:
            return jsonify({"error": "Request body required"}), 400

        email = data.get("email", "").strip()
        password = data.get("password", "")

        if not email or not password:
            return jsonify({"error": "Email and password required"}), 400

        # Get Cognito configuration
        region = os.environ.get("AWS_REGION", "us-west-2")
        client_id = os.environ.get("COGNITO_CLIENT_ID", "")

        if not client_id:
            return jsonify({"error": "Cognito not configured"}), 503

        # Authenticate with Cognito
        cognito = boto3.client("cognito-idp", region_name=region)

        try:
            response = cognito.initiate_auth(
                ClientId=client_id,
                AuthFlow="USER_PASSWORD_AUTH",
                AuthParameters={"USERNAME": email, "PASSWORD": password},
            )

            # Check if password change required (NEW_PASSWORD_REQUIRED challenge)
            if response.get("ChallengeName") == "NEW_PASSWORD_REQUIRED":
                return jsonify(
                    {
                        "challenge": "NEW_PASSWORD_REQUIRED",
                        "session": response.get("Session"),
                        "message": "Please set a new password",
                    }
                )

            # Successful authentication
            auth_result = response.get("AuthenticationResult", {})

            return jsonify(
                {
                    "success": True,
                    "accessToken": auth_result.get("AccessToken"),
                    "idToken": auth_result.get("IdToken"),
                    "refreshToken": auth_result.get("RefreshToken"),
                    "expiresIn": auth_result.get("ExpiresIn"),
                }
            )

        except cognito.exceptions.NotAuthorizedException:
            return jsonify({"error": "Invalid email or password"}), 401
        except cognito.exceptions.UserNotFoundException:
            return jsonify({"error": "User not found"}), 401
        except cognito.exceptions.UserNotConfirmedException:
            return jsonify({"error": "Email not verified"}), 401
        except Exception as e:
            print(f"Cognito auth error: {e}")
            return jsonify({"error": str(e)}), 401

    except Exception as e:
        print(f"Login error: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/auth/signup", methods=["POST"])
def auth_signup():
    """
    Register a new user with Cognito.

    Request body:
        {
            "email": "user@example.com",
            "password": "Password123"
        }

    Returns:
        Success message if registration successful, error otherwise.
        User will receive verification code via email.
    """
    import boto3

    try:
        data = request.json
        if not data:
            return jsonify({"error": "Request body required"}), 400

        email = data.get("email", "").strip()
        password = data.get("password", "")

        if not email or not password:
            return jsonify({"error": "Email and password required"}), 400

        # Get Cognito configuration
        region = os.environ.get("AWS_REGION", "us-west-2")
        client_id = os.environ.get("COGNITO_CLIENT_ID", "")

        if not client_id:
            return jsonify({"error": "Cognito not configured"}), 503

        # Register with Cognito
        cognito = boto3.client("cognito-idp", region_name=region)

        try:
            response = cognito.sign_up(
                ClientId=client_id,
                Username=email,
                Password=password,
                UserAttributes=[{"Name": "email", "Value": email}],
            )

            return jsonify(
                {
                    "success": True,
                    "message": "Verification code sent to your email",
                    "userSub": response.get("UserSub"),
                }
            )

        except cognito.exceptions.UsernameExistsException:
            return jsonify({"error": "An account with this email already exists"}), 409
        except cognito.exceptions.InvalidPasswordException as e:
            return jsonify({"error": str(e)}), 400
        except cognito.exceptions.InvalidParameterException as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            print(f"Cognito signup error: {e}")
            return jsonify({"error": str(e)}), 400

    except Exception as e:
        print(f"Signup error: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/auth/confirm-signup", methods=["POST"])
def auth_confirm_signup():
    """
    Confirm user registration with verification code.

    Request body:
        {
            "email": "user@example.com",
            "code": "123456"
        }

    Returns:
        Success message if confirmed, error otherwise.
    """
    import boto3

    try:
        data = request.json
        if not data:
            return jsonify({"error": "Request body required"}), 400

        email = data.get("email", "").strip()
        code = data.get("code", "").strip()

        if not email or not code:
            return jsonify({"error": "Email and verification code required"}), 400

        # Get Cognito configuration
        region = os.environ.get("AWS_REGION", "us-west-2")
        client_id = os.environ.get("COGNITO_CLIENT_ID", "")

        if not client_id:
            return jsonify({"error": "Cognito not configured"}), 503

        # Confirm signup with Cognito
        cognito = boto3.client("cognito-idp", region_name=region)

        try:
            cognito.confirm_sign_up(
                ClientId=client_id,
                Username=email,
                ConfirmationCode=code,
            )

            return jsonify(
                {"success": True, "message": "Email verified! You can now sign in."}
            )

        except cognito.exceptions.CodeMismatchException:
            return jsonify({"error": "Invalid verification code"}), 400
        except cognito.exceptions.ExpiredCodeException:
            return jsonify({"error": "Verification code expired"}), 400
        except cognito.exceptions.UserNotFoundException:
            return jsonify({"error": "User not found"}), 404
        except Exception as e:
            print(f"Cognito confirm error: {e}")
            return jsonify({"error": str(e)}), 400

    except Exception as e:
        print(f"Confirm signup error: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/auth/resend-code", methods=["POST"])
def auth_resend_code():
    """
    Resend verification code to user's email.

    Request body:
        {
            "email": "user@example.com"
        }

    Returns:
        Success message if code sent, error otherwise.
    """
    import boto3

    try:
        data = request.json
        if not data:
            return jsonify({"error": "Request body required"}), 400

        email = data.get("email", "").strip()

        if not email:
            return jsonify({"error": "Email required"}), 400

        # Get Cognito configuration
        region = os.environ.get("AWS_REGION", "us-west-2")
        client_id = os.environ.get("COGNITO_CLIENT_ID", "")

        if not client_id:
            return jsonify({"error": "Cognito not configured"}), 503

        # Resend code via Cognito
        cognito = boto3.client("cognito-idp", region_name=region)

        try:
            cognito.resend_confirmation_code(ClientId=client_id, Username=email)

            return jsonify(
                {"success": True, "message": "Verification code sent to your email"}
            )

        except cognito.exceptions.UserNotFoundException:
            return jsonify({"error": "User not found"}), 404
        except cognito.exceptions.InvalidParameterException:
            return jsonify({"error": "User is already verified"}), 400
        except Exception as e:
            print(f"Cognito resend error: {e}")
            return jsonify({"error": str(e)}), 400

    except Exception as e:
        print(f"Resend code error: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/auth/new-password", methods=["POST"])
def auth_new_password():
    """
    Complete NEW_PASSWORD_REQUIRED challenge.

    Request body:
        {
            "email": "user@example.com",
            "newPassword": "NewPassword123",
            "session": "session_from_login_response"
        }

    Returns:
        JWT tokens if successful
    """
    import boto3

    try:
        data = request.json
        if not data:
            return jsonify({"error": "Request body required"}), 400

        email = data.get("email", "").strip()
        new_password = data.get("newPassword", "")
        session = data.get("session", "")

        if not email or not new_password or not session:
            return jsonify({"error": "Email, newPassword, and session required"}), 400

        region = os.environ.get("AWS_REGION", "us-west-2")
        client_id = os.environ.get("COGNITO_CLIENT_ID", "")

        if not client_id:
            return jsonify({"error": "Cognito not configured"}), 503

        cognito = boto3.client("cognito-idp", region_name=region)

        try:
            response = cognito.respond_to_auth_challenge(
                ClientId=client_id,
                ChallengeName="NEW_PASSWORD_REQUIRED",
                Session=session,
                ChallengeResponses={
                    "USERNAME": email,
                    "NEW_PASSWORD": new_password,
                },
            )

            auth_result = response.get("AuthenticationResult", {})

            return jsonify(
                {
                    "success": True,
                    "accessToken": auth_result.get("AccessToken"),
                    "idToken": auth_result.get("IdToken"),
                    "refreshToken": auth_result.get("RefreshToken"),
                    "expiresIn": auth_result.get("ExpiresIn"),
                }
            )

        except Exception as e:
            print(f"New password error: {e}")
            return jsonify({"error": str(e)}), 400

    except Exception as e:
        print(f"New password error: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/auth/refresh", methods=["POST"])
def auth_refresh():
    """
    Refresh access token using refresh token.

    Request body:
        {
            "refreshToken": "refresh_token_here"
        }

    Returns:
        New access and ID tokens
    """
    import boto3

    try:
        data = request.json
        if not data:
            return jsonify({"error": "Request body required"}), 400

        refresh_token = data.get("refreshToken", "")

        if not refresh_token:
            return jsonify({"error": "Refresh token required"}), 400

        region = os.environ.get("AWS_REGION", "us-west-2")
        client_id = os.environ.get("COGNITO_CLIENT_ID", "")

        if not client_id:
            return jsonify({"error": "Cognito not configured"}), 503

        cognito = boto3.client("cognito-idp", region_name=region)

        try:
            response = cognito.initiate_auth(
                ClientId=client_id,
                AuthFlow="REFRESH_TOKEN_AUTH",
                AuthParameters={"REFRESH_TOKEN": refresh_token},
            )

            auth_result = response.get("AuthenticationResult", {})

            return jsonify(
                {
                    "success": True,
                    "accessToken": auth_result.get("AccessToken"),
                    "idToken": auth_result.get("IdToken"),
                    "expiresIn": auth_result.get("ExpiresIn"),
                }
            )

        except cognito.exceptions.NotAuthorizedException:
            return jsonify({"error": "Invalid or expired refresh token"}), 401
        except Exception as e:
            print(f"Token refresh error: {e}")
            return jsonify({"error": str(e)}), 401

    except Exception as e:
        print(f"Refresh error: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    """
    Log out user by invalidating tokens.

    Headers:
        Authorization: Bearer <access_token>

    Returns:
        Success message
    """
    import boto3

    try:
        # Get access token from header
        auth_header = request.headers.get("Authorization", "")
        access_token = None
        if auth_header.startswith("Bearer "):
            access_token = auth_header.split(" ", 1)[1]

        if not access_token:
            # No token to invalidate, just return success
            return jsonify({"success": True, "message": "Logged out"})

        region = os.environ.get("AWS_REGION", "us-west-2")

        cognito = boto3.client("cognito-idp", region_name=region)

        try:
            # Global sign out invalidates all tokens for the user
            cognito.global_sign_out(AccessToken=access_token)
            return jsonify({"success": True, "message": "Logged out successfully"})
        except cognito.exceptions.NotAuthorizedException:
            # Token already invalid, that's fine
            return jsonify({"success": True, "message": "Logged out"})
        except Exception as e:
            print(f"Logout error: {e}")
            # Still return success - client will clear tokens anyway
            return jsonify({"success": True, "message": "Logged out"})

    except Exception as e:
        print(f"Logout error: {e}")
        return jsonify({"success": True, "message": "Logged out"})


@app.route("/api/auth/update-profile", methods=["POST"])
def auth_update_profile():
    """
    Update user profile attributes in Cognito.

    Headers:
        Authorization: Bearer <access_token>

    Request body:
        {
            "name": "John Smith"
        }

    Returns:
        Success message with updated user info
    """
    import boto3

    try:
        # Get access token from header
        auth_header = request.headers.get("Authorization", "")
        access_token = None
        if auth_header.startswith("Bearer "):
            access_token = auth_header.split(" ", 1)[1]

        if not access_token:
            return jsonify({"error": "Authentication required"}), 401

        data = request.json
        if not data:
            return jsonify({"error": "Request body required"}), 400

        name = data.get("name", "").strip()
        if not name:
            return jsonify({"error": "Name is required"}), 400

        region = os.environ.get("AWS_REGION", "us-west-2")
        cognito = boto3.client("cognito-idp", region_name=region)

        try:
            # Update user attributes
            cognito.update_user_attributes(
                AccessToken=access_token,
                UserAttributes=[{"Name": "name", "Value": name}],
            )

            return jsonify(
                {"success": True, "message": "Profile updated", "name": name}
            )

        except cognito.exceptions.NotAuthorizedException:
            return jsonify({"error": "Invalid or expired token"}), 401
        except Exception as e:
            print(f"Profile update error: {e}")
            return jsonify({"error": str(e)}), 400

    except Exception as e:
        print(f"Update profile error: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ============================================================================
# ADMIN ENDPOINTS - Database migrations and maintenance
# ============================================================================


@app.route("/api/admin/neo4j/write", methods=["POST"])
def admin_neo4j_write():
    """
    Execute a write Cypher query (admin only, for cleanup operations)

    Request body:
        {
            "query": "MATCH (n) WHERE id(n) = 123 DELETE n",
            "admin_key": "cleanup-2026"
        }

    Returns:
        Result of write operation
    """
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Request body required"}), 400

        # Simple admin key check (not for production security, just to prevent accidental calls)
        admin_key = data.get("admin_key", "")
        if admin_key != "cleanup-2026":
            return jsonify({"error": "Invalid admin key"}), 403

        query = data.get("query", "").strip()
        if not query:
            return jsonify({"error": "Query is required"}), 400

        neo4j = get_neo4j()
        if not neo4j or not neo4j.is_connected():
            return (
                jsonify(
                    {
                        "error": "Knowledge graph not available",
                        "message": "Neo4j service is not connected",
                    }
                ),
                503,
            )

        # Execute write operation
        result = neo4j.execute_write(query)

        return jsonify({"success": True, "result": result})

    except Exception as e:
        print(f"Error executing admin Cypher write: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/migrate", methods=["POST"])
@require_cognito_auth
def run_migration():
    """Run database migrations - add alternate_names column to companies. Requires auth."""
    try:
        conn = db_service._get_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500

        cursor = conn.cursor()

        # Add alternate_names column if it doesn't exist
        cursor.execute(
            """
            ALTER TABLE companies
            ADD COLUMN IF NOT EXISTS alternate_names TEXT
        """
        )
        conn.commit()

        cursor.close()
        return jsonify(
            {
                "success": True,
                "message": "Migration completed - alternate_names column added",
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/companies/<ticker>/alternate-names", methods=["PUT"])
@require_cognito_auth
def set_alternate_names(ticker):
    """Set alternate names for a company. Requires auth."""
    try:
        data = request.get_json()
        alternate_names = data.get("alternate_names", "")

        conn = db_service._get_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500

        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE companies
            SET alternate_names = %s
            WHERE ticker = %s
        """,
            (alternate_names, ticker.upper()),
        )
        conn.commit()

        updated = cursor.rowcount
        cursor.close()

        if updated > 0:
            return jsonify(
                {
                    "success": True,
                    "ticker": ticker.upper(),
                    "alternate_names": alternate_names,
                }
            )
        else:
            return jsonify({"error": f"Company {ticker} not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/build-graph/<ticker>", methods=["POST"])
@require_cognito_auth
def build_knowledge_graph(ticker):
    """
    Build knowledge graph for a company from SEC filings and transcripts.

    Requires authentication.

    This uses AWS Comprehend to extract entities from documents and
    populates the Neo4j knowledge graph.
    """
    try:
        ticker = ticker.upper()

        # Check if Neo4j is connected
        neo4j = get_neo4j()
        if not neo4j or not neo4j.is_connected():
            return (
                jsonify(
                    {
                        "error": "Knowledge graph not available",
                        "message": "Neo4j service is not connected",
                    }
                ),
                503,
            )

        # Import and run graph builder
        from services.graph_builder_service import GraphBuilderService

        builder = GraphBuilderService()

        # Build graph for this ticker
        result = builder.build_graph_for_ticker(
            ticker=ticker,
            include_entities=True,
            include_concepts=True,
            include_key_phrases=True,
        )

        return jsonify({"success": True, "ticker": ticker, **result})

    except Exception as e:
        print(f"Error building knowledge graph: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/build-graph", methods=["POST"])
@require_cognito_auth
def build_all_knowledge_graphs():
    """
    Build knowledge graph for all companies in the database.

    Requires authentication.
    """
    try:
        # Check if Neo4j is connected
        neo4j = get_neo4j()
        if not neo4j or not neo4j.is_connected():
            return (
                jsonify(
                    {
                        "error": "Knowledge graph not available",
                        "message": "Neo4j service is not connected",
                    }
                ),
                503,
            )

        # Get all companies from database
        companies = db_service.get_all_companies()

        from services.graph_builder_service import GraphBuilderService

        builder = GraphBuilderService()

        results = []
        for company in companies:
            ticker = company.get("ticker")
            if ticker:
                try:
                    result = builder.build_graph_for_ticker(ticker)
                    results.append({"ticker": ticker, "status": "success", **result})
                except Exception as e:
                    results.append(
                        {"ticker": ticker, "status": "error", "error": str(e)}
                    )

        # After building all company graphs, infer relationships
        relationship_stats = {
            "entity_relationships": 0,
            "concept_relationships": 0,
            "company_concept_associations": 0,
        }

        try:
            relationship_stats["entity_relationships"] = (
                builder.infer_entity_relationships()
            )
            relationship_stats["concept_relationships"] = (
                builder.infer_concept_relationships()
            )
            relationship_stats["company_concept_associations"] = (
                builder.create_company_concept_associations()
            )
        except Exception as e:
            print(f"Warning: Error inferring relationships: {e}")

        return jsonify(
            {
                "success": True,
                "companies_processed": len(results),
                "results": results,
                "relationships": relationship_stats,
            }
        )

    except Exception as e:
        print(f"Error building knowledge graphs: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/clear-graph", methods=["POST"])
@require_cognito_auth
def clear_knowledge_graph():
    """
    Clear all nodes and relationships from the knowledge graph.

    Requires authentication. WARNING: This is destructive!
    """
    try:
        neo4j = get_neo4j()
        if not neo4j or not neo4j.is_connected():
            return (
                jsonify(
                    {
                        "error": "Knowledge graph not available",
                        "message": "Neo4j service is not connected",
                    }
                ),
                503,
            )

        # Clear the graph
        result = neo4j.clear_graph()

        # Create indexes for new schema
        neo4j.create_indexes()

        return jsonify(
            {
                "success": True,
                "message": "Knowledge graph cleared and indexes created",
                "result": result,
            }
        )

    except Exception as e:
        print(f"Error clearing knowledge graph: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/infer-relationships", methods=["POST"])
@require_cognito_auth
def infer_graph_relationships():
    """
    Infer relationships in the knowledge graph.

    Creates:
    - Entity co-occurrence relationships (RELATED_TO between organizations)
    - Concept co-occurrence relationships (RELATED_TO between concepts)
    - Company-concept associations (ASSOCIATED_WITH with frequency/source)

    Requires authentication.
    """
    try:
        neo4j = get_neo4j()
        if not neo4j or not neo4j.is_connected():
            return (
                jsonify(
                    {
                        "error": "Knowledge graph not available",
                        "message": "Neo4j service is not connected",
                    }
                ),
                503,
            )

        from services.graph_builder_service import get_graph_builder_service

        builder = get_graph_builder_service()

        # Get optional ticker filter from request
        data = request.json or {}
        ticker = data.get("ticker")
        if ticker:
            ticker = ticker.upper()

        # Infer all relationship types
        results = {
            "entity_relationships": builder.infer_entity_relationships(ticker),
            "concept_relationships": builder.infer_concept_relationships(ticker),
            "company_concept_associations": builder.create_company_concept_associations(
                ticker
            ),
        }

        return jsonify(
            {
                "success": True,
                "ticker_filter": ticker,
                **results,
            }
        )

    except Exception as e:
        print(f"Error inferring relationships: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/sync-cache-to-graph", methods=["POST"])
@require_cognito_auth
def sync_cache_to_graph():
    """
    Sync PostgreSQL cache data to Neo4j knowledge graph.

    Creates nodes from cache tables:
    - SentimentSnapshot from sentiment_cache
    - GrowthSnapshot from growth_cache
    - ForecastSnapshot from forecast_cache
    - HeadcountPoint from headcount_history
    - JobFunction from jobs_by_function in growth_cache

    Request body (optional):
        {
            "ticker": "CRWD"  // Optional: sync single company
        }

    Requires authentication.
    """
    try:
        neo4j = get_neo4j()
        if not neo4j or not neo4j.is_connected():
            return (
                jsonify(
                    {
                        "error": "Knowledge graph not available",
                        "message": "Neo4j service is not connected",
                    }
                ),
                503,
            )

        from services.graph_enrichment_service import get_graph_enrichment_service

        enrichment_svc = get_graph_enrichment_service()

        data = request.json or {}
        ticker = data.get("ticker")

        if ticker:
            ticker = ticker.upper()
            results = enrichment_svc.enrich_graph_for_ticker(ticker)
        else:
            results = enrichment_svc.enrich_all_tickers()

        return jsonify(
            {
                "success": True,
                "message": f"Cache data synced to Neo4j"
                + (f" for {ticker}" if ticker else " for all companies"),
                "results": results,
            }
        )

    except Exception as e:
        print(f"Error syncing cache to graph: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/knowledge-graph/schema", methods=["GET"])
def get_graph_schema():
    """
    Get knowledge graph schema and taxonomy information.

    Public endpoint - returns schema documentation.
    """
    try:
        neo4j = get_neo4j()
        if not neo4j:
            return jsonify({"error": "Neo4j service not available"}), 503

        schema = neo4j.get_schema_info()

        # Add taxonomy information
        try:
            from data.taxonomy import CYBER_SECTORS, GICS_SECTORS

            schema["cyber_sectors"] = {
                key: {"name": val["name"], "description": val["description"]}
                for key, val in CYBER_SECTORS.items()
            }
            schema["gics_sectors"] = GICS_SECTORS
        except ImportError:
            pass

        return jsonify(schema)

    except Exception as e:
        print(f"Error getting graph schema: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================================
# PATENT ENDPOINTS
# ============================================================================


def get_patent_service():
    """Lazy load patent service"""
    try:
        from services.patent_service import patent_service

        return patent_service
    except Exception as e:
        print(f"Error loading patent service: {e}")
        return None


@app.route("/api/patents/search", methods=["GET"])
def search_patents():
    """
    Search for patents by assignee (company) or inventor name

    Query params:
        assignee: Company/organization name
        inventor: Inventor name
        start_date: Start date (YYYYMMDD format)
        end_date: End date (YYYYMMDD format)
        limit: Max results (default: 50)

    Returns:
        List of matching patents
    """
    try:
        patent_svc = get_patent_service()
        if not patent_svc:
            return jsonify({"error": "Patent service not available"}), 503

        assignee = request.args.get("assignee", "").strip()
        inventor = request.args.get("inventor", "").strip()
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")
        limit = int(request.args.get("limit", 50))

        if not assignee and not inventor:
            return (
                jsonify({"error": "Either assignee or inventor parameter is required"}),
                400,
            )

        patents = []

        if assignee:
            patents = patent_svc.search_patents_by_assignee(
                assignee, start_date=start_date, end_date=end_date, limit=limit
            )
        elif inventor:
            patents = patent_svc.search_patents_by_inventor(
                inventor, start_date=start_date, end_date=end_date, limit=limit
            )

        # Transform patents for frontend
        transformed = [patent_svc.transform_patent_for_neo4j(p) for p in patents]

        return jsonify({"count": len(transformed), "patents": transformed})

    except Exception as e:
        print(f"Error searching patents: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/patents/<ticker>/fetch", methods=["POST"])
def fetch_patents_for_company(ticker):
    """
    Fetch and store patents for a company

    This endpoint:
    1. Looks up the company name from the ticker
    2. Searches USPTO for patents by that company
    3. Creates Patent nodes in Neo4j linked to the Organization
    4. Saves patents as artifacts in PostgreSQL

    Query params:
        days_back: Number of days to search (default: 365)
        save_neo4j: Save to Neo4j (default: true)
        save_artifacts: Save as artifacts (default: true)

    Returns:
        Summary of fetched and stored patents
    """
    try:
        ticker = ticker.upper()

        patent_svc = get_patent_service()
        if not patent_svc:
            return jsonify({"error": "Patent service not available"}), 503

        # Get company name from database
        company = db_service.get_company(ticker) if db_service else None

        if not company:
            return jsonify({"error": f"Company {ticker} not found"}), 404

        company_name = company.get("company_name", "")
        if not company_name:
            return jsonify({"error": f"No company name found for {ticker}"}), 400

        # Fetch options
        days_back = int(request.args.get("days_back", 365))
        save_neo4j = request.args.get("save_neo4j", "true").lower() == "true"
        save_artifacts = request.args.get("save_artifacts", "true").lower() == "true"

        # Fetch patents
        result = patent_svc.fetch_patents_for_organization(
            organization_name=company_name, ticker=ticker, days_back=days_back
        )

        # Save to Neo4j if requested
        neo4j_created = 0
        if save_neo4j and result["neo4j_patents"]:
            neo4j_created = patent_svc.create_patent_nodes_in_neo4j(
                result["neo4j_patents"], company_name
            )

        # Save as artifacts if requested
        artifacts_saved = 0
        if save_artifacts and result["artifacts"]:
            artifacts_saved = patent_svc.save_patents_as_artifacts(result["artifacts"])

        return jsonify(
            {
                "ticker": ticker,
                "company_name": company_name,
                "patent_count": result["patent_count"],
                "neo4j_nodes_created": neo4j_created,
                "artifacts_saved": artifacts_saved,
                "date_range": result["date_range"],
                "patents": result["neo4j_patents"][:10],  # Return first 10 for preview
            }
        )

    except Exception as e:
        print(f"Error fetching patents for {ticker}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/patents/<patent_number>", methods=["GET"])
def get_patent_details(patent_number):
    """
    Get details for a specific patent

    Returns:
        Patent details from USPTO
    """
    try:
        patent_svc = get_patent_service()
        if not patent_svc:
            return jsonify({"error": "Patent service not available"}), 503

        details = patent_svc.get_patent_details(patent_number)

        if not details:
            return jsonify({"error": f"Patent {patent_number} not found"}), 404

        return jsonify(details)

    except Exception as e:
        print(f"Error getting patent details: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================================
# DATA ENRICHMENT ENDPOINTS
# ============================================================================


def get_enrichment_service():
    """Lazy load data enrichment service"""
    try:
        from services.data_enrichment_service import DataEnrichmentService

        return DataEnrichmentService()
    except Exception as e:
        print(f"Error loading enrichment service: {e}")
        return None


@app.route("/api/enrichment/run-all", methods=["POST"])
@require_cognito_auth
def run_full_enrichment():
    """
    Run full data enrichment pipeline for all companies.

    This endpoint triggers:
    1. LLM feature extraction from SEC filings
    2. NVD/CVE vulnerability event integration
    3. SEC 8-K executive event extraction
    4. Analyst sentiment extraction from earnings calls

    Requires authentication. This is a long-running operation.

    Request body (optional):
        {
            "skip_llm_features": false,
            "skip_vulnerabilities": false,
            "skip_executive_events": false,
            "skip_analyst_sentiment": false
        }

    Returns:
        Summary of enrichment results for all companies
    """
    try:
        enrichment_svc = get_enrichment_service()
        if not enrichment_svc:
            return jsonify({"error": "Enrichment service not available"}), 503

        data = request.json or {}
        skip_llm = data.get("skip_llm_features", False)
        skip_vulns = data.get("skip_vulnerabilities", False)
        skip_exec = data.get("skip_executive_events", False)
        skip_analyst = data.get("skip_analyst_sentiment", False)

        results = enrichment_svc.run_full_enrichment(
            skip_llm_features=skip_llm,
            skip_vulnerabilities=skip_vulns,
            skip_executive_events=skip_exec,
            skip_analyst_sentiment=skip_analyst,
        )

        return jsonify(
            {
                "success": True,
                "message": "Full enrichment pipeline completed",
                "results": results,
            }
        )

    except Exception as e:
        print(f"Error running full enrichment: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/enrichment/company/<ticker>", methods=["POST"])
@require_cognito_auth
def enrich_single_company(ticker):
    """
    Run data enrichment for a single company.

    Path params:
        ticker: Stock ticker symbol (e.g., CRWD, PANW)

    Request body (optional):
        {
            "skip_llm_features": false,
            "skip_vulnerabilities": false,
            "skip_executive_events": false,
            "skip_analyst_sentiment": false
        }

    Returns:
        Enrichment results for the specified company
    """
    ticker = ticker.upper()
    try:
        enrichment_svc = get_enrichment_service()
        if not enrichment_svc:
            return jsonify({"error": "Enrichment service not available"}), 503

        data = request.json or {}
        skip_llm = data.get("skip_llm_features", False)
        skip_vulns = data.get("skip_vulnerabilities", False)
        skip_exec = data.get("skip_executive_events", False)
        skip_analyst = data.get("skip_analyst_sentiment", False)

        results = enrichment_svc.enrich_single_company(
            ticker,
            skip_llm_features=skip_llm,
            skip_vulnerabilities=skip_vulns,
            skip_executive_events=skip_exec,
            skip_analyst_sentiment=skip_analyst,
        )

        return jsonify(
            {
                "success": True,
                "ticker": ticker,
                "message": f"Enrichment completed for {ticker}",
                "results": results,
            }
        )

    except Exception as e:
        print(f"Error enriching company {ticker}: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/enrichment/vulnerabilities/<ticker>", methods=["POST"])
@require_cognito_auth
def fetch_vulnerabilities(ticker):
    """
    Fetch and store vulnerability data for a company from NVD.

    Path params:
        ticker: Stock ticker symbol (e.g., CRWD, PANW)

    Query params:
        days_back: Number of days to search (default: 90)

    Returns:
        List of vulnerabilities found and stored
    """
    ticker = ticker.upper()
    try:
        from services.data_enrichment_service import VulnerabilityEventService

        vuln_svc = VulnerabilityEventService()

        days_back = int(request.args.get("days_back", 90))

        # Get company info for product name lookup
        company = db_service.get_company(ticker)
        if not company:
            return jsonify({"error": f"Company {ticker} not found"}), 404

        company_name = company.get("company_name", ticker)

        vulnerabilities = vuln_svc.fetch_vulnerabilities_for_company(
            ticker, company_name, days_back=days_back
        )

        return jsonify(
            {
                "success": True,
                "ticker": ticker,
                "company_name": company_name,
                "vulnerabilities_found": len(vulnerabilities),
                "vulnerabilities": vulnerabilities[:20],  # Return first 20 for preview
            }
        )

    except Exception as e:
        print(f"Error fetching vulnerabilities for {ticker}: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/enrichment/executive-events/<ticker>", methods=["POST"])
@require_cognito_auth
def extract_executive_events(ticker):
    """
    Extract executive appointment/departure events from 8-K filings.

    Path params:
        ticker: Stock ticker symbol (e.g., CRWD, PANW)

    Returns:
        List of executive events extracted from 8-K filings
    """
    ticker = ticker.upper()
    try:
        from services.data_enrichment_service import ExecutiveEventExtractor

        exec_svc = ExecutiveEventExtractor()

        events = exec_svc.extract_executive_events(ticker)

        return jsonify(
            {
                "success": True,
                "ticker": ticker,
                "events_found": len(events),
                "events": events,
            }
        )

    except Exception as e:
        print(f"Error extracting executive events for {ticker}: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/enrichment/llm-features/<ticker>", methods=["POST"])
@require_cognito_auth
def extract_llm_features(ticker):
    """
    Extract LLM-powered features from SEC filings for a company.

    Path params:
        ticker: Stock ticker symbol (e.g., CRWD, PANW)

    Returns:
        Extracted features including cyber_sector_relevance, market_positioning,
        threat_specialization, competitive_moat, and risk_summary
    """
    ticker = ticker.upper()
    try:
        from services.data_enrichment_service import CompanyFeatureExtractor

        feature_svc = CompanyFeatureExtractor()

        features = feature_svc.extract_company_features(ticker)

        if not features:
            return jsonify(
                {
                    "success": False,
                    "ticker": ticker,
                    "message": "No SEC filings found to extract features from",
                }
            )

        return jsonify(
            {
                "success": True,
                "ticker": ticker,
                "features": features,
            }
        )

    except Exception as e:
        print(f"Error extracting LLM features for {ticker}: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ============================================================================
# FEATURE EVALUATION ENDPOINTS
# ============================================================================


def get_evaluation_service():
    """Lazy load feature evaluation service"""
    try:
        from services.feature_evaluation_service import FeatureEvaluationService

        return FeatureEvaluationService()
    except Exception as e:
        print(f"Error loading evaluation service: {e}")
        traceback.print_exc()
        return None


@app.route("/api/evaluation/ablation-study", methods=["POST"])
# TODO: Re-enable @require_cognito_auth once frontend Cognito login is fixed
def run_ablation_study():
    """
    Run ablation study comparing model performance with different feature sets.

    Per the LLM scientific paper methodology, this compares:
    1. Baseline only (traditional numerical features)
    2. Baseline + LLM features
    3. Baseline + Event features
    4. Baseline + Sentiment features
    5. Full model (all features)

    Request body (optional):
        {
            "target_threshold": 0.05,  // Threshold for rare event (default 5%)
            "days_forward": 30,        // Days to look ahead for target (default 30)
            "cv_folds": 5              // Cross-validation folds (default 5)
        }

    Returns:
        Ablation study results with metrics for each feature configuration
    """
    try:
        eval_svc = get_evaluation_service()
        if not eval_svc:
            return jsonify({"error": "Evaluation service not available"}), 503

        data = request.json or {}
        target_threshold = data.get("target_threshold", 0.05)
        days_forward = data.get("days_forward", 30)
        cv_folds = data.get("cv_folds", 5)

        results = eval_svc.run_ablation_study(
            target_threshold=target_threshold,
            days_forward=days_forward,
            cv_folds=cv_folds,
        )

        return jsonify({"success": True, "results": results})

    except Exception as e:
        print(f"Error running ablation study: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/evaluation/feature-importance", methods=["GET"])
# TODO: Re-enable @require_cognito_auth once frontend Cognito login is fixed
def get_feature_importance():
    """
    Get feature importance rankings from the full model.

    Query params (optional):
        target_threshold: float (default 0.05) - Threshold for rare event
        days_forward: int (default 30) - Days to look ahead for target

    Returns:
        Feature importance rankings with scores
    """
    try:
        eval_svc = get_evaluation_service()
        if not eval_svc:
            return jsonify({"error": "Evaluation service not available"}), 503

        target_threshold = float(request.args.get("target_threshold", 0.05))
        days_forward = int(request.args.get("days_forward", 30))

        results = eval_svc.get_feature_importance(
            target_threshold=target_threshold,
            days_forward=days_forward,
        )

        return jsonify({"success": True, "results": results})

    except Exception as e:
        print(f"Error getting feature importance: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/evaluation/feature-coverage", methods=["GET"])
# TODO: Re-enable @require_cognito_auth once frontend Cognito login is fixed
def get_feature_coverage():
    """
    Get feature coverage statistics - how many companies have each feature type.

    Returns:
        Coverage statistics showing data availability for each feature category
    """
    try:
        eval_svc = get_evaluation_service()
        if not eval_svc:
            return jsonify({"error": "Evaluation service not available"}), 503

        results = eval_svc.get_feature_coverage()

        return jsonify({"success": True, "coverage": results})

    except Exception as e:
        print(f"Error getting feature coverage: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ============================================================================
# GDS ANALYTICS ENDPOINTS - Graph Data Science algorithms
# ============================================================================

_gds_service = None


def get_gds_service():
    """Get or create the GDS service singleton."""
    global _gds_service
    if _gds_service is None:
        try:
            from services.gds_service import GDSService

            _gds_service = GDSService()
        except Exception as e:
            print(f"Failed to initialize GDS service: {e}")
            return None
    return _gds_service


@app.route("/api/gds/version", methods=["GET"])
def gds_version():
    """Get the installed GDS version."""
    try:
        gds = get_gds_service()
        if not gds:
            return jsonify({"error": "GDS service not available"}), 503

        version = gds.get_gds_version()
        return jsonify({"version": version})

    except Exception as e:
        print(f"Error getting GDS version: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/gds/summary", methods=["GET"])
def gds_summary():
    """Get summary of GDS analytics capabilities and current state."""
    try:
        gds = get_gds_service()
        if not gds:
            return jsonify({"error": "GDS service not available"}), 503

        summary = gds.get_analytics_summary()
        return jsonify(summary)

    except Exception as e:
        print(f"Error getting GDS summary: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/gds/graphs", methods=["GET"])
def gds_list_graphs():
    """List all existing graph projections."""
    try:
        gds = get_gds_service()
        if not gds:
            return jsonify({"error": "GDS service not available"}), 503

        graphs = gds.list_graphs()
        return jsonify({"graphs": graphs})

    except Exception as e:
        print(f"Error listing graphs: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/gds/graphs/competition", methods=["POST"])
def gds_create_competition_graph():
    """Create the competition graph projection for centrality analysis."""
    try:
        gds = get_gds_service()
        if not gds:
            return jsonify({"error": "GDS service not available"}), 503

        result = gds.create_competition_graph()
        return jsonify({"success": True, **result})

    except Exception as e:
        print(f"Error creating competition graph: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/gds/centrality/pagerank", methods=["GET"])
def gds_pagerank():
    """
    Run PageRank to find market leaders.

    Query params:
        limit: int (default 20) - Number of results to return
    """
    try:
        gds = get_gds_service()
        if not gds:
            return jsonify({"error": "GDS service not available"}), 503

        limit = int(request.args.get("limit", 20))
        results = gds.run_pagerank(limit=limit)

        return jsonify(
            {
                "algorithm": "pagerank",
                "description": "Market leaders - companies central to competition network",
                "results": results,
            }
        )

    except Exception as e:
        print(f"Error running PageRank: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/gds/centrality/betweenness", methods=["GET"])
def gds_betweenness():
    """
    Run Betweenness Centrality to find strategic positions.

    Query params:
        limit: int (default 20) - Number of results to return
    """
    try:
        gds = get_gds_service()
        if not gds:
            return jsonify({"error": "GDS service not available"}), 503

        limit = int(request.args.get("limit", 20))
        results = gds.run_betweenness_centrality(limit=limit)

        return jsonify(
            {
                "algorithm": "betweenness_centrality",
                "description": "Strategic bridges - acquisition targets, consolidation points",
                "results": results,
            }
        )

    except Exception as e:
        print(f"Error running betweenness: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/gds/centrality/degree", methods=["GET"])
def gds_degree():
    """
    Get degree centrality (competitor count) for companies.

    Query params:
        limit: int (default 20) - Number of results to return
    """
    try:
        gds = get_gds_service()
        if not gds:
            return jsonify({"error": "GDS service not available"}), 503

        limit = int(request.args.get("limit", 20))
        results = gds.run_degree_centrality(limit=limit)

        return jsonify(
            {
                "algorithm": "degree_centrality",
                "description": "Competitive breadth - companies with most competitors",
                "results": results,
            }
        )

    except Exception as e:
        print(f"Error running degree centrality: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/gds/community/louvain", methods=["GET"])
def gds_louvain():
    """
    Run Louvain community detection to find market segments.
    """
    try:
        gds = get_gds_service()
        if not gds:
            return jsonify({"error": "GDS service not available"}), 503

        results = gds.run_louvain_communities()

        return jsonify(
            {
                "algorithm": "louvain",
                "description": "Market segments - clusters of closely competing companies",
                **results,
            }
        )

    except Exception as e:
        print(f"Error running Louvain: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/gds/community/wcc", methods=["GET"])
def gds_wcc():
    """
    Run Weakly Connected Components to find isolated groups.
    """
    try:
        gds = get_gds_service()
        if not gds:
            return jsonify({"error": "GDS service not available"}), 503

        results = gds.run_wcc()

        return jsonify(
            {
                "algorithm": "wcc",
                "description": "Connected components - isolated market niches",
                **results,
            }
        )

    except Exception as e:
        print(f"Error running WCC: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/gds/similarity/patents", methods=["GET"])
def gds_patent_similarity():
    """
    Run node similarity based on patent portfolios.

    Query params:
        top_k: int (default 10) - Top K similar pairs to find per node
    """
    try:
        gds = get_gds_service()
        if not gds:
            return jsonify({"error": "GDS service not available"}), 503

        top_k = int(request.args.get("top_k", 10))
        results = gds.run_node_similarity(top_k=top_k)

        return jsonify(
            {
                "algorithm": "node_similarity",
                "description": "Patent portfolio similarity - companies with similar IP strategies",
                "results": results,
            }
        )

    except Exception as e:
        print(f"Error running patent similarity: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/gds/similarity/company/<ticker>", methods=["GET"])
def gds_similar_to_company(ticker):
    """
    Find companies most similar to a specific company.

    Query params:
        top_k: int (default 10) - Number of similar companies to return
    """
    try:
        gds = get_gds_service()
        if not gds:
            return jsonify({"error": "GDS service not available"}), 503

        top_k = int(request.args.get("top_k", 10))
        results = gds.find_similar_to_company(ticker=ticker, top_k=top_k)

        return jsonify(
            {
                "ticker": ticker.upper(),
                "description": f"Companies most similar to {ticker.upper()}",
                "results": results,
            }
        )

    except Exception as e:
        print(f"Error finding similar companies: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/gds/risk/vulnerabilities", methods=["GET"])
def gds_vulnerability_analysis():
    """
    Analyze vulnerability distribution and potential spread patterns.
    """
    try:
        gds = get_gds_service()
        if not gds:
            return jsonify({"error": "GDS service not available"}), 503

        results = gds.analyze_vulnerability_spread()

        return jsonify(
            {
                "analysis": "vulnerability_spread",
                "description": "Companies with vulnerabilities and their network connections",
                **results,
            }
        )

    except Exception as e:
        print(f"Error analyzing vulnerabilities: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/gds/executive/network", methods=["GET"])
def gds_executive_network():
    """
    Analyze executive network and key personnel.

    Query params:
        limit: int (default 20) - Number of results to return
    """
    try:
        gds = get_gds_service()
        if not gds:
            return jsonify({"error": "GDS service not available"}), 503

        limit = int(request.args.get("limit", 20))
        results = gds.analyze_executive_network(limit=limit)

        return jsonify(
            {
                "analysis": "executive_network",
                "description": "Key executives and their company associations",
                "results": results,
            }
        )

    except Exception as e:
        print(f"Error analyzing executive network: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================================
# REGULATORY COMPLIANCE ENDPOINTS
# ============================================================================


@app.route("/api/regulatory/dashboard/summary", methods=["GET"])
def regulatory_dashboard_summary():
    """
    Get regulatory dashboard summary statistics.

    Returns:
        Summary metrics including alert counts by status, impact, and agency.
    """
    try:
        summary = regulatory_service.get_dashboard_summary()
        return jsonify(summary)
    except Exception as e:
        print(f"Error getting regulatory dashboard summary: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/regulatory/alerts", methods=["GET"])
def get_regulatory_alerts():
    """
    Get regulatory alerts with optional filters.

    Query params:
        ticker: str - Filter by company ticker
        status: str - Filter by status (UNACKNOWLEDGED, ACKNOWLEDGED, RESOLVED)
        impact_level: str - Filter by impact (CRITICAL, HIGH, MEDIUM, LOW)
        limit: int - Maximum results (default 100)
    """
    try:
        ticker = request.args.get("ticker")
        status = request.args.get("status")
        impact_level = request.args.get("impact_level")
        limit = int(request.args.get("limit", 100))

        alerts = regulatory_service.get_alerts(
            ticker=ticker, status=status, impact_level=impact_level, limit=limit
        )

        return jsonify({"alerts": alerts, "count": len(alerts)})
    except Exception as e:
        print(f"Error getting regulatory alerts: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/regulatory/alerts/<int:alert_id>", methods=["GET"])
def get_regulatory_alert(alert_id: int):
    """Get a specific regulatory alert by ID."""
    try:
        alerts = regulatory_service.get_alerts(limit=1000)
        alert = next((a for a in alerts if a["id"] == alert_id), None)

        if not alert:
            return jsonify({"error": "Alert not found"}), 404

        return jsonify(alert)
    except Exception as e:
        print(f"Error getting regulatory alert: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/regulatory/alerts/<int:alert_id>/acknowledge", methods=["POST"])
@require_cognito_auth
def acknowledge_regulatory_alert(alert_id: int):
    """
    Acknowledge a regulatory alert.

    Requires authentication. Uses the authenticated user's email.
    """
    try:
        user_email = request.cognito_user.get("email", "unknown")
        result = regulatory_service.acknowledge_alert(alert_id, user_email)

        if not result:
            return jsonify({"error": "Alert not found or update failed"}), 404

        return jsonify({"message": "Alert acknowledged", "alert": result})
    except Exception as e:
        print(f"Error acknowledging alert: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/regulatory/alerts/<int:alert_id>/status", methods=["PUT"])
@require_cognito_auth
def update_regulatory_alert_status(alert_id: int):
    """
    Update regulatory alert status.

    Request body:
        status: str - New status (UNACKNOWLEDGED, ACKNOWLEDGED, RESOLVED, IN_PROGRESS)
    """
    try:
        data = request.get_json() or {}
        status = data.get("status")

        if not status:
            return jsonify({"error": "Status is required"}), 400

        result = regulatory_service.update_alert_status(alert_id, status)

        if not result:
            return jsonify({"error": "Alert not found or update failed"}), 404

        return jsonify({"message": "Status updated", "alert": result})
    except Exception as e:
        print(f"Error updating alert status: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/regulatory/regulations", methods=["GET"])
def get_regulations():
    """
    Get all regulations with optional filters.

    Query params:
        agency: str - Filter by agency (SEC, CISA, FTC, etc.)
        severity: str - Filter by severity (CRITICAL, HIGH, MEDIUM, INFO)
        limit: int - Maximum results (default 100)
    """
    try:
        agency = request.args.get("agency")
        severity = request.args.get("severity")
        limit = int(request.args.get("limit", 100))

        regulations = regulatory_service.get_regulations(
            agency=agency, severity=severity, limit=limit
        )

        return jsonify({"regulations": regulations, "count": len(regulations)})
    except Exception as e:
        print(f"Error getting regulations: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/regulatory/regulations/<int:regulation_id>", methods=["GET"])
def get_regulation(regulation_id: int):
    """Get a specific regulation by ID."""
    try:
        regulation = regulatory_service.get_regulation(regulation_id)

        if not regulation:
            return jsonify({"error": "Regulation not found"}), 404

        # Get alerts for this regulation
        alerts = regulatory_service.get_alerts(limit=1000)
        regulation_alerts = [a for a in alerts if a["regulation_id"] == regulation_id]
        regulation["affected_companies"] = regulation_alerts

        return jsonify(regulation)
    except Exception as e:
        print(f"Error getting regulation: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/regulatory/regulations", methods=["POST"])
@require_cognito_auth
def create_regulation():
    """
    Manually create a regulation entry.

    Request body:
        title: str (required) - Regulation title
        agency: str (required) - Regulatory agency
        summary: str - Regulation summary
        effective_date: str - Effective date (YYYY-MM-DD)
        source_url: str - Link to regulation
        severity: str - CRITICAL, HIGH, MEDIUM, or INFO
        keywords: list - Relevant keywords
    """
    try:
        data = request.get_json() or {}

        title = data.get("title")
        agency = data.get("agency")

        if not title or not agency:
            return jsonify({"error": "Title and agency are required"}), 400

        regulation = regulatory_service.create_manual_regulation(
            title=title,
            agency=agency,
            summary=data.get("summary"),
            effective_date=data.get("effective_date"),
            source_url=data.get("source_url"),
            severity=data.get("severity", "MEDIUM"),
            keywords=data.get("keywords"),
        )

        if not regulation:
            return jsonify({"error": "Failed to create regulation"}), 500

        return jsonify({"message": "Regulation created", "regulation": regulation}), 201
    except Exception as e:
        print(f"Error creating regulation: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/regulatory/company/<ticker>/alerts", methods=["GET"])
def get_company_regulatory_alerts(ticker: str):
    """
    Get regulatory alerts for a specific company.

    Path params:
        ticker: Company stock ticker

    Query params:
        status: str - Filter by status
        limit: int - Maximum results (default 50)
    """
    try:
        status = request.args.get("status")
        limit = int(request.args.get("limit", 50))

        alerts = regulatory_service.get_alerts(
            ticker=ticker.upper(), status=status, limit=limit
        )

        return jsonify(
            {"ticker": ticker.upper(), "alerts": alerts, "count": len(alerts)}
        )
    except Exception as e:
        print(f"Error getting company alerts: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/regulatory/ingest", methods=["POST"])
@require_cognito_auth
def ingest_regulations():
    """
    Trigger regulatory ingestion from Federal Register API.

    Request body:
        start_date: str - Start date (YYYY-MM-DD), default 90 days ago
        end_date: str - End date (YYYY-MM-DD), default today

    Returns:
        Ingestion statistics
    """
    try:
        data = request.get_json() or {}
        start_date = data.get("start_date")
        end_date = data.get("end_date")

        result = regulatory_service.ingest_regulations(start_date, end_date)

        return jsonify({"message": "Ingestion complete", **result})
    except Exception as e:
        print(f"Error ingesting regulations: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/regulatory/clear", methods=["DELETE"])
@require_cognito_auth
def clear_regulatory_data():
    """
    Clear all regulatory alerts and regulations (for re-ingestion).

    Requires authentication. Use before re-running ingestion with new LLM validation.
    """
    try:
        conn = db_service._get_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500

        cursor = conn.cursor()

        # Delete alerts first (foreign key constraint)
        cursor.execute("DELETE FROM regulatory_alerts")
        alerts_deleted = cursor.rowcount

        # Delete regulations
        cursor.execute("DELETE FROM regulations")
        regulations_deleted = cursor.rowcount

        conn.commit()
        cursor.close()

        return jsonify(
            {
                "message": "Regulatory data cleared",
                "alerts_deleted": alerts_deleted,
                "regulations_deleted": regulations_deleted,
            }
        )
    except Exception as e:
        print(f"Error clearing regulatory data: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("Starting Cyber Risk Dashboard API...")
    print("Endpoints:")
    print("   - GET  /health")
    print("   - GET  /api/artifacts")
    print("   - GET  /api/companies")
    print("   - GET  /api/artifacts/<ticker>")
    print("   - GET  /api/document/<filename>")
    print("   - GET  /api/forecast?ticker=CRWD&days=30")
    print("   - GET  /api/evaluate/<ticker>")
    print("   - GET  /api/sentiment/<ticker>")
    print("   - GET  /api/sentiment/<ticker>/timeline")
    print("   - GET  /api/sentiment/<ticker>/words")
    print("   - GET  /api/sentiment/cache/stats")
    print("   - POST /api/sentiment/cache/clear")
    print("   - GET  /api/financials/<ticker>")
    print("   - GET  /api/company-growth/available")
    print("   - GET  /api/company-growth/<ticker>")
    print("   - GET  /api/company-growth/<ticker>/jobs")
    print("   - GET  /api/company-growth/<ticker>/headcount")
    print("   - GET  /api/company-growth/compare?tickers=CRWD,ZS,NET")
    print("   - POST /api/lex/message")
    print("   - DELETE /api/lex/session")
    print("")
    print("GraphRAG LLM Chat Endpoints:")
    print("   - POST /api/chat")
    print("   - GET  /api/chat/history/<session_id>")
    print("   - DELETE /api/chat/session/<session_id>")
    print("")
    print("Knowledge Graph Endpoints:")
    print("   - GET  /api/knowledge-graph/<ticker>")
    print("   - POST /api/knowledge-graph/query")
    print("   - GET  /api/knowledge-graph/stats")
    print("   - POST /api/cypher/query")
    print("")
    print("Auth Endpoints:")
    print("   - GET  /api/auth/status")
    print("")
    print("RAG Endpoints:")
    print("   - POST /api/rag/search")
    print("   - POST /api/rag/index")
    print("   - POST /api/rag/index-ticker/<ticker>")
    print("   - GET  /api/rag/stats")
    print("")
    print("Patent Endpoints:")
    print("   - GET  /api/patents/search?assignee=CrowdStrike")
    print("   - GET  /api/patents/search?inventor=John+Smith")
    print("   - POST /api/patents/<ticker>/fetch")
    print("   - GET  /api/patents/<patent_number>")
    print("")
    print("Data Enrichment Endpoints:")
    print("   - POST /api/enrichment/run-all")
    print("   - POST /api/enrichment/company/<ticker>")
    print("   - POST /api/enrichment/vulnerabilities/<ticker>")
    print("   - POST /api/enrichment/executive-events/<ticker>")
    print("   - POST /api/enrichment/llm-features/<ticker>")
    print("")
    print("Feature Evaluation Endpoints:")
    print("   - POST /api/evaluation/ablation-study")
    print("   - GET  /api/evaluation/feature-importance")
    print("   - GET  /api/evaluation/feature-coverage")
    print("")
    print("GDS Analytics Endpoints:")
    print("   - GET  /api/gds/version")
    print("   - GET  /api/gds/summary")
    print("   - GET  /api/gds/graphs")
    print("   - POST /api/gds/graphs/competition")
    print("   - GET  /api/gds/centrality/pagerank")
    print("   - GET  /api/gds/centrality/betweenness")
    print("   - GET  /api/gds/centrality/degree")
    print("   - GET  /api/gds/community/louvain")
    print("   - GET  /api/gds/community/wcc")
    print("   - GET  /api/gds/similarity/patents")
    print("   - GET  /api/gds/similarity/company/<ticker>")
    print("   - GET  /api/gds/risk/vulnerabilities")
    print("   - GET  /api/gds/executive/network")
    print("")
    print("Regulatory Compliance Endpoints:")
    print("   - GET  /api/regulatory/dashboard/summary")
    print("   - GET  /api/regulatory/alerts")
    print("   - GET  /api/regulatory/alerts/<id>")
    print("   - POST /api/regulatory/alerts/<id>/acknowledge")
    print("   - PUT  /api/regulatory/alerts/<id>/status")
    print("   - GET  /api/regulatory/regulations")
    print("   - GET  /api/regulatory/regulations/<id>")
    print("   - POST /api/regulatory/regulations")
    print("   - GET  /api/regulatory/company/<ticker>/alerts")
    print("   - POST /api/regulatory/ingest")
    app.run(host="0.0.0.0", port=5000, debug=True)
