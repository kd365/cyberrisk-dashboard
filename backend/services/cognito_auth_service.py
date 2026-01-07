# =============================================================================
# Cognito Authentication Service
# =============================================================================
#
# This service handles AWS Cognito JWT token verification for protected
# endpoints. Provides decorators for requiring authentication on write
# operations while allowing public read access.
#
# Cost: FREE (Cognito first 50K MAU free)
#
# =============================================================================

import os
import json
import time
import logging
import urllib.request
from functools import wraps
from typing import Dict, Optional

from flask import request, jsonify, g

logger = logging.getLogger(__name__)


class CognitoAuthService:
    """
    AWS Cognito authentication service.

    Verifies JWT tokens from Cognito User Pool to authenticate users
    for protected operations (add/remove companies, etc.).
    """

    def __init__(self):
        """Initialize with Cognito configuration from environment."""
        self.region = os.environ.get('AWS_REGION', 'us-west-2')
        self.user_pool_id = os.environ.get('COGNITO_USER_POOL_ID', '')
        self.client_id = os.environ.get('COGNITO_CLIENT_ID', '')

        # JWKS URL for token verification
        if self.user_pool_id:
            self.jwks_url = (
                f'https://cognito-idp.{self.region}.amazonaws.com/'
                f'{self.user_pool_id}/.well-known/jwks.json'
            )
            self.issuer = (
                f'https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool_id}'
            )
        else:
            self.jwks_url = None
            self.issuer = None

        # Cache for JWKS keys
        self._jwks = None
        self._jwks_last_fetched = 0
        self._jwks_cache_duration = 3600  # 1 hour

        # Check if jose library is available
        self._jose_available = False
        try:
            from jose import jwt, jwk
            self._jose_available = True
        except ImportError:
            logger.warning(
                "python-jose not installed. JWT verification disabled. "
                "Install with: pip install python-jose[cryptography]"
            )

    def _get_jwks(self) -> Optional[Dict]:
        """
        Fetch and cache JWKS keys from Cognito.

        Returns:
            JWKS dictionary or None if unavailable
        """
        if not self.jwks_url:
            return None

        current_time = time.time()

        # Return cached keys if still valid
        if (self._jwks is not None and
                current_time - self._jwks_last_fetched < self._jwks_cache_duration):
            return self._jwks

        try:
            with urllib.request.urlopen(self.jwks_url, timeout=10) as response:
                self._jwks = json.loads(response.read())
                self._jwks_last_fetched = current_time
                logger.debug("JWKS keys refreshed from Cognito")
                return self._jwks
        except Exception as e:
            logger.error(f"Failed to fetch JWKS: {e}")
            return self._jwks  # Return stale cache if available

    def verify_token(self, token: str) -> Optional[Dict]:
        """
        Verify a Cognito JWT token.

        Args:
            token: JWT token from Authorization header

        Returns:
            Decoded claims if valid, None if invalid
        """
        if not self._jose_available:
            logger.warning("JWT verification skipped - jose library not available")
            return None

        if not token:
            return None

        try:
            from jose import jwt, jwk
            from jose.utils import base64url_decode

            # Get the key ID from token header
            headers = jwt.get_unverified_headers(token)
            kid = headers.get('kid')

            if not kid:
                logger.warning("Token missing key ID")
                return None

            # Find the matching key in JWKS
            jwks = self._get_jwks()
            if not jwks:
                logger.error("No JWKS available")
                return None

            key = None
            for k in jwks.get('keys', []):
                if k.get('kid') == kid:
                    key = k
                    break

            if not key:
                logger.warning(f"No matching key found for kid: {kid}")
                return None

            # Verify the token
            claims = jwt.decode(
                token,
                key,
                algorithms=['RS256'],
                audience=self.client_id,
                issuer=self.issuer,
                options={'verify_at_hash': False}
            )

            # Additional expiration check
            if claims.get('exp', 0) < time.time():
                logger.warning("Token expired")
                return None

            return claims

        except Exception as e:
            logger.warning(f"Token verification failed: {e}")
            return None

    def get_user_email(self, token: str) -> Optional[str]:
        """
        Extract email from a verified token.

        Args:
            token: JWT token

        Returns:
            User email or None
        """
        claims = self.verify_token(token)
        if claims:
            return claims.get('email')
        return None

    def get_token_from_request(self) -> Optional[str]:
        """
        Extract Bearer token from current Flask request.

        Returns:
            Token string or None
        """
        auth_header = request.headers.get('Authorization', '')

        if auth_header.startswith('Bearer '):
            return auth_header.split(' ', 1)[1]

        return None

    def is_authenticated(self) -> bool:
        """
        Check if current request is authenticated.

        Returns:
            True if valid token present
        """
        token = self.get_token_from_request()
        if not token:
            return False

        claims = self.verify_token(token)
        return claims is not None


# =============================================================================
# Flask Decorators
# =============================================================================

# Global service instance
cognito_auth = CognitoAuthService()


def require_cognito_auth(f):
    """
    Decorator for endpoints requiring Cognito authentication.

    Usage:
        @app.route('/api/companies/db', methods=['POST'])
        @require_cognito_auth
        def add_company():
            user_email = request.cognito_user.get('email')
            ...
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # Get token from Authorization header
        token = cognito_auth.get_token_from_request()

        if not token:
            return jsonify({
                'error': 'Authentication required',
                'message': 'Please sign in to perform this action.',
                'code': 'AUTH_REQUIRED'
            }), 401

        # Verify token
        claims = cognito_auth.verify_token(token)

        if not claims:
            return jsonify({
                'error': 'Invalid or expired token',
                'message': 'Please sign in again.',
                'code': 'INVALID_TOKEN'
            }), 401

        # Add user info to request context
        request.cognito_user = claims
        g.user_email = claims.get('email')

        return f(*args, **kwargs)

    return decorated


def optional_cognito_auth(f):
    """
    Decorator that checks authentication but doesn't require it.

    Populates request.cognito_user if authenticated, otherwise None.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        token = cognito_auth.get_token_from_request()

        if token:
            claims = cognito_auth.verify_token(token)
            request.cognito_user = claims
            g.user_email = claims.get('email') if claims else None
        else:
            request.cognito_user = None
            g.user_email = None

        return f(*args, **kwargs)

    return decorated


# =============================================================================
# Auth Status Endpoint Helper
# =============================================================================

def get_auth_status() -> Dict:
    """
    Get current authentication status.

    Returns:
        Dict with authenticated status and user info
    """
    token = cognito_auth.get_token_from_request()

    if not token:
        return {'authenticated': False}

    claims = cognito_auth.verify_token(token)

    if claims:
        return {
            'authenticated': True,
            'email': claims.get('email'),
            'expires_at': claims.get('exp'),
            'user_pool_id': cognito_auth.user_pool_id
        }

    return {'authenticated': False}
