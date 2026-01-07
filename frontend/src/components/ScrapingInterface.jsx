import React, { useState, useEffect } from 'react';

function ScrapingInterface({ isAuthenticated, onAuthComplete }) {
  const [formData, setFormData] = useState({
    name: '',
    email: '',
  });
  const [companies, setCompanies] = useState([]);
  const [selectedCompanies, setSelectedCompanies] = useState(['CRWD']);
  const [isLoading, setIsLoading] = useState(false);
  const [status, setStatus] = useState('');
  const [scrapeType, setScrapeType] = useState('all');
  const [documentStatus, setDocumentStatus] = useState({});
  const [showInfo, setShowInfo] = useState(true);

  const handleAuthChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: value
    }));
  };

  const handleAuthSubmit = (e) => {
    e.preventDefault();
    
    // Store in localStorage
    localStorage.setItem('user_name', formData.name);
    localStorage.setItem('user_email', formData.email);
    
    // Notify parent component
    if (onAuthComplete) {
      onAuthComplete(formData);
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
          statusMap[ticker] = data.to_fetch;
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
          type: scrapeType,
          companies: selectedCompanies,
          generate_artifacts: true
        })
      });
      
      const data = await response.json();
      
      if (response.ok) {
        setStatus(`Success: Queued ${selectedCompanies.length} company/companies for scraping`);
      } else {
        setStatus(`Error: Scraping failed - ${data.message || data.error}`);
      }
    } catch (error) {
      setStatus(`Error: ${error.message}`);
    } finally {
      setIsLoading(false);
    }
  };

  // If not authenticated, show auth form
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
                <h3 style={{ marginTop: 0, color: '#004085' }}>About Your Information</h3>
                <p style={{ lineHeight: '1.6', color: '#004085' }}>
                  We need your <strong>name and email</strong> to:
                </p>
                <ul style={{ marginLeft: '20px', color: '#004085' }}>
                  <li>Track SEC filing requests under your profile</li>
                  <li>Manage API rate limits for SEC.gov scraping</li>
                  <li>Store your preferences and saved analyses</li>
                  <li>Notify you when data updates complete</li>
                </ul>
                <p style={{ fontSize: '12px', color: '#004085', marginBottom: 0 }}>
                  <strong>Data stored locally:</strong> Your information is stored in your browser's local storage. 
                  We recommend using a valid email for SEC filing requests.
                </p>
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

        <div style={{
          background: 'white',
          border: '1px solid #ddd',
          borderRadius: '8px',
          padding: '30px',
          boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
        }}>
          <h2 style={{ textAlign: 'center', marginBottom: '10px' }}>Get Started</h2>
          <p style={{ textAlign: 'center', color: '#666', marginBottom: '30px', fontSize: '14px' }}>
            Please enter your information to access SEC filings, earnings transcripts, and analysis for 50+ cybersecurity companies.
          </p>
          <form onSubmit={handleAuthSubmit}>
            <div className="form-group" style={{ marginBottom: '20px' }}>
              <label htmlFor="name" style={{ display: 'block', marginBottom: '8px', fontWeight: 'bold' }}>
                Full Name *
              </label>
              <input
                type="text"
                id="name"
                name="name"
                value={formData.name}
                onChange={handleAuthChange}
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

            <div className="form-group" style={{ marginBottom: '20px' }}>
              <label htmlFor="email" style={{ display: 'block', marginBottom: '8px', fontWeight: 'bold' }}>
                Email Address *
              </label>
              <input
                type="email"
                id="email"
                name="email"
                value={formData.email}
                onChange={handleAuthChange}
                placeholder="e.g., john@company.com"
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
              const hasDocuments = status && status.existing > 0;
              const needsMore = status && status.to_fetch > 0;
              
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
                        {hasDocuments && (
                          <span style={{ color: '#28a745' }}>
                            {status.existing} documents saved
                          </span>
                        )}
                        {needsMore && (
                          <span style={{ color: '#ff6b6b', marginLeft: hasDocuments ? '8px' : '0' }}>
                            {needsMore > 0 && `${needsMore} more available`}
                          </span>
                        )}
                        {!hasDocuments && !needsMore && (
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
          <h4 style={{ marginTop: 0, color: '#004085' }}>How It Works</h4>
          <ul style={{ marginLeft: '20px', lineHeight: '1.6', color: '#004085', marginBottom: 0 }}>
            <li><strong>10-K Filings:</strong> Annual reports with cybersecurity risk disclosures</li>
            <li><strong>10-Q Filings:</strong> Quarterly reports (more frequent updates)</li>
            <li><strong>Earnings Transcripts:</strong> Call transcripts from Alpha Vantage</li>
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
                padding: '8px',
                border: '1px solid #ddd',
                borderRadius: '4px'
              }}
            >
              <option value="all">All Documents (10-K, 10-Q, Transcripts)</option>
              <option value="sec">SEC Filings Only (10-K, 10-Q)</option>
              <option value="transcripts">Earnings Transcripts Only</option>
            </select>
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
