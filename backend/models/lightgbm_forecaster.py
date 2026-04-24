"""
LightGBM Stock Price Forecaster

Leaf-wise gradient boosting model for stock price prediction.
Key advantage over XGBoost: native categorical feature handling,
faster training, and histogram-based split finding.
"""

import numpy as np
import pandas as pd
import logging
import os
import pickle
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

_lgb = None


def _load_lightgbm():
    global _lgb
    if _lgb is None:
        import lightgbm as lgb

        _lgb = lgb
    return _lgb


class LightGBMForecaster:
    """
    Stock price forecaster using LightGBM leaf-wise gradient boosting.

    Features:
    - Native categorical feature support (no one-hot encoding needed)
    - Histogram-based split finding for faster training
    - Built-in feature importance
    """

    def __init__(self, ticker: str, **kwargs):
        self.ticker = ticker
        self.model = None
        self.feature_columns = None
        self.categorical_features = []
        self.data = None
        self.params = {
            "n_estimators": kwargs.get("n_estimators", 500),
            "max_depth": kwargs.get("max_depth", -1),  # -1 = no limit (leaf-wise)
            "num_leaves": kwargs.get("num_leaves", 31),
            "learning_rate": kwargs.get("learning_rate", 0.05),
            "subsample": kwargs.get("subsample", 0.8),
            "colsample_bytree": kwargs.get("colsample_bytree", 0.8),
            "min_child_samples": kwargs.get("min_child_samples", 20),
            "reg_alpha": kwargs.get("reg_alpha", 0.1),
            "reg_lambda": kwargs.get("reg_lambda", 1.0),
        }

    def prepare_features(self, period: str = "2y") -> pd.DataFrame:
        """Compute feature matrix using shared feature engineering module."""
        from models.feature_engineering import build_feature_matrix, get_feature_columns

        self.data = build_feature_matrix(self.ticker, period=period)
        self.feature_columns = [
            c for c in get_feature_columns() if c in self.data.columns
        ]

        # Identify categorical features for native handling
        self.categorical_features = [
            c for c in ["day_of_week", "month", "quarter"] if c in self.feature_columns
        ]

        return self.data

    def train(
        self, df: Optional[pd.DataFrame] = None, test_ratio: float = 0.1
    ) -> Dict[str, Any]:
        """Train LightGBM model with early stopping."""
        lgb = _load_lightgbm()

        if df is None:
            if self.data is None:
                self.prepare_features()
            df = self.data

        features = df[self.feature_columns].copy()
        target = df["target"].copy()

        valid_mask = features.notna().all(axis=1) & target.notna()
        features = features[valid_mask]
        target = target[valid_mask]

        # Convert categorical columns to category dtype for LightGBM native handling
        for col in self.categorical_features:
            if col in features.columns:
                features[col] = features[col].astype("category")

        split_idx = int(len(features) * (1 - test_ratio))
        X_train, X_val = features.iloc[:split_idx], features.iloc[split_idx:]
        y_train, y_val = target.iloc[:split_idx], target.iloc[split_idx:]

        callbacks = [
            lgb.early_stopping(stopping_rounds=30, verbose=False),
            lgb.log_evaluation(period=0),
        ]

        self.model = lgb.LGBMRegressor(
            n_estimators=self.params["n_estimators"],
            max_depth=self.params["max_depth"],
            num_leaves=self.params["num_leaves"],
            learning_rate=self.params["learning_rate"],
            subsample=self.params["subsample"],
            colsample_bytree=self.params["colsample_bytree"],
            min_child_samples=self.params["min_child_samples"],
            reg_alpha=self.params["reg_alpha"],
            reg_lambda=self.params["reg_lambda"],
            objective="regression",
            random_state=42,
            verbose=-1,
        )

        self.model.fit(
            X_train,
            y_train,
            eval_set=[(X_val, y_val)],
            callbacks=callbacks,
        )

        train_pred = self.model.predict(X_train)
        val_pred = self.model.predict(X_val)

        train_mape = np.mean(np.abs((y_train - train_pred) / y_train)) * 100
        val_mape = np.mean(np.abs((y_val - val_pred) / y_val)) * 100

        logger.info(
            f"LightGBM trained for {self.ticker}: train MAPE={train_mape:.2f}%, val MAPE={val_mape:.2f}%"
        )

        return {
            "train_mape": float(train_mape),
            "val_mape": float(val_mape),
            "best_iteration": (
                self.model.best_iteration_
                if hasattr(self.model, "best_iteration_")
                else self.params["n_estimators"]
            ),
            "n_features": len(self.feature_columns),
            "n_categorical": len(self.categorical_features),
            "train_size": len(X_train),
            "val_size": len(X_val),
        }

    def forecast(self, days_ahead: int = 30) -> Dict[str, Any]:
        """Generate multi-step forecast by iterative single-step prediction."""
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
        for col in self.categorical_features:
            if col in recent_features.columns:
                recent_features[col] = recent_features[col].astype("category")

        for i in range(days_ahead):
            pred = self.model.predict(recent_features)[0]
            predictions.append(float(pred))

            next_date = last_date + pd.Timedelta(days=i + 1)
            while next_date.dayofweek >= 5:
                next_date += pd.Timedelta(days=1)
            forecast_dates.append(next_date)

            recent_features = recent_features.copy()
            if len(predictions) > 1:
                recent_features["returns_1d"] = (pred - predictions[-2]) / predictions[
                    -2
                ]
            else:
                recent_features["returns_1d"] = (pred - current_price) / current_price

        predicted_price = predictions[-1]
        expected_return = ((predicted_price - current_price) / current_price) * 100

        # Confidence interval from training residuals
        train_pred = self.model.predict(df[self.feature_columns].dropna())
        residuals = df["target"].dropna().values[: len(train_pred)] - train_pred
        std_residual = np.std(residuals)

        forecast_df = pd.DataFrame(
            {
                "ds": forecast_dates,
                "yhat": predictions,
                "yhat_lower": [p - 1.96 * std_residual for p in predictions],
                "yhat_upper": [p + 1.96 * std_residual for p in predictions],
            }
        )

        historical_days = 60
        historical_data = df[["close"]].tail(historical_days).copy()
        historical_data = historical_data.rename(columns={"close": "actual"})
        historical_data.index.name = "ds"
        historical_data = historical_data.reset_index()

        return {
            "current_price": current_price,
            "predicted_price": predicted_price,
            "expected_return_pct": expected_return,
            "confidence_lower": float(predicted_price - 1.96 * std_residual),
            "confidence_upper": float(predicted_price + 1.96 * std_residual),
            "forecast_df": forecast_df,
            "historical_df": historical_data,
        }

    def evaluate(self, test_days: int = 30) -> Dict[str, Any]:
        """Evaluate model using walk-forward backtesting."""
        lgb = _load_lightgbm()

        if self.data is None:
            self.prepare_features()

        df = self.data.copy()
        valid_mask = df[self.feature_columns].notna().all(axis=1) & df["target"].notna()
        df = df[valid_mask]

        if len(df) < test_days + 100:
            raise ValueError(f"Not enough data for evaluation")

        train_df = df.iloc[:-test_days]
        test_df = df.iloc[-test_days:]

        split_idx = int(len(train_df) * 0.9)
        X_train = train_df[self.feature_columns].iloc[:split_idx].copy()
        y_train = train_df["target"].iloc[:split_idx]
        X_val = train_df[self.feature_columns].iloc[split_idx:].copy()
        y_val = train_df["target"].iloc[split_idx:]

        for col in self.categorical_features:
            if col in X_train.columns:
                X_train[col] = X_train[col].astype("category")
                X_val[col] = X_val[col].astype("category")

        callbacks = [
            lgb.early_stopping(stopping_rounds=30, verbose=False),
            lgb.log_evaluation(period=0),
        ]

        eval_model = lgb.LGBMRegressor(
            **{k: v for k, v in self.params.items()},
            objective="regression",
            random_state=42,
            verbose=-1,
        )
        eval_model.fit(
            X_train,
            y_train,
            eval_set=[(X_val, y_val)],
            callbacks=callbacks,
        )

        X_test = test_df[self.feature_columns].copy()
        for col in self.categorical_features:
            if col in X_test.columns:
                X_test[col] = X_test[col].astype("category")

        y_test = test_df["target"].values
        predictions = eval_model.predict(X_test)

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
            "model": "lightgbm",
        }

    def get_feature_importance(self) -> Dict[str, Any]:
        """Get feature importance from trained model."""
        if self.model is None:
            raise ValueError("Model not trained. Call train() first.")

        importance = self.model.feature_importances_
        importance_dict = dict(zip(self.feature_columns, importance.tolist()))
        sorted_importance = dict(
            sorted(importance_dict.items(), key=lambda x: x[1], reverse=True)
        )

        return {"builtin_importance": sorted_importance}

    def save_model(self, path: Optional[str] = None):
        """Save trained model to disk."""
        if self.model is None:
            raise ValueError("No model to save")
        if path is None:
            save_dir = os.path.join(os.path.dirname(__file__), "saved")
            os.makedirs(save_dir, exist_ok=True)
            path = os.path.join(save_dir, f"lightgbm_{self.ticker}.pkl")
        with open(path, "wb") as f:
            pickle.dump(
                {
                    "model": self.model,
                    "feature_columns": self.feature_columns,
                    "categorical_features": self.categorical_features,
                    "params": self.params,
                    "ticker": self.ticker,
                },
                f,
            )

    def load_model(self, path: Optional[str] = None):
        """Load trained model from disk."""
        if path is None:
            path = os.path.join(
                os.path.dirname(__file__), "saved", f"lightgbm_{self.ticker}.pkl"
            )
        if not os.path.exists(path):
            raise FileNotFoundError(f"No saved model at {path}")
        with open(path, "rb") as f:
            data = pickle.load(f)
        self.model = data["model"]
        self.feature_columns = data["feature_columns"]
        self.categorical_features = data.get("categorical_features", [])
        self.params = data["params"]
