"""
Shared Feature Engineering Module

Centralizes all feature computation for ML forecasting models.
Computes technical indicators, volume features, volatility metrics,
and calendar features from stock price data.

Designed to be extended with sentiment, news, and LLM features in later phases.
"""


import numpy as np
import pandas as pd
import yfinance as yf
import logging
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional


logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────
# Cross-asset cache configuration (tier 1: memory, tier 2: disk)
# ─────────────────────────────────────────────────────
_cross_asset_memory_cache = {"data": None, "fetched_at": None}
_CROSS_ASSET_CACHE_DIR = Path(__file__).parent / "cache"
_CROSS_ASSET_CACHE_DIR.mkdir(exist_ok=True)
_CROSS_ASSET_CACHE_FILE = _CROSS_ASSET_CACHE_DIR / "cross_asset.parquet"
_CACHE_TTL_HOURS = 24



def fetch_stock_data(ticker: str, period: str = "2y") -> pd.DataFrame:
    """
    Fetch historical OHLCV data from Yahoo Finance.

    Returns DataFrame with columns: Date, Open, High, Low, Close, Volume
    indexed by date (timezone-naive).
    """
    stock = yf.Ticker(ticker)
    hist = stock.history(period=period)

    if hist.empty:
        raise ValueError(f"No data found for ticker {ticker}")

    hist.index = pd.to_datetime(hist.index).tz_localize(None)
    hist = hist[["Open", "High", "Low", "Close", "Volume"]].copy()
    hist.index.name = "Date"

    return hist

def fetch_cross_asset_data(period: str = "2y", force_refresh: bool = False) ->pd.DataFrame:
    """ Fetching cross-asset features from yfinance, specifically a DataFrame
        indexed by date with the following columns:
        - spy_return_1d: Daily return of SPY
        - qqq_return_1d: Daily return of QQQ
        - hack_return_1d: Daily return of HACK
        - vix_close: Closing price of VIX
        - vix_change_1d: Daily change in VIX closing price
    """
    now = datetime.utcnow()
    ttl = timedelta(hours=_CACHE_TTL_HOURS)

    ## In Memory Cache
    if not force_refresh:
        cache = _cross_asset_memory_cache

        if _cross_asset_memory_cache["data"] is not None and (now - _cross_asset_memory_cache["fetched_at"]) < ttl:
            logger.info("Using in-memory cache for cross-asset data")
            return cache["data"].copy()
        
    if not force_refresh and _CROSS_ASSET_CACHE_FILE.exists():
        try:
            fetched_at = datetime.utcfromtimestamp(_CROSS_ASSET_CACHE_FILE.stat().st_mtime)
            if (now - fetched_at) < ttl:
                data = pd.read_parquet(_CROSS_ASSET_CACHE_FILE)
                logger.info("Using disk cache for cross-asset data")
                _cross_asset_memory_cache["data"] = data
                _cross_asset_memory_cache["fetched_at"] = fetched_at
                return data.copy()
        except Exception as e:
            logger.warning(f"Failed to read cross-asset cache from disk: {e}")


    # 1. Fetch OHLCV for each ticker using yf.download()
    try:
        data = yf.download(["SPY", "QQQ", "HACK", "^VIX"], period=period, progress=False, auto_adjust=True)
    except Exception as e:
        logger.error(f"Error fetching cross-asset data: {e}")
        return pd.DataFrame()

    close = data["Close"]


    # 2. Compute daily returns for SPY, QQQ, HACK (pct_change)
    result = pd.DataFrame(index=close.index)
    result["spy_return_1d"] = close["SPY"].pct_change()
    result["qqq_return_1d"] = close["QQQ"].pct_change()
    result["hack_return_1d"] = close["HACK"].pct_change()
    result["vix_close"] = close["^VIX"]
    result["vix_change_1d"] = result["vix_close"].pct_change()

    
    # 3. For VIX, keep the raw level AND compute its daily change
    #    (VIX is a rate, not a price — level matters, not just change)
    result.index = pd.to_datetime(result.index).tz_localize(None)
    result.index.name = "Date"

    # 4. Return a DataFrame indexed by date (timezone-naive)
    # Write to both cache tiers
    _cross_asset_memory_cache["data"] = result
    _cross_asset_memory_cache["fetched_at"] = now
    try:
        result.to_parquet(_CROSS_ASSET_CACHE_FILE)
        logger.debug(f"Cross-asset cache written to {_CROSS_ASSET_CACHE_FILE}")
    except Exception as e:
        logger.warning(f"Failed to write cross-asset disk cache: {e}")
    
    return result.copy()

def compute_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute technical indicators from OHLCV data.

    Expects columns: Open, High, Low, Close, Volume
    """
    out = pd.DataFrame(index=df.index)

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]

    # --- Moving Averages ---
    out["sma_20"] = close.rolling(20).mean()
    out["sma_50"] = close.rolling(50).mean()
    out["sma_200"] = close.rolling(200).mean()
    out["ema_12"] = close.ewm(span=12, adjust=False).mean()
    out["ema_26"] = close.ewm(span=26, adjust=False).mean()

    # Price relative to moving averages (normalized)
    out["price_to_sma20"] = close / out["sma_20"] - 1
    out["price_to_sma50"] = close / out["sma_50"] - 1

    # --- RSI (14-day) ---
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    out["rsi_14"] = 100 - (100 / (1 + rs))

    # --- MACD (12/26/9) ---
    out["macd"] = out["ema_12"] - out["ema_26"]
    out["macd_signal"] = out["macd"].ewm(span=9, adjust=False).mean()
    out["macd_histogram"] = out["macd"] - out["macd_signal"]

    # --- Bollinger Bands (20-day, 2 std) ---
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    out["bb_upper"] = bb_mid + 2 * bb_std
    out["bb_lower"] = bb_mid - 2 * bb_std
    out["bb_width"] = (out["bb_upper"] - out["bb_lower"]) / bb_mid
    out["bb_position"] = (close - out["bb_lower"]) / (out["bb_upper"] - out["bb_lower"])

    # --- ATR (14-day Average True Range) ---
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    out["atr_14"] = true_range.rolling(14).mean()
    out["atr_pct"] = out["atr_14"] / close  # ATR as % of price

    # --- OBV (On-Balance Volume) ---
    obv = (np.sign(close.diff()) * volume).fillna(0).cumsum()
    out["obv"] = obv
    out["obv_sma20"] = obv.rolling(20).mean()

    # --- Volume features ---
    vol_sma20 = volume.rolling(20).mean()
    out["volume_ratio"] = volume / vol_sma20.replace(0, np.nan)
    out["volume_trend"] = vol_sma20.pct_change(periods=5)

    # --- Volatility features ---
    returns = close.pct_change()
    out["returns_1d"] = returns
    out["volatility_20d"] = returns.rolling(20).std() * np.sqrt(252)
    out["volatility_60d"] = returns.rolling(60).std() * np.sqrt(252)

    # Garman-Klass volatility (uses OHLC, more efficient estimator)
    log_hl = (np.log(high / low)) ** 2
    log_co = (np.log(close / df["Open"])) ** 2
    gk = 0.5 * log_hl - (2 * np.log(2) - 1) * log_co
    out["gk_volatility_20d"] = gk.rolling(20).mean() * np.sqrt(252)

    # --- Momentum features ---
    out["momentum_5d"] = close.pct_change(periods=5)
    out["momentum_10d"] = close.pct_change(periods=10)
    out["momentum_20d"] = close.pct_change(periods=20)

    # --- Calendar features ---
    out["day_of_week"] = df.index.dayofweek
    out["month"] = df.index.month
    out["quarter"] = df.index.quarter

    return out


def build_feature_matrix(
    ticker: str,
    period: str = "2y",
    target_days: int = 1,
    include_sentiment: bool = False,
    include_news: bool = False,
    include_llm: bool = False,
    include_cross_asset: bool = True
) -> pd.DataFrame:
    """
    Build a complete feature matrix for a ticker.

    Args:
        ticker: Stock ticker symbol
        period: Historical data period
        target_days: Days ahead for target variable (default 1 = next-day)
        include_sentiment: Pull sentiment features from cache (Phase 3)
        include_news: Pull news features from DB (Phase 2)
        include_llm: Pull LLM features from DB (Phase 3)
        include_cross_asset: Pull cross-asset features (SPY, QQQ, HACK, VIX)
    Returns:
        DataFrame with features and target column ('target').
        Target = next-day close price (for regression) or direction (for classification).
    """
    # Fetch raw data
    df = fetch_stock_data(ticker, period)

    # Compute technical indicators
    features = compute_technical_indicators(df)

    # Add raw price/volume for reference
    features["close"] = df["Close"]
    features["volume_raw"] = df["Volume"]

    # --- Cross-asset features ---
    if include_cross_asset:
        try:
            cross_asset = fetch_cross_asset_data(period)
            if not cross_asset.empty:
                features = features.join(cross_asset, how="left")
                cross_asset_cols = ["spy_return_1d", "qqq_return_1d", "hack_return_1d",
                                    "vix_close", "vix_change_1d"]
                features[cross_asset_cols] = features[cross_asset_cols].ffill()
        except Exception as e:
            logger.warning(f"Could not load cross-asset features for {ticker}: {e}")



    # --- Target variable ---
    features["target_price"] = df["Close"].shift(-target_days)
    features["target_return"] = df["Close"].pct_change(periods=target_days).shift(-target_days)
    features["target_log_return"] = np.log(df["Close"].shift(-target_days) / df["Close"])  # Log return
    features["target_direction"] = (features["target_return"] > 0).astype(int)
    features["target_abs_return"] = np.abs(features["target_return"])
    # Backwards Compatibility
    features["target"] = features["target_price"] 

    # --- Sentiment features (Phase integration) ---
    if include_sentiment:
        try:
            sentiment_features = _get_sentiment_features(ticker, df.index)
            if sentiment_features is not None:
                features = features.join(sentiment_features, how="left")
                features = features.ffill()
        except Exception as e:
            logger.warning(f"Could not load sentiment features for {ticker}: {e}")

    # --- News features (Phase 2 integration) ---
    if include_news:
        try:
            news_features = _get_news_features(ticker, df.index)
            if news_features is not None:
                features = features.join(news_features, how="left")
                features = features.fillna(0)
        except Exception as e:
            logger.warning(f"Could not load news features for {ticker}: {e}")

    # --- LLM features (Phase 3 integration) ---
    if include_llm:
        try:
            llm_features = _get_llm_features(ticker, df.index)
            if llm_features is not None:
                features = features.join(llm_features, how="left")
                features = features.ffill()
        except Exception as e:
            logger.warning(f"Could not load LLM features for {ticker}: {e}")

    # Drop rows with NaN in target (last target_days rows) and initial warmup
    features = features.dropna(subset=["target"])

    return features


def get_feature_columns(
    include_sentiment: bool = False,
    include_news: bool = False,
    include_llm: bool = False,
    include_cross_asset: bool = False
) -> list:
    """
    Get the list of feature column names (excludes target columns and raw price/volume).
    Useful for model training to select only feature columns.
    """
    # Base technical features
    base_features = [
        "sma_20", "sma_50", "sma_200", "ema_12", "ema_26",
        "price_to_sma20", "price_to_sma50",
        "rsi_14",
        "macd", "macd_signal", "macd_histogram",
        "bb_upper", "bb_lower", "bb_width", "bb_position",
        "atr_14", "atr_pct",
        "obv", "obv_sma20",
        "volume_ratio", "volume_trend",
        "returns_1d", "volatility_20d", "volatility_60d", "gk_volatility_20d",
        "momentum_5d", "momentum_10d", "momentum_20d",
        "day_of_week", "month", "quarter",
    ]

    if include_news:
        base_features += [
            "news_sentiment_7d", "news_sentiment_30d",
            "news_volume_7d", "news_sentiment_volatility",
            "negative_news_spike", "breach_news_count_30d",
            "product_news_sentiment_30d",
        ]

    if include_llm:
        base_features += [
            "llm_leadership_cyber_expertise", "llm_product_market_fit",
            "llm_competitive_moat", "llm_innovation_intensity",
            "llm_customer_concentration_risk", "llm_regulatory_alignment",
            "llm_management_sentiment", "llm_growth_trajectory",
            "llm_risk_disclosure_quality", "llm_threat_landscape_awareness",
        ]

    if include_cross_asset:
        base_features += [
            "spy_return_1d", "qqq_return_1d", "hack_return_1d",
            "vix_close", "vix_change_1d",
        ]

    return base_features


# ---------------------------------------------------------------------------
# Phase integration stubs — will be implemented in Phases 2 and 3
# ---------------------------------------------------------------------------

def _get_sentiment_features(ticker: str, date_index: pd.DatetimeIndex) -> Optional[pd.DataFrame]:
    """Pull Comprehend sentiment scores from sentiment_cache and align to dates."""
    try:
        from services.sentiment_cache import get_cached_sentiment

        sentiment = get_cached_sentiment(ticker)
        if not sentiment:
            return None

        overall = sentiment.get("overall", {})
        score = overall.get("positive", 0) - overall.get("negative", 0)

        # Static score applied across all dates (updated when sentiment refreshes)
        df = pd.DataFrame(
            {"sentiment_score": score},
            index=date_index,
        )
        return df
    except ImportError:
        return None


def _get_news_features(ticker: str, date_index: pd.DatetimeIndex) -> Optional[pd.DataFrame]:
    """Pull news features from news_events table. Implemented in Phase 2."""
    return None


def _get_llm_features(ticker: str, date_index: pd.DatetimeIndex) -> Optional[pd.DataFrame]:
    """Pull LLM-extracted features from company_features table. Implemented in Phase 3."""
    return None
