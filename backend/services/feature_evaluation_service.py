"""
LLM Feature Evaluation Service

Implements evaluation methodology from:
"From Limited Data to Rare-event Prediction: LLM-powered Feature Engineering"

Key evaluation methods:
1. Ablation study - compare model performance with/without LLM features
2. Feature importance analysis
3. Rare event prediction metrics
4. Cross-validation with time-series aware splits
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class FeatureEvaluationService:
    """
    Evaluates the efficacy of LLM-extracted features for prediction tasks.
    """

    def __init__(self):
        self._neo4j = None
        self._db = None

    @property
    def neo4j(self):
        if self._neo4j is None:
            from services.neo4j_service import get_neo4j_service

            self._neo4j = get_neo4j_service()
        return self._neo4j

    @property
    def db(self):
        if self._db is None:
            from services.database_service import db_service

            self._db = db_service
        return self._db

    # =========================================================================
    # Feature Collection
    # =========================================================================

    def get_baseline_features(self, ticker: str) -> Dict[str, Any]:
        """
        Collect traditional numerical features (baseline).

        Features:
        - Current price, price change
        - Volume metrics
        - Basic financials from cache
        """
        try:
            from services.forecast_cache import get_stock_data

            stock = get_stock_data(ticker)

            if not stock:
                return {"error": f"No stock data for {ticker}"}

            return {
                "current_price": stock.get("current_price"),
                "price_change_pct": stock.get("change_pct"),
                "volume": stock.get("volume"),
                "market_cap": stock.get("market_cap"),
                "pe_ratio": stock.get("pe_ratio"),
                "52w_high": stock.get("fifty_two_week_high"),
                "52w_low": stock.get("fifty_two_week_low"),
            }
        except Exception as e:
            logger.warning(f"Error getting baseline features for {ticker}: {e}")
            return {}

    def get_llm_features(self, ticker: str) -> Dict[str, Any]:
        """
        Collect LLM-extracted features from Neo4j.

        Features extracted by CompanyFeatureExtractor:
        - cyber_sector_relevance (0-4)
        - market_positioning (categorical)
        - threat_specialization (list)
        - competitive_moat (categorical)
        - analyst_sentiment (categorical)
        - management_tone (categorical)
        - guidance_direction (categorical)
        """
        query = """
            MATCH (o:Organization {ticker: $ticker})
            RETURN
                o.cyber_sector_relevance as cyber_sector_relevance,
                o.market_positioning as market_positioning,
                o.threat_specialization as threat_specialization,
                o.competitive_moat as competitive_moat,
                o.analyst_sentiment as analyst_sentiment,
                o.analyst_concerns as analyst_concerns,
                o.management_tone as management_tone,
                o.guidance_direction as guidance_direction
        """
        try:
            result = self.neo4j.execute_read(query, {"ticker": ticker})
            if result:
                features = dict(result[0])
                # Count threat specializations
                specs = features.get("threat_specialization") or []
                features["threat_spec_count"] = len(specs) if specs else 0
                # Count analyst concerns
                concerns = features.get("analyst_concerns") or []
                features["concern_count"] = len(concerns) if concerns else 0
                return features
            return {}
        except Exception as e:
            logger.warning(f"Error getting LLM features for {ticker}: {e}")
            return {}

    def get_event_features(self, ticker: str, days_back: int = 90) -> Dict[str, Any]:
        """
        Collect event-based features from Neo4j.

        Features:
        - Vulnerability count and severity
        - Executive event count (appointments/departures)
        - Patent activity
        """
        features = {}

        # Vulnerability features
        vuln_query = """
            MATCH (o:Organization {ticker: $ticker})-[:HAS_VULNERABILITY]->(v:Vulnerability)
            RETURN
                count(v) as vulnerability_count,
                avg(CASE v.severity
                    WHEN 'CRITICAL' THEN 4.0
                    WHEN 'HIGH' THEN 3.0
                    WHEN 'MEDIUM' THEN 2.0
                    WHEN 'LOW' THEN 1.0
                    ELSE 0.0 END) as avg_severity,
                sum(CASE v.severity WHEN 'CRITICAL' THEN 1 ELSE 0 END) as critical_count,
                sum(CASE v.severity WHEN 'HIGH' THEN 1 ELSE 0 END) as high_count
        """
        try:
            result = self.neo4j.execute_read(vuln_query, {"ticker": ticker})
            if result:
                features.update(
                    {
                        "vulnerability_count": result[0]["vulnerability_count"] or 0,
                        "avg_vuln_severity": result[0]["avg_severity"] or 0,
                        "critical_vuln_count": result[0]["critical_count"] or 0,
                        "high_vuln_count": result[0]["high_count"] or 0,
                    }
                )
        except Exception as e:
            logger.warning(f"Error getting vulnerability features: {e}")

        # Executive event features
        exec_query = """
            MATCH (o:Organization {ticker: $ticker})-[:HAS_EXECUTIVE_EVENT]->(e:ExecutiveEvent)
            RETURN
                count(e) as total_exec_events,
                sum(CASE e.event_type WHEN 'departure' THEN 1
                                      WHEN 'resignation' THEN 1 ELSE 0 END) as departures,
                sum(CASE e.event_type WHEN 'appointment' THEN 1 ELSE 0 END) as appointments
        """
        try:
            result = self.neo4j.execute_read(exec_query, {"ticker": ticker})
            if result:
                features.update(
                    {
                        "exec_event_count": result[0]["total_exec_events"] or 0,
                        "exec_departures": result[0]["departures"] or 0,
                        "exec_appointments": result[0]["appointments"] or 0,
                    }
                )
        except Exception as e:
            logger.warning(f"Error getting executive features: {e}")

        # Patent features
        patent_query = """
            MATCH (o:Organization {ticker: $ticker})-[:FILED]->(p:Patent)
            RETURN count(p) as patent_count
        """
        try:
            result = self.neo4j.execute_read(patent_query, {"ticker": ticker})
            if result:
                features["patent_count"] = result[0]["patent_count"] or 0
        except Exception as e:
            logger.warning(f"Error getting patent features: {e}")

        return features

    def get_sentiment_features(self, ticker: str) -> Dict[str, Any]:
        """
        Collect sentiment analysis features from cached data.
        """
        try:
            from services.sentiment_cache import get_cached_sentiment

            sentiment = get_cached_sentiment(ticker)

            if not sentiment:
                return {}

            overall = sentiment.get("overall", {})
            return {
                "sentiment_positive": overall.get("positive", 0),
                "sentiment_negative": overall.get("negative", 0),
                "sentiment_neutral": overall.get("neutral", 0),
                "sentiment_mixed": overall.get("mixed", 0),
                "sentiment_dominant": overall.get("dominant", "NEUTRAL"),
                "sentiment_confidence": overall.get("confidence", 0),
            }
        except Exception as e:
            logger.warning(f"Error getting sentiment features for {ticker}: {e}")
            return {}

    def collect_all_features(self, ticker: str) -> Dict[str, Any]:
        """
        Collect all feature types for a company.
        """
        features = {"ticker": ticker}

        # Baseline (numerical)
        baseline = self.get_baseline_features(ticker)
        features.update({f"baseline_{k}": v for k, v in baseline.items()})

        # LLM-extracted
        llm = self.get_llm_features(ticker)
        features.update({f"llm_{k}": v for k, v in llm.items()})

        # Event-based
        events = self.get_event_features(ticker)
        features.update({f"event_{k}": v for k, v in events.items()})

        # Sentiment
        sentiment = self.get_sentiment_features(ticker)
        features.update({f"sent_{k}": v for k, v in sentiment.items()})

        return features

    # =========================================================================
    # Target Variable Generation
    # =========================================================================

    def generate_target_returns(
        self, ticker: str, days_forward: int = 30, threshold: float = 0.05
    ) -> Optional[int]:
        """
        Generate binary target: 1 if forward return > threshold, 0 otherwise.

        This is a "rare event" prediction task per the paper.
        """
        try:
            import yfinance as yf

            stock = yf.Ticker(ticker)
            hist = stock.history(period="3mo")

            if len(hist) < days_forward + 5:
                return None

            current_price = hist["Close"].iloc[-days_forward - 1]
            future_price = hist["Close"].iloc[-1]

            forward_return = (future_price - current_price) / current_price

            return 1 if forward_return > threshold else 0
        except Exception as e:
            logger.warning(f"Error generating target for {ticker}: {e}")
            return None

    # =========================================================================
    # Evaluation Methods
    # =========================================================================

    def build_feature_matrix(
        self, tickers: List[str] = None
    ) -> Tuple[pd.DataFrame, Dict]:
        """
        Build feature matrix for all companies.

        Returns:
            DataFrame with features and metadata about feature groups
        """
        if tickers is None:
            companies = self.db.get_all_companies()
            tickers = [c["ticker"] for c in companies]

        all_features = []
        for ticker in tickers:
            logger.info(f"Collecting features for {ticker}...")
            features = self.collect_all_features(ticker)
            all_features.append(features)

        df = pd.DataFrame(all_features)
        df = df.set_index("ticker")

        # Define feature groups for ablation study
        feature_groups = {
            "baseline": [c for c in df.columns if c.startswith("baseline_")],
            "llm": [c for c in df.columns if c.startswith("llm_")],
            "event": [c for c in df.columns if c.startswith("event_")],
            "sentiment": [c for c in df.columns if c.startswith("sent_")],
        }

        return df, feature_groups

    def encode_categorical_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Encode categorical LLM features for modeling.
        """
        categorical_cols = [
            "llm_market_positioning",
            "llm_competitive_moat",
            "llm_analyst_sentiment",
            "llm_management_tone",
            "llm_guidance_direction",
            "sent_sentiment_dominant",
        ]

        # Filter to columns that exist
        cols_to_encode = [c for c in categorical_cols if c in df.columns]

        if cols_to_encode:
            df = pd.get_dummies(df, columns=cols_to_encode, dummy_na=True)

        return df

    def run_ablation_study(
        self,
        target_threshold: float = 0.05,
        days_forward: int = 30,
        cv_folds: int = 5,
    ) -> Dict[str, Any]:
        """
        Run ablation study comparing feature sets.

        Per the paper, we compare:
        1. Baseline only (traditional numerical features)
        2. Baseline + LLM features
        3. Baseline + Event features
        4. Baseline + Sentiment features
        5. Full model (all features)

        Returns metrics for each configuration.
        """
        from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import (
            accuracy_score,
            classification_report,
            f1_score,
            precision_score,
            recall_score,
            roc_auc_score,
        )
        from sklearn.model_selection import cross_val_score
        from sklearn.preprocessing import StandardScaler

        logger.info("Building feature matrix...")
        df, feature_groups = self.build_feature_matrix()

        # Generate targets
        logger.info("Generating target variables...")
        targets = {}
        for ticker in df.index:
            target = self.generate_target_returns(ticker, days_forward, target_threshold)
            if target is not None:
                targets[ticker] = target

        # Filter to tickers with targets
        df = df.loc[df.index.isin(targets.keys())]
        y = pd.Series(targets)[df.index]

        logger.info(f"Dataset: {len(df)} companies, {y.sum()} positive cases")

        if len(df) < 10:
            return {
                "error": "Insufficient data for evaluation",
                "companies": len(df),
                "positive_cases": int(y.sum()),
            }

        # Encode categorical features
        df_encoded = self.encode_categorical_features(df.copy())

        # Fill NaN with 0 for numerical, drop remaining
        df_encoded = df_encoded.fillna(0)

        # Define feature set configurations
        configs = {
            "baseline_only": feature_groups["baseline"],
            "baseline_llm": feature_groups["baseline"]
            + [c for c in df_encoded.columns if c.startswith("llm_")],
            "baseline_events": feature_groups["baseline"] + feature_groups["event"],
            "baseline_sentiment": feature_groups["baseline"]
            + [c for c in df_encoded.columns if c.startswith("sent_")],
            "full_model": list(df_encoded.columns),
        }

        results = {
            "dataset_info": {
                "total_companies": len(df),
                "positive_cases": int(y.sum()),
                "negative_cases": int(len(y) - y.sum()),
                "positive_rate": float(y.mean()),
                "target_threshold": target_threshold,
                "days_forward": days_forward,
            },
            "feature_groups": {k: len(v) for k, v in feature_groups.items()},
            "ablation_results": {},
        }

        # Run evaluation for each configuration
        for config_name, feature_cols in configs.items():
            logger.info(f"Evaluating {config_name} ({len(feature_cols)} features)...")

            # Filter to available columns
            available_cols = [c for c in feature_cols if c in df_encoded.columns]

            if not available_cols:
                results["ablation_results"][config_name] = {
                    "error": "No features available"
                }
                continue

            X = df_encoded[available_cols]

            # Scale features
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X)

            # Use Gradient Boosting (handles imbalanced data better)
            model = GradientBoostingClassifier(
                n_estimators=50, max_depth=3, random_state=42
            )

            try:
                # Cross-validation
                n_cv = min(cv_folds, len(df) // 2)
                cv_auc = cross_val_score(model, X_scaled, y, cv=n_cv, scoring="roc_auc")
                cv_f1 = cross_val_score(model, X_scaled, y, cv=n_cv, scoring="f1")
                cv_precision = cross_val_score(
                    model, X_scaled, y, cv=n_cv, scoring="precision"
                )
                cv_recall = cross_val_score(
                    model, X_scaled, y, cv=n_cv, scoring="recall"
                )

                results["ablation_results"][config_name] = {
                    "n_features": len(available_cols),
                    "auc_mean": float(np.mean(cv_auc)),
                    "auc_std": float(np.std(cv_auc)),
                    "f1_mean": float(np.mean(cv_f1)),
                    "f1_std": float(np.std(cv_f1)),
                    "precision_mean": float(np.mean(cv_precision)),
                    "recall_mean": float(np.mean(cv_recall)),
                }
            except Exception as e:
                results["ablation_results"][config_name] = {"error": str(e)}

        # Calculate lift from LLM features
        if (
            "baseline_only" in results["ablation_results"]
            and "full_model" in results["ablation_results"]
        ):
            baseline_auc = results["ablation_results"]["baseline_only"].get(
                "auc_mean", 0
            )
            full_auc = results["ablation_results"]["full_model"].get("auc_mean", 0)

            if baseline_auc > 0:
                results["llm_feature_lift"] = {
                    "auc_lift_pct": float(
                        (full_auc - baseline_auc) / baseline_auc * 100
                    ),
                    "auc_lift_absolute": float(full_auc - baseline_auc),
                }

        return results

    def get_feature_importance(
        self,
        target_threshold: float = 0.05,
        days_forward: int = 30,
    ) -> Dict[str, Any]:
        """
        Get feature importance rankings using a trained model.
        """
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.preprocessing import StandardScaler

        df, feature_groups = self.build_feature_matrix()

        # Generate targets
        targets = {}
        for ticker in df.index:
            target = self.generate_target_returns(
                ticker, days_forward, target_threshold
            )
            if target is not None:
                targets[ticker] = target

        df = df.loc[df.index.isin(targets.keys())]
        y = pd.Series(targets)[df.index]

        if len(df) < 10:
            return {"error": "Insufficient data"}

        df_encoded = self.encode_categorical_features(df.copy())
        df_encoded = df_encoded.fillna(0)

        X = df_encoded
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        model = GradientBoostingClassifier(
            n_estimators=100, max_depth=4, random_state=42
        )
        model.fit(X_scaled, y)

        # Get feature importances
        importances = pd.Series(model.feature_importances_, index=df_encoded.columns)
        importances = importances.sort_values(ascending=False)

        # Group by feature type
        importance_by_group = {}
        for group, cols in feature_groups.items():
            group_cols = [
                c
                for c in importances.index
                if any(c.startswith(col.replace("_", "")) for col in cols)
            ]
            if group_cols:
                importance_by_group[group] = float(importances[group_cols].sum())

        return {
            "top_features": importances.head(20).to_dict(),
            "importance_by_group": importance_by_group,
            "total_features": len(importances),
        }

    def get_feature_coverage(self) -> Dict[str, Any]:
        """
        Check what percentage of companies have each LLM feature populated.
        """
        companies = self.db.get_all_companies()
        tickers = [c["ticker"] for c in companies]

        coverage = {
            "cyber_sector_relevance": 0,
            "market_positioning": 0,
            "competitive_moat": 0,
            "analyst_sentiment": 0,
            "management_tone": 0,
            "guidance_direction": 0,
            "vulnerabilities": 0,
            "executive_events": 0,
        }

        for ticker in tickers:
            llm = self.get_llm_features(ticker)
            events = self.get_event_features(ticker)

            if llm.get("cyber_sector_relevance") is not None:
                coverage["cyber_sector_relevance"] += 1
            if llm.get("market_positioning"):
                coverage["market_positioning"] += 1
            if llm.get("competitive_moat"):
                coverage["competitive_moat"] += 1
            if llm.get("analyst_sentiment"):
                coverage["analyst_sentiment"] += 1
            if llm.get("management_tone"):
                coverage["management_tone"] += 1
            if llm.get("guidance_direction"):
                coverage["guidance_direction"] += 1
            if events.get("vulnerability_count", 0) > 0:
                coverage["vulnerabilities"] += 1
            if events.get("exec_event_count", 0) > 0:
                coverage["executive_events"] += 1

        total = len(tickers)
        return {
            "total_companies": total,
            "coverage": {
                k: {"count": v, "pct": v / total * 100 if total > 0 else 0}
                for k, v in coverage.items()
            },
        }


# Singleton
_evaluation_service = None


def get_evaluation_service() -> FeatureEvaluationService:
    global _evaluation_service
    if _evaluation_service is None:
        _evaluation_service = FeatureEvaluationService()
    return _evaluation_service
