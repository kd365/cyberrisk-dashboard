import React, { useState, useEffect } from 'react';
import ScrapingInterface from './ScrapingInterface';
import ArtifactTable from './ArtifactTable';
import TimeSeriesForecast from './TimeSeriesForecast';
import SentimentAnalysis from './SentimentAnalysisEnhanced';
import CompanyGrowth from './CompanyGrowth';
import LexChatbot from './LexChatbot';
import GraphRAGAssistant from './GraphRAGAssistant';
import { useAuth } from './AuthProvider';

// Icon components (simple SVG icons)
const Icons = {
  Dashboard: () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </svg>
  ),
  Chart: () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M3 3v18h18" />
      <path d="M18 17V9" />
      <path d="M13 17V5" />
      <path d="M8 17v-3" />
    </svg>
  ),
  Sentiment: () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="10" />
      <path d="M8 14s1.5 2 4 2 4-2 4-2" />
      <line x1="9" y1="9" x2="9.01" y2="9" />
      <line x1="15" y1="9" x2="15.01" y2="9" />
    </svg>
  ),
  Growth: () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="22 7 13.5 15.5 8.5 10.5 2 17" />
      <polyline points="16 7 22 7 22 13" />
    </svg>
  ),
  Document: () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
    </svg>
  ),
  Companies: () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M3 21h18" />
      <path d="M9 8h1" />
      <path d="M9 12h1" />
      <path d="M9 16h1" />
      <path d="M14 8h1" />
      <path d="M14 12h1" />
      <path d="M14 16h1" />
      <path d="M5 21V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16" />
    </svg>
  ),
  TrendUp: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="23 6 13.5 15.5 8.5 10.5 1 18" />
      <polyline points="17 6 23 6 23 12" />
    </svg>
  ),
  Shield: () => (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    </svg>
  ),
  Menu: () => (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="3" y1="12" x2="21" y2="12" />
      <line x1="3" y1="6" x2="21" y2="6" />
      <line x1="3" y1="18" x2="21" y2="18" />
    </svg>
  ),
  Close: () => (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  ),
  Logout: () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <polyline points="16 17 21 12 16 7" />
      <line x1="21" y1="12" x2="9" y2="12" />
    </svg>
  ),
  Chat: () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  ),
  Network: () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="5" r="3" />
      <circle cx="5" cy="19" r="3" />
      <circle cx="19" cy="19" r="3" />
      <line x1="12" y1="8" x2="5" y2="16" />
      <line x1="12" y1="8" x2="19" y2="16" />
    </svg>
  )
};

function Dashboard() {
  // Use Cognito auth from AuthProvider
  const { isAuthenticated, signOut } = useAuth();

  const [activeTab, setActiveTab] = useState('scraping');
  const [selectedCompany, setSelectedCompany] = useState('CRWD');
  const [companies, setCompanies] = useState([]);
  const [companiesLoading, setCompaniesLoading] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [metrics, setMetrics] = useState({
    totalCompanies: 0,
    totalArtifacts: 0,
    avgSentiment: null,
    lastUpdated: null
  });

  // Fetch companies from API
  useEffect(() => {
    const fetchCompanies = async () => {
      try {
        const response = await fetch('/api/companies');
        if (!response.ok) {
          setCompanies([]);
          setCompaniesLoading(false);
          return;
        }
        const data = await response.json();
        setCompanies(data || []);
        setMetrics(prev => ({ ...prev, totalCompanies: data?.length || 0 }));
        if (data && data.length > 0) {
          setSelectedCompany(data[0].ticker || 'CRWD');
        }
      } catch (error) {
        console.error('Error fetching companies:', error);
        setCompanies([]);
      } finally {
        setCompaniesLoading(false);
      }
    };
    fetchCompanies();
  }, []);

  // Fetch artifacts count
  useEffect(() => {
    const fetchArtifacts = async () => {
      try {
        const response = await fetch('/api/all-artifacts');
        if (response.ok) {
          const data = await response.json();
          setMetrics(prev => ({
            ...prev,
            totalArtifacts: data?.length || 0,
            lastUpdated: new Date().toLocaleDateString()
          }));
        }
      } catch (error) {
        console.error('Error fetching artifacts:', error);
      }
    };
    fetchArtifacts();
  }, []);

  // Auth complete handler (for legacy ScrapingInterface compatibility)
  const handleAuthComplete = () => {
    // Auth is now handled by AuthProvider/useAuth
    // This just closes the login modal if shown
    setShowLoginModal(false);
  };

  // Logout handler using Cognito
  const handleLogout = async () => {
    await signOut();
  };

  const navItems = [
    { id: 'scraping', label: 'Data Collection', icon: Icons.Document },
    { id: 'forecast', label: 'Price Forecast', icon: Icons.Chart },
    { id: 'sentiment', label: 'Sentiment Analysis', icon: Icons.Sentiment },
    { id: 'growth', label: 'Company Growth', icon: Icons.Growth },
    { id: 'knowledge', label: 'Knowledge Assistant', icon: Icons.Network },
    { id: 'assistant', label: 'Lex Assistant', icon: Icons.Chat },
  ];

  const styles = {
    layout: {
      display: 'flex',
      minHeight: '100vh',
      background: '#f1f5f9'
    },
    sidebar: {
      width: sidebarOpen ? '280px' : '0px',
      background: '#1c2434',
      color: '#dee4ee',
      display: 'flex',
      flexDirection: 'column',
      transition: 'width 300ms ease',
      overflow: 'hidden',
      position: 'fixed',
      height: '100vh',
      zIndex: 100
    },
    sidebarContent: {
      width: '280px',
      display: 'flex',
      flexDirection: 'column',
      height: '100%'
    },
    logo: {
      padding: '24px 20px',
      borderBottom: '1px solid #333a48',
      display: 'flex',
      alignItems: 'center',
      gap: '12px'
    },
    logoText: {
      fontSize: '20px',
      fontWeight: '700',
      color: '#fff',
      whiteSpace: 'nowrap'
    },
    nav: {
      flex: 1,
      padding: '20px 16px'
    },
    navLabel: {
      fontSize: '11px',
      fontWeight: '600',
      textTransform: 'uppercase',
      letterSpacing: '0.5px',
      color: '#8a99af',
      padding: '0 12px',
      marginBottom: '12px'
    },
    navItem: (active) => ({
      display: 'flex',
      alignItems: 'center',
      gap: '12px',
      padding: '12px 16px',
      borderRadius: '8px',
      cursor: 'pointer',
      color: active ? '#fff' : '#dee4ee',
      background: active ? '#333a48' : 'transparent',
      marginBottom: '4px',
      transition: 'all 150ms ease',
      fontSize: '15px',
      fontWeight: active ? '500' : '400'
    }),
    sidebarFooter: {
      padding: '20px',
      borderTop: '1px solid #333a48'
    },
    main: {
      flex: 1,
      marginLeft: sidebarOpen ? '280px' : '0px',
      transition: 'margin-left 300ms ease',
      minHeight: '100vh'
    },
    header: {
      background: '#fff',
      padding: '16px 24px',
      borderBottom: '1px solid #e2e8f0',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      position: 'sticky',
      top: 0,
      zIndex: 50
    },
    headerLeft: {
      display: 'flex',
      alignItems: 'center',
      gap: '16px'
    },
    menuButton: {
      background: 'none',
      border: 'none',
      cursor: 'pointer',
      padding: '8px',
      borderRadius: '8px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      color: '#64748b'
    },
    pageTitle: {
      fontSize: '18px',
      fontWeight: '600',
      color: '#1e293b'
    },
    content: {
      padding: '24px'
    },
    metricsGrid: {
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
      gap: '20px',
      marginBottom: '24px'
    },
    metricCard: {
      background: '#fff',
      borderRadius: '12px',
      padding: '20px 24px',
      border: '1px solid #e2e8f0',
      display: 'flex',
      alignItems: 'flex-start',
      gap: '16px'
    },
    metricIcon: (color) => ({
      width: '48px',
      height: '48px',
      borderRadius: '10px',
      background: color,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      color: '#fff',
      flexShrink: 0
    }),
    metricValue: {
      fontSize: '28px',
      fontWeight: '700',
      color: '#1e293b',
      lineHeight: 1.2
    },
    metricLabel: {
      fontSize: '14px',
      color: '#64748b',
      marginTop: '4px'
    },
    contentCard: {
      background: '#fff',
      borderRadius: '12px',
      border: '1px solid #e2e8f0',
      overflow: 'hidden'
    },
    cardBody: {
      padding: '24px'
    },
    select: {
      padding: '10px 40px 10px 16px',
      border: '1px solid #e2e8f0',
      borderRadius: '8px',
      fontSize: '14px',
      color: '#1e293b',
      background: '#fff',
      cursor: 'pointer',
      minWidth: '280px',
      appearance: 'none',
      backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='%2364748b' stroke-width='2'%3E%3Cpolyline points='6 9 12 15 18 9'%3E%3C/polyline%3E%3C/svg%3E")`,
      backgroundRepeat: 'no-repeat',
      backgroundPosition: 'right 12px center'
    },
    authMessage: {
      textAlign: 'center',
      padding: '60px 40px',
      color: '#64748b'
    },
    logoutButton: {
      display: 'flex',
      alignItems: 'center',
      gap: '12px',
      padding: '12px 16px',
      borderRadius: '8px',
      cursor: 'pointer',
      color: '#dee4ee',
      background: 'transparent',
      border: 'none',
      width: '100%',
      fontSize: '15px',
      transition: 'all 150ms ease'
    }
  };

  const getCurrentPageTitle = () => {
    const item = navItems.find(item => item.id === activeTab);
    return item ? item.label : 'Dashboard';
  };

  return (
    <div style={styles.layout}>
      {/* Sidebar */}
      <aside style={styles.sidebar}>
        <div style={styles.sidebarContent}>
          {/* Logo */}
          <div style={styles.logo}>
            <div style={{ color: '#3c50e0' }}>
              <Icons.Shield />
            </div>
            <span style={styles.logoText}>CyberRisk</span>
          </div>

          {/* Navigation */}
          <nav style={styles.nav}>
            <div style={styles.navLabel}>Menu</div>
            {navItems.map((item) => (
              <div
                key={item.id}
                style={styles.navItem(activeTab === item.id)}
                onClick={() => setActiveTab(item.id)}
                onMouseEnter={(e) => {
                  if (activeTab !== item.id) {
                    e.currentTarget.style.background = '#333a48';
                  }
                }}
                onMouseLeave={(e) => {
                  if (activeTab !== item.id) {
                    e.currentTarget.style.background = 'transparent';
                  }
                }}
              >
                <item.icon />
                <span>{item.label}</span>
              </div>
            ))}
          </nav>

          {/* Footer */}
          {isAuthenticated && (
            <div style={styles.sidebarFooter}>
              <button
                onClick={handleLogout}
                style={styles.logoutButton}
                onMouseEnter={(e) => e.currentTarget.style.background = '#333a48'}
                onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
              >
                <Icons.Logout />
                <span>Logout</span>
              </button>
            </div>
          )}
        </div>
      </aside>

      {/* Main Content */}
      <main style={styles.main}>
        {/* Header */}
        <header style={styles.header}>
          <div style={styles.headerLeft}>
            <button
              style={styles.menuButton}
              onClick={() => setSidebarOpen(!sidebarOpen)}
            >
              {sidebarOpen ? <Icons.Close /> : <Icons.Menu />}
            </button>
            <h1 style={styles.pageTitle}>{getCurrentPageTitle()}</h1>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            {!companiesLoading && (
              <select
                value={selectedCompany}
                onChange={(e) => setSelectedCompany(e.target.value)}
                style={styles.select}
                disabled={companiesLoading}
              >
                {companies.map((company) => (
                  <option key={company.ticker} value={company.ticker}>
                    {company.ticker} - {company.name}
                  </option>
                ))}
              </select>
            )}
          </div>
        </header>

        {/* Content */}
        <div style={styles.content}>
          {/* Metrics Cards */}
          <div style={styles.metricsGrid}>
            <div style={styles.metricCard}>
              <div style={styles.metricIcon('#3c50e0')}>
                <Icons.Companies />
              </div>
              <div>
                <div style={styles.metricValue}>{metrics.totalCompanies}</div>
                <div style={styles.metricLabel}>Companies Tracked</div>
              </div>
            </div>
            <div style={styles.metricCard}>
              <div style={styles.metricIcon('#10b981')}>
                <Icons.Document />
              </div>
              <div>
                <div style={styles.metricValue}>{metrics.totalArtifacts}</div>
                <div style={styles.metricLabel}>Total Documents</div>
              </div>
            </div>
            <div style={styles.metricCard}>
              <div style={styles.metricIcon('#f59e0b')}>
                <Icons.Chart />
              </div>
              <div>
                <div style={styles.metricValue}>{selectedCompany}</div>
                <div style={styles.metricLabel}>Selected Company</div>
              </div>
            </div>
            <div style={styles.metricCard}>
              <div style={styles.metricIcon('#8b5cf6')}>
                <Icons.TrendUp />
              </div>
              <div>
                <div style={styles.metricValue}>{metrics.lastUpdated || '--'}</div>
                <div style={styles.metricLabel}>Last Updated</div>
              </div>
            </div>
          </div>

          {/* Main Content Card */}
          <div style={styles.contentCard}>
            <div style={styles.cardBody}>
              {activeTab === 'scraping' && (
                <>
                  <ScrapingInterface isAuthenticated={isAuthenticated} onAuthComplete={handleAuthComplete} />
                  {isAuthenticated && (
                    <>
                      <hr style={{ margin: '30px 0', borderColor: '#e2e8f0', borderStyle: 'solid', borderWidth: '1px 0 0 0' }} />
                      <ArtifactTable selectedTicker={selectedCompany} />
                    </>
                  )}
                </>
              )}

              {activeTab === 'forecast' && isAuthenticated && (
                <TimeSeriesForecast ticker={selectedCompany} />
              )}

              {activeTab === 'sentiment' && isAuthenticated && (
                <SentimentAnalysis ticker={selectedCompany} />
              )}

              {activeTab === 'growth' && isAuthenticated && (
                <CompanyGrowth ticker={selectedCompany} />
              )}

              {activeTab === 'knowledge' && isAuthenticated && (
                <GraphRAGAssistant ticker={selectedCompany} />
              )}

              {activeTab === 'assistant' && isAuthenticated && (
                <LexChatbot />
              )}

              {!isAuthenticated && activeTab !== 'scraping' && (
                <div style={styles.authMessage}>
                  <Icons.Shield />
                  <h3 style={{ marginTop: '16px', marginBottom: '8px', color: '#1e293b' }}>Authentication Required</h3>
                  <p>Please authenticate in the Data Collection tab to access analysis features.</p>
                </div>
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

export default Dashboard;
