import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';

// =============================================================================
// Cognito Auth Context & Provider
// =============================================================================
//
// This component provides authentication state management using AWS Cognito.
// It wraps the application and exposes auth state and methods via React Context.
//
// =============================================================================

const AuthContext = createContext(null);

// Cognito configuration - loaded from environment variables
// Used by backend API calls - kept for reference
// eslint-disable-next-line no-unused-vars
const COGNITO_CONFIG = {
  userPoolId: process.env.REACT_APP_COGNITO_USER_POOL_ID,
  clientId: process.env.REACT_APP_COGNITO_CLIENT_ID,
  region: process.env.REACT_APP_AWS_REGION || 'us-west-2',
};

// Token storage keys
const TOKEN_KEYS = {
  accessToken: 'cognito_access_token',
  idToken: 'cognito_id_token',
  refreshToken: 'cognito_refresh_token',
  expiresAt: 'cognito_expires_at',
};

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  // Check if tokens are expired
  const isTokenExpired = useCallback(() => {
    const expiresAt = localStorage.getItem(TOKEN_KEYS.expiresAt);
    if (!expiresAt) return true;
    return Date.now() > parseInt(expiresAt, 10);
  }, []);

  // Get current access token
  const getAccessToken = useCallback(() => {
    if (isTokenExpired()) return null;
    return localStorage.getItem(TOKEN_KEYS.accessToken);
  }, [isTokenExpired]);

  // Get current ID token
  const getIdToken = useCallback(() => {
    if (isTokenExpired()) return null;
    return localStorage.getItem(TOKEN_KEYS.idToken);
  }, [isTokenExpired]);

  // Parse JWT token to get claims
  const parseJwt = (token) => {
    try {
      const base64Url = token.split('.')[1];
      const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
      const jsonPayload = decodeURIComponent(
        atob(base64)
          .split('')
          .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
          .join('')
      );
      return JSON.parse(jsonPayload);
    } catch (e) {
      return null;
    }
  };

  // Store tokens after successful auth
  const storeTokens = useCallback((tokens) => {
    const { AccessToken, IdToken, RefreshToken, ExpiresIn } = tokens;

    localStorage.setItem(TOKEN_KEYS.accessToken, AccessToken);
    localStorage.setItem(TOKEN_KEYS.idToken, IdToken);
    if (RefreshToken) {
      localStorage.setItem(TOKEN_KEYS.refreshToken, RefreshToken);
    }

    // Calculate expiration time (convert ExpiresIn seconds to milliseconds)
    const expiresAt = Date.now() + (ExpiresIn * 1000);
    localStorage.setItem(TOKEN_KEYS.expiresAt, expiresAt.toString());

    // Parse user info from ID token
    const claims = parseJwt(IdToken);
    if (claims) {
      setUser({
        email: claims.email,
        name: claims.name || claims.email,
        sub: claims.sub,
        groups: claims['cognito:groups'] || [],
      });
    }
  }, []);

  // Clear all stored tokens
  const clearTokens = useCallback(() => {
    Object.values(TOKEN_KEYS).forEach((key) => {
      localStorage.removeItem(key);
    });
    // Also clear legacy keys
    localStorage.removeItem('user_name');
    localStorage.removeItem('user_email');
    setUser(null);
  }, []);

  // Sign in with email and password
  const signIn = async (email, password) => {
    setError(null);
    setIsLoading(true);

    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Authentication failed');
      }

      if (data.challenge === 'NEW_PASSWORD_REQUIRED') {
        // User needs to change password
        return {
          requiresNewPassword: true,
          session: data.session,
          email
        };
      }

      // Backend returns tokens directly (accessToken, idToken, refreshToken, expiresIn)
      storeTokens({
        AccessToken: data.accessToken,
        IdToken: data.idToken,
        RefreshToken: data.refreshToken,
        ExpiresIn: data.expiresIn,
      });
      return { success: true };

    } catch (err) {
      setError(err.message);
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  // Complete new password challenge
  const completeNewPassword = async (email, newPassword, session) => {
    setError(null);
    setIsLoading(true);

    try {
      const response = await fetch('/api/auth/new-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, newPassword, session }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Password change failed');
      }

      // Backend returns tokens directly
      storeTokens({
        AccessToken: data.accessToken,
        IdToken: data.idToken,
        RefreshToken: data.refreshToken,
        ExpiresIn: data.expiresIn,
      });
      return { success: true };

    } catch (err) {
      setError(err.message);
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  // Sign out
  const signOut = useCallback(async () => {
    try {
      const accessToken = getAccessToken();
      if (accessToken) {
        await fetch('/api/auth/logout', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${accessToken}`,
          },
        });
      }
    } catch (err) {
      console.error('Logout error:', err);
    } finally {
      clearTokens();
    }
  }, [clearTokens, getAccessToken]);

  // Refresh tokens using refresh token
  const refreshTokens = useCallback(async () => {
    const refreshToken = localStorage.getItem(TOKEN_KEYS.refreshToken);
    if (!refreshToken) {
      clearTokens();
      return false;
    }

    try {
      const response = await fetch('/api/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refreshToken }),
      });

      if (!response.ok) {
        throw new Error('Token refresh failed');
      }

      const data = await response.json();
      // Backend returns tokens directly (no refreshToken on refresh - reuse existing)
      storeTokens({
        AccessToken: data.accessToken,
        IdToken: data.idToken,
        RefreshToken: refreshToken, // Keep existing refresh token
        ExpiresIn: data.expiresIn,
      });
      return true;

    } catch (err) {
      console.error('Token refresh error:', err);
      clearTokens();
      return false;
    }
  }, [clearTokens, storeTokens]);

  // Check authentication status on mount
  useEffect(() => {
    const checkAuth = async () => {
      const idToken = localStorage.getItem(TOKEN_KEYS.idToken);

      if (!idToken) {
        // Check for legacy auth (simple name/email)
        const legacyName = localStorage.getItem('user_name');
        const legacyEmail = localStorage.getItem('user_email');
        if (legacyName && legacyEmail) {
          setUser({ name: legacyName, email: legacyEmail, legacy: true });
        }
        setIsLoading(false);
        return;
      }

      if (isTokenExpired()) {
        // Try to refresh
        const refreshed = await refreshTokens();
        if (!refreshed) {
          setIsLoading(false);
          return;
        }
      }

      // Parse user from token
      const claims = parseJwt(idToken);
      if (claims) {
        setUser({
          email: claims.email,
          name: claims.name || claims.email,
          sub: claims.sub,
          groups: claims['cognito:groups'] || [],
        });
      }

      setIsLoading(false);
    };

    checkAuth();
  }, [isTokenExpired, refreshTokens]);

  // Set up token refresh interval
  useEffect(() => {
    if (!user) return;

    // Refresh tokens 5 minutes before expiration
    const checkAndRefresh = async () => {
      const expiresAt = localStorage.getItem(TOKEN_KEYS.expiresAt);
      if (!expiresAt) return;

      const timeUntilExpiry = parseInt(expiresAt, 10) - Date.now();
      const fiveMinutes = 5 * 60 * 1000;

      if (timeUntilExpiry < fiveMinutes) {
        await refreshTokens();
      }
    };

    const interval = setInterval(checkAndRefresh, 60000); // Check every minute
    return () => clearInterval(interval);
  }, [user, refreshTokens]);

  // Fetch wrapper with automatic token injection
  const authenticatedFetch = useCallback(async (url, options = {}) => {
    const accessToken = getAccessToken();

    if (!accessToken) {
      // Try to refresh
      const refreshed = await refreshTokens();
      if (!refreshed) {
        throw new Error('Not authenticated');
      }
    }

    const headers = {
      ...options.headers,
      'Authorization': `Bearer ${getAccessToken()}`,
    };

    const response = await fetch(url, { ...options, headers });

    // If unauthorized, try to refresh and retry
    if (response.status === 401) {
      const refreshed = await refreshTokens();
      if (refreshed) {
        headers['Authorization'] = `Bearer ${getAccessToken()}`;
        return fetch(url, { ...options, headers });
      }
      throw new Error('Session expired');
    }

    return response;
  }, [getAccessToken, refreshTokens]);

  const value = {
    user,
    isAuthenticated: !!user,
    isLoading,
    error,
    signIn,
    signOut,
    completeNewPassword,
    refreshTokens,
    getAccessToken,
    getIdToken,
    authenticatedFetch,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

// =============================================================================
// Hook to use auth context
// =============================================================================

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}

// =============================================================================
// Login Form Component
// =============================================================================

export function LoginForm({ onSuccess }) {
  const { signIn, completeNewPassword, isLoading, error } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [localError, setLocalError] = useState('');
  const [challengeState, setChallengeState] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLocalError('');

    try {
      if (challengeState?.requiresNewPassword) {
        // Handle new password challenge
        if (newPassword !== confirmPassword) {
          setLocalError('Passwords do not match');
          return;
        }
        if (newPassword.length < 8) {
          setLocalError('Password must be at least 8 characters');
          return;
        }

        await completeNewPassword(
          challengeState.email,
          newPassword,
          challengeState.session
        );
        onSuccess?.();
      } else {
        // Normal login
        const result = await signIn(email, password);
        if (result.requiresNewPassword) {
          setChallengeState(result);
        } else if (result.success) {
          onSuccess?.();
        }
      }
    } catch (err) {
      setLocalError(err.message);
    }
  };

  const styles = {
    form: {
      maxWidth: '400px',
      margin: '0 auto',
      padding: '32px',
      background: '#fff',
      borderRadius: '12px',
      boxShadow: '0 4px 6px rgba(0, 0, 0, 0.1)',
    },
    title: {
      fontSize: '24px',
      fontWeight: '600',
      marginBottom: '24px',
      textAlign: 'center',
      color: '#1e293b',
    },
    field: {
      marginBottom: '16px',
    },
    label: {
      display: 'block',
      marginBottom: '6px',
      fontSize: '14px',
      fontWeight: '500',
      color: '#374151',
    },
    input: {
      width: '100%',
      padding: '12px 16px',
      border: '1px solid #d1d5db',
      borderRadius: '8px',
      fontSize: '14px',
      boxSizing: 'border-box',
    },
    button: {
      width: '100%',
      padding: '12px 24px',
      background: '#3c50e0',
      color: '#fff',
      border: 'none',
      borderRadius: '8px',
      fontSize: '16px',
      fontWeight: '500',
      cursor: 'pointer',
      marginTop: '8px',
    },
    error: {
      padding: '12px',
      background: '#fef2f2',
      border: '1px solid #fecaca',
      borderRadius: '8px',
      color: '#dc2626',
      fontSize: '14px',
      marginBottom: '16px',
    },
    info: {
      padding: '12px',
      background: '#eff6ff',
      border: '1px solid #bfdbfe',
      borderRadius: '8px',
      color: '#1d4ed8',
      fontSize: '14px',
      marginBottom: '16px',
    },
  };

  const displayError = localError || error;

  if (challengeState?.requiresNewPassword) {
    return (
      <form onSubmit={handleSubmit} style={styles.form}>
        <h2 style={styles.title}>Set New Password</h2>

        <div style={styles.info}>
          Please set a new password for your account.
        </div>

        {displayError && <div style={styles.error}>{displayError}</div>}

        <div style={styles.field}>
          <label style={styles.label}>New Password</label>
          <input
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            style={styles.input}
            placeholder="Enter new password"
            required
            minLength={8}
          />
        </div>

        <div style={styles.field}>
          <label style={styles.label}>Confirm Password</label>
          <input
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            style={styles.input}
            placeholder="Confirm new password"
            required
          />
        </div>

        <button type="submit" style={styles.button} disabled={isLoading}>
          {isLoading ? 'Setting Password...' : 'Set Password'}
        </button>
      </form>
    );
  }

  return (
    <form onSubmit={handleSubmit} style={styles.form}>
      <h2 style={styles.title}>Sign In</h2>

      {displayError && <div style={styles.error}>{displayError}</div>}

      <div style={styles.field}>
        <label style={styles.label}>Email</label>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          style={styles.input}
          placeholder="Enter your email"
          required
        />
      </div>

      <div style={styles.field}>
        <label style={styles.label}>Password</label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          style={styles.input}
          placeholder="Enter your password"
          required
        />
      </div>

      <button type="submit" style={styles.button} disabled={isLoading}>
        {isLoading ? 'Signing In...' : 'Sign In'}
      </button>
    </form>
  );
}

export default AuthProvider;
