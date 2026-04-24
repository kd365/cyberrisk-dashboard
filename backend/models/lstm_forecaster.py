"""
LSTM Stock Price Forecaster

Deep learning sequence model for stock price prediction.
Uses a 2-layer LSTM architecture with dropout for regularization.
Captures temporal dependencies in multivariate time series data.

Designed to train on CPU (small dataset) or GPU via Google Colab.
"""

import numpy as np
import pandas as pd
import logging
import os
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Lazy imports for PyTorch
_torch = None
_nn = None


def _load_torch():
    global _torch, _nn
    if _torch is None:
        import torch
        import torch.nn as nn

        _torch = torch
        _nn = nn
    return _torch, _nn


class LSTMModel:
    """PyTorch LSTM model wrapper (defined at module level to avoid pickling issues)."""

    def __init__(self, input_size, hidden_size=64, num_layers=2, dropout=0.2):
        torch, nn = _load_torch()

        self.hidden_size = hidden_size
        self.num_layers = num_layers

        # Build sequential model
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=dropout if num_layers > 1 else 0,
            batch_first=True,
        )
        self.fc = nn.Linear(hidden_size, 1)

        # Combine into nn.Module-like interface via ModuleDict is complex,
        # so we manage parameters manually
        self.device = torch.device(
            "cuda"
            if torch.cuda.is_available()
            else (
                "mps"
                if hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
                else "cpu"
            )
        )
        self.lstm = self.lstm.to(self.device)
        self.fc = self.fc.to(self.device)

    def forward(self, x):
        """Forward pass through LSTM + linear layer."""
        lstm_out, _ = self.lstm(x)
        # Take the output of the last time step
        last_out = lstm_out[:, -1, :]
        prediction = self.fc(last_out)
        return prediction

    def parameters(self):
        return list(self.lstm.parameters()) + list(self.fc.parameters())

    def train_mode(self):
        self.lstm.train()
        self.fc.train()

    def eval_mode(self):
        self.lstm.eval()
        self.fc.eval()


class LSTMForecaster:
    """
    Stock price forecaster using LSTM (Long Short-Term Memory) neural network.

    Features:
    - 2-layer LSTM with dropout regularization
    - Sequence-based learning (60-day lookback window)
    - MinMax normalization for stable training
    - Early stopping to prevent overfitting
    """

    SEQUENCE_LENGTH = 60

    def __init__(self, ticker: str, **kwargs):
        self.ticker = ticker
        self.model = None
        self.feature_columns = None
        self.data = None
        self.scaler_X = None
        self.scaler_y = None
        self.training_history = []
        self.params = {
            "hidden_size": kwargs.get("hidden_size", 64),
            "num_layers": kwargs.get("num_layers", 2),
            "dropout": kwargs.get("dropout", 0.2),
            "learning_rate": kwargs.get("learning_rate", 0.001),
            "epochs": kwargs.get("epochs", 100),
            "batch_size": kwargs.get("batch_size", 32),
            "patience": kwargs.get("patience", 15),
        }

    def prepare_features(self, period: str = "2y") -> pd.DataFrame:
        """Compute feature matrix using shared feature engineering module."""
        from models.feature_engineering import build_feature_matrix, get_feature_columns

        self.data = build_feature_matrix(self.ticker, period=period)

        # Use a subset of features that work well with LSTM
        # (avoid redundant/highly correlated features)
        lstm_features = [
            "rsi_14",
            "macd",
            "macd_histogram",
            "bb_position",
            "bb_width",
            "atr_pct",
            "volume_ratio",
            "returns_1d",
            "volatility_20d",
            "momentum_5d",
            "momentum_10d",
            "momentum_20d",
            "price_to_sma20",
            "price_to_sma50",
        ]

        self.feature_columns = [c for c in lstm_features if c in self.data.columns]
        return self.data

    def _create_sequences(self, features: np.ndarray, targets: np.ndarray):
        """Create overlapping sequences for LSTM input."""
        X, y = [], []
        for i in range(self.SEQUENCE_LENGTH, len(features)):
            X.append(features[i - self.SEQUENCE_LENGTH : i])
            y.append(targets[i])
        return np.array(X), np.array(y)

    def train(
        self, df: Optional[pd.DataFrame] = None, test_ratio: float = 0.1
    ) -> Dict[str, Any]:
        """
        Train LSTM model with early stopping.

        Returns training metrics including loss history.
        """
        torch, nn = _load_torch()
        from sklearn.preprocessing import MinMaxScaler

        if df is None:
            if self.data is None:
                self.prepare_features()
            df = self.data

        # Prepare data
        features = df[self.feature_columns].copy()
        target = df["target"].copy()

        valid_mask = features.notna().all(axis=1) & target.notna()
        features = features[valid_mask]
        target = target[valid_mask]

        # Scale features and target
        self.scaler_X = MinMaxScaler()
        self.scaler_y = MinMaxScaler()

        X_scaled = self.scaler_X.fit_transform(features.values)
        y_scaled = self.scaler_y.fit_transform(target.values.reshape(-1, 1)).flatten()

        # Create sequences
        X_seq, y_seq = self._create_sequences(X_scaled, y_scaled)

        # Split chronologically
        split_idx = int(len(X_seq) * (1 - test_ratio))
        X_train = torch.FloatTensor(X_seq[:split_idx])
        y_train = torch.FloatTensor(y_seq[:split_idx]).unsqueeze(1)
        X_val = torch.FloatTensor(X_seq[split_idx:])
        y_val = torch.FloatTensor(y_seq[split_idx:]).unsqueeze(1)

        # Initialize model
        input_size = len(self.feature_columns)
        self.model = LSTMModel(
            input_size=input_size,
            hidden_size=self.params["hidden_size"],
            num_layers=self.params["num_layers"],
            dropout=self.params["dropout"],
        )

        device = self.model.device
        X_train, y_train = X_train.to(device), y_train.to(device)
        X_val, y_val = X_val.to(device), y_val.to(device)

        criterion = nn.MSELoss()
        optimizer = torch.optim.Adam(
            self.model.parameters(), lr=self.params["learning_rate"]
        )

        # Training loop with early stopping
        best_val_loss = float("inf")
        patience_counter = 0
        self.training_history = []

        for epoch in range(self.params["epochs"]):
            self.model.train_mode()

            # Mini-batch training
            batch_size = self.params["batch_size"]
            indices = torch.randperm(len(X_train))
            total_train_loss = 0
            n_batches = 0

            for start in range(0, len(X_train), batch_size):
                batch_idx = indices[start : start + batch_size]
                X_batch = X_train[batch_idx]
                y_batch = y_train[batch_idx]

                optimizer.zero_grad()
                output = self.model.forward(X_batch)
                loss = criterion(output, y_batch)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)
                optimizer.step()

                total_train_loss += loss.item()
                n_batches += 1

            avg_train_loss = total_train_loss / max(n_batches, 1)

            # Validation
            self.model.eval_mode()
            with torch.no_grad():
                val_output = self.model.forward(X_val)
                val_loss = criterion(val_output, y_val).item()

            self.training_history.append(
                {
                    "epoch": epoch + 1,
                    "train_loss": avg_train_loss,
                    "val_loss": val_loss,
                }
            )

            # Early stopping
            if val_loss < best_val_loss:
                best_val_loss = val_loss
                patience_counter = 0
                # Save best model state
                best_state = {
                    "lstm": {
                        k: v.clone() for k, v in self.model.lstm.state_dict().items()
                    },
                    "fc": {k: v.clone() for k, v in self.model.fc.state_dict().items()},
                }
            else:
                patience_counter += 1
                if patience_counter >= self.params["patience"]:
                    logger.info(f"LSTM early stopping at epoch {epoch + 1}")
                    break

        # Restore best model
        if best_state:
            self.model.lstm.load_state_dict(best_state["lstm"])
            self.model.fc.load_state_dict(best_state["fc"])

        # Calculate MAPE on validation set
        self.model.eval_mode()
        with torch.no_grad():
            val_pred_scaled = self.model.forward(X_val).cpu().numpy()
        val_pred = self.scaler_y.inverse_transform(val_pred_scaled).flatten()
        val_actual = self.scaler_y.inverse_transform(y_val.cpu().numpy()).flatten()

        val_mape = np.mean(np.abs((val_actual - val_pred) / val_actual)) * 100

        logger.info(
            f"LSTM trained for {self.ticker}: val MAPE={val_mape:.2f}%, epochs={len(self.training_history)}"
        )

        return {
            "val_mape": float(val_mape),
            "best_val_loss": float(best_val_loss),
            "epochs_trained": len(self.training_history),
            "n_features": len(self.feature_columns),
            "sequence_length": self.SEQUENCE_LENGTH,
            "train_size": len(X_train),
            "val_size": len(X_val),
        }

    def forecast(self, days_ahead: int = 30) -> Dict[str, Any]:
        """Generate multi-step forecast using trained LSTM."""
        torch, _ = _load_torch()

        if self.model is None:
            raise ValueError("Model not trained. Call train() first.")
        if self.data is None:
            raise ValueError("No data loaded. Call prepare_features() first.")

        df = self.data.copy()
        current_price = float(df["close"].iloc[-1])
        last_date = df.index[-1]

        # Prepare the last sequence
        features = df[self.feature_columns].dropna()
        X_scaled = self.scaler_X.transform(features.values)
        last_sequence = X_scaled[-self.SEQUENCE_LENGTH :]

        predictions = []
        forecast_dates = []
        device = self.model.device

        self.model.eval_mode()
        current_seq = last_sequence.copy()

        with torch.no_grad():
            for i in range(days_ahead):
                X_input = torch.FloatTensor(current_seq).unsqueeze(0).to(device)
                pred_scaled = self.model.forward(X_input).cpu().numpy()[0, 0]

                pred_price = self.scaler_y.inverse_transform([[pred_scaled]])[0, 0]
                predictions.append(float(pred_price))

                next_date = last_date + pd.Timedelta(days=i + 1)
                while next_date.dayofweek >= 5:
                    next_date += pd.Timedelta(days=1)
                forecast_dates.append(next_date)

                # Shift sequence forward (use last row features as template, update returns)
                new_row = current_seq[-1].copy()
                current_seq = np.vstack([current_seq[1:], new_row])

        predicted_price = predictions[-1]
        expected_return = ((predicted_price - current_price) / current_price) * 100

        # Estimate confidence from prediction variance
        # Run multiple forward passes with dropout (MC Dropout approximation)
        all_preds = []
        self.model.train_mode()  # Enable dropout
        with torch.no_grad():
            current_seq_orig = last_sequence.copy()
            for _ in range(50):
                seq = current_seq_orig.copy()
                run_preds = []
                for j in range(days_ahead):
                    X_input = torch.FloatTensor(seq).unsqueeze(0).to(device)
                    p = self.model.forward(X_input).cpu().numpy()[0, 0]
                    run_preds.append(self.scaler_y.inverse_transform([[p]])[0, 0])
                    new_row = seq[-1].copy()
                    seq = np.vstack([seq[1:], new_row])
                all_preds.append(run_preds)
        self.model.eval_mode()

        all_preds = np.array(all_preds)
        pred_std = np.std(all_preds, axis=0)

        forecast_df = pd.DataFrame(
            {
                "ds": forecast_dates,
                "yhat": predictions,
                "yhat_lower": [p - 1.96 * s for p, s in zip(predictions, pred_std)],
                "yhat_upper": [p + 1.96 * s for p, s in zip(predictions, pred_std)],
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
            "confidence_lower": float(predictions[-1] - 1.96 * pred_std[-1]),
            "confidence_upper": float(predictions[-1] + 1.96 * pred_std[-1]),
            "forecast_df": forecast_df,
            "historical_df": historical_data,
        }

    def evaluate(self, test_days: int = 30) -> Dict[str, Any]:
        """Evaluate LSTM using walk-forward backtesting."""
        torch, nn = _load_torch()
        from sklearn.preprocessing import MinMaxScaler

        if self.data is None:
            self.prepare_features()

        df = self.data.copy()
        valid_mask = df[self.feature_columns].notna().all(axis=1) & df["target"].notna()
        df = df[valid_mask]

        if len(df) < test_days + self.SEQUENCE_LENGTH + 100:
            raise ValueError("Not enough data for evaluation")

        # Split
        train_df = df.iloc[:-test_days]
        test_df = df.iloc[-test_days - self.SEQUENCE_LENGTH :]  # Include lookback

        # Scale on training data only
        scaler_X = MinMaxScaler()
        scaler_y = MinMaxScaler()

        X_train_scaled = scaler_X.fit_transform(train_df[self.feature_columns].values)
        y_train_scaled = scaler_y.fit_transform(
            train_df["target"].values.reshape(-1, 1)
        ).flatten()

        X_seq, y_seq = self._create_sequences(X_train_scaled, y_train_scaled)

        # Quick training for evaluation
        input_size = len(self.feature_columns)
        eval_model = LSTMModel(
            input_size,
            self.params["hidden_size"],
            self.params["num_layers"],
            self.params["dropout"],
        )
        device = eval_model.device

        X_tensor = torch.FloatTensor(X_seq).to(device)
        y_tensor = torch.FloatTensor(y_seq).unsqueeze(1).to(device)

        criterion = nn.MSELoss()
        optimizer = torch.optim.Adam(
            eval_model.parameters(), lr=self.params["learning_rate"]
        )

        eval_model.train_mode()
        for epoch in range(50):
            optimizer.zero_grad()
            output = eval_model.forward(X_tensor)
            loss = criterion(output, y_tensor)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(eval_model.parameters(), max_norm=1.0)
            optimizer.step()

        # Predict on test set
        eval_model.eval_mode()
        X_test_all = scaler_X.transform(test_df[self.feature_columns].values)

        predictions = []
        with torch.no_grad():
            for i in range(self.SEQUENCE_LENGTH, len(X_test_all)):
                seq = X_test_all[i - self.SEQUENCE_LENGTH : i]
                X_input = torch.FloatTensor(seq).unsqueeze(0).to(device)
                pred = eval_model.forward(X_input).cpu().numpy()[0, 0]
                predictions.append(scaler_y.inverse_transform([[pred]])[0, 0])

        actual_prices = test_df["target"].values[self.SEQUENCE_LENGTH :]
        min_len = min(len(predictions), len(actual_prices))
        predictions = np.array(predictions[:min_len])
        actual_prices = actual_prices[:min_len]

        mape = np.mean(np.abs((actual_prices - predictions) / actual_prices)) * 100
        rmse = np.sqrt(np.mean((actual_prices - predictions) ** 2))
        mae = np.mean(np.abs(actual_prices - predictions))

        if len(actual_prices) > 1:
            actual_direction = np.diff(actual_prices) > 0
            predicted_direction = np.diff(predictions) > 0
            directional_accuracy = (
                np.mean(actual_direction == predicted_direction) * 100
            )
        else:
            directional_accuracy = 0.0

        return {
            "mape": float(mape),
            "rmse": float(rmse),
            "mae": float(mae),
            "directional_accuracy": float(directional_accuracy),
            "test_days": test_days,
            "model": "lstm",
        }

    def get_feature_importance(self) -> Dict[str, Any]:
        """LSTM doesn't have built-in feature importance. Return feature list."""
        return {
            "note": "LSTM does not provide built-in feature importance. Use SHAP with the XGBoost model for feature analysis.",
            "features_used": self.feature_columns or [],
        }

    def save_model(self, path: Optional[str] = None):
        """Save LSTM model weights and scalers."""
        torch, _ = _load_torch()

        if self.model is None:
            raise ValueError("No model to save")
        if path is None:
            save_dir = os.path.join(os.path.dirname(__file__), "saved")
            os.makedirs(save_dir, exist_ok=True)
            path = os.path.join(save_dir, f"lstm_{self.ticker}.pt")

        torch.save(
            {
                "lstm_state": self.model.lstm.state_dict(),
                "fc_state": self.model.fc.state_dict(),
                "feature_columns": self.feature_columns,
                "scaler_X": self.scaler_X,
                "scaler_y": self.scaler_y,
                "params": self.params,
                "ticker": self.ticker,
            },
            path,
        )
        logger.info(f"LSTM model saved to {path}")

    def load_model(self, path: Optional[str] = None):
        """Load LSTM model weights and scalers."""
        torch, _ = _load_torch()

        if path is None:
            path = os.path.join(
                os.path.dirname(__file__), "saved", f"lstm_{self.ticker}.pt"
            )
        if not os.path.exists(path):
            raise FileNotFoundError(f"No saved model at {path}")

        data = torch.load(path, map_location="cpu", weights_only=False)
        self.feature_columns = data["feature_columns"]
        self.scaler_X = data["scaler_X"]
        self.scaler_y = data["scaler_y"]
        self.params = data["params"]

        self.model = LSTMModel(
            input_size=len(self.feature_columns),
            hidden_size=self.params["hidden_size"],
            num_layers=self.params["num_layers"],
            dropout=self.params["dropout"],
        )
        self.model.lstm.load_state_dict(data["lstm_state"])
        self.model.fc.load_state_dict(data["fc_state"])
        logger.info(f"LSTM model loaded from {path}")
