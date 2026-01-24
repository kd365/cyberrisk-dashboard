import React, { useState, useEffect } from 'react';
import { useAuth, LoginForm } from './AuthProvider';

function ScrapingInterface({ isAuthenticated: propIsAuthenticated, onAuthComplete }) {
  // Use Cognito auth context
  const { user, isAuthenticated: authIsAuthenticated, isLoading: authLoading } = useAuth();

  // Combine prop-based and context-based authentication
  const isAuthenticated = authIsAuthenticated || propIsAuthenticated;

  // For SEC scraping, we need user's name (Cognito has email)
  const [userName, setUserName] = useState(() => localStorage.getItem('user_name') || '');
  const [needsName, setNeedsName] = useState(false);

  const [companies, setCompanies] = useState([]);
  const [selectedCompanies, setSelectedCompanies] = useState(['CRWD']);
  const [isLoading, setIsLoading] = useState(false);
  const [status, setStatus] = useState('');
  const [scrapeType, setScrapeType] = useState('all');
  const [documentStatus, setDocumentStatus] = useState({});
  const [showInfo, setShowInfo] = useState(true);

  // Check if we need the user's name for SEC scraping
  useEffect(() => {
    // If user has name from Cognito, use that
    if (user?.name && !userName) {
      setUserName(user.name);
      localStorage.setItem('user_name', user.name);
    } else if (isAuthenticated && !userName && !user?.name) {
      setNeedsName(true);
    }
  }, [isAuthenticated, userName, user?.name]);

  // When user logs in via Cognito, store email for SEC scraping compatibility
  useEffect(() => {
    if (user?.email) {
      localStorage.setItem('user_email', user.email);
    }
  }, [user?.email]);

  const handleNameSubmit = async (e) => {
    e.preventDefault();
    if (userName.trim()) {
      try {
        // Update name in Cognito
        const accessToken = localStorage.getItem('cognito_access_token');
        if (accessToken) {
          const response = await fetch('/api/auth/update-profile', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': `Bearer ${accessToken}`,
            },
            body: JSON.stringify({ name: userName.trim() }),
          });

          if (!response.ok) {
            console.error('Failed to update profile in Cognito');
          }
        }

        // Also store locally for SEC scraping
        localStorage.setItem('user_name', userName.trim());
        setNeedsName(false);

        if (onAuthComplete) {
          onAuthComplete({ name: userName, email: user?.email });
        }
      } catch (error) {
        console.error('Error updating profile:', error);
        // Still allow proceeding even if Cognito update fails
        localStorage.setItem('user_name', userName.trim());
        setNeedsName(false);
      }
    }
  };

  // Fetch available companies
  useEffect(() => {
    const fetchCompanies = async () => {
      try {
        const response = await fetch('/api/companies');
        const data = await response.json();
        setCompanies(data || []);
      } catch (error) {
        console.error('Error fetching companies:', error);
      }
    };
    
    fetchCompanies();
  }, []);

  // Check document status when selected companies change
  useEffect(() => {
    const checkDocumentStatus = async () => {
      const statusMap = {};

      for (const ticker of selectedCompanies) {
        try {
          const response = await fetch(`/api/artifacts/status/${ticker}`);
          const data = await response.json();
          // Store the full status info including existing count
          statusMap[ticker] = {
            existing: data.status?.total || 0,
            breakdown: data.status?.by_type || {}
          };
        } catch (error) {
          console.error(`Error checking status for ${ticker}:`, error);
        }
      }

      setDocumentStatus(statusMap);
    };

    if (isAuthenticated && selectedCompanies.length > 0) {
      checkDocumentStatus();
    }
  }, [selectedCompanies, isAuthenticated]);

  const handleCompanyToggle = (ticker) => {
    setSelectedCompanies(prev => 
      prev.includes(ticker)
        ? prev.filter(t => t !== ticker)
        : [...prev, ticker]
    );
  };

  const handleSelectAll = () => {
    if (selectedCompanies.length === companies.length) {
      setSelectedCompanies([]);
    } else {
      setSelectedCompanies(companies.map(c => c.ticker));
    }
  };

  const handleScrape = async () => {
    if (selectedCompanies.length === 0) {
      setStatus('Error: Please select at least one company');
      return;
    }

    setIsLoading(true);
    setStatus(`Scraping ${selectedCompanies.length} company/companies...`);
    
    try {
      const response = await fetch('/api/scraping/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          type: scrapeType === 'sec_no_8k' ? 'sec' : scrapeType,
          companies: selectedCompanies,
          include_8k: scrapeType !== 'sec_no_8k' && scrapeType !== 'transcripts',
          generate_artifacts: true
        })
      });
      
      const data = await response.json();
      
      if (response.ok) {
        setStatus(`Success: Started scraping ${selectedCompanies.length} company/companies. Documents will be scraped and 8-K events (executive changes, M&A, security incidents) will be automatically extracted to the knowledge graph.`);
      } else {
        setStatus(`Error: Scraping failed - ${data.message || data.error}`);
      }
    } catch (error) {
      setStatus(`Error: ${error.message}`);
    } finally {
      setIsLoading(false);
    }
  };

  // Show loading while auth is being checked
  if (authLoading) {
    return (
      <div style={{ maxWidth: '600px', margin: '0 auto', padding: '40px', textAlign: 'center' }}>
        <p>Loading...</p>
      </div>
    );
  }

  // If not authenticated, show Cognito login form
  if (!isAuthenticated) {
    return (
      <div style={{ maxWidth: '600px', margin: '0 auto', padding: '20px' }}>
        {showInfo && (
          <div style={{
            background: '#e7f3ff',
            border: '1px solid #b3d9ff',
            borderRadius: '8px',
            padding: '20px',
            marginBottom: '20px'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start' }}>
              <div>
                <h3 style={{ marginTop: 0, color: '#004085' }}>Welcome to CyberRisk Dashboard</h3>
                <p style={{ lineHeight: '1.6', color: '#004085' }}>
                  Sign in to access:
                </p>
                <ul style={{ marginLeft: '20px', color: '#004085' }}>
                  <li>SEC filings and earnings transcripts for 30+ cybersecurity companies</li>
                  <li>AI-powered sentiment analysis and risk assessment</li>
                  <li>Knowledge graph exploration and chat assistant</li>
                  <li>Price forecasting and growth analytics</li>
                </ul>
              </div>
              <button
                onClick={() => setShowInfo(false)}
                style={{
                  background: 'none',
                  border: 'none',
                  fontSize: '20px',
                  cursor: 'pointer',
                  padding: 0,
                  marginLeft: '10px'
                }}
              >
                ✕
              </button>
            </div>
          </div>
        )}

        <LoginForm onSuccess={onAuthComplete} />
      </div>
    );
  }

  // If authenticated but no name for SEC scraping, collect it
  if (needsName) {
    return (
      <div style={{ maxWidth: '600px', margin: '0 auto', padding: '20px' }}>
        <div style={{
          background: 'white',
          border: '1px solid #ddd',
          borderRadius: '8px',
          padding: '30px',
          boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
        }}>
          <h2 style={{ textAlign: 'center', marginBottom: '10px' }}>One More Step</h2>
          <p style={{ textAlign: 'center', color: '#666', marginBottom: '20px', fontSize: '14px' }}>
            SEC.gov requires user identification for API requests. Please provide your name.
          </p>
          <p style={{ textAlign: 'center', color: '#28a745', marginBottom: '20px', fontSize: '14px' }}>
            Signed in as: <strong>{user?.email}</strong>
          </p>
          <form onSubmit={handleNameSubmit}>
            <div className="form-group" style={{ marginBottom: '20px' }}>
              <label htmlFor="name" style={{ display: 'block', marginBottom: '8px', fontWeight: 'bold' }}>
                Full Name *
              </label>
              <input
                type="text"
                id="name"
                value={userName}
                onChange={(e) => setUserName(e.target.value)}
                placeholder="e.g., John Smith"
                required
                style={{
                  width: '100%',
                  padding: '10px',
                  border: '1px solid #ddd',
                  borderRadius: '4px',
                  boxSizing: 'border-box',
                  fontSize: '14px'
                }}
              />
            </div>

            <button
              type="submit"
              style={{
                width: '100%',
                padding: '12px',
                background: '#28a745',
                color: 'white',
                border: 'none',
                borderRadius: '4px',
                cursor: 'pointer',
                fontSize: '16px',
                fontWeight: 'bold'
              }}
            >
              Continue to Dashboard →
            </button>
          </form>
        </div>
      </div>
    );
  }

  // If authenticated, show scraping interface
  return (
    <div style={{ display: 'flex', gap: '20px', marginBottom: '20px' }}>
      {/* Company Selection Panel */}
      <div style={{
        flex: 1,
        background: '#f8f9fa',
        padding: '20px',
        borderRadius: '8px',
        border: '1px solid #dee2e6'
      }}>
        <h3>Select Companies to Scrape</h3>
        <p style={{ color: '#666', marginTop: '-10px' }}>
          Choose one or more companies to fetch SEC filings and earnings transcripts
        </p>
        
        <div style={{ marginBottom: '15px' }}>
          <button
            onClick={handleSelectAll}
            style={{
              background: 'none',
              border: '1px solid #007bff',
              color: '#007bff',
              padding: '8px 12px',
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '12px',
              fontWeight: 'bold'
            }}
          >
            {selectedCompanies.length === companies.length ? 'Deselect All' : 'Select All'}
          </button>
          <span style={{ marginLeft: '10px', color: '#666', fontSize: '12px' }}>
            {selectedCompanies.length} of {companies.length} selected
          </span>
        </div>

        <div style={{
          maxHeight: '350px',
          overflowY: 'auto',
          border: '1px solid #dee2e6',
          borderRadius: '4px',
          padding: '10px',
          background: 'white'
        }}>
          {companies.length === 0 ? (
            <p style={{ color: '#666', textAlign: 'center' }}>Loading companies...</p>
          ) : (
            companies.map((company) => {
              const status = documentStatus[company.ticker];
              const docCount = status?.existing || 0;
              
              return (
                <label key={company.ticker} style={{
                  display: 'flex',
                  alignItems: 'center',
                  padding: '10px',
                  borderBottom: '1px solid #f0f0f0',
                  cursor: 'pointer',
                  background: selectedCompanies.includes(company.ticker) ? '#e7f3ff' : 'transparent'
                }}>
                  <input
                    type="checkbox"
                    checked={selectedCompanies.includes(company.ticker)}
                    onChange={() => handleCompanyToggle(company.ticker)}
                    style={{ marginRight: '10px', cursor: 'pointer' }}
                  />
                  <span style={{ flex: 1 }}>
                    <strong>{company.ticker}</strong>
                    <br />
                    <span style={{ fontSize: '12px', color: '#666' }}>
                      {company.name}
                    </span>
                    {status && (
                      <div style={{ fontSize: '11px', marginTop: '4px' }}>
                        {docCount > 0 ? (
                          <span style={{ color: '#28a745' }}>
                            {docCount} documents saved
                          </span>
                        ) : (
                          <span style={{ color: '#999' }}>No documents yet</span>
                        )}
                      </div>
                    )}
                  </span>
                </label>
              );
            })
          )}
        </div>
      </div>

      {/* Scraping Settings Panel */}
      <div style={{
        flex: 1,
        background: '#fff'
      }}>
        <div style={{
          background: '#e7f3ff',
          padding: '20px',
          borderRadius: '8px',
          border: '1px solid #b3d9ff',
          marginBottom: '20px'
        }}>
          <h4 style={{ marginTop: 0, color: '#004085' }}>Document Types</h4>
          <ul style={{ marginLeft: '20px', lineHeight: '1.6', color: '#004085', marginBottom: 0 }}>
            <li><strong>10-K:</strong> Annual reports with cybersecurity risk disclosures</li>
            <li><strong>10-Q:</strong> Quarterly reports with updates</li>
            <li><strong>8-K:</strong> Material events - breaches, executive changes, M&A</li>
            <li><strong>Transcripts:</strong> Earnings call transcripts from Alpha Vantage</li>
          </ul>
        </div>

        <div style={{
          background: '#f8f9fa',
          padding: '20px',
          borderRadius: '8px',
          border: '1px solid #dee2e6'
        }}>
          <h4 style={{ marginTop: 0 }}>Scraping Settings</h4>
          
          <div style={{ marginBottom: '15px' }}>
            <label style={{ fontWeight: 'bold', marginBottom: '8px', display: 'block' }}>
              Document Types
            </label>
            <select
              value={scrapeType}
              onChange={(e) => setScrapeType(e.target.value)}
              style={{
                width: '100%',
                padding: '10px',
                border: '1px solid #ddd',
                borderRadius: '4px',
                fontSize: '14px'
              }}
            >
              <option value="all">All Documents (10-K, 10-Q, 8-K, Transcripts)</option>
              <option value="sec">SEC Filings Only (10-K, 10-Q, 8-K)</option>
              <option value="sec_no_8k">SEC Filings (10-K, 10-Q only)</option>
              <option value="transcripts">Earnings Transcripts Only</option>
              <option value="8k">8-K Current Reports Only</option>
            </select>
            <p style={{ fontSize: '12px', color: '#666', marginTop: '8px', marginBottom: 0 }}>
              8-K filings include cybersecurity incidents, leadership changes, M&A, and material events
            </p>
          </div>

          <button
            onClick={handleScrape}
            disabled={isLoading || selectedCompanies.length === 0}
            style={{
              width: '100%',
              padding: '12px',
              background: isLoading || selectedCompanies.length === 0 ? '#ccc' : '#28a745',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: isLoading || selectedCompanies.length === 0 ? 'not-allowed' : 'pointer',
              fontSize: '16px',
              fontWeight: 'bold'
            }}
          >
            {isLoading ? 'Scraping in Progress...' : 'Start Scraping'}
          </button>
        </div>

        {status && (
          <div style={{
            marginTop: '15px',
            padding: '12px',
            background: status.startsWith('Error') ? '#f8d7da' : status.startsWith('Success') ? '#d4edda' : '#fff3cd',
            color: status.startsWith('Error') ? '#721c24' : status.startsWith('Success') ? '#155724' : '#856404',
            borderRadius: '4px',
            fontSize: '14px'
          }}>
            {status}
          </div>
        )}
      </div>
    </div>
  );
}

export default ScrapingInterface;
