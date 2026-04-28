"""
Direction Classifier — Stage 1 of the signed-return forecasting pipeline.

Predicts P(next-day return > 0) using XGBoost binary classification. Consumes
the shared feature matrix (technical indicators, cross-asset signals, lag
features) and outputs calibrated probabilities for the magnitude regressor
and combination layer in later stages.
"""

import logging
import os
import pickle
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Lazy XGBoost import — matches the existing forecaster pattern so the Flask
# app doesn't crash at startup if the dep is missing.
_xgb = None


def _load_xgboost():
    global _xgb
    if _xgb is None:
        import xgboost as xgb

        _xgb = xgb
    return _xgb


class DirectionClassifier:
    """Binary classifier predicting P(next-day return > 0).

    Design choices:
    - Loss is log-loss (binary:logistic). Hard-direction wrong predictions are
      penalized more by log-loss than by MSE on signed returns, which matches
      how this signal feeds the two-stage combiner.
    - We keep rows that have NaN in lag columns (early days of the window).
      XGBoost handles NaN natively by learning a default split direction.
      Only rows with NaN in target_direction are filtered.
    - Hyperparameters mirror the regression XGBoostForecaster so feature
      importances are comparable across the two stages.
    """

    def __init__(self, ticker: str, **kwargs):
        self.ticker = ticker
        self.model = None
        self.feature_columns = None
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

    # ------------------------------------------------------------------
    # Data prep
    # ------------------------------------------------------------------

    def prepare_features(self, period: str = "2y") -> pd.DataFrame:
        """Build feature matrix with cross-asset + lag features enabled.

        Sentiment / news / LLM features stay off until those phases are wired
        in (Phase 7 of the workshop).
        """
        from models.feature_engineering import build_feature_matrix, get_feature_columns

        self.data = build_feature_matrix(
            self.ticker,
            period=period,
            include_cross_asset=True,
            include_lags=True,
        )
        # Intersect declared feature names with what's actually in the frame —
        # cross-asset cols can drop out if yfinance is rate-limited
        self.feature_columns = [
            c
            for c in get_feature_columns(include_cross_asset=True, include_lags=True)
            if c in self.data.columns
        ]
        return self.data

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(
        self, df: Optional[pd.DataFrame] = None, test_ratio: float = 0.1
    ) -> Dict[str, Any]:
        """Train XGBoost binary classifier with early stopping on val log-loss.

        Returns a dict of train/val accuracy, log-loss, AUC, plus class balance
        and best iteration.
        """
        from sklearn.metrics import accuracy_score, log_loss, roc_auc_score

        xgb = _load_xgboost()

        if df is None:
            if self.data is None:
                self.prepare_features()
            df = self.data

        features = df[self.feature_columns]
        target = df["target_direction"]

        # Only filter rows where target is NaN (last target_days rows of the
        # window). NaN in feature columns is fine — XGBoost handles it.
        valid_mask = target.notna()
        features = features[valid_mask]
        target = target[valid_mask]

        # Chronological split — never shuffle time series
        split_idx = int(len(features) * (1 - test_ratio))
        X_train, X_val = features.iloc[:split_idx], features.iloc[split_idx:]
        y_train, y_val = target.iloc[:split_idx], target.iloc[split_idx:]

        self.model = xgb.XGBClassifier(
            n_estimators=self.params["n_estimators"],
            max_depth=self.params["max_depth"],
            learning_rate=self.params["learning_rate"],
            subsample=self.params["subsample"],
            colsample_bytree=self.params["colsample_bytree"],
            min_child_weight=self.params["min_child_weight"],
            reg_alpha=self.params["reg_alpha"],
            reg_lambda=self.params["reg_lambda"],
            objective="binary:logistic",
            eval_metric="logloss",
            random_state=42,
            early_stopping_rounds=30,
        )

        self.model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

        # Probabilities, not hard labels — these flow through to the magnitude
        # combiner in Part 6
        train_proba = self.model.predict_proba(X_train)[:, 1]
        val_proba = self.model.predict_proba(X_val)[:, 1]

        metrics = {
            "train_accuracy": float(accuracy_score(y_train, train_proba > 0.5)),
            "val_accuracy": float(accuracy_score(y_val, val_proba > 0.5)),
            "train_log_loss": float(log_loss(y_train, train_proba)),
            "val_log_loss": float(log_loss(y_val, val_proba)),
            "train_auc": float(roc_auc_score(y_train, train_proba)),
            "val_auc": float(roc_auc_score(y_val, val_proba)),
            "best_iteration": (
                int(self.model.best_iteration)
                if hasattr(self.model, "best_iteration")
                else self.params["n_estimators"]
            ),
            "n_features": len(self.feature_columns),
            "train_size": int(len(X_train)),
            "val_size": int(len(X_val)),
            "class_balance_train": float(y_train.mean()),
            "class_balance_val": float(y_val.mean()),
        }

        logger.info(
            f"DirectionClassifier {self.ticker}: "
            f"val_acc={metrics['val_accuracy']:.3f}, "
            f"val_auc={metrics['val_auc']:.3f}, "
            f"val_logloss={metrics['val_log_loss']:.3f}"
        )
        return metrics

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict_proba(self, df: Optional[pd.DataFrame] = None) -> pd.Series:
        """Return P(up) probabilities aligned to the input index.

        If df is None, predicts on self.data. The returned Series is aligned
        by date so it can be merged with magnitude predictions in Part 6.
        """
        if self.model is None:
            raise ValueError("Model not trained. Call train() first.")

        if df is None:
            df = self.data

        X = df[self.feature_columns]
        proba = self.model.predict_proba(X)[:, 1]
        return pd.Series(proba, index=X.index, name="p_up")

    def predict_latest(self) -> float:
        """Convenience: return P(up) for the most recent row.

        Useful for the daily prediction display in the frontend.
        """
        if self.data is None:
            raise ValueError("No data loaded. Call prepare_features() first.")
        latest = self.data[self.feature_columns].iloc[-1:]
        return float(self.model.predict_proba(latest)[0, 1])

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate(self, test_days: int = 30) -> Dict[str, Any]:
        """Walk-forward backtest on the last test_days.

        Trains a fresh model on everything except the last test_days, predicts
        on the held-out test set, reports accuracy / log-loss / AUC plus the
        naive baseline ("always predict up", which equals the up-day rate).
        """
        from sklearn.metrics import accuracy_score, log_loss, roc_auc_score

        xgb = _load_xgboost()

        if self.data is None:
            self.prepare_features()

        df = self.data.dropna(subset=["target_direction"]).copy()

        if len(df) < test_days + 100:
            raise ValueError(
                f"Not enough data for evaluation. Have {len(df)}, need {test_days + 100}"
            )

        train_df = df.iloc[:-test_days]
        test_df = df.iloc[-test_days:]

        # Internal val split for early stopping during eval training
        split_idx = int(len(train_df) * 0.9)
        X_train = train_df[self.feature_columns].iloc[:split_idx]
        y_train = train_df["target_direction"].iloc[:split_idx]
        X_val = train_df[self.feature_columns].iloc[split_idx:]
        y_val = train_df["target_direction"].iloc[split_idx:]

        eval_model = xgb.XGBClassifier(
            **{k: v for k, v in self.params.items()},
            objective="binary:logistic",
            eval_metric="logloss",
            random_state=42,
            early_stopping_rounds=30,
        )
        eval_model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

        X_test = test_df[self.feature_columns]
        y_test = test_df["target_direction"].astype(int).values
        proba = eval_model.predict_proba(X_test)[:, 1]

        # Defend against single-class test windows (rare but possible at small
        # test_days). roc_auc_score raises on single-class y_true.
        try:
            auc = float(roc_auc_score(y_test, proba))
        except ValueError:
            auc = float("nan")

        return {
            "model": "direction_classifier",
            "test_days": test_days,
            "accuracy": float(accuracy_score(y_test, proba > 0.5)),
            "log_loss": float(log_loss(y_test, proba, labels=[0, 1])),
            "auc": auc,
            "naive_up_rate": float(y_test.mean()),
            "naive_baseline_accuracy": float(max(y_test.mean(), 1 - y_test.mean())),
            "n_predictions": int(len(y_test)),
        }

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_feature_importance(self) -> Dict[str, float]:
        """Return feature importances sorted descending."""
        if self.model is None:
            raise ValueError("Model not trained. Call train() first.")
        importance = self.model.feature_importances_
        d = dict(zip(self.feature_columns, importance.tolist()))
        return dict(sorted(d.items(), key=lambda x: x[1], reverse=True))

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_model(self, path: Optional[str] = None):
        if self.model is None:
            raise ValueError("No model to save")
        if path is None:
            save_dir = os.path.join(os.path.dirname(__file__), "saved")
            os.makedirs(save_dir, exist_ok=True)
            path = os.path.join(save_dir, f"direction_{self.ticker}.pkl")
        with open(path, "wb") as f:
            pickle.dump(
                {
                    "model": self.model,
                    "feature_columns": self.feature_columns,
                    "params": self.params,
                    "ticker": self.ticker,
                },
                f,
            )
        logger.info(f"Direction model saved to {path}")

    def load_model(self, path: Optional[str] = None):
        if path is None:
            path = os.path.join(
                os.path.dirname(__file__), "saved", f"direction_{self.ticker}.pkl"
            )
        if not os.path.exists(path):
            raise FileNotFoundError(f"No saved model at {path}")
        with open(path, "rb") as f:
            data = pickle.load(f)
        self.model = data["model"]
        self.feature_columns = data["feature_columns"]
        self.params = data["params"]
