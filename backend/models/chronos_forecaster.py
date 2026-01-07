# backend/models/chronos_forecaster.py
"""
Chronos Time Series Forecaster for Stock Price Prediction

Uses Amazon's Chronos T5-based foundation model with best practices:
- Log returns instead of raw prices for better percentage-based learning
- Rolling window context (250-500 days minimum for 90-day forecasts)
- Probabilistic forecasts with P10, P50 (median), P90 quantiles
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# Lazy load Chronos to avoid import errors if not installed
CHRONOS_AVAILABLE = False
ChronosPipeline = None

def _load_chronos():
    """Lazy load Chronos pipeline"""
    global CHRONOS_AVAILABLE, ChronosPipeline
    if ChronosPipeline is not None:
        return CHRONOS_AVAILABLE

    try:
        from chronos import ChronosPipeline as CP
        import torch
        ChronosPipeline = CP
        CHRONOS_AVAILABLE = True
        print("✅ Chronos-Bolt loaded successfully")
    except ImportError as e:
        print(f"⚠️  Chronos not available: {e}")
        print("   Install with: pip install chronos-forecasting torch")
        CHRONOS_AVAILABLE = False

    return CHRONOS_AVAILABLE


class ChronosForecaster:
    """
    Stock price forecaster using Amazon Chronos (T5-based)

    Features:
    - Uses log returns for better model performance
    - Provides probabilistic forecasts (P10, P50, P90)
    - Zero-shot inference (no training required)
    """

    # Model variants - using original T5-based chronos models (more stable)
    # Bolt models have config issues with current chronos-forecasting package
    MODEL_VARIANTS = {
        'tiny': 'amazon/chronos-t5-tiny',        # Fastest, smallest (~8M params)
        'mini': 'amazon/chronos-t5-mini',        # Good balance (~20M params)
        'small': 'amazon/chronos-t5-small',      # Recommended default (~46M params)
        'base': 'amazon/chronos-t5-base',        # Higher accuracy (~200M params)
    }

    def __init__(self, ticker, model_size='small'):
        """
        Initialize Chronos forecaster

        Args:
            ticker: Stock ticker symbol
            model_size: One of 'tiny', 'mini', 'small', 'base'
        """
        self.ticker = ticker
        self.model_size = model_size
        self.model_name = self.MODEL_VARIANTS.get(model_size, self.MODEL_VARIANTS['small'])
        self.pipeline = None
        self.data = None
        self.log_returns = None
        self.last_price = None
        self.forecast_result = None

    def _ensure_model_loaded(self):
        """Ensure Chronos model is loaded"""
        if not _load_chronos():
            raise RuntimeError("Chronos is not available. Install with: pip install chronos-forecasting torch")

        if self.pipeline is None:
            import torch
            print(f"🔄 Loading Chronos model: {self.model_name}...")

            # Determine device
            if torch.cuda.is_available():
                device = "cuda"
                dtype = torch.float16
            elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                device = "mps"
                dtype = torch.float32
            else:
                device = "cpu"
                dtype = torch.float32

            self.pipeline = ChronosPipeline.from_pretrained(
                self.model_name,
                device_map=device,
                dtype=dtype,
            )
            print(f"✅ Chronos model loaded on {device}")

    def fetch_stock_data(self, period='3y'):
        """
        Fetch historical stock data with sufficient context

        For good forecasts, we need 250-500+ days of history.
        Using 3 years by default for robust context.
        """
        print(f"📊 Fetching {period} of data for {self.ticker}...")

        stock = yf.Ticker(self.ticker)
        hist = stock.history(period=period)

        if hist.empty:
            raise ValueError(f"No data found for ticker {self.ticker}")

        # Store raw prices
        df = pd.DataFrame({
            'ds': hist.index,
            'price': hist['Close']
        })
        df['ds'] = pd.to_datetime(df['ds']).dt.tz_localize(None)

        # Calculate log returns (percentage changes in log scale)
        # This helps the model focus on relative moves, not absolute prices
        df['log_return'] = np.log(df['price'] / df['price'].shift(1))
        df = df.dropna()  # Remove first row (NaN from shift)

        print(f"✅ Retrieved {len(df)} days of data")
        print(f"   Date range: {df['ds'].min().date()} to {df['ds'].max().date()}")
        print(f"   Price range: ${df['price'].min():.2f} - ${df['price'].max():.2f}")
        print(f"   Log return stats: mean={df['log_return'].mean():.4f}, std={df['log_return'].std():.4f}")

        self.data = df
        self.last_price = df['price'].iloc[-1]
        self.log_returns = df['log_return'].values

        return df

    def forecast(self, days_ahead=30, num_samples=100):
        """
        Generate probabilistic forecast

        Args:
            days_ahead: Number of days to forecast
            num_samples: Number of sample paths to generate (for probabilistic forecasts)

        Returns:
            Dict with forecast data including P10, P50 (median), P90 quantiles
        """
        self._ensure_model_loaded()

        if self.data is None:
            raise ValueError("No data loaded. Call fetch_stock_data() first.")

        print(f"\n🔮 Forecasting {days_ahead} days ahead with Chronos-Bolt...")

        import torch

        # Use log returns as context (not raw prices)
        # This is key for Chronos to focus on percentage moves
        context = torch.tensor(self.log_returns).unsqueeze(0)  # Add batch dimension

        print(f"   Context length: {len(self.log_returns)} days")
        print(f"   Model: {self.model_name}")

        # Generate forecast samples
        # Each sample is one possible future trajectory
        forecast_samples = self.pipeline.predict(
            context,
            prediction_length=days_ahead,
            num_samples=num_samples,
        )

        # forecast_samples shape: (1, num_samples, days_ahead)
        samples = forecast_samples[0].numpy()  # Remove batch dimension

        # Calculate quantiles for each forecast day
        p10 = np.percentile(samples, 10, axis=0)  # Lower bound (10th percentile)
        p50 = np.percentile(samples, 50, axis=0)  # Median (our main prediction)
        p90 = np.percentile(samples, 90, axis=0)  # Upper bound (90th percentile)

        # Convert log returns back to prices
        # Cumulative sum of log returns, then exponentiate
        cumulative_p10 = np.cumsum(p10)
        cumulative_p50 = np.cumsum(p50)
        cumulative_p90 = np.cumsum(p90)

        predicted_prices_p10 = self.last_price * np.exp(cumulative_p10)
        predicted_prices_p50 = self.last_price * np.exp(cumulative_p50)
        predicted_prices_p90 = self.last_price * np.exp(cumulative_p90)

        # Generate forecast dates
        last_date = self.data['ds'].iloc[-1]
        forecast_dates = pd.date_range(
            start=last_date + timedelta(days=1),
            periods=days_ahead,
            freq='D'
        )
        # Skip weekends for stock market
        forecast_dates = forecast_dates[forecast_dates.dayofweek < 5][:days_ahead]

        # If we need more dates (because we removed weekends), generate more
        while len(forecast_dates) < days_ahead:
            last_forecast_date = forecast_dates[-1] if len(forecast_dates) > 0 else last_date
            additional_dates = pd.date_range(
                start=last_forecast_date + timedelta(days=1),
                periods=days_ahead - len(forecast_dates) + 10,
                freq='D'
            )
            additional_dates = additional_dates[additional_dates.dayofweek < 5]
            forecast_dates = forecast_dates.append(additional_dates)[:days_ahead]

        # Build forecast DataFrame
        forecast_df = pd.DataFrame({
            'ds': forecast_dates[:len(predicted_prices_p50)],
            'yhat': predicted_prices_p50,
            'yhat_lower': predicted_prices_p10,
            'yhat_upper': predicted_prices_p90,
        })

        # Get historical data for chart (last 60 days)
        historical_days = 60
        historical_data = self.data.tail(historical_days)[['ds', 'price']].copy()
        historical_data = historical_data.rename(columns={'price': 'actual'})

        # Calculate metrics
        current_price = self.last_price
        predicted_price = predicted_prices_p50[-1]  # Median prediction
        expected_return = ((predicted_price - current_price) / current_price) * 100

        # Calculate expected volatility from sample spread
        price_samples_final = self.last_price * np.exp(np.cumsum(samples, axis=1)[:, -1])
        expected_volatility = np.std(price_samples_final) / current_price * 100

        print(f"✅ Chronos forecast complete!")
        print(f"\n📊 FORECAST SUMMARY:")
        print(f"   Current Price: ${current_price:.2f}")
        print(f"   Predicted Price (P50, {days_ahead} days): ${predicted_price:.2f}")
        print(f"   Expected Return: {expected_return:+.2f}%")
        print(f"   Confidence Range (P10-P90): ${predicted_prices_p10[-1]:.2f} - ${predicted_prices_p90[-1]:.2f}")
        print(f"   Expected Volatility: {expected_volatility:.1f}%")

        self.forecast_result = {
            'current_price': current_price,
            'predicted_price': predicted_price,
            'expected_return_pct': expected_return,
            'confidence_lower': float(predicted_prices_p10[-1]),
            'confidence_upper': float(predicted_prices_p90[-1]),
            'expected_volatility_pct': expected_volatility,
            'forecast_df': forecast_df,
            'historical_df': historical_data,
            'samples': samples,  # Raw samples for additional analysis
        }

        return self.forecast_result

    def evaluate(self, test_days=30):
        """
        Evaluate model on recent data (backtesting)

        Uses log returns for evaluation to match training approach.
        """
        print(f"\n📏 Evaluating Chronos model (backtesting on last {test_days} days)...")

        if self.data is None:
            raise ValueError("No data loaded. Call fetch_stock_data() first.")

        self._ensure_model_loaded()

        import torch

        # Split data
        train_data = self.data[:-test_days].copy()
        test_data = self.data[-test_days:].copy()

        print(f"   Train size: {len(train_data)} days")
        print(f"   Test size: {len(test_data)} days")

        # Use log returns for context
        train_log_returns = train_data['log_return'].values
        context = torch.tensor(train_log_returns).unsqueeze(0)

        # Generate forecast
        forecast_samples = self.pipeline.predict(
            context,
            prediction_length=test_days,
            num_samples=100,
        )

        samples = forecast_samples[0].numpy()
        p50 = np.percentile(samples, 50, axis=0)  # Median prediction

        # Convert to prices
        last_train_price = train_data['price'].iloc[-1]
        cumulative_returns = np.cumsum(p50)
        predicted_prices = last_train_price * np.exp(cumulative_returns)

        # Get actual prices
        actual_prices = test_data['price'].values

        # Align lengths (might differ due to weekends)
        min_len = min(len(predicted_prices), len(actual_prices))
        predicted_prices = predicted_prices[:min_len]
        actual_prices = actual_prices[:min_len]

        # Calculate metrics
        mape = np.mean(np.abs((actual_prices - predicted_prices) / actual_prices)) * 100
        rmse = np.sqrt(np.mean((actual_prices - predicted_prices) ** 2))
        mae = np.mean(np.abs(actual_prices - predicted_prices))

        # Directional accuracy
        if len(actual_prices) > 1:
            actual_direction = np.diff(actual_prices) > 0
            predicted_direction = np.diff(predicted_prices) > 0
            directional_accuracy = np.mean(actual_direction == predicted_direction) * 100
        else:
            directional_accuracy = 0

        print(f"\n✅ CHRONOS EVALUATION RESULTS:")
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
            print(f"   ⚠️  Moderate accuracy")
        else:
            print(f"   ❌ Higher error - typical for volatile stocks")

        return {
            'mape': float(mape),
            'rmse': float(rmse),
            'mae': float(mae),
            'directional_accuracy': float(directional_accuracy),
            'test_days': test_days,
            'model': 'chronos-bolt',
            'model_variant': self.model_size,
        }


def main():
    """Test Chronos forecaster"""
    print("=" * 70)
    print("🚀 CHRONOS-BOLT FORECASTER TEST")
    print("=" * 70)

    TICKER = 'CRWD'
    FORECAST_DAYS = 30

    try:
        # 1. Create forecaster
        print(f"\n1️⃣  INITIALIZING CHRONOS FORECASTER FOR {TICKER}")
        forecaster = ChronosForecaster(TICKER, model_size='small')

        # 2. Fetch data (3 years for good context)
        print(f"\n2️⃣  FETCHING STOCK DATA")
        forecaster.fetch_stock_data(period='3y')

        # 3. Generate forecast
        print(f"\n3️⃣  GENERATING FORECAST")
        results = forecaster.forecast(days_ahead=FORECAST_DAYS)

        # 4. Evaluate
        print(f"\n4️⃣  EVALUATING MODEL")
        evaluation = forecaster.evaluate(test_days=30)

        print("\n" + "=" * 70)
        print("✅ CHRONOS-BOLT TEST COMPLETE!")
        print("=" * 70)
        print(f"\nModel Performance:")
        print(f"  - MAPE: {evaluation['mape']:.2f}%")
        print(f"  - Direction Accuracy: {evaluation['directional_accuracy']:.1f}%")
        print(f"  - Expected {FORECAST_DAYS}-day return: {results['expected_return_pct']:+.2f}%")

        return True

    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    main()
