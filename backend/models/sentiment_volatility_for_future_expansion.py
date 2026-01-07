"""
Sentiment-Volatility Model

Maps sentiment analysis to price volatility predictions.
"""

# Sentiment → price volatility
# backend/models/sentiment_volatility.py
import pandas as pd
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.metrics import r2_score, mean_squared_error

class SentimentVolatilityModel:
    """
    Predicts stock volatility based on sentiment analysis
    Hypothesis: Negative cyber news → increased volatility
    """
    
    def __init__(self):
        self.model = Ridge(alpha=1.0)
        
    def create_sentiment_features(self, ticker):
        """Extract sentiment over time"""
        from services.comprehend_service import ComprehendService
        from services.data_pipeline import DataPipeline
        
        pipeline = DataPipeline()
        comprehend = ComprehendService()
        
        # Get historical SEC filings (quarterly)
        filings_by_date = pipeline.get_historical_sec_filings(ticker)
        
        sentiment_timeline = []
        for date, filing_text in filings_by_date.items():
            sentiment = comprehend.analyze_sentiment(filing_text[:5000])
            
            sentiment_timeline.append({
                'date': pd.to_datetime(date),
                'sentiment_negative': sentiment['SentimentScore']['Negative'],
                'sentiment_positive': sentiment['SentimentScore']['Positive'],
                'sentiment_net': (
                    sentiment['SentimentScore']['Positive'] - 
                    sentiment['SentimentScore']['Negative']
                )
            })
        
        return pd.DataFrame(sentiment_timeline).set_index('date')
    
    def train(self, ticker):
        """Train sentiment → volatility model"""
        
        # Get sentiment features
        sentiment_df = self.create_sentiment_features(ticker)
        
        # Get stock volatility
        stock = yf.Ticker(ticker)
        prices = stock.history(period='2y')
        
        # Calculate realized volatility
        prices['returns'] = prices['Close'].pct_change()
        prices['volatility_30d'] = prices['returns'].rolling(30).std()
        
        # Merge sentiment with volatility
        # Forward-fill sentiment (quarterly) to daily
        sentiment_daily = sentiment_df.resample('D').ffill()
        
        df = prices.join(sentiment_daily, how='inner')
        df = df.dropna()
        
        # Features: sentiment lags (sentiment predicts future volatility)
        X = df[['sentiment_negative', 'sentiment_positive', 'sentiment_net']]
        y = df['volatility_30d'].shift(-30)  # Predict 30 days ahead
        
        df['target_volatility'] = y
        df = df.dropna()
        
        # Train model
        self.model.fit(
            df[['sentiment_negative', 'sentiment_positive', 'sentiment_net']], 
            df['target_volatility']
        )
        
        # Evaluate
        predictions = self.model.predict(X)
        r2 = r2_score(df['target_volatility'], predictions)
        rmse = np.sqrt(mean_squared_error(df['target_volatility'], predictions))
        
        return {
            'r2_score': r2,
            'rmse': rmse,
            'interpretation': f"Sentiment explains {r2*100:.1f}% of volatility variation",
            'coefficients': dict(zip(
                ['negative', 'positive', 'net'],
                self.model.coef_
            ))
        }