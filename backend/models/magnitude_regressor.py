"""
Magnitude Regressor — Stage 2 of the signed-return forecasting pipeline.

Predicts E[|next-day return|] conditional on the direction outcome. Two
instances are trained per ticker:

    mag_up   = MagnitudeRegressor(ticker, direction='up')   # trained on up-days
    mag_down = MagnitudeRegressor(ticker, direction='down') # trained on down-days

The combiner in Part 6 mixes them with the direction probability:

    predicted_signed_return = p_up * mag_up.predict() - (1 - p_up) * mag_down.predict()

Splitting the magnitude model by direction lets each instance specialize on
the asymmetric distributions of up-day vs down-day moves. Up days tend to be
closer to lognormal; down days have heavier tails (panic/limit-down).
"""

import logging
import os
import pickle
from typing import Any, Dict, Literal, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Lazy XGBoost import — same pattern as the rest of the model layer
_xgb = None


def _load_xgboost():
    global _xgb
    if _xgb is None:
        import xgboost as xgb

        _xgb = xgb
    return _xgb


class MagnitudeRegressor:
    """XGBoost regressor predicting absolute next-day return given direction.

    Design choices:
    - Target is always non-negative (`target_abs_return`), so MSE loss is well
      behaved and predictions are clamped at 0.
    - Trained on a directional subset (up-days or down-days) so each instance
      specializes on one tail of the return distribution.
    - Same feature set as DirectionClassifier so feature-importance reports
      are comparable across the two stages.
    - min_child_weight is lower (2 vs 3 in the direction model) because each
      magnitude model sees roughly half the data.
    """

    def __init__(self, ticker: str, direction: Literal["up", "down"], **kwargs):
        if direction not in ("up", "down"):
            raise ValueError(f"direction must be 'up' or 'down', got {direction!r}")
        self.ticker = ticker
        self.direction = direction
        self.model = None
        self.feature_columns = None
        self.data = None
        self.params = {
            "n_estimators": kwargs.get("n_estimators", 500),
            "max_depth": kwargs.get("max_depth", 6),
            "learning_rate": kwargs.get("learning_rate", 0.05),
            "subsample": kwargs.get("subsample", 0.8),
            "colsample_bytree": kwargs.get("colsample_bytree", 0.8),
            # Lower than direction classifier (3) — half the rows means
            # we want to allow leaves to form on smaller groups.
            "min_child_weight": kwargs.get("min_child_weight", 2),
            "reg_alpha": kwargs.get("reg_alpha", 0.1),
            "reg_lambda": kwargs.get("reg_lambda", 1.0),
        }

    # ------------------------------------------------------------------
    # Data prep
    # ------------------------------------------------------------------

    def prepare_features(self, period: str = "2y") -> pd.DataFrame:
        """Build the full feature matrix; subsetting by direction happens in
        train(). The unfiltered `self.data` is preserved so predict() at
        inference time can score any row regardless of direction."""
        from models.feature_engineering import build_feature_matrix, get_feature_columns

        self.data = build_feature_matrix(
            self.ticker,
            period=period,
            include_cross_asset=True,
            include_lags=True,
        )
        self.feature_columns = [
            c
            for c in get_feature_columns(include_cross_asset=True, include_lags=True)
            if c in self.data.columns
        ]
        return self.data

    def _filter_by_direction(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return only the rows matching this regressor's direction."""
        target_dir = 1 if self.direction == "up" else 0
        mask = df["target_direction"] == target_dir
        return df[mask]

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(
        self, df: Optional[pd.DataFrame] = None, test_ratio: float = 0.1
    ) -> Dict[str, Any]:
        """Train on the directional subset.

        Returns metrics: train/val MAPE, RMSE, MAE, R², plus best iteration.
        """
        from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

        xgb = _load_xgboost()

        if df is None:
            if self.data is None:
                self.prepare_features()
            df = self.data

        # 1) Drop rows with NaN target (last target_days rows)
        df_valid = df.dropna(subset=["target_direction", "target_abs_return"])

        # 2) Subset to directional rows
        df_dir = self._filter_by_direction(df_valid)

        if len(df_dir) < 50:
            raise ValueError(
                f"Not enough {self.direction}-direction samples for {self.ticker}: "
                f"have {len(df_dir)}, need at least 50"
            )

        features = df_dir[self.feature_columns]
        target = df_dir["target_abs_return"]

        # Chronological split — never shuffle time series
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
            eval_metric="rmse",
            random_state=42,
            early_stopping_rounds=30,
        )

        self.model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

        # Predictions are absolute returns (always >= 0). Clamp negative model
        # outputs at 0 — XGBoost regression can produce small negatives near
        # the floor of the target distribution.
        train_pred = np.clip(self.model.predict(X_train), 0, None)
        val_pred = np.clip(self.model.predict(X_val), 0, None)

        # MAPE on returns is sensitive to small denominators — guard against
        # division by zero on near-zero return days
        def safe_mape(y_true, y_pred, eps=1e-4):
            return float(
                np.mean(np.abs((y_true - y_pred) / np.maximum(np.abs(y_true), eps)))
                * 100
            )

        metrics = {
            "direction": self.direction,
            "train_rmse": float(np.sqrt(mean_squared_error(y_train, train_pred))),
            "val_rmse": float(np.sqrt(mean_squared_error(y_val, val_pred))),
            "train_mae": float(mean_absolute_error(y_train, train_pred)),
            "val_mae": float(mean_absolute_error(y_val, val_pred)),
            "train_mape": safe_mape(y_train.values, train_pred),
            "val_mape": safe_mape(y_val.values, val_pred),
            "train_r2": float(r2_score(y_train, train_pred)),
            "val_r2": float(r2_score(y_val, val_pred)),
            "best_iteration": (
                int(self.model.best_iteration)
                if hasattr(self.model, "best_iteration")
                else self.params["n_estimators"]
            ),
            "n_features": len(self.feature_columns),
            "train_size": int(len(X_train)),
            "val_size": int(len(X_val)),
            "mean_abs_return_train": float(y_train.mean()),
            "mean_abs_return_val": float(y_val.mean()),
        }

        logger.info(
            f"MagnitudeRegressor[{self.direction}] {self.ticker}: "
            f"val_rmse={metrics['val_rmse']:.4f}, "
            f"val_mae={metrics['val_mae']:.4f}, "
            f"val_r2={metrics['val_r2']:.3f}"
        )
        return metrics

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict(self, df: Optional[pd.DataFrame] = None) -> pd.Series:
        """Return predicted absolute return aligned to the input index.

        Note: this scores ANY row, regardless of direction. The combiner
        passes the same input rows to both up-magnitude and down-magnitude
        models and weights them by P(up) and 1-P(up) respectively.
        """
        if self.model is None:
            raise ValueError("Model not trained. Call train() first.")
        if df is None:
            df = self.data

        X = df[self.feature_columns]
        pred = np.clip(self.model.predict(X), 0, None)
        return pd.Series(pred, index=X.index, name=f"mag_{self.direction}")

    def predict_latest(self) -> float:
        """Convenience: predict for the most recent row in self.data."""
        if self.data is None:
            raise ValueError("No data loaded. Call prepare_features() first.")
        latest = self.data[self.feature_columns].iloc[-1:]
        return float(np.clip(self.model.predict(latest)[0], 0, None))

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate(self, test_days: int = 30) -> Dict[str, Any]:
        """Walk-forward backtest restricted to the directional subset of the
        last test_days. Trains a fresh model on everything before that window."""
        from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

        xgb = _load_xgboost()

        if self.data is None:
            self.prepare_features()

        df = self.data.dropna(subset=["target_direction", "target_abs_return"]).copy()

        if len(df) < test_days + 100:
            raise ValueError(
                f"Not enough data for evaluation. Have {len(df)}, need {test_days + 100}"
            )

        train_df = df.iloc[:-test_days]
        test_df = df.iloc[-test_days:]

        # Subset both halves to this regressor's direction
        train_dir = self._filter_by_direction(train_df)
        test_dir = self._filter_by_direction(test_df)

        if len(train_dir) < 50 or len(test_dir) == 0:
            return {
                "model": "magnitude_regressor",
                "direction": self.direction,
                "error": (
                    f"Insufficient {self.direction}-direction samples: "
                    f"train={len(train_dir)}, test={len(test_dir)}"
                ),
                "test_days": test_days,
            }

        # Internal val split for early stopping
        split_idx = int(len(train_dir) * 0.9)
        X_train = train_dir[self.feature_columns].iloc[:split_idx]
        y_train = train_dir["target_abs_return"].iloc[:split_idx]
        X_val = train_dir[self.feature_columns].iloc[split_idx:]
        y_val = train_dir["target_abs_return"].iloc[split_idx:]

        eval_model = xgb.XGBRegressor(
            **{k: v for k, v in self.params.items()},
            objective="reg:squarederror",
            eval_metric="rmse",
            random_state=42,
            early_stopping_rounds=30,
        )
        eval_model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

        X_test = test_dir[self.feature_columns]
        y_test = test_dir["target_abs_return"].values
        pred = np.clip(eval_model.predict(X_test), 0, None)

        return {
            "model": "magnitude_regressor",
            "direction": self.direction,
            "test_days": test_days,
            "n_test_samples": int(len(y_test)),
            "rmse": float(np.sqrt(mean_squared_error(y_test, pred))),
            "mae": float(mean_absolute_error(y_test, pred)),
            "r2": float(r2_score(y_test, pred)) if len(y_test) > 1 else float("nan"),
            "mean_actual": float(y_test.mean()),
            "mean_predicted": float(pred.mean()),
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
            path = os.path.join(
                save_dir, f"magnitude_{self.direction}_{self.ticker}.pkl"
            )
        with open(path, "wb") as f:
            pickle.dump(
                {
                    "model": self.model,
                    "feature_columns": self.feature_columns,
                    "params": self.params,
                    "ticker": self.ticker,
                    "direction": self.direction,
                },
                f,
            )
        logger.info(f"Magnitude model saved to {path}")

    def load_model(self, path: Optional[str] = None):
        if path is None:
            path = os.path.join(
                os.path.dirname(__file__),
                "saved",
                f"magnitude_{self.direction}_{self.ticker}.pkl",
            )
        if not os.path.exists(path):
            raise FileNotFoundError(f"No saved model at {path}")
        with open(path, "rb") as f:
            data = pickle.load(f)
        self.model = data["model"]
        self.feature_columns = data["feature_columns"]
        self.params = data["params"]
        if data.get("direction") and data["direction"] != self.direction:
            raise ValueError(
                f"Model file is for direction={data['direction']}, "
                f"but instance is direction={self.direction}"
            )
