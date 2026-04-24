"""
Random Forest Stock Price Forecaster

Bagged ensemble of decision trees for stock price prediction.
Serves as an interpretable baseline model with built-in feature importance.
Robust to overfitting due to bootstrap aggregation.
"""

import numpy as np
import pandas as pd
import logging
import os
import pickle
from typing import Dict, Any, Optional
from sklearn.ensemble import RandomForestRegressor

logger = logging.getLogger(__name__)


class RandomForestForecaster:
    """
    Stock price forecaster using Random Forest regression.

    Features:
    - Bootstrap aggregation for robust predictions
    - Built-in feature importance (mean decrease in impurity)
    - Parallelized training
    - No hyperparameter sensitivity (good baseline)
    """

    def __init__(self, ticker: str, **kwargs):
        self.ticker = ticker
        self.model = None
        self.feature_columns = None
        self.data = None
        self.params = {
            "n_estimators": kwargs.get("n_estimators", 300),
            "max_depth": kwargs.get("max_depth", 15),
            "min_samples_split": kwargs.get("min_samples_split", 10),
            "min_samples_leaf": kwargs.get("min_samples_leaf", 5),
            "max_features": kwargs.get("max_features", "sqrt"),
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
        """Train Random Forest model."""
        if df is None:
            if self.data is None:
                self.prepare_features()
            df = self.data

        features = df[self.feature_columns].copy()
        target = df["target"].copy()

        valid_mask = features.notna().all(axis=1) & target.notna()
        features = features[valid_mask]
        target = target[valid_mask]

        split_idx = int(len(features) * (1 - test_ratio))
        X_train, X_val = features.iloc[:split_idx], features.iloc[split_idx:]
        y_train, y_val = target.iloc[:split_idx], target.iloc[split_idx:]

        self.model = RandomForestRegressor(
            n_estimators=self.params["n_estimators"],
            max_depth=self.params["max_depth"],
            min_samples_split=self.params["min_samples_split"],
            min_samples_leaf=self.params["min_samples_leaf"],
            max_features=self.params["max_features"],
            random_state=42,
            n_jobs=-1,
        )

        self.model.fit(X_train, y_train)

        train_pred = self.model.predict(X_train)
        val_pred = self.model.predict(X_val)

        train_mape = np.mean(np.abs((y_train - train_pred) / y_train)) * 100
        val_mape = np.mean(np.abs((y_val - val_pred) / y_val)) * 100

        logger.info(f"RandomForest trained for {self.ticker}: train MAPE={train_mape:.2f}%, val MAPE={val_mape:.2f}%")

        return {
            "train_mape": float(train_mape),
            "val_mape": float(val_mape),
            "n_features": len(self.feature_columns),
            "train_size": len(X_train),
            "val_size": len(X_val),
            "oob_score": float(self.model.oob_score_) if hasattr(self.model, "oob_score_") else None,
        }

    def forecast(self, days_ahead: int = 30) -> Dict[str, Any]:
        """Generate multi-step forecast."""
        if self.model is None:
            raise ValueError("Model not trained. Call train() first.")
        if self.data is None:
            raise ValueError("No data loaded. Call prepare_features() first.")

        df = self.data.copy()
        current_price = float(df["close"].iloc[-1])
        last_date = df.index[-1]

        predictions = []
        forecast_dates = []
        recent_features = df[self.feature_columns].iloc[-1:].copy()

        for i in range(days_ahead):
            # Get predictions from all trees for confidence intervals
            tree_preds = np.array([
                tree.predict(recent_features)[0]
                for tree in self.model.estimators_
            ])
            pred = np.mean(tree_preds)
            pred_std = np.std(tree_preds)

            predictions.append((float(pred), float(pred_std)))

            next_date = last_date + pd.Timedelta(days=i + 1)
            while next_date.dayofweek >= 5:
                next_date += pd.Timedelta(days=1)
            forecast_dates.append(next_date)

            recent_features = recent_features.copy()
            prev_price = predictions[-2][0] if len(predictions) > 1 else current_price
            recent_features["returns_1d"] = (pred - prev_price) / prev_price

        pred_prices = [p[0] for p in predictions]
        pred_stds = [p[1] for p in predictions]
        predicted_price = pred_prices[-1]
        expected_return = ((predicted_price - current_price) / current_price) * 100

        forecast_df = pd.DataFrame({
            "ds": forecast_dates,
            "yhat": pred_prices,
            "yhat_lower": [p - 1.96 * s for p, s in zip(pred_prices, pred_stds)],
            "yhat_upper": [p + 1.96 * s for p, s in zip(pred_prices, pred_stds)],
        })

        historical_days = 60
        historical_data = df[["close"]].tail(historical_days).copy()
        historical_data = historical_data.rename(columns={"close": "actual"})
        historical_data.index.name = "ds"
        historical_data = historical_data.reset_index()

        return {
            "current_price": current_price,
            "predicted_price": predicted_price,
            "expected_return_pct": expected_return,
            "confidence_lower": float(pred_prices[-1] - 1.96 * pred_stds[-1]),
            "confidence_upper": float(pred_prices[-1] + 1.96 * pred_stds[-1]),
            "forecast_df": forecast_df,
            "historical_df": historical_data,
        }

    def evaluate(self, test_days: int = 30) -> Dict[str, Any]:
        """Evaluate model using walk-forward backtesting."""
        if self.data is None:
            self.prepare_features()

        df = self.data.copy()
        valid_mask = df[self.feature_columns].notna().all(axis=1) & df["target"].notna()
        df = df[valid_mask]

        if len(df) < test_days + 100:
            raise ValueError("Not enough data for evaluation")

        train_df = df.iloc[:-test_days]
        test_df = df.iloc[-test_days:]

        eval_model = RandomForestRegressor(
            **self.params,
            random_state=42,
            n_jobs=-1,
        )
        eval_model.fit(train_df[self.feature_columns], train_df["target"])

        y_test = test_df["target"].values
        predictions = eval_model.predict(test_df[self.feature_columns])

        mape = np.mean(np.abs((y_test - predictions) / y_test)) * 100
        rmse = np.sqrt(np.mean((y_test - predictions) ** 2))
        mae = np.mean(np.abs(y_test - predictions))

        actual_direction = np.diff(y_test) > 0
        predicted_direction = np.diff(predictions) > 0
        directional_accuracy = np.mean(actual_direction == predicted_direction) * 100

        return {
            "mape": float(mape),
            "rmse": float(rmse),
            "mae": float(mae),
            "directional_accuracy": float(directional_accuracy),
            "test_days": test_days,
            "model": "random_forest",
        }

    def get_feature_importance(self) -> Dict[str, Any]:
        """Get feature importance from trained model."""
        if self.model is None:
            raise ValueError("Model not trained. Call train() first.")

        importance = self.model.feature_importances_
        importance_dict = dict(zip(self.feature_columns, importance.tolist()))
        sorted_importance = dict(sorted(importance_dict.items(), key=lambda x: x[1], reverse=True))

        return {"builtin_importance": sorted_importance}

    def save_model(self, path: Optional[str] = None):
        if self.model is None:
            raise ValueError("No model to save")
        if path is None:
            save_dir = os.path.join(os.path.dirname(__file__), "saved")
            os.makedirs(save_dir, exist_ok=True)
            path = os.path.join(save_dir, f"random_forest_{self.ticker}.pkl")
        with open(path, "wb") as f:
            pickle.dump({
                "model": self.model,
                "feature_columns": self.feature_columns,
                "params": self.params,
                "ticker": self.ticker,
            }, f)

    def load_model(self, path: Optional[str] = None):
        if path is None:
            path = os.path.join(os.path.dirname(__file__), "saved", f"random_forest_{self.ticker}.pkl")
        if not os.path.exists(path):
            raise FileNotFoundError(f"No saved model at {path}")
        with open(path, "rb") as f:
            data = pickle.load(f)
        self.model = data["model"]
        self.feature_columns = data["feature_columns"]
        self.params = data["params"]
