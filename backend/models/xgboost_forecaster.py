"""
XGBoost Stock Price Forecaster

Gradient-boosted decision tree model for stock price prediction.
Uses technical indicators, volume features, and volatility metrics.
Supports SHAP-based feature importance analysis.
"""

import numpy as np
import pandas as pd
import logging
import os
import pickle
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Lazy imports
_xgb = None
_shap = None


def _load_xgboost():
    global _xgb
    if _xgb is None:
        import xgboost as xgb
        _xgb = xgb
    return _xgb


def _load_shap():
    global _shap
    if _shap is None:
        try:
            import shap
            _shap = shap
        except ImportError:
            logger.warning("SHAP not available. Install with: pip install shap")
    return _shap


class XGBoostForecaster:
    """
    Stock price forecaster using XGBoost gradient-boosted trees.

    Features:
    - Walk-forward training on tabular features
    - Hyperparameter tuning via early stopping
    - SHAP-based feature importance
    - Serializable model weights
    """

    def __init__(self, ticker: str, **kwargs):
        self.ticker = ticker
        self.model = None
        self.feature_columns = None
        self.scaler = None
        self.data = None
        self.params = {
            "n_estimators": kwargs.get("n_estimators", 500),
            "max_depth": kwargs.get("max_depth", 6),
            "learning_rate": kwargs.get("learning_rate", 0.05),
            "subsample": kwargs.get("subsample", 0.8),
            "colsample_bytree": kwargs.get("colsample_bytree", 0.8),
            "min_child_weight": kwargs.get("min_child_weight", 3),
            "reg_alpha": kwargs.get("reg_alpha", 0.1),
            "reg_lambda": kwargs.get("reg_lambda", 1.0),
        }

    def prepare_features(self, period: str = "2y") -> pd.DataFrame:
        """Compute feature matrix using shared feature engineering module."""
        from models.feature_engineering import build_feature_matrix, get_feature_columns

        self.data = build_feature_matrix(self.ticker, period=period)
        self.feature_columns = [
            c for c in get_feature_columns()
            if c in self.data.columns
        ]
        return self.data

    def train(self, df: Optional[pd.DataFrame] = None, test_ratio: float = 0.1) -> Dict[str, Any]:
        """
        Train XGBoost model with early stopping.

        Args:
            df: Feature matrix (uses self.data if None)
            test_ratio: Fraction of data for validation (for early stopping)

        Returns:
            Training metrics dict
        """
        xgb = _load_xgboost()

        if df is None:
            if self.data is None:
                self.prepare_features()
            df = self.data

        # Split chronologically (no shuffle for time series)
        features = df[self.feature_columns].copy()
        target = df["target"].copy()

        # Drop any remaining NaN rows
        valid_mask = features.notna().all(axis=1) & target.notna()
        features = features[valid_mask]
        target = target[valid_mask]

        split_idx = int(len(features) * (1 - test_ratio))
        X_train, X_val = features.iloc[:split_idx], features.iloc[split_idx:]
        y_train, y_val = target.iloc[:split_idx], target.iloc[split_idx:]

        self.model = xgb.XGBRegressor(
            n_estimators=self.params["n_estimators"],
            max_depth=self.params["max_depth"],
            learning_rate=self.params["learning_rate"],
            subsample=self.params["subsample"],
            colsample_bytree=self.params["colsample_bytree"],
            min_child_weight=self.params["min_child_weight"],
            reg_alpha=self.params["reg_alpha"],
            reg_lambda=self.params["reg_lambda"],
            objective="reg:squarederror",
            random_state=42,
            early_stopping_rounds=30,
        )

        self.model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            verbose=False,
        )

        # Training metrics
        train_pred = self.model.predict(X_train)
        val_pred = self.model.predict(X_val)

        train_mape = np.mean(np.abs((y_train - train_pred) / y_train)) * 100
        val_mape = np.mean(np.abs((y_val - val_pred) / y_val)) * 100

        logger.info(f"XGBoost trained for {self.ticker}: train MAPE={train_mape:.2f}%, val MAPE={val_mape:.2f}%")

        return {
            "train_mape": float(train_mape),
            "val_mape": float(val_mape),
            "best_iteration": self.model.best_iteration if hasattr(self.model, "best_iteration") else self.params["n_estimators"],
            "n_features": len(self.feature_columns),
            "train_size": len(X_train),
            "val_size": len(X_val),
        }

    def forecast(self, days_ahead: int = 30) -> Dict[str, Any]:
        """
        Generate multi-step forecast by iterative single-step prediction.

        Returns dict matching the existing forecast API format.
        """
        if self.model is None:
            raise ValueError("Model not trained. Call train() first.")
        if self.data is None:
            raise ValueError("No data loaded. Call prepare_features() first.")

        df = self.data.copy()
        current_price = float(df["close"].iloc[-1])
        last_date = df.index[-1]

        # For multi-step: use the last known features and predict iteratively
        # XGBoost predicts next-day price; we chain predictions forward
        predictions = []
        forecast_dates = []

        # Start from the last row of features
        recent_features = df[self.feature_columns].iloc[-1:].copy()

        for i in range(days_ahead):
            pred = self.model.predict(recent_features)[0]
            predictions.append(float(pred))

            next_date = last_date + pd.Timedelta(days=i + 1)
            # Skip weekends
            while next_date.dayofweek >= 5:
                next_date += pd.Timedelta(days=1)
            forecast_dates.append(next_date)

            # Update features with predicted price for next iteration
            # Only update price-derived features that can be computed
            if len(predictions) > 1:
                recent_features = recent_features.copy()
                recent_features["returns_1d"] = (pred - predictions[-2]) / predictions[-2]
            else:
                recent_features = recent_features.copy()
                recent_features["returns_1d"] = (pred - current_price) / current_price

        predicted_price = predictions[-1]
        expected_return = ((predicted_price - current_price) / current_price) * 100

        # Confidence interval from training residuals
        if len(df) > 60:
            train_pred = self.model.predict(df[self.feature_columns].dropna())
            residuals = df["target"].dropna().values[:len(train_pred)] - train_pred
            std_residual = np.std(residuals)
        else:
            std_residual = current_price * 0.05

        confidence_lower = predicted_price - 1.96 * std_residual
        confidence_upper = predicted_price + 1.96 * std_residual

        # Build forecast DataFrame
        forecast_df = pd.DataFrame({
            "ds": forecast_dates,
            "yhat": predictions,
            "yhat_lower": [p - 1.96 * std_residual for p in predictions],
            "yhat_upper": [p + 1.96 * std_residual for p in predictions],
        })

        # Historical data for chart
        historical_days = 60
        historical_data = df[["close"]].tail(historical_days).copy()
        historical_data = historical_data.rename(columns={"close": "actual"})
        historical_data.index.name = "ds"
        historical_data = historical_data.reset_index()

        return {
            "current_price": current_price,
            "predicted_price": predicted_price,
            "expected_return_pct": expected_return,
            "confidence_lower": float(confidence_lower),
            "confidence_upper": float(confidence_upper),
            "forecast_df": forecast_df,
            "historical_df": historical_data,
        }

    def evaluate(self, test_days: int = 30) -> Dict[str, Any]:
        """
        Evaluate model using walk-forward backtesting on the last test_days.
        """
        if self.data is None:
            self.prepare_features()

        df = self.data.copy()
        valid_mask = df[self.feature_columns].notna().all(axis=1) & df["target"].notna()
        df = df[valid_mask]

        if len(df) < test_days + 100:
            raise ValueError(f"Not enough data for evaluation. Have {len(df)}, need {test_days + 100}")

        # Train on everything except last test_days
        train_df = df.iloc[:-test_days]
        test_df = df.iloc[-test_days:]

        # Train a fresh model on train data
        xgb = _load_xgboost()
        split_idx = int(len(train_df) * 0.9)
        X_train = train_df[self.feature_columns].iloc[:split_idx]
        y_train = train_df["target"].iloc[:split_idx]
        X_val = train_df[self.feature_columns].iloc[split_idx:]
        y_val = train_df["target"].iloc[split_idx:]

        eval_model = xgb.XGBRegressor(
            **{k: v for k, v in self.params.items()},
            objective="reg:squarederror",
            random_state=42,
            early_stopping_rounds=30,
        )
        eval_model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

        # Predict on test set
        X_test = test_df[self.feature_columns]
        y_test = test_df["target"].values
        predictions = eval_model.predict(X_test)

        # Metrics
        mape = np.mean(np.abs((y_test - predictions) / y_test)) * 100
        rmse = np.sqrt(np.mean((y_test - predictions) ** 2))
        mae = np.mean(np.abs(y_test - predictions))

        # Directional accuracy
        actual_direction = np.diff(y_test) > 0
        predicted_direction = np.diff(predictions) > 0
        directional_accuracy = np.mean(actual_direction == predicted_direction) * 100

        return {
            "mape": float(mape),
            "rmse": float(rmse),
            "mae": float(mae),
            "directional_accuracy": float(directional_accuracy),
            "test_days": test_days,
            "model": "xgboost",
        }

    def get_feature_importance(self, use_shap: bool = True) -> Dict[str, Any]:
        """
        Get feature importance rankings.

        Args:
            use_shap: If True, compute SHAP values (slower but more accurate).
                      Falls back to built-in importance if SHAP unavailable.
        """
        if self.model is None:
            raise ValueError("Model not trained. Call train() first.")

        result = {}

        # Built-in importance (always available)
        importance = self.model.feature_importances_
        importance_dict = dict(zip(self.feature_columns, importance.tolist()))
        sorted_importance = dict(sorted(importance_dict.items(), key=lambda x: x[1], reverse=True))
        result["builtin_importance"] = sorted_importance

        # SHAP importance (if available)
        if use_shap:
            shap = _load_shap()
            if shap is not None and self.data is not None:
                try:
                    X = self.data[self.feature_columns].dropna()
                    # Use a sample for speed
                    sample_size = min(200, len(X))
                    X_sample = X.sample(n=sample_size, random_state=42)

                    explainer = shap.TreeExplainer(self.model)
                    shap_values = explainer.shap_values(X_sample)

                    mean_abs_shap = np.abs(shap_values).mean(axis=0)
                    shap_dict = dict(zip(self.feature_columns, mean_abs_shap.tolist()))
                    sorted_shap = dict(sorted(shap_dict.items(), key=lambda x: x[1], reverse=True))
                    result["shap_importance"] = sorted_shap
                except Exception as e:
                    logger.warning(f"SHAP computation failed: {e}")

        return result

    def save_model(self, path: Optional[str] = None):
        """Save trained model to disk."""
        if self.model is None:
            raise ValueError("No model to save")

        if path is None:
            save_dir = os.path.join(os.path.dirname(__file__), "saved")
            os.makedirs(save_dir, exist_ok=True)
            path = os.path.join(save_dir, f"xgboost_{self.ticker}.pkl")

        with open(path, "wb") as f:
            pickle.dump({
                "model": self.model,
                "feature_columns": self.feature_columns,
                "params": self.params,
                "ticker": self.ticker,
            }, f)
        logger.info(f"XGBoost model saved to {path}")

    def load_model(self, path: Optional[str] = None):
        """Load trained model from disk."""
        if path is None:
            path = os.path.join(os.path.dirname(__file__), "saved", f"xgboost_{self.ticker}.pkl")

        if not os.path.exists(path):
            raise FileNotFoundError(f"No saved model at {path}")

        with open(path, "rb") as f:
            data = pickle.load(f)

        self.model = data["model"]
        self.feature_columns = data["feature_columns"]
        self.params = data["params"]
        logger.info(f"XGBoost model loaded from {path}")
