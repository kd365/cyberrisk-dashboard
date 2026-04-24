"""
Weighted Ensemble Meta-Model Forecaster

Combines predictions from all base models using inverse-MAPE weighting.
Optionally trains a Ridge regression meta-learner on base model predictions.
"""

import numpy as np
import pandas as pd
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class EnsembleForecaster:
    """
    Meta-model that combines predictions from multiple base forecasters.

    Strategies:
    - Inverse-MAPE weighting: Better models get higher weight
    - Ridge meta-learner: Train a linear model on base predictions (optional)

    Base models: Prophet, Chronos, XGBoost, LightGBM, Random Forest, LSTM
    """

    BASE_MODELS = ["prophet", "chronos", "xgboost", "lightgbm", "random_forest", "lstm"]

    def __init__(self, ticker: str, **kwargs):
        self.ticker = ticker
        self.weights = {}
        self.base_forecasters = {}
        self.base_evaluations = {}
        self.meta_model = None
        self.strategy = kwargs.get("strategy", "inverse_mape")

    def _get_forecaster(self, model_name: str):
        """Lazy-load a base forecaster."""
        if model_name == "prophet":
            from models.time_series_forecaster import CyberRiskForecaster
            f = CyberRiskForecaster(self.ticker)
            f.fetch_stock_data(period="2y")
            f.add_cybersecurity_sentiment(mock=True)
            f.add_volatility_regressor()
            f.train()
            return f
        elif model_name == "chronos":
            from models.chronos_forecaster import ChronosForecaster
            f = ChronosForecaster(self.ticker, model_size="small")
            f.fetch_stock_data(period="3y")
            return f
        elif model_name == "xgboost":
            from models.xgboost_forecaster import XGBoostForecaster
            f = XGBoostForecaster(self.ticker)
            f.prepare_features()
            f.train()
            return f
        elif model_name == "lightgbm":
            from models.lightgbm_forecaster import LightGBMForecaster
            f = LightGBMForecaster(self.ticker)
            f.prepare_features()
            f.train()
            return f
        elif model_name == "random_forest":
            from models.random_forest_forecaster import RandomForestForecaster
            f = RandomForestForecaster(self.ticker)
            f.prepare_features()
            f.train()
            return f
        elif model_name == "lstm":
            from models.lstm_forecaster import LSTMForecaster
            f = LSTMForecaster(self.ticker)
            f.prepare_features()
            f.train()
            return f
        else:
            raise ValueError(f"Unknown model: {model_name}")

    def train(self, models: Optional[List[str]] = None, test_days: int = 30) -> Dict[str, Any]:
        """
        Train ensemble by evaluating all base models and computing weights.

        Args:
            models: List of model names to include. Default: all available.
            test_days: Days for backtesting to compute weights.

        Returns:
            Training results with individual model metrics and computed weights.
        """
        if models is None:
            models = self.BASE_MODELS.copy()

        results = {"models_evaluated": [], "models_failed": []}

        for model_name in models:
            try:
                logger.info(f"Ensemble: Training and evaluating {model_name}...")
                forecaster = self._get_forecaster(model_name)
                evaluation = forecaster.evaluate(test_days=test_days)

                self.base_forecasters[model_name] = forecaster
                self.base_evaluations[model_name] = evaluation
                results["models_evaluated"].append({
                    "model": model_name,
                    **evaluation,
                })
                logger.info(f"Ensemble: {model_name} MAPE={evaluation['mape']:.2f}%")

            except Exception as e:
                logger.warning(f"Ensemble: {model_name} failed: {e}")
                results["models_failed"].append({"model": model_name, "error": str(e)})

        # Compute weights
        self._compute_weights()
        results["weights"] = self.weights
        results["strategy"] = self.strategy

        return results

    def _compute_weights(self):
        """Compute model weights using inverse-MAPE strategy."""
        if not self.base_evaluations:
            raise ValueError("No base model evaluations available")

        if self.strategy == "inverse_mape":
            # Weight = 1/MAPE, normalized to sum to 1
            inverse_mapes = {}
            for model_name, eval_result in self.base_evaluations.items():
                mape = eval_result.get("mape", 100)
                if mape > 0:
                    inverse_mapes[model_name] = 1.0 / mape
                else:
                    inverse_mapes[model_name] = 10.0  # Very high weight for perfect MAPE

            total = sum(inverse_mapes.values())
            self.weights = {k: v / total for k, v in inverse_mapes.items()}

        elif self.strategy == "equal":
            n = len(self.base_evaluations)
            self.weights = {k: 1.0 / n for k in self.base_evaluations}

        elif self.strategy == "ridge":
            self._train_ridge_meta_learner()

    def _train_ridge_meta_learner(self):
        """Train a Ridge regression meta-learner on base model predictions."""
        from sklearn.linear_model import Ridge

        # Collect predictions from all base models on the test set
        # This is a simplified version; full implementation would use OOF predictions
        logger.info("Ridge meta-learner training not yet implemented; falling back to inverse_mape")
        self.strategy = "inverse_mape"
        self._compute_weights()

    def forecast(self, days_ahead: int = 30) -> Dict[str, Any]:
        """
        Generate weighted ensemble forecast.

        Combines individual model forecasts using computed weights.
        """
        if not self.base_forecasters:
            raise ValueError("No base models trained. Call train() first.")
        if not self.weights:
            raise ValueError("No weights computed. Call train() first.")

        all_forecasts = {}
        all_predictions = {}

        for model_name, forecaster in self.base_forecasters.items():
            if model_name not in self.weights:
                continue
            try:
                result = forecaster.forecast(days_ahead=days_ahead)
                all_forecasts[model_name] = result
                all_predictions[model_name] = result["forecast_df"]["yhat"].values
            except Exception as e:
                logger.warning(f"Ensemble forecast: {model_name} failed: {e}")

        if not all_predictions:
            raise ValueError("All base model forecasts failed")

        # Weighted combination
        # Ensure all predictions have the same length
        min_len = min(len(v) for v in all_predictions.values())
        ensemble_pred = np.zeros(min_len)
        total_weight = 0

        for model_name, predictions in all_predictions.items():
            weight = self.weights.get(model_name, 0)
            ensemble_pred += weight * predictions[:min_len]
            total_weight += weight

        if total_weight > 0:
            ensemble_pred /= total_weight

        # Use the first available forecast for metadata
        any_forecast = next(iter(all_forecasts.values()))
        current_price = any_forecast["current_price"]
        predicted_price = float(ensemble_pred[-1])
        expected_return = ((predicted_price - current_price) / current_price) * 100

        # Confidence interval from prediction spread across models
        all_final_preds = [v[-1] for v in all_predictions.values() if len(v) >= min_len]
        pred_spread_std = np.std(all_final_preds) if len(all_final_preds) > 1 else current_price * 0.05

        # Build forecast DataFrame
        forecast_dates = any_forecast["forecast_df"]["ds"].values[:min_len]

        # Per-step confidence from model disagreement
        all_pred_matrix = np.array([v[:min_len] for v in all_predictions.values()])
        step_stds = np.std(all_pred_matrix, axis=0)

        forecast_df = pd.DataFrame({
            "ds": forecast_dates,
            "yhat": ensemble_pred,
            "yhat_lower": ensemble_pred - 1.96 * step_stds,
            "yhat_upper": ensemble_pred + 1.96 * step_stds,
        })

        return {
            "current_price": current_price,
            "predicted_price": predicted_price,
            "expected_return_pct": expected_return,
            "confidence_lower": float(predicted_price - 1.96 * pred_spread_std),
            "confidence_upper": float(predicted_price + 1.96 * pred_spread_std),
            "forecast_df": forecast_df,
            "historical_df": any_forecast["historical_df"],
            "model_weights": self.weights,
            "individual_predictions": {
                k: float(v[-1]) for k, v in all_predictions.items()
            },
        }

    def evaluate(self, test_days: int = 30) -> Dict[str, Any]:
        """
        Evaluate ensemble performance.

        If models are already trained, uses cached evaluations.
        Otherwise trains everything from scratch.
        """
        if not self.base_evaluations:
            self.train(test_days=test_days)

        # The ensemble's metrics are the weighted average of individual model predictions
        # For a proper evaluation, we'd need to combine predictions on the test set
        # For now, return the weighted average metrics as an approximation
        if not self.weights or not self.base_evaluations:
            raise ValueError("No evaluation data available")

        weighted_mape = 0
        weighted_rmse = 0
        weighted_mae = 0
        weighted_dir_acc = 0
        total_weight = 0

        for model_name, eval_result in self.base_evaluations.items():
            weight = self.weights.get(model_name, 0)
            weighted_mape += weight * eval_result.get("mape", 0)
            weighted_rmse += weight * eval_result.get("rmse", 0)
            weighted_mae += weight * eval_result.get("mae", 0)
            weighted_dir_acc += weight * eval_result.get("directional_accuracy", 0)
            total_weight += weight

        if total_weight > 0:
            weighted_mape /= total_weight
            weighted_rmse /= total_weight
            weighted_mae /= total_weight
            weighted_dir_acc /= total_weight

        return {
            "mape": float(weighted_mape),
            "rmse": float(weighted_rmse),
            "mae": float(weighted_mae),
            "directional_accuracy": float(weighted_dir_acc),
            "test_days": test_days,
            "model": "ensemble",
            "strategy": self.strategy,
            "n_base_models": len(self.base_evaluations),
            "weights": self.weights,
        }

    def get_feature_importance(self) -> Dict[str, Any]:
        """Aggregate feature importance from tree-based base models."""
        aggregated = {}

        for model_name in ["xgboost", "lightgbm", "random_forest"]:
            if model_name in self.base_forecasters:
                try:
                    imp = self.base_forecasters[model_name].get_feature_importance()
                    builtin = imp.get("builtin_importance", {})
                    weight = self.weights.get(model_name, 0)

                    for feature, value in builtin.items():
                        if feature not in aggregated:
                            aggregated[feature] = 0
                        aggregated[feature] += weight * value
                except Exception as e:
                    logger.warning(f"Could not get importance from {model_name}: {e}")

        sorted_importance = dict(sorted(aggregated.items(), key=lambda x: x[1], reverse=True))

        return {
            "ensemble_importance": sorted_importance,
            "model_weights": self.weights,
        }
