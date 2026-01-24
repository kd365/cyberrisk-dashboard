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

  // Sign up with email and password
  const signUp = async (email, password) => {
    setError(null);
    setIsLoading(true);

    try {
      const response = await fetch('/api/auth/signup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Sign up failed');
      }

      return { success: true, message: data.message };

    } catch (err) {
      setError(err.message);
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  // Confirm sign up with verification code
  const confirmSignUp = async (email, code) => {
    setError(null);
    setIsLoading(true);

    try {
      const response = await fetch('/api/auth/confirm-signup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, code }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Verification failed');
      }

      return { success: true, message: data.message };

    } catch (err) {
      setError(err.message);
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  // Resend verification code
  const resendCode = async (email) => {
    setError(null);

    try {
      const response = await fetch('/api/auth/resend-code', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Failed to resend code');
      }

      return { success: true, message: data.message };

    } catch (err) {
      setError(err.message);
      throw err;
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
    signUp,
    confirmSignUp,
    resendCode,
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
  const { signIn, signUp, confirmSignUp, resendCode, completeNewPassword, isLoading, error } = useAuth();
  const [mode, setMode] = useState('signin'); // 'signin', 'signup', 'verify'
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [verificationCode, setVerificationCode] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [localError, setLocalError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [challengeState, setChallengeState] = useState(null);

  const handleSignIn = async (e) => {
    e.preventDefault();
    setLocalError('');

    try {
      const result = await signIn(email, password);
      if (result.requiresNewPassword) {
        setChallengeState(result);
      } else if (result.success) {
        onSuccess?.();
      }
    } catch (err) {
      // Check if user needs to verify email first
      const errorMsg = err.message.toLowerCase();
      if (errorMsg.includes('not confirmed') || errorMsg.includes('not verified')) {
        setMode('verify');
        setSuccessMessage('Please verify your email first. Check your inbox for the verification code.');
        setLocalError('');
      } else {
        setLocalError(err.message);
      }
    }
  };

  const handleSignUp = async (e) => {
    e.preventDefault();
    setLocalError('');

    if (password !== confirmPassword) {
      setLocalError('Passwords do not match');
      return;
    }
    if (password.length < 8) {
      setLocalError('Password must be at least 8 characters');
      return;
    }

    try {
      await signUp(email, password);
      setMode('verify');
      setSuccessMessage(`Verification code sent to ${email}. Please check your inbox (and spam folder).`);
      setLocalError('');
    } catch (err) {
      setLocalError(err.message);
    }
  };

  const handleVerify = async (e) => {
    e.preventDefault();
    setLocalError('');

    try {
      await confirmSignUp(email, verificationCode);
      setSuccessMessage('Email verified! You can now sign in.');
      setMode('signin');
      setPassword('');
      setVerificationCode('');
    } catch (err) {
      setLocalError(err.message);
    }
  };

  const handleResendCode = async () => {
    setLocalError('');
    try {
      await resendCode(email);
      setSuccessMessage('New verification code sent');
    } catch (err) {
      setLocalError(err.message);
    }
  };

  const handleNewPassword = async (e) => {
    e.preventDefault();
    setLocalError('');

    if (newPassword !== confirmPassword) {
      setLocalError('Passwords do not match');
      return;
    }
    if (newPassword.length < 8) {
      setLocalError('Password must be at least 8 characters');
      return;
    }

    try {
      await completeNewPassword(challengeState.email, newPassword, challengeState.session);
      onSuccess?.();
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
    secondaryButton: {
      width: '100%',
      padding: '12px 24px',
      background: 'transparent',
      color: '#3c50e0',
      border: '1px solid #3c50e0',
      borderRadius: '8px',
      fontSize: '16px',
      fontWeight: '500',
      cursor: 'pointer',
      marginTop: '12px',
    },
    link: {
      color: '#3c50e0',
      cursor: 'pointer',
      textDecoration: 'underline',
      background: 'none',
      border: 'none',
      fontSize: '14px',
    },
    footer: {
      textAlign: 'center',
      marginTop: '20px',
      fontSize: '14px',
      color: '#64748b',
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
    success: {
      padding: '12px',
      background: '#f0fdf4',
      border: '1px solid #bbf7d0',
      borderRadius: '8px',
      color: '#16a34a',
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

  // New password challenge form
  if (challengeState?.requiresNewPassword) {
    return (
      <form onSubmit={handleNewPassword} style={styles.form}>
        <h2 style={styles.title}>Set New Password</h2>
        <div style={styles.info}>Please set a new password for your account.</div>
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

  // Email verification form
  if (mode === 'verify') {
    return (
      <form onSubmit={handleVerify} style={styles.form}>
        <h2 style={styles.title}>Verify Email</h2>
        {successMessage && <div style={styles.success}>{successMessage}</div>}
        {displayError && <div style={styles.error}>{displayError}</div>}
        <div style={styles.info}>Enter the verification code sent to {email}</div>
        <div style={styles.field}>
          <label style={styles.label}>Verification Code</label>
          <input
            type="text"
            value={verificationCode}
            onChange={(e) => setVerificationCode(e.target.value)}
            style={styles.input}
            placeholder="Enter 6-digit code"
            required
            maxLength={6}
          />
        </div>
        <button type="submit" style={styles.button} disabled={isLoading}>
          {isLoading ? 'Verifying...' : 'Verify Email'}
        </button>
        <button type="button" onClick={handleResendCode} style={styles.secondaryButton} disabled={isLoading}>
          Resend Code
        </button>
        <div style={styles.footer}>
          <button type="button" onClick={() => setMode('signin')} style={styles.link}>
            Back to Sign In
          </button>
        </div>
      </form>
    );
  }

  // Sign up form
  if (mode === 'signup') {
    return (
      <form onSubmit={handleSignUp} style={styles.form}>
        <h2 style={styles.title}>Create Account</h2>
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
            placeholder="At least 8 characters"
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
            placeholder="Confirm password"
            required
          />
        </div>
        <button type="submit" style={styles.button} disabled={isLoading}>
          {isLoading ? 'Creating Account...' : 'Sign Up'}
        </button>
        <div style={styles.footer}>
          Already have an account?{' '}
          <button type="button" onClick={() => { setMode('signin'); setLocalError(''); setSuccessMessage(''); }} style={styles.link}>
            Sign In
          </button>
        </div>
      </form>
    );
  }

  // Sign in form (default)
  return (
    <form onSubmit={handleSignIn} style={styles.form}>
      <h2 style={styles.title}>Sign In</h2>
      {successMessage && <div style={styles.success}>{successMessage}</div>}
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
      <div style={styles.footer}>
        Don't have an account?{' '}
        <button type="button" onClick={() => { setMode('signup'); setLocalError(''); setSuccessMessage(''); }} style={styles.link}>
          Sign Up
        </button>
      </div>
    </form>
  );
}

export default AuthProvider;
