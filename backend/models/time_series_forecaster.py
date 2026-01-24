# test_prophet_model.py
"""
Complete working Prophet model for stock forecasting
Includes AWS Comprehend sentiment as external regressor
Run this to verify everything works before integrating
"""

import pandas as pd
import numpy as np
import yfinance as yf
from prophet import Prophet
from datetime import datetime, timedelta
import warnings

warnings.filterwarnings("ignore")

# Optional: AWS Comprehend (comment out if not ready yet)
try:
    import boto3

    AWS_AVAILABLE = True
except ImportError:
    AWS_AVAILABLE = False
    print("⚠️  boto3 not installed. Running without AWS Comprehend integration.")
    print("   Install with: pip install boto3")


class CyberRiskForecaster:
    """
    Stock price forecaster with cybersecurity risk integration
    """

    def __init__(self, ticker):
        self.ticker = ticker
        self.model = Prophet(
            changepoint_prior_scale=0.05,  # Flexibility in trend
            seasonality_prior_scale=10,  # Capture patterns
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=True,
        )
        self.data = None
        self.forecast_result = None

    def fetch_stock_data(self, period="2y"):
        """Fetch historical stock data"""
        print(f"📊 Fetching {period} of data for {self.ticker}...")

        stock = yf.Ticker(self.ticker)
        hist = stock.history(period=period)

        if hist.empty:
            raise ValueError(f"No data found for ticker {self.ticker}")

        # Prophet requires 'ds' (date) and 'y' (value) columns
        df = pd.DataFrame({"ds": hist.index, "y": hist["Close"]})

        df["ds"] = pd.to_datetime(df["ds"]).dt.tz_localize(None)  # Remove timezone

        print(f"✅ Retrieved {len(df)} days of data")
        print(f"   Date range: {df['ds'].min().date()} to {df['ds'].max().date()}")
        print(f"   Price range: ${df['y'].min():.2f} - ${df['y'].max():.2f}")

        self.data = df
        return df

    def add_cybersecurity_sentiment(self, mock=True):
        """
        Add cybersecurity sentiment as external regressor
        Uses AWS Comprehend for real sentiment or mock data for testing
        """
        if not mock and AWS_AVAILABLE:
            print("🤖 Analyzing cybersecurity sentiment with AWS Comprehend...")
            sentiment_scores = self._get_real_sentiment()
        else:
            print("🎭 Using mock sentiment data (for testing)...")
            sentiment_scores = self._get_mock_sentiment()

        # Merge sentiment with stock data
        self.data = self.data.merge(sentiment_scores, on="ds", how="left")
        self.data["cyber_sentiment"] = self.data["cyber_sentiment"].fillna(0)

        # Add to Prophet model
        self.model.add_regressor("cyber_sentiment")

        print(f"✅ Added sentiment regressor")
        print(f"   Mean sentiment: {self.data['cyber_sentiment'].mean():.3f}")
        print(
            f"   Range: {self.data['cyber_sentiment'].min():.3f} to {self.data['cyber_sentiment'].max():.3f}"
        )

        return self.data

    def _get_mock_sentiment(self):
        """Generate mock sentiment data for testing"""
        # Create quarterly sentiment scores (simulating SEC filings)
        # Note: 'QE' = Quarter End (replaces deprecated 'Q')
        dates = pd.date_range(
            start=self.data["ds"].min(), end=self.data["ds"].max(), freq="QE"
        )

        # Simulate sentiment: slightly negative with some variation
        # (cybersecurity mentions in SEC filings tend to be risk-focused)
        sentiment = np.random.normal(-0.15, 0.3, len(dates))
        sentiment = np.clip(sentiment, -1, 1)

        df = pd.DataFrame({"ds": dates, "cyber_sentiment": sentiment})

        # Forward-fill to daily (sentiment stays constant between filings)
        daily_dates = pd.DataFrame({"ds": self.data["ds"]})
        df = daily_dates.merge(df, on="ds", how="left")
        df["cyber_sentiment"] = df["cyber_sentiment"].ffill().fillna(0)

        return df

    def _get_real_sentiment(self):
        """Get real sentiment from AWS Comprehend targeted sentiment analysis"""
        try:
            from backend.services.s3_service import S3ArtifactService
            from backend.services.comprehend_service import ComprehendService

            print("🤖 Fetching real sentiment from AWS Comprehend...")

            # Initialize services
            s3_service = S3ArtifactService()
            comprehend_service = ComprehendService()

            # Get artifacts for this ticker
            artifacts = s3_service.get_artifacts_table()
            ticker_artifacts = [
                a
                for a in artifacts
                if a.get("ticker") == self.ticker
                and a.get("type") in ["10-K", "10-Q", "Earnings Transcript"]
            ]

            if not ticker_artifacts:
                print("  ⚠️  No artifacts found, using mock sentiment")
                return self._get_mock_sentiment()

            # Get sentiment timeline
            sentiment_data = comprehend_service.analyze_ticker_sentiment(
                self.ticker,
                artifacts,
                include_entities=False,  # Skip entities for faster processing
            )

            if not sentiment_data or not sentiment_data.get("timeline"):
                print("  ⚠️  No sentiment data extracted, using mock sentiment")
                return self._get_mock_sentiment()

            # Convert sentiment timeline to daily sentiment scores
            timeline = sentiment_data["timeline"]

            # Create DataFrame with sentiment by date
            sentiment_by_date = []
            for entry in timeline:
                date = entry.get("date")
                sentiment = entry.get("sentiment", {})

                # Calculate sentiment score (-1 to 1 scale)
                # Positive sentiment = positive score, Negative = negative score
                positive = sentiment.get("Positive", 0)
                negative = sentiment.get("Negative", 0)
                neutral = sentiment.get("Neutral", 0)
                mixed = sentiment.get("Mixed", 0)

                # Score: positive - negative (range -1 to 1)
                score = positive - negative

                sentiment_by_date.append(
                    {"ds": pd.to_datetime(date), "cyber_sentiment": score}
                )

            df = pd.DataFrame(sentiment_by_date)

            if df.empty:
                print("  ⚠️  Empty sentiment data, using mock sentiment")
                return self._get_mock_sentiment()

            # Sort by date
            df = df.sort_values("ds")

            # Merge with stock data dates (forward-fill sentiment)
            daily_dates = pd.DataFrame({"ds": self.data["ds"]})
            df = daily_dates.merge(df, on="ds", how="left")
            df["cyber_sentiment"] = df["cyber_sentiment"].ffill().fillna(0)

            print(f"  ✅ Extracted sentiment from {len(timeline)} documents")
            print(f"     Mean sentiment: {df['cyber_sentiment'].mean():.3f}")

            return df

        except Exception as e:
            print(f"  ❌ Error getting real sentiment: {e}")
            import traceback

            traceback.print_exc()
            print("  ⚠️  Falling back to mock sentiment")
            return self._get_mock_sentiment()

    def add_volatility_regressor(self):
        """Add stock volatility as external regressor"""
        print("📈 Calculating volatility regressor...")

        # Calculate 30-day rolling volatility
        returns = self.data["y"].pct_change()
        volatility = returns.rolling(window=30).std() * np.sqrt(252)  # Annualized

        self.data["volatility"] = volatility.fillna(volatility.mean())

        # Add to model
        self.model.add_regressor("volatility")

        print(f"✅ Added volatility regressor")
        print(f"   Mean volatility: {self.data['volatility'].mean():.3f}")

        return self.data

    def train(self):
        """Train the Prophet model"""
        print(f"\n🎯 Training Prophet model on {len(self.data)} data points...")

        # Prepare data (only columns Prophet needs)
        train_cols = ["ds", "y"]
        if "cyber_sentiment" in self.data.columns:
            train_cols.append("cyber_sentiment")
        if "volatility" in self.data.columns:
            train_cols.append("volatility")

        train_data = self.data[train_cols].copy()

        # Train
        self.model.fit(train_data)

        print("✅ Model trained successfully!")

        return self.model

    def forecast(self, days_ahead=30):
        """Generate forecast"""
        print(f"\n🔮 Forecasting {days_ahead} days ahead...")

        # Create future dataframe
        future = self.model.make_future_dataframe(periods=days_ahead)

        # Add regressor values for future dates
        if "cyber_sentiment" in self.data.columns:
            # Use last known sentiment (or could use trend)
            last_sentiment = self.data["cyber_sentiment"].iloc[-1]
            future["cyber_sentiment"] = last_sentiment

        if "volatility" in self.data.columns:
            # Use recent average volatility
            recent_vol = self.data["volatility"].tail(30).mean()
            future["volatility"] = recent_vol

        # Generate forecast
        forecast = self.model.predict(future)

        self.forecast_result = forecast

        # Get key metrics
        current_price = self.data["y"].iloc[-1]
        predicted_price = forecast["yhat"].iloc[-1]
        expected_return = ((predicted_price - current_price) / current_price) * 100

        print(f"✅ Forecast complete!")
        print(f"\n📊 FORECAST SUMMARY:")
        print(f"   Current Price: ${current_price:.2f}")
        print(f"   Predicted Price ({days_ahead} days): ${predicted_price:.2f}")
        print(f"   Expected Return: {expected_return:+.2f}%")
        print(
            f"   Confidence Interval: ${forecast['yhat_lower'].iloc[-1]:.2f} - ${forecast['yhat_upper'].iloc[-1]:.2f}"
        )

        # Get historical data for the chart (last 60 days before forecast)
        historical_days = 60
        historical_data = self.data.tail(historical_days)[["ds", "y"]].copy()
        historical_data = historical_data.rename(columns={"y": "actual"})

        return {
            "current_price": current_price,
            "predicted_price": predicted_price,
            "expected_return_pct": expected_return,
            "confidence_lower": forecast["yhat_lower"].iloc[-1],
            "confidence_upper": forecast["yhat_upper"].iloc[-1],
            "forecast_df": forecast.tail(days_ahead),
            "historical_df": historical_data,
        }

    def evaluate(self, test_days=30):
        """Evaluate model on recent data (backtesting)"""
        print(f"\n📏 Evaluating model (backtesting on last {test_days} days)...")

        # Split data
        train = self.data[:-test_days].copy()
        test = self.data[-test_days:].copy()

        print(f"   Train size: {len(train)} days")
        print(f"   Test size: {len(test)} days")

        # Create new model for evaluation
        eval_model = Prophet(
            changepoint_prior_scale=0.05,
            seasonality_prior_scale=10,
            daily_seasonality=True,
            weekly_seasonality=True,
        )

        # Add regressors if they exist
        train_cols = ["ds", "y"]
        if "cyber_sentiment" in train.columns:
            eval_model.add_regressor("cyber_sentiment")
            train_cols.append("cyber_sentiment")
        if "volatility" in train.columns:
            eval_model.add_regressor("volatility")
            train_cols.append("volatility")

        # Train on training data
        eval_model.fit(train[train_cols])

        # Predict on test period
        future = eval_model.make_future_dataframe(periods=test_days)

        # Add regressor values
        if "cyber_sentiment" in self.data.columns:
            future = future.merge(
                self.data[["ds", "cyber_sentiment"]], on="ds", how="left"
            )
            future["cyber_sentiment"] = future["cyber_sentiment"].ffill()

        if "volatility" in self.data.columns:
            future = future.merge(self.data[["ds", "volatility"]], on="ds", how="left")
            future["volatility"] = future["volatility"].ffill()

        forecast = eval_model.predict(future)

        # Get predictions for test period
        predictions = forecast.tail(test_days)
        actuals = test["y"].values
        predicted = predictions["yhat"].values

        # Calculate metrics
        mape = np.mean(np.abs((actuals - predicted) / actuals)) * 100
        rmse = np.sqrt(np.mean((actuals - predicted) ** 2))
        mae = np.mean(np.abs(actuals - predicted))

        # Directional accuracy (did we predict up/down correctly?)
        actual_direction = np.diff(actuals) > 0
        predicted_direction = np.diff(predicted) > 0
        directional_accuracy = np.mean(actual_direction == predicted_direction) * 100

        print(f"\n✅ EVALUATION RESULTS:")
        print(f"   MAPE (Mean Absolute % Error): {mape:.2f}%")
        print(f"   RMSE (Root Mean Squared Error): ${rmse:.2f}")
        print(f"   MAE (Mean Absolute Error): ${mae:.2f}")
        print(f"   Directional Accuracy: {directional_accuracy:.1f}%")

        # Interpretation
        if mape < 5:
            print(f"   📈 Excellent model accuracy!")
        elif mape < 10:
            print(f"   ✅ Good model accuracy")
        elif mape < 15:
            print(f"   ⚠️  Moderate accuracy - consider more features")
        else:
            print(f"   ❌ Poor accuracy - model needs improvement")

        return {
            "mape": mape,
            "rmse": rmse,
            "mae": mae,
            "directional_accuracy": directional_accuracy,
            "test_days": test_days,
        }

    def print_component_importance(self):
        """Analyze which components drive the forecast"""
        if self.forecast_result is None:
            print("⚠️  No forecast available. Run forecast() first.")
            return

        print("\n🔍 FORECAST COMPONENTS:")

        # Get latest forecast row
        latest = self.forecast_result.iloc[-1]

        components = {
            "Trend": latest.get("trend", 0),
            "Weekly Pattern": latest.get("weekly", 0),
            "Yearly Pattern": latest.get("yearly", 0),
        }

        # Add regressors if present
        if "cyber_sentiment" in self.forecast_result.columns:
            components["Cyber Sentiment"] = latest.get("cyber_sentiment", 0)
        if "volatility" in self.forecast_result.columns:
            components["Volatility"] = latest.get("volatility", 0)

        # Print each component
        for name, value in components.items():
            print(f"   {name}: ${value:.2f}")


def main():
    """
    Main execution - run this to test Prophet model
    """
    print("=" * 70)
    print("🚀 CYBERSECURITY RISK FORECASTER - PROPHET MODEL TEST")
    print("=" * 70)

    # Configuration
    TICKER = "MSFT"  # Microsoft - good for cybersecurity context
    FORECAST_DAYS = 30

    try:
        # 1. Create forecaster
        print(f"\n1️⃣  INITIALIZING FORECASTER FOR {TICKER}")
        forecaster = CyberRiskForecaster(TICKER)

        # 2. Fetch data
        print(f"\n2️⃣  FETCHING STOCK DATA")
        forecaster.fetch_stock_data(period="2y")

        # 3. Add cybersecurity sentiment
        print(f"\n3️⃣  ADDING CYBERSECURITY FEATURES")
        forecaster.add_cybersecurity_sentiment(mock=True)
        forecaster.add_volatility_regressor()

        # 4. Train model
        print(f"\n4️⃣  TRAINING MODEL")
        forecaster.train()

        # 5. Generate forecast
        print(f"\n5️⃣  GENERATING FORECAST")
        results = forecaster.forecast(days_ahead=FORECAST_DAYS)

        # 6. Evaluate model
        print(f"\n6️⃣  EVALUATING MODEL PERFORMANCE")
        evaluation = forecaster.evaluate(test_days=30)

        # 7. Component analysis
        print(f"\n7️⃣  ANALYZING FORECAST COMPONENTS")
        forecaster.print_component_importance()

        # Final summary
        print("\n" + "=" * 70)
        print("✅ PROPHET MODEL TEST COMPLETE!")
        print("=" * 70)
        print(f"\nNEXT STEPS:")
        print(f"1. ✅ Prophet working correctly")
        print(f"2. 📝 Save this as: backend/models/time_series_forecaster.py")
        print(f"3. 🔗 Integrate with Flask API (add /api/forecast endpoint)")
        print(f"4. 🎨 Create React component to visualize forecast")
        print(f"5. ☁️  Add real AWS Comprehend integration")
        print(f"\nModel Performance:")
        print(f"  - MAPE: {evaluation['mape']:.2f}% (lower is better)")
        print(f"  - Direction Accuracy: {evaluation['directional_accuracy']:.1f}%")
        print(
            f"  - Expected {FORECAST_DAYS}-day return: {results['expected_return_pct']:+.2f}%"
        )

        # Save forecast to CSV for inspection
        output_file = f"{TICKER}_forecast.csv"
        results["forecast_df"].to_csv(output_file)
        print(f"\n💾 Forecast saved to: {output_file}")

        return True

    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    # Run the test
    success = main()

    if success:
        print("\n🎉 SUCCESS! Prophet model is working correctly.")
        print("You can now integrate this into your Flask backend.")
    else:
        print("\n⚠️  Test failed. Check the error messages above.")
