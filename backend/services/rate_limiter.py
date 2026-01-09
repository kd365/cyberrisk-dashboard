# =============================================================================
# Rate Limiter Service - Protect Expensive Model Operations
# =============================================================================
#
# Limits expensive operations (model runs, Comprehend calls) to prevent
# abuse and cost overruns. Uses Redis or in-memory storage for tracking.
#
# Features:
# - Per-user cooldown periods
# - Global daily limits
# - Cached operations are always allowed
#
# =============================================================================

import os
import time
import logging
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta
from functools import wraps
from flask import request, jsonify

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Rate limiter for expensive model operations.

    Uses in-memory storage (could be upgraded to Redis for multi-instance).
    Admins are exempt from rate limits.
    """

    def __init__(self):
        """Initialize rate limiter with configurable limits."""
        # Configuration from environment or defaults
        self.user_cooldown_seconds = int(
            os.environ.get("MODEL_RUN_COOLDOWN", 3600)
        )  # 1 hour
        self.global_daily_limit = int(
            os.environ.get("MODEL_RUNS_PER_DAY", 100)
        )  # 100 runs/day

        # Admin emails exempt from rate limiting (comma-separated in env)
        admin_emails_str = os.environ.get("ADMIN_EMAILS", "")
        self.admin_emails = set(
            email.strip().lower()
            for email in admin_emails_str.split(",")
            if email.strip()
        )

        # In-memory tracking (replace with Redis for production scaling)
        self._user_last_run: Dict[str, float] = {}  # user_id -> timestamp
        self._daily_runs: Dict[str, int] = {}  # date_str -> count
        self._run_log: list = []  # List of (timestamp, user_id, operation) for auditing

    def _get_user_id(self) -> str:
        """Get user identifier from request context."""
        # Try to get email from Cognito claims (set by @require_cognito_auth)
        if hasattr(request, "cognito_user") and request.cognito_user:
            return request.cognito_user.get("email", "unknown")

        # Fall back to IP address for unauthenticated requests
        return request.remote_addr or "unknown"

    def _get_today_key(self) -> str:
        """Get date key for daily tracking."""
        return datetime.utcnow().strftime("%Y-%m-%d")

    def _is_admin(self, user_id: str) -> bool:
        """Check if user is an admin (exempt from rate limits)."""
        return user_id.lower() in self.admin_emails

    def check_rate_limit(
        self, operation: str = "model_run"
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if operation is allowed under rate limits.

        Args:
            operation: Type of operation (for logging)

        Returns:
            Tuple of (allowed: bool, error_message: str or None)
        """
        user_id = self._get_user_id()
        now = time.time()
        today = self._get_today_key()

        # Admins bypass all rate limits
        if self._is_admin(user_id):
            logger.info(f"Admin {user_id} bypassing rate limit for {operation}")
            return True, None

        # Check global daily limit
        daily_count = self._daily_runs.get(today, 0)
        if daily_count >= self.global_daily_limit:
            logger.warning(
                f"Global daily limit reached: {daily_count}/{self.global_daily_limit}"
            )
            return (
                False,
                f"Daily limit reached ({self.global_daily_limit} runs/day). Please use cached results or try again tomorrow.",
            )

        # Check per-user cooldown
        last_run = self._user_last_run.get(user_id, 0)
        time_since_last = now - last_run

        if time_since_last < self.user_cooldown_seconds:
            remaining = int(self.user_cooldown_seconds - time_since_last)
            remaining_mins = remaining // 60
            remaining_secs = remaining % 60

            if remaining_mins > 0:
                time_str = (
                    f"{remaining_mins} minute{'s' if remaining_mins != 1 else ''}"
                )
            else:
                time_str = (
                    f"{remaining_secs} second{'s' if remaining_secs != 1 else ''}"
                )

            logger.info(f"User {user_id} rate limited, {time_str} remaining")
            return (
                False,
                f"Please wait {time_str} between model runs. Use cached results in the meantime.",
            )

        return True, None

    def record_run(self, operation: str = "model_run"):
        """
        Record that a model run occurred.

        Args:
            operation: Type of operation
        """
        user_id = self._get_user_id()
        now = time.time()
        today = self._get_today_key()

        # Update per-user tracking
        self._user_last_run[user_id] = now

        # Update daily count
        self._daily_runs[today] = self._daily_runs.get(today, 0) + 1

        # Log for auditing
        self._run_log.append(
            {
                "timestamp": now,
                "user_id": user_id,
                "operation": operation,
                "date": today,
            }
        )

        # Clean up old daily counts (keep last 7 days)
        cutoff_date = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
        self._daily_runs = {
            k: v for k, v in self._daily_runs.items() if k >= cutoff_date
        }

        logger.info(
            f"Recorded {operation} for user {user_id}. Daily total: {self._daily_runs[today]}"
        )

    def get_status(self) -> Dict:
        """Get current rate limit status for user."""
        user_id = self._get_user_id()
        now = time.time()
        today = self._get_today_key()

        is_admin = self._is_admin(user_id)
        last_run = self._user_last_run.get(user_id, 0)
        time_since_last = now - last_run
        cooldown_remaining = max(0, self.user_cooldown_seconds - time_since_last)

        return {
            "user_id": user_id,
            "is_admin": is_admin,
            "cooldown_remaining_seconds": 0 if is_admin else int(cooldown_remaining),
            "can_run": is_admin or cooldown_remaining == 0,
            "daily_runs_used": self._daily_runs.get(today, 0),
            "daily_limit": self.global_daily_limit,
            "cooldown_seconds": self.user_cooldown_seconds,
        }

    def get_run_history(self, limit: int = 50) -> list:
        """Get recent run history (for admin auditing)."""
        return self._run_log[-limit:]


# =============================================================================
# Flask Decorator
# =============================================================================

# Global instance
rate_limiter = RateLimiter()


def rate_limit_model_run(operation: str = "model_run"):
    """
    Decorator to enforce rate limits on expensive operations.

    Usage:
        @app.route('/api/forecast', methods=['POST'])
        @require_cognito_auth
        @rate_limit_model_run('forecast')
        def generate_forecast():
            ...
    """

    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            allowed, error_message = rate_limiter.check_rate_limit(operation)

            if not allowed:
                return (
                    jsonify(
                        {
                            "error": "Rate limit exceeded",
                            "message": error_message,
                            "status": rate_limiter.get_status(),
                        }
                    ),
                    429,
                )

            # Execute the function
            result = f(*args, **kwargs)

            # Record the run (only if successful - check response code)
            # Note: This records all runs; you might want to only record successful ones
            rate_limiter.record_run(operation)

            return result

        return decorated

    return decorator


def check_rate_limit_only(operation: str = "model_run"):
    """
    Check rate limit without auto-recording.

    Use this when you want manual control over when to record the run
    (e.g., only record after successful model execution).
    """
    return rate_limiter.check_rate_limit(operation)


def record_model_run(operation: str = "model_run"):
    """Manually record a model run."""
    rate_limiter.record_run(operation)


def get_rate_limit_status() -> Dict:
    """Get current rate limit status for the requesting user."""
    return rate_limiter.get_status()
