import React, { useState, useEffect, useRef } from 'react';

// ============================================================================
// GraphRAG Assistant - AI Chat + Cypher Console
// ============================================================================

// Icons
const Icons = {
  Send: () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="22" y1="2" x2="11" y2="13" />
      <polygon points="22 2 15 22 11 13 2 9 22 2" />
    </svg>
  ),
  Bot: () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="3" y="11" width="18" height="10" rx="2" />
      <circle cx="12" cy="5" r="2" />
      <path d="M12 7v4" />
      <line x1="8" y1="16" x2="8" y2="16" />
      <line x1="16" y1="16" x2="16" y2="16" />
    </svg>
  ),
  User: () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  ),
  Terminal: () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="4 17 10 11 4 5" />
      <line x1="12" y1="19" x2="20" y2="19" />
    </svg>
  ),
  Chat: () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  ),
  Play: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polygon points="5 3 19 12 5 21 5 3" />
    </svg>
  ),
  Clear: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    </svg>
  ),
  Code: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="16 18 22 12 16 6" />
      <polyline points="8 6 2 12 8 18" />
    </svg>
  ),
  Table: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
      <line x1="3" y1="9" x2="21" y2="9" />
      <line x1="3" y1="15" x2="21" y2="15" />
      <line x1="9" y1="3" x2="9" y2="21" />
    </svg>
  ),
  Chart: () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="18" y1="20" x2="18" y2="10" />
      <line x1="12" y1="20" x2="12" y2="4" />
      <line x1="6" y1="20" x2="6" y2="14" />
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
  ),
  Spinner: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ animation: 'spin 1s linear infinite' }}>
      <circle cx="12" cy="12" r="10" strokeOpacity="0.25" />
      <path d="M12 2a10 10 0 0 1 10 10" strokeLinecap="round" />
    </svg>
  )
};

// ============================================================================
// Main Component
// ============================================================================

function GraphRAGAssistant({ ticker = 'CRWD', authToken = null, userEmail = null }) {
  const [activeSubTab, setActiveSubTab] = useState('chat');
  const [graphStats, setGraphStats] = useState(null);
  const [graphConnected, setGraphConnected] = useState(false);

  // Check graph connection on mount
  useEffect(() => {
    const checkGraph = async () => {
      try {
        const response = await fetch('/api/knowledge-graph/stats');
        const data = await response.json();
        setGraphConnected(data.connected || false);
        if (data.connected) {
          setGraphStats(data);
        }
      } catch (error) {
        console.error('Error checking graph:', error);
        setGraphConnected(false);
      }
    };
    checkGraph();
  }, []);

  const subTabs = [
    { id: 'chat', label: 'GraphRAG Chat', icon: Icons.Chat },
    { id: 'intelligence', label: 'Competitive Intelligence', icon: Icons.Chart },
    { id: 'cypher', label: 'Cypher Console', icon: Icons.Terminal }
  ];

  const styles = {
    container: {
      display: 'flex',
      flexDirection: 'column',
      height: 'calc(100vh - 300px)',
      minHeight: '500px'
    },
    tabBar: {
      display: 'flex',
      gap: '4px',
      padding: '8px',
      background: '#f8fafc',
      borderRadius: '8px 8px 0 0',
      borderBottom: '1px solid #e2e8f0'
    },
    tab: (active) => ({
      display: 'flex',
      alignItems: 'center',
      gap: '8px',
      padding: '10px 16px',
      borderRadius: '6px',
      cursor: 'pointer',
      background: active ? '#fff' : 'transparent',
      border: active ? '1px solid #e2e8f0' : '1px solid transparent',
      color: active ? '#1e293b' : '#64748b',
      fontWeight: active ? '500' : '400',
      fontSize: '14px',
      transition: 'all 150ms ease'
    }),
    statsBar: {
      display: 'flex',
      flexWrap: 'wrap',
      alignItems: 'center',
      gap: '8px 16px',
      padding: '10px 16px',
      background: '#f1f5f9',
      borderBottom: '1px solid #e2e8f0',
      fontSize: '12px',
      color: '#64748b',
      minHeight: 'auto'
    },
    statItem: {
      display: 'flex',
      alignItems: 'center',
      gap: '4px'
    },
    statValue: {
      fontWeight: '600',
      color: '#1e293b'
    },
    connectionStatus: (connected) => ({
      display: 'flex',
      alignItems: 'center',
      gap: '6px',
      padding: '4px 12px',
      borderRadius: '12px',
      background: connected ? '#dcfce7' : '#fef2f2',
      color: connected ? '#166534' : '#991b1b',
      fontSize: '12px',
      fontWeight: '500'
    }),
    dot: (connected) => ({
      width: '8px',
      height: '8px',
      borderRadius: '50%',
      background: connected ? '#22c55e' : '#ef4444'
    }),
    content: {
      flex: 1,
      overflow: 'hidden'
    }
  };

  return (
    <div style={styles.container}>
      {/* Tab Bar */}
      <div style={styles.tabBar}>
        {subTabs.map(tab => (
          <div
            key={tab.id}
            style={styles.tab(activeSubTab === tab.id)}
            onClick={() => setActiveSubTab(tab.id)}
          >
            <tab.icon />
            <span>{tab.label}</span>
          </div>
        ))}

        <div style={{ marginLeft: 'auto' }}>
          <div style={styles.connectionStatus(graphConnected)}>
            <div style={styles.dot(graphConnected)} />
            {graphConnected ? 'Graph Connected' : 'Graph Offline'}
          </div>
        </div>
      </div>

      {/* Stats Bar */}
      {graphStats && (
        <div style={styles.statsBar}>
          <div style={styles.statItem}>
            Organizations: <span style={styles.statValue}>{graphStats.organizations?.toLocaleString() || 0}</span>
          </div>
          <div style={styles.statItem}>
            Documents: <span style={styles.statValue}>{graphStats.documents?.toLocaleString() || 0}</span>
          </div>
          <div style={styles.statItem}>
            Concepts: <span style={styles.statValue}>{graphStats.concepts?.toLocaleString() || 0}</span>
          </div>
          <div style={styles.statItem}>
            Persons: <span style={styles.statValue}>{graphStats.persons?.toLocaleString() || 0}</span>
          </div>
          <div style={styles.statItem}>
            Patents: <span style={styles.statValue}>{graphStats.patents?.toLocaleString() || 0}</span>
          </div>
          <div style={styles.statItem}>
            Locations: <span style={styles.statValue}>{graphStats.locations?.toLocaleString() || 0}</span>
          </div>
          <div style={styles.statItem}>
            Events: <span style={styles.statValue}>{graphStats.events?.toLocaleString() || 0}</span>
          </div>
          <div style={styles.statItem}>
            Relationships: <span style={styles.statValue}>{graphStats.relationships?.toLocaleString() || 0}</span>
          </div>
        </div>
      )}

      {/* Content */}
      <div style={styles.content}>
        {activeSubTab === 'chat' && (
          <ChatInterface ticker={ticker} authToken={authToken} userEmail={userEmail} />
        )}
        {activeSubTab === 'intelligence' && (
          <CompetitiveIntelligence ticker={ticker} />
        )}
        {activeSubTab === 'cypher' && (
          <CypherConsole />
        )}
      </div>
    </div>
  );
}

// ============================================================================
// Chat Interface
// ============================================================================

function ChatInterface({ ticker, authToken, userEmail }) {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: `Hello! I'm CyberRisk Explorer, your AI assistant for analyzing cybersecurity companies. I can help you with:

• Company information and stock data
• Sentiment analysis from SEC filings
• Stock price forecasts
• Growth metrics and hiring trends
• Knowledge graph queries about company documents

What would you like to know about ${ticker} or other tracked companies?`
    }
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const [statusMessage, setStatusMessage] = useState(null);
  const [statusStep, setStatusStep] = useState(null);
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const sendMessage = async () => {
    if (!input.trim() || loading) return;

    const userMessage = input.trim();
    setInput('');
    setLoading(true);
    setStatusMessage(null);
    setStatusStep(null);

    // Add user message
    setMessages(prev => [...prev, { role: 'user', content: userMessage }]);

    try {
      // Use streaming endpoint for real-time status updates
      const response = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { 'Authorization': `Bearer ${authToken}` } : {})
        },
        body: JSON.stringify({
          message: userMessage,
          session_id: sessionId,
          user_email: userEmail
        })
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      // Read SSE stream
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || ''; // Keep incomplete line in buffer

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const eventData = JSON.parse(line.slice(6));

              if (eventData.type === 'status') {
                // Update status display
                setStatusMessage(eventData.message);
                setStatusStep(eventData.step);
              } else if (eventData.type === 'response') {
                // Final response received
                const data = eventData.data;
                if (data.session_id) {
                  setSessionId(data.session_id);
                }
                setMessages(prev => [...prev, {
                  role: 'assistant',
                  content: data.response || 'Sorry, I encountered an error.',
                  tools_used: data.tools_used
                }]);
                setStatusMessage(null);
                setStatusStep(null);
              } else if (eventData.type === 'error') {
                setMessages(prev => [...prev, {
                  role: 'assistant',
                  content: eventData.message || 'Sorry, I encountered an error.'
                }]);
                setStatusMessage(null);
                setStatusStep(null);
              }
            } catch (parseError) {
              console.warn('Failed to parse SSE event:', line);
            }
          }
        }
      }

    } catch (error) {
      console.error('Chat error:', error);
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: 'Sorry, I encountered an error connecting to the server. Please try again.'
      }]);
      setStatusMessage(null);
      setStatusStep(null);
    } finally {
      setLoading(false);
      setStatusMessage(null);
      setStatusStep(null);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const clearChat = () => {
    setMessages([{
      role: 'assistant',
      content: `Chat cleared. How can I help you with ${ticker}?`
    }]);
    setSessionId(null);
  };

  const styles = {
    container: {
      display: 'flex',
      flexDirection: 'column',
      height: '100%'
    },
    messages: {
      flex: 1,
      overflow: 'auto',
      padding: '16px',
      display: 'flex',
      flexDirection: 'column',
      gap: '16px'
    },
    message: (isUser) => ({
      display: 'flex',
      gap: '12px',
      alignItems: 'flex-start',
      flexDirection: isUser ? 'row-reverse' : 'row'
    }),
    avatar: (isUser) => ({
      width: '36px',
      height: '36px',
      borderRadius: '50%',
      background: isUser ? '#3c50e0' : '#10b981',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      color: '#fff',
      flexShrink: 0
    }),
    bubble: (isUser) => ({
      maxWidth: '70%',
      padding: '12px 16px',
      borderRadius: '12px',
      background: isUser ? '#3c50e0' : '#f1f5f9',
      color: isUser ? '#fff' : '#1e293b',
      whiteSpace: 'pre-wrap',
      lineHeight: '1.5',
      fontSize: '14px'
    }),
    toolsUsed: {
      marginTop: '8px',
      display: 'flex',
      gap: '6px',
      flexWrap: 'wrap'
    },
    toolBadge: {
      padding: '2px 8px',
      borderRadius: '4px',
      background: '#dbeafe',
      color: '#1d4ed8',
      fontSize: '11px',
      fontWeight: '500'
    },
    inputArea: {
      padding: '16px',
      borderTop: '1px solid #e2e8f0',
      background: '#fff'
    },
    inputRow: {
      display: 'flex',
      gap: '12px',
      alignItems: 'flex-end'
    },
    textarea: {
      flex: 1,
      padding: '12px 16px',
      border: '1px solid #e2e8f0',
      borderRadius: '12px',
      resize: 'none',
      fontSize: '14px',
      fontFamily: 'inherit',
      outline: 'none',
      minHeight: '44px',
      maxHeight: '120px'
    },
    sendButton: {
      padding: '12px',
      borderRadius: '12px',
      background: '#3c50e0',
      color: '#fff',
      border: 'none',
      cursor: 'pointer',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      opacity: loading ? 0.7 : 1
    },
    clearButton: {
      padding: '8px 12px',
      borderRadius: '8px',
      background: '#f1f5f9',
      color: '#64748b',
      border: 'none',
      cursor: 'pointer',
      display: 'flex',
      alignItems: 'center',
      gap: '6px',
      fontSize: '13px'
    },
    typing: {
      display: 'flex',
      gap: '4px',
      padding: '0'
    },
    typingDot: {
      width: '8px',
      height: '8px',
      borderRadius: '50%',
      background: '#94a3b8',
      animation: 'pulse 1.4s infinite ease-in-out'
    },
    statusContainer: {
      display: 'flex',
      flexDirection: 'column',
      gap: '8px',
      minWidth: '200px'
    },
    statusText: {
      fontSize: '13px',
      color: '#475569',
      display: 'flex',
      alignItems: 'center',
      gap: '8px'
    },
    progressBar: {
      height: '4px',
      background: '#e2e8f0',
      borderRadius: '2px',
      overflow: 'hidden'
    },
    progressFill: (step, total) => ({
      height: '100%',
      width: `${(step / total) * 100}%`,
      background: 'linear-gradient(90deg, #3b82f6, #8b5cf6)',
      borderRadius: '2px',
      transition: 'width 300ms ease'
    })
  };

  return (
    <div style={styles.container}>
      <div style={styles.messages}>
        {messages.map((msg, idx) => (
          <div key={idx} style={styles.message(msg.role === 'user')}>
            <div style={styles.avatar(msg.role === 'user')}>
              {msg.role === 'user' ? <Icons.User /> : <Icons.Bot />}
            </div>
            <div>
              <div style={styles.bubble(msg.role === 'user')}>
                {msg.content}
              </div>
              {msg.tools_used && msg.tools_used.length > 0 && (
                <div style={styles.toolsUsed}>
                  {msg.tools_used.map((tool, i) => (
                    <span key={i} style={styles.toolBadge}>{tool}</span>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}

        {loading && (
          <div style={styles.message(false)}>
            <div style={styles.avatar(false)}>
              <Icons.Bot />
            </div>
            <div style={styles.bubble(false)}>
              {statusMessage ? (
                <div style={styles.statusContainer}>
                  <div style={styles.statusText}>
                    <Icons.Spinner />
                    {statusMessage}
                  </div>
                  {statusStep && (
                    <div style={styles.progressBar}>
                      <div style={styles.progressFill(statusStep, 4)} />
                    </div>
                  )}
                </div>
              ) : (
                <div style={styles.typing}>
                  <div style={{ ...styles.typingDot, animationDelay: '0s' }} />
                  <div style={{ ...styles.typingDot, animationDelay: '0.2s' }} />
                  <div style={{ ...styles.typingDot, animationDelay: '0.4s' }} />
                </div>
              )}
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <div style={styles.inputArea}>
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '8px' }}>
          <button style={styles.clearButton} onClick={clearChat}>
            <Icons.Clear />
            Clear Chat
          </button>
        </div>
        <div style={styles.inputRow}>
          <textarea
            style={styles.textarea}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder={`Ask about ${ticker} or other companies...`}
            rows={1}
          />
          <button
            style={styles.sendButton}
            onClick={sendMessage}
            disabled={loading || !input.trim()}
          >
            <Icons.Send />
          </button>
        </div>
      </div>

      <style>{`
        @keyframes pulse {
          0%, 80%, 100% { transform: scale(0); }
          40% { transform: scale(1); }
        }
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}

// ============================================================================
// Competitive Intelligence (GDS Analytics)
// ============================================================================

function CompetitiveIntelligence({ ticker }) {
  const [marketLeaders, setMarketLeaders] = useState(null);
  const [marketSegments, setMarketSegments] = useState(null);
  const [similarCompanies, setSimilarCompanies] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedTicker, setSelectedTicker] = useState(ticker || 'CRWD');

  useEffect(() => {
    loadGDSData();
  }, []);

  useEffect(() => {
    if (selectedTicker) {
      loadSimilarCompanies(selectedTicker);
    }
  }, [selectedTicker]);

  const loadGDSData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [leadersRes, segmentsRes] = await Promise.all([
        fetch('/api/gds/centrality/pagerank?limit=15'),
        fetch('/api/gds/community/louvain')
      ]);

      const leadersData = await leadersRes.json();
      const segmentsData = await segmentsRes.json();

      if (leadersData.error) throw new Error(leadersData.error);
      if (segmentsData.error) throw new Error(segmentsData.error);

      setMarketLeaders(leadersData);
      setMarketSegments(segmentsData);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const loadSimilarCompanies = async (tickerSymbol) => {
    try {
      const res = await fetch(`/api/gds/similarity/company/${tickerSymbol}?top_k=8`);
      const data = await res.json();
      if (!data.error) {
        setSimilarCompanies(data);
      }
    } catch (err) {
      console.error('Error loading similar companies:', err);
    }
  };

  const styles = {
    container: {
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      overflow: 'auto',
      padding: '16px',
      gap: '20px'
    },
    grid: {
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(400px, 1fr))',
      gap: '20px'
    },
    card: {
      background: '#fff',
      borderRadius: '12px',
      border: '1px solid #e2e8f0',
      overflow: 'hidden'
    },
    cardHeader: {
      padding: '16px',
      borderBottom: '1px solid #e2e8f0',
      background: '#f8fafc'
    },
    cardTitle: {
      margin: 0,
      fontSize: '16px',
      fontWeight: '600',
      color: '#1e293b',
      display: 'flex',
      alignItems: 'center',
      gap: '8px'
    },
    cardSubtitle: {
      margin: '4px 0 0 0',
      fontSize: '13px',
      color: '#64748b'
    },
    cardBody: {
      padding: '16px',
      maxHeight: '350px',
      overflow: 'auto'
    },
    leaderRow: (index) => ({
      display: 'flex',
      alignItems: 'center',
      gap: '12px',
      padding: '10px 12px',
      borderRadius: '8px',
      background: index === 0 ? '#fef9c3' : index < 3 ? '#f0fdf4' : '#f8fafc',
      marginBottom: '8px',
      cursor: 'pointer',
      transition: 'background 150ms ease'
    }),
    rank: (index) => ({
      width: '28px',
      height: '28px',
      borderRadius: '50%',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontWeight: '700',
      fontSize: '13px',
      background: index === 0 ? '#eab308' : index < 3 ? '#22c55e' : '#94a3b8',
      color: '#fff'
    }),
    companyName: {
      flex: 1,
      fontWeight: '500',
      color: '#1e293b'
    },
    ticker: {
      fontSize: '12px',
      color: '#64748b',
      background: '#e2e8f0',
      padding: '2px 8px',
      borderRadius: '4px'
    },
    score: {
      fontSize: '14px',
      fontWeight: '600',
      color: '#0f766e'
    },
    segmentCard: {
      padding: '12px',
      borderRadius: '8px',
      background: '#f8fafc',
      marginBottom: '12px',
      border: '1px solid #e2e8f0'
    },
    segmentHeader: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      marginBottom: '8px'
    },
    segmentTitle: {
      fontWeight: '600',
      color: '#1e293b',
      fontSize: '14px'
    },
    segmentCount: {
      fontSize: '12px',
      color: '#64748b',
      background: '#e2e8f0',
      padding: '2px 8px',
      borderRadius: '12px'
    },
    companyChip: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: '4px',
      padding: '4px 10px',
      borderRadius: '16px',
      background: '#dbeafe',
      color: '#1e40af',
      fontSize: '12px',
      fontWeight: '500',
      margin: '2px'
    },
    similarRow: {
      display: 'flex',
      alignItems: 'center',
      gap: '12px',
      padding: '10px 12px',
      borderRadius: '8px',
      background: '#f8fafc',
      marginBottom: '8px'
    },
    similarBar: {
      height: '6px',
      borderRadius: '3px',
      background: '#e2e8f0',
      flex: 1,
      overflow: 'hidden'
    },
    similarFill: (score, max) => ({
      height: '100%',
      width: `${Math.min(100, (score / max) * 100)}%`,
      background: 'linear-gradient(90deg, #3b82f6, #8b5cf6)',
      borderRadius: '3px'
    }),
    selector: {
      padding: '8px 12px',
      borderRadius: '8px',
      border: '1px solid #e2e8f0',
      fontSize: '14px',
      background: '#fff',
      cursor: 'pointer'
    },
    loading: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '40px',
      color: '#64748b'
    },
    error: {
      padding: '20px',
      background: '#fef2f2',
      color: '#991b1b',
      borderRadius: '8px',
      textAlign: 'center'
    },
    refreshBtn: {
      padding: '8px 16px',
      borderRadius: '6px',
      border: 'none',
      background: '#3b82f6',
      color: '#fff',
      cursor: 'pointer',
      fontSize: '13px',
      fontWeight: '500'
    }
  };

  if (loading && !marketLeaders) {
    return (
      <div style={styles.loading}>
        <span>Loading competitive intelligence...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div style={styles.container}>
        <div style={styles.error}>
          <p><strong>Error loading GDS analytics:</strong></p>
          <p>{error}</p>
          <button style={styles.refreshBtn} onClick={loadGDSData}>Retry</button>
        </div>
      </div>
    );
  }

  const segmentColors = ['#3b82f6', '#8b5cf6', '#ec4899', '#f59e0b', '#10b981', '#6366f1'];

  return (
    <div style={styles.container}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: '20px', color: '#1e293b' }}>Competitive Intelligence</h2>
          <p style={{ margin: '4px 0 0 0', color: '#64748b', fontSize: '14px' }}>
            Graph-based analytics powered by Neo4j GDS
          </p>
        </div>
        <button style={styles.refreshBtn} onClick={loadGDSData}>
          Refresh Data
        </button>
      </div>

      {/* Grid */}
      <div style={styles.grid}>
        {/* Market Leaders */}
        <div style={styles.card}>
          <div style={styles.cardHeader}>
            <h3 style={styles.cardTitle}>
              <Icons.Chart />
              Market Leaders
            </h3>
            <p style={styles.cardSubtitle}>
              Ranked by PageRank centrality in competition network
            </p>
          </div>
          <div style={styles.cardBody}>
            {marketLeaders?.results?.map((leader, index) => (
              <div
                key={leader.ticker}
                style={styles.leaderRow(index)}
                onClick={() => setSelectedTicker(leader.ticker)}
              >
                <div style={styles.rank(index)}>{index + 1}</div>
                <span style={styles.companyName}>{leader.company}</span>
                <span style={styles.ticker}>{leader.ticker}</span>
                <span style={styles.score}>{leader.pagerank_score?.toFixed(2)}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Market Segments */}
        <div style={styles.card}>
          <div style={styles.cardHeader}>
            <h3 style={styles.cardTitle}>
              <Icons.Network />
              Market Segments
            </h3>
            <p style={styles.cardSubtitle}>
              Competitive clusters detected by Louvain community algorithm
            </p>
          </div>
          <div style={styles.cardBody}>
            {marketSegments?.segments?.map((segment, idx) => (
              <div key={segment.segment_id} style={styles.segmentCard}>
                <div style={styles.segmentHeader}>
                  <span style={{ ...styles.segmentTitle, color: segmentColors[idx % segmentColors.length] }}>
                    Segment {idx + 1}
                  </span>
                  <span style={styles.segmentCount}>{segment.company_count} companies</span>
                </div>
                <div>
                  {segment.companies?.slice(0, 8).map(c => (
                    <span
                      key={c.ticker}
                      style={{
                        ...styles.companyChip,
                        cursor: 'pointer',
                        background: selectedTicker === c.ticker ? '#1e40af' : '#dbeafe',
                        color: selectedTicker === c.ticker ? '#fff' : '#1e40af'
                      }}
                      onClick={() => setSelectedTicker(c.ticker)}
                    >
                      {c.ticker}
                    </span>
                  ))}
                  {segment.companies?.length > 8 && (
                    <span style={{ ...styles.companyChip, background: '#f1f5f9', color: '#64748b' }}>
                      +{segment.companies.length - 8} more
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Similar Companies */}
        <div style={{ ...styles.card, gridColumn: 'span 2' }}>
          <div style={styles.cardHeader}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <h3 style={styles.cardTitle}>
                  Similar Companies to {selectedTicker}
                </h3>
                <p style={styles.cardSubtitle}>
                  Based on shared competitors and document concepts
                </p>
              </div>
              <select
                style={styles.selector}
                value={selectedTicker}
                onChange={(e) => setSelectedTicker(e.target.value)}
              >
                {marketLeaders?.results?.map(l => (
                  <option key={l.ticker} value={l.ticker}>{l.ticker} - {l.company}</option>
                ))}
              </select>
            </div>
          </div>
          <div style={{ ...styles.cardBody, display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '8px' }}>
            {similarCompanies?.results?.map((sim) => {
              const maxScore = similarCompanies.results[0]?.similarity_score || 1;
              return (
                <div key={sim.ticker} style={styles.similarRow}>
                  <span style={{ width: '60px', fontWeight: '600', color: '#1e293b' }}>{sim.ticker}</span>
                  <div style={styles.similarBar}>
                    <div style={styles.similarFill(sim.similarity_score, maxScore)} />
                  </div>
                  <span style={{ fontSize: '12px', color: '#64748b', width: '100px', textAlign: 'right' }}>
                    {sim.shared_competitors} competitors, {sim.shared_concepts} concepts
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// Cypher Console
// ============================================================================

function CypherConsole() {
  const [query, setQuery] = useState('MATCH (o:Organization {tracked: true}) RETURN o.ticker, o.name LIMIT 10');
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  // eslint-disable-next-line no-unused-vars
  const [history, setHistory] = useState([]);
  const [viewMode, setViewMode] = useState('table'); // 'table' or 'json'

  const exampleQueries = [
    { label: 'Tracked Companies', query: 'MATCH (o:Organization {tracked: true}) RETURN o.ticker, o.name' },
    { label: 'Company Concepts', query: "MATCH (o:Organization {ticker: 'CRWD'})<-[:FILED_BY]-(d:Document)-[:DISCUSSES]->(c:Concept) RETURN c.name, c.category, count(d) as mentions ORDER BY mentions DESC LIMIT 20" },
    { label: 'Persons Mentioned', query: 'MATCH (d:Document)-[:MENTIONS]->(p:Person) RETURN p.name, count(d) as mentions ORDER BY mentions DESC LIMIT 20' },
    { label: 'Graph Stats', query: 'MATCH (n) RETURN labels(n)[0] as type, count(n) as count ORDER BY count DESC' }
  ];

  const executeQuery = async () => {
    if (!query.trim()) return;

    setLoading(true);
    setError(null);
    setResults(null);

    try {
      const response = await fetch('/api/cypher/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: query.trim() })
      });

      const data = await response.json();

      if (data.error) {
        setError(data.error);
      } else {
        setResults(data);
        // Add to history
        setHistory(prev => [query, ...prev.filter(q => q !== query)].slice(0, 10));
      }
    } catch (err) {
      setError('Failed to execute query');
    } finally {
      setLoading(false);
    }
  };

  const styles = {
    container: {
      height: '100%',
      display: 'flex',
      flexDirection: 'column',
      padding: '16px'
    },
    editor: {
      marginBottom: '16px'
    },
    label: {
      fontSize: '13px',
      fontWeight: '500',
      color: '#64748b',
      marginBottom: '8px',
      display: 'block'
    },
    textarea: {
      width: '100%',
      minHeight: '100px',
      padding: '12px',
      border: '1px solid #e2e8f0',
      borderRadius: '8px',
      fontFamily: 'monospace',
      fontSize: '13px',
      resize: 'vertical',
      outline: 'none'
    },
    buttonRow: {
      display: 'flex',
      gap: '8px',
      marginTop: '12px'
    },
    executeButton: {
      display: 'flex',
      alignItems: 'center',
      gap: '6px',
      padding: '10px 16px',
      borderRadius: '8px',
      background: '#3c50e0',
      color: '#fff',
      border: 'none',
      cursor: 'pointer',
      fontSize: '14px',
      fontWeight: '500'
    },
    clearButton: {
      padding: '10px 16px',
      borderRadius: '8px',
      background: '#f1f5f9',
      color: '#64748b',
      border: 'none',
      cursor: 'pointer',
      fontSize: '14px'
    },
    examples: {
      display: 'flex',
      gap: '8px',
      flexWrap: 'wrap',
      marginBottom: '16px'
    },
    exampleButton: {
      padding: '6px 12px',
      borderRadius: '6px',
      background: '#f1f5f9',
      border: '1px solid #e2e8f0',
      cursor: 'pointer',
      fontSize: '12px',
      color: '#64748b'
    },
    results: {
      flex: 1,
      overflow: 'auto',
      background: '#f8fafc',
      borderRadius: '8px',
      border: '1px solid #e2e8f0'
    },
    resultHeader: {
      padding: '12px 16px',
      background: '#f1f5f9',
      borderBottom: '1px solid #e2e8f0',
      fontSize: '13px',
      color: '#64748b'
    },
    table: {
      width: '100%',
      borderCollapse: 'collapse'
    },
    th: {
      padding: '10px 12px',
      textAlign: 'left',
      borderBottom: '1px solid #e2e8f0',
      background: '#f8fafc',
      fontSize: '12px',
      fontWeight: '600',
      color: '#64748b'
    },
    td: {
      padding: '10px 12px',
      borderBottom: '1px solid #e2e8f0',
      fontSize: '13px',
      color: '#1e293b'
    },
    error: {
      padding: '16px',
      color: '#dc2626',
      background: '#fef2f2',
      borderRadius: '8px',
      fontSize: '14px'
    },
    empty: {
      padding: '32px',
      textAlign: 'center',
      color: '#64748b'
    },
    viewToggle: {
      display: 'flex',
      gap: '4px',
      marginLeft: 'auto'
    },
    viewButton: (active) => ({
      display: 'flex',
      alignItems: 'center',
      gap: '4px',
      padding: '6px 12px',
      borderRadius: '6px',
      background: active ? '#3c50e0' : '#f1f5f9',
      color: active ? '#fff' : '#64748b',
      border: 'none',
      cursor: 'pointer',
      fontSize: '12px',
      fontWeight: '500'
    }),
    jsonView: {
      padding: '16px',
      fontFamily: 'monospace',
      fontSize: '12px',
      whiteSpace: 'pre-wrap',
      wordBreak: 'break-word',
      background: '#1e293b',
      color: '#e2e8f0',
      borderRadius: '0 0 8px 8px',
      overflow: 'auto',
      maxHeight: '400px'
    }
  };

  return (
    <div style={styles.container}>
      <div style={styles.editor}>
        <label style={styles.label}>Cypher Query (read-only)</label>
        <textarea
          style={styles.textarea}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Enter Cypher query..."
        />
        <div style={styles.buttonRow}>
          <button
            style={styles.executeButton}
            onClick={executeQuery}
            disabled={loading}
          >
            <Icons.Play />
            {loading ? 'Executing...' : 'Execute'}
          </button>
          <button
            style={styles.clearButton}
            onClick={() => { setQuery(''); setResults(null); setError(null); }}
          >
            Clear
          </button>
        </div>
      </div>

      <div style={styles.examples}>
        <span style={{ fontSize: '12px', color: '#64748b', marginRight: '8px' }}>Examples:</span>
        {exampleQueries.map((eq, idx) => (
          <button
            key={idx}
            style={styles.exampleButton}
            onClick={() => setQuery(eq.query)}
          >
            {eq.label}
          </button>
        ))}
      </div>

      <div style={styles.results}>
        {error && <div style={styles.error}>{error}</div>}

        {results && !error && (
          <>
            <div style={{ ...styles.resultHeader, display: 'flex', alignItems: 'center' }}>
              <span>{results.count} row{results.count !== 1 ? 's' : ''} returned</span>
              <div style={styles.viewToggle}>
                <button
                  style={styles.viewButton(viewMode === 'table')}
                  onClick={() => setViewMode('table')}
                >
                  <Icons.Table /> Table
                </button>
                <button
                  style={styles.viewButton(viewMode === 'json')}
                  onClick={() => setViewMode('json')}
                >
                  <Icons.Code /> JSON
                </button>
              </div>
            </div>

            {viewMode === 'table' ? (
              results.records?.length > 0 ? (
                <table style={styles.table}>
                  <thead>
                    <tr>
                      {results.columns?.map((col, idx) => (
                        <th key={idx} style={styles.th}>{col}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {results.records.map((row, rowIdx) => (
                      <tr key={rowIdx}>
                        {results.columns?.map((col, colIdx) => (
                          <td key={colIdx} style={styles.td}>
                            {typeof row[col] === 'object'
                              ? JSON.stringify(row[col])
                              : String(row[col] ?? '')}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div style={styles.empty}>No results returned</div>
              )
            ) : (
              <div style={styles.jsonView}>
                {JSON.stringify(results, null, 2)}
              </div>
            )}
          </>
        )}

        {!results && !error && (
          <div style={styles.empty}>
            <Icons.Terminal />
            <p style={{ marginTop: '12px' }}>Execute a query to see results</p>
          </div>
        )}
      </div>
    </div>
  );
}

export default GraphRAGAssistant;
