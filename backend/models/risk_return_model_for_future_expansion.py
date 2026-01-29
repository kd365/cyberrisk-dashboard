"""
Risk-Return Model

Maps cyber risk indicators to expected returns.
"""

# Cyber risk → expected return
# backend/models/risk_return_model.py
import pandas as pd
import numpy as np
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler


class CyberRiskReturnModel:
    def __init__(self):
        self.model = GradientBoostingRegressor(
            n_estimators=200, learning_rate=0.05, max_depth=4, random_state=42
        )
        self.scaler = StandardScaler()
        self.feature_importance = None

    def engineer_features(self, ticker, lookback_days=90):
        """Create comprehensive feature set"""

        # 1. Stock features
        stock_data = yf.Ticker(ticker).history(period="2y")

        # Technical indicators
        stock_data["returns_1d"] = stock_data["Close"].pct_change(1)
        stock_data["returns_7d"] = stock_data["Close"].pct_change(7)
        stock_data["returns_30d"] = stock_data["Close"].pct_change(30)
        stock_data["volatility_30d"] = stock_data["returns_1d"].rolling(30).std()
        stock_data["volume_change"] = stock_data["Volume"].pct_change(7)

        # RSI (Relative Strength Index)
        delta = stock_data["Close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        stock_data["rsi"] = 100 - (100 / (1 + rs))

        # 2. Cybersecurity risk features
        risk_data = self.get_cyber_risk_features(ticker)

        # 3. Sentiment features
        sentiment_data = self.get_sentiment_features(ticker)

        # 4. News volume features
        news_data = self.get_news_features(ticker)

        # Merge all features
        df = stock_data.join(risk_data).join(sentiment_data).join(news_data)

        # Target: Future 30-day return
        df["target_return_30d"] = df["Close"].pct_change(30).shift(-30)

        return df.dropna()

    def get_cyber_risk_features(self, ticker):
        """Extract cybersecurity risk metrics"""
        # This uses your AWS Comprehend analysis
        from services.comprehend_service import ComprehendService
        from services.data_pipeline import DataPipeline

        pipeline = DataPipeline()
        comprehend = ComprehendService()

        # Get SEC filings from S3
        sec_filings = pipeline.get_sec_filings(ticker)

        features = {
            "cyber_mentions": self.count_cyber_keywords(sec_filings),
            "breach_mentions": self.count_breach_keywords(sec_filings),
            "security_investment": self.extract_security_spending(sec_filings),
        }

        # AWS Comprehend sentiment
        sentiment = comprehend.analyze_sentiment(sec_filings[:5000])
        features["sec_sentiment_negative"] = sentiment["SentimentScore"]["Negative"]
        features["sec_sentiment_positive"] = sentiment["SentimentScore"]["Positive"]

        # Entity extraction
        entities = comprehend.extract_risk_entities(sec_filings[:5000])
        features["risk_entity_count"] = len(
            [
                e
                for e in entities
                if any(
                    word in e["Text"].lower()
                    for word in ["breach", "attack", "vulnerability", "threat"]
                )
            ]
        )

        return pd.DataFrame([features], index=[ticker])

    def get_sentiment_features(self, ticker):
        """Get sentiment from earnings calls"""
        from services.data_pipeline import DataPipeline
        from services.comprehend_service import ComprehendService

        pipeline = DataPipeline()
        comprehend = ComprehendService()

        # Get call transcripts
        transcripts = pipeline.get_call_transcripts(ticker)

        if transcripts:
            sentiment = comprehend.analyze_sentiment(transcripts[:5000])
            return pd.DataFrame(
                [
                    {
                        "call_sentiment_score": (
                            sentiment["SentimentScore"]["Positive"]
                            - sentiment["SentimentScore"]["Negative"]
                        )
                    }
                ],
                index=[ticker],
            )
        else:
            return pd.DataFrame([{"call_sentiment_score": 0}], index=[ticker])

    def get_news_features(self, ticker):
        """News volume and sentiment"""
        from services.news_service import CyberNewsService

        news_service = CyberNewsService(api_key="YOUR_KEY")
        articles = news_service.get_cybersecurity_news(ticker, days=30)

        # Count negative keywords in headlines
        negative_count = sum(
            1
            for article in articles
            if any(
                word in article["title"].lower()
                for word in ["breach", "hack", "attack", "vulnerability"]
            )
        )

        return pd.DataFrame(
            [
                {
                    "news_volume_30d": len(articles),
                    "negative_news_ratio": (
                        negative_count / len(articles) if articles else 0
                    ),
                }
            ],
            index=[ticker],
        )

    def train(self, tickers=["MSFT", "GOOGL", "AAPL", "AMZN", "META"]):
        """Train on multiple companies for generalization"""

        all_data = []
        for ticker in tickers:
            df = self.engineer_features(ticker)
            df["ticker"] = ticker
            all_data.append(df)

        # Combine all companies
        combined = pd.concat(all_data)

        # Features and target
        feature_cols = [
            "returns_7d",
            "returns_30d",
            "volatility_30d",
            "rsi",
            "cyber_mentions",
            "breach_mentions",
            "risk_entity_count",
            "sec_sentiment_negative",
            "call_sentiment_score",
            "news_volume_30d",
            "negative_news_ratio",
        ]

        X = combined[feature_cols]
        y = combined["target_return_30d"]

        # Scale features
        X_scaled = self.scaler.fit_transform(X)

        # Time series cross-validation
        tscv = TimeSeriesSplit(n_splits=5)
        scores = []

        for train_idx, test_idx in tscv.split(X_scaled):
            X_train, X_test = X_scaled[train_idx], X_scaled[test_idx]
            y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

            self.model.fit(X_train, y_train)
            score = self.model.score(X_test, y_test)
            scores.append(score)

        # Final train on all data
        self.model.fit(X_scaled, y)

        # Feature importance
        self.feature_importance = pd.DataFrame(
            {"feature": feature_cols, "importance": self.model.feature_importances_}
        ).sort_values("importance", ascending=False)

        return {
            "cross_val_scores": scores,
            "mean_r2": np.mean(scores),
            "feature_importance": self.feature_importance,
            "training_samples": len(combined),
        }

    def predict_return(self, ticker):
        """Predict 30-day return for a company"""

        # Get current features
        df = self.engineer_features(ticker)
        latest = df.iloc[-1:]

        feature_cols = [
            "returns_7d",
            "returns_30d",
            "volatility_30d",
            "rsi",
            "cyber_mentions",
            "breach_mentions",
            "risk_entity_count",
            "sec_sentiment_negative",
            "call_sentiment_score",
            "news_volume_30d",
            "negative_news_ratio",
        ]

        X = latest[feature_cols]
        X_scaled = self.scaler.transform(X)

        predicted_return = self.model.predict(X_scaled)[0]

        # Risk-adjusted return (Sharpe-like metric)
        current_volatility = latest["volatility_30d"].values[0]
        risk_adjusted_return = predicted_return / (current_volatility + 0.01)

        return {
            "ticker": ticker,
            "predicted_30d_return_pct": predicted_return * 100,
            "current_volatility": current_volatility,
            "risk_adjusted_return": risk_adjusted_return,
            "cyber_risk_score": latest["risk_entity_count"].values[0],
            "recommendation": self.get_recommendation(
                predicted_return, current_volatility
            ),
        }

    def get_recommendation(self, predicted_return, volatility):
        """Investment recommendation"""
        if predicted_return > 0.05 and volatility < 0.02:
            return "STRONG BUY - High return, low risk"
        elif predicted_return > 0.02:
            return "BUY - Positive expected return"
        elif predicted_return > -0.02:
            return "HOLD - Neutral outlook"
        else:
            return "SELL - Negative expected return"
