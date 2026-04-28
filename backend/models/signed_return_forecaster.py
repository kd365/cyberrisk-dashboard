"""
Signed Return Forecaster — Stage 3 of the two-stage architecture.

Owns three sub-models and combines them into a unified next-day signed-return
prediction. The architectural payoff over single-target price regression is:
  - Direction model optimizes for log-loss / AUC (right tool for "which way?")
  - Magnitude models optimize for MSE on |return|, specialized by direction
  - Combined output is a calibrated signed-return distribution

Combined formula:
    signed_return = p_up * mag_up - (1 - p_up) * mag_down

Evaluation metrics target the questions a quant actually asks:
  - Information Coefficient (Spearman corr of predicted vs actual return)
  - Directional accuracy + lift over naive baseline
  - Hit rate at a confidence threshold
  - Sharpe ratio of the long-short signal
  - Calibration via decile binning
"""

import logging
import os
import pickle
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from .direction_classifier import DirectionClassifier
from .magnitude_regressor import MagnitudeRegressor

logger = logging.getLogger(__name__)


class SignedReturnForecaster:
    """Joint owner of direction + up-magnitude + down-magnitude models."""

    def __init__(self, ticker: str, include_llm: bool = False, **kwargs):
        """
        Args:
            ticker: Stock ticker symbol.
            include_llm: When True, the feature matrix joins LLM-extracted
                features from the Neo4j Organization node (cyber_sector_relevance,
                competitive_moat dummies, etc.). Falls back to no-op if Neo4j
                is unreachable.
            **kwargs: Forwarded to DirectionClassifier and MagnitudeRegressor.
        """
        self.ticker = ticker
        self.include_llm = include_llm
        self.direction_clf: Optional[DirectionClassifier] = None
        self.mag_up: Optional[MagnitudeRegressor] = None
        self.mag_down: Optional[MagnitudeRegressor] = None
        self.data: Optional[pd.DataFrame] = None
        self._kwargs = kwargs  # forwarded to sub-model constructors

    # ------------------------------------------------------------------
    # Data prep — build feature matrix once, share across all 3 models
    # ------------------------------------------------------------------

    def prepare_features(self, period: str = "2y") -> pd.DataFrame:
        """Fetch the feature matrix once and reuse across sub-models.

        Without this, each sub-model would call build_feature_matrix()
        independently — three yfinance fetches, three lag computations.
        Sharing the frame makes the trio essentially free after the first
        ticker's prep.
        """
        from models.feature_engineering import build_feature_matrix

        self.data = build_feature_matrix(
            self.ticker,
            period=period,
            include_cross_asset=True,
            include_lags=True,
            include_llm=self.include_llm,
        )
        return self.data

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(self, test_ratio: float = 0.1) -> Dict[str, Any]:
        """Train all three sub-models on the shared feature matrix.

        Returns a dict with stage metrics nested under 'direction', 'mag_up',
        'mag_down', plus a 'combined_validation' block that scores the joint
        signed-return prediction on the same chronological holdout.
        """
        if self.data is None:
            self.prepare_features()

        # Initialize sub-models with the shared data already loaded so they
        # don't re-fetch.
        self.direction_clf = DirectionClassifier(self.ticker, **self._kwargs)
        self.direction_clf.data = self.data
        self.direction_clf.feature_columns = self._get_feature_cols()

        self.mag_up = MagnitudeRegressor(self.ticker, direction="up", **self._kwargs)
        self.mag_up.data = self.data
        self.mag_up.feature_columns = self._get_feature_cols()

        self.mag_down = MagnitudeRegressor(
            self.ticker, direction="down", **self._kwargs
        )
        self.mag_down.data = self.data
        self.mag_down.feature_columns = self._get_feature_cols()

        # Train each stage. Pass df=self.data explicitly so they don't
        # re-prep; subset filtering happens inside each train().
        direction_metrics = self.direction_clf.train(
            df=self.data, test_ratio=test_ratio
        )
        mag_up_metrics = self.mag_up.train(df=self.data, test_ratio=test_ratio)
        mag_down_metrics = self.mag_down.train(df=self.data, test_ratio=test_ratio)

        # Combined validation: score the same chronological holdout that the
        # direction model used (which is the most-natural "joint" eval)
        combined = self._combined_holdout_metrics(test_ratio=test_ratio)

        return {
            "direction": direction_metrics,
            "mag_up": mag_up_metrics,
            "mag_down": mag_down_metrics,
            "combined_validation": combined,
        }

    def _get_feature_cols(self):
        """Helper: column intersection used by every sub-model."""
        from models.feature_engineering import get_feature_columns

        return [
            c
            for c in get_feature_columns(
                include_cross_asset=True,
                include_lags=True,
                include_llm=self.include_llm,
            )
            if c in self.data.columns
        ]

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict(self, df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """Produce the full prediction frame.

        Columns:
            p_up           : direction probability
            mag_up_pred    : E[return | up]
            mag_down_pred  : E[|return| | down]
            signed_return  : combined prediction
            confidence     : |2*p_up - 1| ∈ [0, 1]
            predicted_direction : sign(signed_return)
        """
        self._require_trained()
        if df is None:
            df = self.data

        p_up = self.direction_clf.predict_proba(df)
        m_up = self.mag_up.predict(df)
        m_down = self.mag_down.predict(df)

        signed = p_up * m_up - (1 - p_up) * m_down
        confidence = (2 * p_up - 1).abs()

        out = pd.DataFrame(
            {
                "p_up": p_up,
                "mag_up_pred": m_up,
                "mag_down_pred": m_down,
                "signed_return": signed,
                "confidence": confidence,
                "predicted_direction": np.sign(signed).astype(int),
            },
            index=df.index,
        )
        return out

    def predict_latest(self) -> Dict[str, Any]:
        """Single-row prediction for the most recent day.

        Returns dict shaped for the frontend daily-prediction card.
        """
        self._require_trained()
        latest = self.data.iloc[-1:]
        pred = self.predict(latest).iloc[0].to_dict()
        pred["ticker"] = self.ticker
        pred["as_of"] = self.data.index[-1].isoformat()
        # Friendly versions
        pred["p_up_pct"] = round(pred["p_up"] * 100, 1)
        pred["signed_return_pct"] = round(pred["signed_return"] * 100, 2)
        pred["confidence_pct"] = round(pred["confidence"] * 100, 1)
        return pred

    # ------------------------------------------------------------------
    # Evaluation — the metrics that actually matter
    # ------------------------------------------------------------------

    def evaluate(self, test_days: int = 30) -> Dict[str, Any]:
        """Walk-forward backtest with quant-style metrics.

        Train fresh sub-models on everything before the last test_days,
        predict on the held-out window, compute IC / Sharpe / hit rate /
        calibration / directional accuracy.
        """
        if self.data is None:
            self.prepare_features()

        df = self.data.dropna(subset=["target_direction", "target_return"]).copy()
        if len(df) < test_days + 100:
            raise ValueError(
                f"Not enough data for evaluation. Have {len(df)}, need {test_days + 100}"
            )

        train_df = df.iloc[:-test_days]
        test_df = df.iloc[-test_days:]

        # Fit fresh sub-models on train_df only
        eval_dir = DirectionClassifier(self.ticker, **self._kwargs)
        eval_dir.data = train_df
        eval_dir.feature_columns = self._get_feature_cols()
        eval_dir.train(df=train_df, test_ratio=0.1)

        eval_mag_up = MagnitudeRegressor(self.ticker, direction="up", **self._kwargs)
        eval_mag_up.data = train_df
        eval_mag_up.feature_columns = self._get_feature_cols()
        eval_mag_up.train(df=train_df, test_ratio=0.1)

        eval_mag_down = MagnitudeRegressor(
            self.ticker, direction="down", **self._kwargs
        )
        eval_mag_down.data = train_df
        eval_mag_down.feature_columns = self._get_feature_cols()
        eval_mag_down.train(df=train_df, test_ratio=0.1)

        # Predict on holdout
        p_up = eval_dir.predict_proba(test_df)
        m_up = eval_mag_up.predict(test_df)
        m_down = eval_mag_down.predict(test_df)
        predicted = p_up * m_up - (1 - p_up) * m_down

        actual = test_df["target_return"]
        actual_dir = test_df["target_direction"].astype(int)

        return self._scoring_block(predicted, actual, actual_dir, test_days)

    def _combined_holdout_metrics(self, test_ratio: float) -> Dict[str, Any]:
        """Compute combined metrics on the same chronological holdout the
        sub-models used during train(). No re-fitting — uses the trained
        models as-is.
        """
        if self.data is None:
            return {}

        df = self.data.dropna(subset=["target_direction", "target_return"]).copy()
        split_idx = int(len(df) * (1 - test_ratio))
        val_df = df.iloc[split_idx:]

        if len(val_df) < 5:
            return {"error": "validation set too small"}

        preds = self.predict(val_df)
        return self._scoring_block(
            preds["signed_return"],
            val_df["target_return"],
            val_df["target_direction"].astype(int),
            test_days=len(val_df),
        )

    def _scoring_block(
        self,
        predicted: pd.Series,
        actual: pd.Series,
        actual_dir: pd.Series,
        test_days: int,
    ) -> Dict[str, Any]:
        """The actual quant metrics. Pulled out so train() and evaluate() share."""
        # Align indexes defensively
        df = pd.DataFrame({"p": predicted, "a": actual, "d": actual_dir}).dropna()
        if len(df) < 3:
            return {"error": "insufficient aligned samples"}

        p, a, d = df["p"], df["a"], df["d"]
        n = len(df)

        # 1) Information Coefficient — Spearman rank correlation
        # The metric quant funds use: how well do predicted returns RANK
        # the actual returns? Insensitive to magnitude scaling.
        ic = float(p.corr(a, method="spearman"))

        # 2) Pearson IC (linear correlation) — secondary
        pearson_ic = float(p.corr(a, method="pearson"))

        # 3) Directional accuracy + naive baseline lift
        pred_dir = (p > 0).astype(int)
        dir_acc = float((pred_dir == d).mean())
        naive_up_rate = float(d.mean())
        naive_acc = max(naive_up_rate, 1 - naive_up_rate)
        lift = dir_acc - naive_acc

        # 4) Hit rate at confidence threshold — use median |signal| as cutoff
        # so we always have ~half the predictions in the "high-confidence" bucket
        threshold = float(p.abs().median())
        confident_mask = p.abs() >= threshold
        if confident_mask.sum() > 0:
            hit_rate_confident = float(
                ((p[confident_mask] > 0).astype(int) == d[confident_mask]).mean()
            )
        else:
            hit_rate_confident = float("nan")

        # 5) Sharpe ratio of long-short signal
        # daily_pnl = sign(predicted) * actual_return
        signal = np.sign(p)
        daily_pnl = signal * a
        # Avoid divide-by-zero on zero-variance edge cases
        if daily_pnl.std() > 1e-9:
            sharpe_daily = float(daily_pnl.mean() / daily_pnl.std())
            sharpe_annualized = sharpe_daily * np.sqrt(252)
        else:
            sharpe_daily = sharpe_annualized = float("nan")

        # 6) Calibration via deciles (or fewer bins if n < 30)
        n_bins = min(10, max(2, n // 5))
        try:
            bins = pd.qcut(p, q=n_bins, labels=False, duplicates="drop")
            calib = (
                pd.DataFrame({"bin": bins, "actual": a, "pred": p})
                .groupby("bin")
                .agg(
                    mean_pred=("pred", "mean"),
                    mean_actual=("actual", "mean"),
                    n=("actual", "size"),
                )
                .reset_index()
                .to_dict("records")
            )
        except Exception:
            calib = []

        # 7) Magnitude error on signed return
        mae_signed = float((p - a).abs().mean())

        return {
            "n_predictions": int(n),
            "test_days": int(test_days),
            "information_coefficient": ic,
            "pearson_ic": pearson_ic,
            "directional_accuracy": dir_acc,
            "naive_baseline_accuracy": naive_acc,
            "directional_lift": lift,
            "hit_rate_high_confidence": hit_rate_confident,
            "high_confidence_threshold": threshold,
            "high_confidence_count": int(confident_mask.sum()),
            "sharpe_daily": sharpe_daily,
            "sharpe_annualized": sharpe_annualized,
            "mae_signed_return": mae_signed,
            "calibration_deciles": calib,
            "naive_up_rate": float(naive_up_rate),
        }

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def explain(self, top_n: int = 10) -> Dict[str, Any]:
        """Return top-N feature importances from each sub-model side by side.

        The interesting insight: direction and magnitude usually weight DIFFERENT
        features. Direction weights momentum (RSI, MACD); magnitude weights
        volatility (ATR, VIX). This justifies the two-stage architecture.
        """
        self._require_trained()

        def top_n_dict(d, n):
            return dict(list(d.items())[:n])

        return {
            "direction_top_features": top_n_dict(
                self.direction_clf.get_feature_importance(), top_n
            ),
            "mag_up_top_features": top_n_dict(
                self.mag_up.get_feature_importance(), top_n
            ),
            "mag_down_top_features": top_n_dict(
                self.mag_down.get_feature_importance(), top_n
            ),
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_model(self, path: Optional[str] = None):
        self._require_trained()
        if path is None:
            save_dir = os.path.join(os.path.dirname(__file__), "saved")
            os.makedirs(save_dir, exist_ok=True)
            path = os.path.join(save_dir, f"signed_return_{self.ticker}.pkl")
        with open(path, "wb") as f:
            pickle.dump(
                {
                    "direction": {
                        "model": self.direction_clf.model,
                        "feature_columns": self.direction_clf.feature_columns,
                        "params": self.direction_clf.params,
                    },
                    "mag_up": {
                        "model": self.mag_up.model,
                        "feature_columns": self.mag_up.feature_columns,
                        "params": self.mag_up.params,
                    },
                    "mag_down": {
                        "model": self.mag_down.model,
                        "feature_columns": self.mag_down.feature_columns,
                        "params": self.mag_down.params,
                    },
                    "ticker": self.ticker,
                },
                f,
            )
        logger.info(f"SignedReturn model saved to {path}")

    def load_model(self, path: Optional[str] = None):
        if path is None:
            path = os.path.join(
                os.path.dirname(__file__), "saved", f"signed_return_{self.ticker}.pkl"
            )
        if not os.path.exists(path):
            raise FileNotFoundError(f"No saved model at {path}")

        if self.data is None:
            self.prepare_features()

        with open(path, "rb") as f:
            data = pickle.load(f)

        self.direction_clf = DirectionClassifier(self.ticker)
        self.direction_clf.model = data["direction"]["model"]
        self.direction_clf.feature_columns = data["direction"]["feature_columns"]
        self.direction_clf.params = data["direction"]["params"]
        self.direction_clf.data = self.data

        self.mag_up = MagnitudeRegressor(self.ticker, direction="up")
        self.mag_up.model = data["mag_up"]["model"]
        self.mag_up.feature_columns = data["mag_up"]["feature_columns"]
        self.mag_up.params = data["mag_up"]["params"]
        self.mag_up.data = self.data

        self.mag_down = MagnitudeRegressor(self.ticker, direction="down")
        self.mag_down.model = data["mag_down"]["model"]
        self.mag_down.feature_columns = data["mag_down"]["feature_columns"]
        self.mag_down.params = data["mag_down"]["params"]
        self.mag_down.data = self.data

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_trained(self):
        if self.direction_clf is None or self.mag_up is None or self.mag_down is None:
            raise ValueError("Forecaster not trained. Call train() first.")
