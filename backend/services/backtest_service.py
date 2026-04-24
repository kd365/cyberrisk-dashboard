"""
Backtesting Framework

Walk-forward validation for all forecasting models.
Computes MAPE, RMSE, MAE, directional accuracy, and Sharpe ratio.
Caches results in PostgreSQL for the model comparison dashboard.
"""

import logging
import json
import time
from datetime import datetime
from typing import Dict, Any, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Available model types and their forecaster classes
MODEL_REGISTRY = {
    "prophet": {
        "name": "Prophet",
        "description": "Facebook Prophet with cybersecurity sentiment regressors",
        "class_path": "models.time_series_forecaster.CyberRiskForecaster",
        "paradigm": "time_series",
    },
    "chronos": {
        "name": "Chronos-Bolt",
        "description": "Amazon T5-based foundation model (zero-shot)",
        "class_path": "models.chronos_forecaster.ChronosForecaster",
        "paradigm": "foundation_model",
    },
    "xgboost": {
        "name": "XGBoost",
        "description": "Gradient-boosted decision trees with SHAP explanations",
        "class_path": "models.xgboost_forecaster.XGBoostForecaster",
        "paradigm": "gradient_boosting",
    },
    "lightgbm": {
        "name": "LightGBM",
        "description": "Leaf-wise gradient boosting with native categorical support",
        "class_path": "models.lightgbm_forecaster.LightGBMForecaster",
        "paradigm": "gradient_boosting",
    },
    "random_forest": {
        "name": "Random Forest",
        "description": "Bagged decision tree ensemble (interpretable baseline)",
        "class_path": "models.random_forest_forecaster.RandomForestForecaster",
        "paradigm": "ensemble",
    },
    "lstm": {
        "name": "LSTM",
        "description": "2-layer LSTM deep learning sequence model",
        "class_path": "models.lstm_forecaster.LSTMForecaster",
        "paradigm": "deep_learning",
    },
    "ensemble": {
        "name": "Weighted Ensemble",
        "description": "Meta-model combining all base models via inverse-MAPE weighting",
        "class_path": "models.ensemble_forecaster.EnsembleForecaster",
        "paradigm": "meta_ensemble",
    },
}


def _instantiate_forecaster(model_type: str, ticker: str):
    """Create and initialize a forecaster instance."""
    if model_type == "prophet":
        from models.time_series_forecaster import CyberRiskForecaster

        f = CyberRiskForecaster(ticker)
        f.fetch_stock_data(period="2y")
        f.add_cybersecurity_sentiment(mock=True)
        f.add_volatility_regressor()
        f.train()
        return f
    elif model_type == "chronos":
        from models.chronos_forecaster import ChronosForecaster

        f = ChronosForecaster(ticker, model_size="small")
        f.fetch_stock_data(period="3y")
        return f
    elif model_type == "xgboost":
        from models.xgboost_forecaster import XGBoostForecaster

        f = XGBoostForecaster(ticker)
        f.prepare_features()
        f.train()
        return f
    elif model_type == "lightgbm":
        from models.lightgbm_forecaster import LightGBMForecaster

        f = LightGBMForecaster(ticker)
        f.prepare_features()
        f.train()
        return f
    elif model_type == "random_forest":
        from models.random_forest_forecaster import RandomForestForecaster

        f = RandomForestForecaster(ticker)
        f.prepare_features()
        f.train()
        return f
    elif model_type == "lstm":
        from models.lstm_forecaster import LSTMForecaster

        f = LSTMForecaster(ticker)
        f.prepare_features()
        f.train()
        return f
    elif model_type == "ensemble":
        from models.ensemble_forecaster import EnsembleForecaster

        f = EnsembleForecaster(ticker)
        f.train()
        return f
    else:
        raise ValueError(f"Unknown model type: {model_type}")


class BacktestService:
    """
    Manages backtesting across all models for a given ticker.
    """

    def __init__(self):
        self._db = None

    @property
    def db(self):
        if self._db is None:
            try:
                from services.database_service import db_service

                self._db = db_service
            except Exception:
                pass
        return self._db

    def run_backtest(
        self,
        ticker: str,
        model_type: str,
        test_days: int = 30,
    ) -> Dict[str, Any]:
        """
        Run a single model backtest.

        Returns metrics dict with mape, rmse, mae, directional_accuracy.
        """
        start_time = time.time()

        try:
            forecaster = _instantiate_forecaster(model_type, ticker)
            metrics = forecaster.evaluate(test_days=test_days)
            elapsed = time.time() - start_time

            result = {
                "ticker": ticker,
                "model_type": model_type,
                "test_days": test_days,
                **metrics,
                "elapsed_seconds": round(elapsed, 2),
                "computed_at": datetime.utcnow().isoformat(),
                "status": "success",
            }

            # Cache result
            self._cache_result(result)

            return result

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"Backtest failed for {model_type}/{ticker}: {e}")
            return {
                "ticker": ticker,
                "model_type": model_type,
                "test_days": test_days,
                "status": "error",
                "error": str(e),
                "elapsed_seconds": round(elapsed, 2),
                "computed_at": datetime.utcnow().isoformat(),
            }

    def run_leaderboard(
        self,
        ticker: str,
        test_days: int = 30,
        models: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Run backtests for all models and return a ranked leaderboard.

        Args:
            ticker: Stock ticker
            test_days: Backtest period
            models: Specific models to test (default: all)

        Returns:
            Leaderboard with ranked models and metrics.
        """
        if models is None:
            models = list(MODEL_REGISTRY.keys())

        results = []
        for model_type in models:
            logger.info(f"Leaderboard: Running {model_type} for {ticker}...")
            result = self.run_backtest(ticker, model_type, test_days)
            results.append(result)

        # Sort by MAPE (lower is better), errors go to bottom
        successful = [r for r in results if r.get("status") == "success"]
        failed = [r for r in results if r.get("status") != "success"]

        successful.sort(key=lambda x: x.get("mape", float("inf")))

        # Add rank
        for i, r in enumerate(successful):
            r["rank"] = i + 1

        return {
            "ticker": ticker,
            "test_days": test_days,
            "leaderboard": successful + failed,
            "best_model": successful[0]["model_type"] if successful else None,
            "models_tested": len(results),
            "models_succeeded": len(successful),
        }

    def get_cached_leaderboard(
        self,
        ticker: str,
        test_days: int = 30,
    ) -> Optional[Dict[str, Any]]:
        """Get cached backtest results from database."""
        if self.db is None:
            return None

        try:
            conn = self.db._get_connection()
            if conn is None:
                return None

            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT model_type, mape, rmse, mae, directional_accuracy,
                       sharpe_ratio, backtest_data, computed_at
                FROM model_backtests
                WHERE ticker = %s AND test_days = %s
                  AND DATE(computed_at) = CURRENT_DATE
                ORDER BY mape ASC
            """,
                (ticker, test_days),
            )

            rows = cursor.fetchall()
            cursor.close()

            if not rows:
                return None

            leaderboard = []
            for i, row in enumerate(rows):
                leaderboard.append(
                    {
                        "rank": i + 1,
                        "model_type": row[0],
                        "mape": float(row[1]) if row[1] else None,
                        "rmse": float(row[2]) if row[2] else None,
                        "mae": float(row[3]) if row[3] else None,
                        "directional_accuracy": float(row[4]) if row[4] else None,
                        "sharpe_ratio": float(row[5]) if row[5] else None,
                        "computed_at": row[7].isoformat() if row[7] else None,
                        "status": "success",
                    }
                )

            return {
                "ticker": ticker,
                "test_days": test_days,
                "leaderboard": leaderboard,
                "best_model": leaderboard[0]["model_type"] if leaderboard else None,
                "from_cache": True,
            }

        except Exception as e:
            logger.warning(f"Could not read cached leaderboard: {e}")
            return None

    def _cache_result(self, result: Dict[str, Any]):
        """Cache backtest result to database."""
        if self.db is None or result.get("status") != "success":
            return

        try:
            conn = self.db._get_connection()
            if conn is None:
                return

            cursor = conn.cursor()

            # Ensure table exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS model_backtests (
                    id SERIAL PRIMARY KEY,
                    ticker VARCHAR(10) NOT NULL,
                    model_type VARCHAR(30) NOT NULL,
                    test_days INT NOT NULL,
                    mape FLOAT,
                    rmse FLOAT,
                    mae FLOAT,
                    directional_accuracy FLOAT,
                    sharpe_ratio FLOAT,
                    backtest_data JSONB,
                    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Upsert (replace if same ticker/model/test_days today)
            cursor.execute(
                """
                DELETE FROM model_backtests
                WHERE ticker = %s AND model_type = %s AND test_days = %s
                  AND DATE(computed_at) = CURRENT_DATE
            """,
                (result["ticker"], result["model_type"], result["test_days"]),
            )

            cursor.execute(
                """
                INSERT INTO model_backtests
                    (ticker, model_type, test_days, mape, rmse, mae,
                     directional_accuracy, sharpe_ratio, backtest_data)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
                (
                    result["ticker"],
                    result["model_type"],
                    result["test_days"],
                    result.get("mape"),
                    result.get("rmse"),
                    result.get("mae"),
                    result.get("directional_accuracy"),
                    result.get("sharpe_ratio"),
                    json.dumps({"elapsed_seconds": result.get("elapsed_seconds")}),
                ),
            )

            conn.commit()
            cursor.close()

        except Exception as e:
            logger.warning(f"Could not cache backtest result: {e}")


# Singleton
_backtest_service = None


def get_backtest_service() -> BacktestService:
    global _backtest_service
    if _backtest_service is None:
        _backtest_service = BacktestService()
    return _backtest_service
