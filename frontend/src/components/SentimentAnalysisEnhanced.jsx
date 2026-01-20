import React, { useState, useEffect } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';

function SentimentAnalysis({ ticker: propTicker }) {
  // Use the prop ticker if provided, otherwise manage our own state
  const [internalCompany, setInternalCompany] = useState('');
  const selectedCompany = propTicker || internalCompany;
  const setSelectedCompany = propTicker ? () => {} : setInternalCompany; // No-op if using prop

  const [companies, setCompanies] = useState([]);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [sentimentData, setSentimentData] = useState(null);
  const [error, setError] = useState(null);
  const [dateRange, setDateRange] = useState({ start: '', end: '' });
  const [activeView, setActiveView] = useState('overview'); // overview, entities, phrases, timeline
  const [fromCache, setFromCache] = useState(false);

  // Fetch companies on mount (only needed if no prop ticker provided)
  useEffect(() => {
    const fetchCompanies = async () => {
      try {
        const response = await fetch('/api/companies');
        const data = await response.json();
        setCompanies(data || []);
        // Only set initial company if no prop ticker provided
        if (!propTicker && data && data.length > 0) {
          setInternalCompany(data[0].ticker);
        }
      } catch (error) {
        console.error('Error fetching companies:', error);
      }
    };
    fetchCompanies();
  }, [propTicker]);

  // Fetch sentiment data when company changes
  useEffect(() => {
    if (selectedCompany) {
      fetchSentimentData(selectedCompany, false);
    }
  }, [selectedCompany]);

  const fetchSentimentData = async (ticker, forceRefresh = false) => {
    setLoading(true);
    setError(null);
    if (forceRefresh) setRefreshing(true);

    try {
      const refreshParam = forceRefresh ? '?refresh=true' : '';
      const response = await fetch(`/api/sentiment/${ticker}${refreshParam}`);

      if (!response.ok) {
        throw new Error('Failed to fetch sentiment data');
      }

      const data = await response.json();
      setSentimentData(data);
      setFromCache(data.from_cache || false);

      // Set default date range
      if (data.timeline && data.timeline.length > 0) {
        const dates = data.timeline.map(t => t.date).filter(d => d);
        if (dates.length > 0) {
          setDateRange({
            start: dates[0],
            end: dates[dates.length - 1]
          });
        }
      }
    } catch (error) {
      console.error('Error fetching sentiment:', error);
      setError(error.message);
      setSentimentData(null);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const handleRefresh = () => {
    if (selectedCompany) {
      fetchSentimentData(selectedCompany, true);
    }
  };

  const exportToCSV = () => {
    if (!sentimentData) return;

    const csvRows = [];

    // Header
    csvRows.push(['Ticker', selectedCompany]);
    csvRows.push(['Export Date', new Date().toISOString()]);
    csvRows.push([]);

    // Overall Sentiment
    csvRows.push(['Overall Sentiment Analysis']);
    csvRows.push(['Metric', 'Value']);
    csvRows.push(['Positive', `${(sentimentData.overall.sentiment.Positive * 100).toFixed(2)}%`]);
    csvRows.push(['Negative', `${(sentimentData.overall.sentiment.Negative * 100).toFixed(2)}%`]);
    csvRows.push(['Neutral', `${(sentimentData.overall.sentiment.Neutral * 100).toFixed(2)}%`]);
    csvRows.push(['Mixed', `${(sentimentData.overall.sentiment.Mixed * 100).toFixed(2)}%`]);
    csvRows.push([]);

    // Word Frequency
    csvRows.push(['Top Keywords']);
    csvRows.push(['Rank', 'Word', 'Count']);
    sentimentData.wordFrequency.slice(0, 20).forEach((word, i) => {
      csvRows.push([i + 1, word.text, word.count]);
    });
    csvRows.push([]);

    // Timeline
    csvRows.push(['Sentiment Timeline']);
    csvRows.push(['Date', 'Document Type', 'Positive %', 'Negative %', 'Neutral %']);
    sentimentData.timeline.forEach(item => {
      csvRows.push([
        item.date,
        item.type,
        (item.sentiment.Positive * 100).toFixed(2),
        (item.sentiment.Negative * 100).toFixed(2),
        (item.sentiment.Neutral * 100).toFixed(2)
      ]);
    });

    // Create CSV
    const csvContent = csvRows.map(row => row.join(',')).join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${selectedCompany}_sentiment_analysis_${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
    window.URL.revokeObjectURL(url);
  };

  const filterTimeline = () => {
    if (!sentimentData || !sentimentData.timeline) return [];

    return sentimentData.timeline.filter(item => {
      if (!dateRange.start && !dateRange.end) return true;

      const itemDate = new Date(item.date);
      const startDate = dateRange.start ? new Date(dateRange.start) : null;
      const endDate = dateRange.end ? new Date(dateRange.end) : null;

      if (startDate && itemDate < startDate) return false;
      if (endDate && itemDate > endDate) return false;

      return true;
    });
  };

  return (
    <div style={{ padding: '20px' }}>
      {/* Header with Actions */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: '20px',
        flexWrap: 'wrap',
        gap: '15px'
      }}>
        <h2 style={{ margin: 0, color: '#2c3e50' }}>
          Sentiment Analysis
        </h2>

        {sentimentData && !loading && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            {fromCache && (
              <span style={{ fontSize: '12px', color: '#28a745' }}>
                Loaded from cache
              </span>
            )}
            <button
              onClick={exportToCSV}
              style={{
                padding: '8px 16px',
                background: '#6c757d',
                color: 'white',
                border: 'none',
                borderRadius: '4px',
                cursor: 'pointer',
                fontSize: '14px',
                fontWeight: '500'
              }}
            >
              Export CSV
            </button>
            <button
              onClick={handleRefresh}
              disabled={refreshing}
              style={{
                padding: '8px 16px',
                background: refreshing ? '#ccc' : '#28a745',
                color: 'white',
                border: 'none',
                borderRadius: '4px',
                cursor: refreshing ? 'not-allowed' : 'pointer',
                fontSize: '14px',
                fontWeight: '500'
              }}
            >
              {refreshing ? 'Refreshing...' : 'Refresh Analysis'}
            </button>
          </div>
        )}
      </div>

      {/* Company Selector - only show if no ticker prop provided */}
      {!propTicker && (
        <div style={{ marginBottom: '30px' }}>
          <label style={{
            display: 'block',
            marginBottom: '10px',
            fontWeight: 'bold',
            fontSize: '14px'
          }}>
            Select Company:
          </label>
          <select
            value={selectedCompany}
            onChange={(e) => setSelectedCompany(e.target.value)}
            style={{
              padding: '10px 12px',
              border: '1px solid #ddd',
              borderRadius: '4px',
              fontSize: '16px',
              maxWidth: '400px',
              width: '100%'
            }}
          >
            {companies.map((company) => (
              <option key={company.ticker} value={company.ticker}>
                {company.ticker} - {company.name}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Loading State */}
      {loading && (
        <div style={{
          textAlign: 'center',
          padding: '40px',
          color: '#666'
        }}>
          <div style={{ fontSize: '18px', marginBottom: '10px' }}>
            Analyzing documents with AWS Comprehend...
          </div>
          <div style={{ fontSize: '14px', color: '#999' }}>
            This may take a moment
          </div>
        </div>
      )}

      {/* Error State */}
      {error && !loading && (
        <div style={{
          background: '#f8d7da',
          color: '#721c24',
          padding: '15px',
          borderRadius: '4px',
          marginBottom: '20px'
        }}>
          Error: {error}
        </div>
      )}

      {/* Main Content */}
      {!loading && !error && sentimentData && (
        <div>
          {/* View Tabs */}
          <div style={{
            display: 'flex',
            gap: '5px',
            marginBottom: '25px',
            borderBottom: '2px solid #e9ecef',
            flexWrap: 'wrap'
          }}>
            <ViewTab
              active={activeView === 'overview'}
              onClick={() => setActiveView('overview')}
            >
              Overview
            </ViewTab>
            <ViewTab
              active={activeView === 'entities'}
              onClick={() => setActiveView('entities')}
            >
              Targeted Sentiment
            </ViewTab>
            <ViewTab
              active={activeView === 'timeline'}
              onClick={() => setActiveView('timeline')}
            >
              Timeline
            </ViewTab>
          </div>

          {/* Overview View */}
          {activeView === 'overview' && (
            <>
              <SentimentOverviewCard data={sentimentData.overall} />
              <WordFrequencySection
                words={sentimentData.wordFrequency}
                ticker={selectedCompany}
              />
              <DocumentTypeComparison
                comparison={sentimentData.documentComparison}
                ticker={selectedCompany}
              />
            </>
          )}

          {/* Entities & Phrases View */}
          {activeView === 'entities' && (
            <>
              <TargetedSentimentSection
                targetedSentiment={sentimentData.targetedSentiment}
                ticker={selectedCompany}
              />
            </>
          )}

          {/* Timeline View */}
          {activeView === 'timeline' && (
            <>
              {/* Date Range Filter */}
              <DateRangeFilter
                dateRange={dateRange}
                setDateRange={setDateRange}
              />
              <SentimentTimelineChart
                timeline={filterTimeline()}
                ticker={selectedCompany}
              />
              <SentimentTimelineTable
                timeline={filterTimeline()}
                ticker={selectedCompany}
              />
            </>
          )}
        </div>
      )}

      {/* No Data State */}
      {!loading && !error && !sentimentData && selectedCompany && (
        <NotAvailablePlaceholder
          message="No documents available for sentiment analysis"
          subtitle="Please scrape documents for this company first"
        />
      )}
    </div>
  );
}

// View Tab Component
function ViewTab({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      style={{
        background: 'none',
        border: 'none',
        padding: '12px 20px',
        fontSize: '15px',
        cursor: 'pointer',
        color: active ? '#007bff' : '#6c757d',
        borderBottom: active ? '3px solid #007bff' : '3px solid transparent',
        fontWeight: active ? 'bold' : 'normal',
        transition: 'all 0.3s'
      }}
    >
      {children}
    </button>
  );
}

// Date Range Filter Component
function DateRangeFilter({ dateRange, setDateRange }) {
  return (
    <div style={{
      background: '#f8f9fa',
      padding: '15px',
      borderRadius: '8px',
      marginBottom: '20px'
    }}>
      <div style={{ fontWeight: 'bold', marginBottom: '10px' }}>
        Filter by Date Range:
      </div>
      <div style={{ display: 'flex', gap: '15px', flexWrap: 'wrap' }}>
        <div>
          <label style={{ fontSize: '12px', color: '#6c757d' }}>Start Date:</label>
          <input
            type="date"
            value={dateRange.start}
            onChange={(e) => setDateRange({ ...dateRange, start: e.target.value })}
            style={{
              display: 'block',
              padding: '8px',
              border: '1px solid #ddd',
              borderRadius: '4px',
              marginTop: '5px'
            }}
          />
        </div>
        <div>
          <label style={{ fontSize: '12px', color: '#6c757d' }}>End Date:</label>
          <input
            type="date"
            value={dateRange.end}
            onChange={(e) => setDateRange({ ...dateRange, end: e.target.value })}
            style={{
              display: 'block',
              padding: '8px',
              border: '1px solid #ddd',
              borderRadius: '4px',
              marginTop: '5px'
            }}
          />
        </div>
        <div style={{ display: 'flex', alignItems: 'flex-end' }}>
          <button
            onClick={() => setDateRange({ start: '', end: '' })}
            style={{
              padding: '8px 12px',
              background: '#6c757d',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '12px'
            }}
          >
            Clear Filter
          </button>
        </div>
      </div>
    </div>
  );
}

// Sentiment Timeline Chart Component
function SentimentTimelineChart({ timeline, ticker }) {
  if (!timeline || timeline.length === 0) {
    return <NotAvailablePlaceholder message="No timeline data available" />;
  }

  // Prepare data for chart
  const chartData = timeline.map(item => ({
    date: new Date(item.date).toLocaleDateString('en-US', { month: 'short', year: '2-digit' }),
    Positive: (item.sentiment.Positive * 100).toFixed(1),
    Negative: (item.sentiment.Negative * 100).toFixed(1),
    Neutral: (item.sentiment.Neutral * 100).toFixed(1),
    type: item.type
  }));

  return (
    <div style={{
      background: 'white',
      border: '1px solid #dee2e6',
      borderRadius: '8px',
      padding: '25px',
      marginBottom: '30px',
      boxShadow: '0 2px 4px rgba(0,0,0,0.05)'
    }}>
      <h3 style={{ marginTop: 0, marginBottom: '20px', color: '#2c3e50' }}>
        Sentiment Trend Over Time - {ticker}
      </h3>

      <ResponsiveContainer width="100%" height={400}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="date" />
          <YAxis label={{ value: 'Sentiment (%)', angle: -90, position: 'insideLeft' }} />
          <Tooltip />
          <Legend />
          <Line
            type="monotone"
            dataKey="Positive"
            stroke="#28a745"
            strokeWidth={2}
            dot={{ r: 4 }}
          />
          <Line
            type="monotone"
            dataKey="Negative"
            stroke="#dc3545"
            strokeWidth={2}
            dot={{ r: 4 }}
          />
          <Line
            type="monotone"
            dataKey="Neutral"
            stroke="#6c757d"
            strokeWidth={2}
            dot={{ r: 4 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// Targeted Sentiment Section Component
function TargetedSentimentSection({ targetedSentiment, ticker }) {
  if (!targetedSentiment || targetedSentiment.length === 0) {
    return <NotAvailablePlaceholder message="Targeted sentiment data not available" />;
  }

  const getSentimentColor = (sentiment) => {
    switch (sentiment) {
      case 'Positive': return '#28a745';
      case 'Negative': return '#dc3545';
      case 'Mixed': return '#ffc107';
      default: return '#6c757d';
    }
  };

  const getSentimentEmoji = (sentiment) => {
    switch (sentiment) {
      case 'Positive': return '+';
      case 'Negative': return '-';
      case 'Mixed': return '~';
      default: return '-';
    }
  };

  // Calculate stats
  const positiveCount = targetedSentiment.filter(e => e.dominant_sentiment === 'Positive').length;
  const negativeCount = targetedSentiment.filter(e => e.dominant_sentiment === 'Negative').length;
  const neutralCount = targetedSentiment.filter(e => e.dominant_sentiment === 'Neutral').length;
  const mixedCount = targetedSentiment.filter(e => e.dominant_sentiment === 'Mixed').length;
  const total = targetedSentiment.length;

  return (
    <div>
      <h3 style={{ marginBottom: '10px', color: '#2c3e50' }}>
        AWS Comprehend Targeted Sentiment Analysis - {ticker}
      </h3>
      <p style={{ color: '#6c757d', fontSize: '14px', marginBottom: '25px', lineHeight: '1.6' }}>
        Identifies specific entities (people, products, organizations) and determines sentiment toward each one individually.
        <br />
        <strong>Example:</strong> "I loved the burger, but the service was slow" → burger: Positive, service: Negative
      </p>

      {/* Sentiment Distribution */}
      <div style={{
        background: '#f8f9fa',
        padding: '20px',
        borderRadius: '8px',
        marginBottom: '25px',
        border: '1px solid #dee2e6'
      }}>
        <h4 style={{ marginTop: 0, marginBottom: '15px', color: '#2c3e50' }}>
          Sentiment Distribution
        </h4>
        <div style={{ display: 'flex', gap: '15px', flexWrap: 'wrap', justifyContent: 'space-around' }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '32px', fontWeight: 'bold', color: '#28a745' }}>
              {positiveCount}
            </div>
            <div style={{ fontSize: '12px', color: '#6c757d' }}>
              Positive ({total > 0 ? ((positiveCount / total) * 100).toFixed(0) : 0}%)
            </div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '32px', fontWeight: 'bold', color: '#dc3545' }}>
              {negativeCount}
            </div>
            <div style={{ fontSize: '12px', color: '#6c757d' }}>
              Negative ({total > 0 ? ((negativeCount / total) * 100).toFixed(0) : 0}%)
            </div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '32px', fontWeight: 'bold', color: '#ffc107' }}>
              {mixedCount}
            </div>
            <div style={{ fontSize: '12px', color: '#6c757d' }}>
              Mixed ({total > 0 ? ((mixedCount / total) * 100).toFixed(0) : 0}%)
            </div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '32px', fontWeight: 'bold', color: '#6c757d' }}>
              {neutralCount}
            </div>
            <div style={{ fontSize: '12px', color: '#6c757d' }}>
              Neutral ({total > 0 ? ((neutralCount / total) * 100).toFixed(0) : 0}%)
            </div>
          </div>
        </div>
      </div>

      {/* Entity Table */}
      <div style={{
        background: 'white',
        border: '1px solid #dee2e6',
        borderRadius: '8px',
        padding: '25px',
        boxShadow: '0 2px 4px rgba(0,0,0,0.05)'
      }}>
        <h4 style={{ marginTop: 0, marginBottom: '20px', color: '#2c3e50' }}>
          Entities with Sentiment Analysis
        </h4>

        <div style={{ overflowX: 'auto' }}>
          <table style={{
            width: '100%',
            borderCollapse: 'collapse',
            minWidth: '700px'
          }}>
            <thead>
              <tr style={{ backgroundColor: '#f8f9fa', borderBottom: '2px solid #dee2e6' }}>
                <th style={{ padding: '12px', textAlign: 'left', fontWeight: 'bold' }}>Rank</th>
                <th style={{ padding: '12px', textAlign: 'left', fontWeight: 'bold' }}>Entity</th>
                <th style={{ padding: '12px', textAlign: 'left', fontWeight: 'bold' }}>Type</th>
                <th style={{ padding: '12px', textAlign: 'center', fontWeight: 'bold' }}>Sentiment</th>
                <th style={{ padding: '12px', textAlign: 'right', fontWeight: 'bold' }}>Confidence</th>
                <th style={{ padding: '12px', textAlign: 'right', fontWeight: 'bold' }}>Mentions</th>
              </tr>
            </thead>
            <tbody>
              {targetedSentiment.map((entity, i) => {
                const sentimentColor = getSentimentColor(entity.dominant_sentiment);
                const sentimentEmoji = getSentimentEmoji(entity.dominant_sentiment);

                return (
                  <tr
                    key={i}
                    style={{
                      borderBottom: '1px solid #dee2e6',
                      backgroundColor: i % 2 === 0 ? '#f8f9fa' : 'white'
                    }}
                  >
                    <td style={{ padding: '12px', fontWeight: 'bold', color: '#7f8c8d' }}>
                      {i + 1}
                    </td>
                    <td style={{ padding: '12px', fontWeight: '600', fontSize: '14px' }}>
                      {entity.entity}
                    </td>
                    <td style={{ padding: '12px' }}>
                      <span style={{
                        padding: '4px 8px',
                        borderRadius: '4px',
                        fontSize: '11px',
                        fontWeight: '600',
                        background: '#e9ecef',
                        color: '#495057'
                      }}>
                        {Array.isArray(entity.types) ? entity.types.join(', ') : entity.types}
                      </span>
                    </td>
                    <td style={{ padding: '12px', textAlign: 'center' }}>
                      <span style={{
                        padding: '6px 12px',
                        borderRadius: '4px',
                        fontSize: '13px',
                        fontWeight: 'bold',
                        background: sentimentColor + '20',
                        color: sentimentColor,
                        display: 'inline-block'
                      }}>
                        {sentimentEmoji} {entity.dominant_sentiment}
                      </span>
                    </td>
                    <td style={{ padding: '12px', textAlign: 'right', fontWeight: '500' }}>
                      {(entity.sentiment_score * 100).toFixed(1)}%
                    </td>
                    <td style={{ padding: '12px', textAlign: 'right' }}>
                      <span style={{
                        padding: '4px 10px',
                        borderRadius: '12px',
                        fontSize: '12px',
                        fontWeight: '600',
                        background: '#007bff',
                        color: 'white'
                      }}>
                        {entity.mention_count}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Key Insights */}
        <div style={{
          marginTop: '25px',
          padding: '15px',
          background: '#fff3cd',
          border: '1px solid #ffc107',
          borderRadius: '6px'
        }}>
          <div style={{ fontWeight: 'bold', marginBottom: '10px', color: '#856404' }}>
            ✨ Key Insights:
          </div>
          <ul style={{ margin: 0, paddingLeft: '20px', color: '#856404', fontSize: '14px', lineHeight: '1.8' }}>
            {targetedSentiment.slice(0, 5).map((entity, i) => (
              <li key={i}>
                <strong>{entity.entity}</strong>: {entity.dominant_sentiment} ({entity.mention_count} mentions across transcripts)
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

// Entities Section Component (OLD - Kept for backwards compatibility)
// eslint-disable-next-line no-unused-vars
function EntitiesSection({ entities, ticker }) {
  if (!entities) {
    return <NotAvailablePlaceholder message="Entity data not available" />;
  }

  return (
    <div>
      <h3 style={{ marginBottom: '20px', color: '#2c3e50' }}>
        Named Entities Mentioned - {ticker}
      </h3>
      <p style={{ color: '#6c757d', fontSize: '14px', marginBottom: '25px' }}>
        Organizations, people, products, and locations identified using AWS Comprehend
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '20px' }}>
        {/* Organizations */}
        <EntityCard
          title="Organizations"
          icon="🏢"
          entities={entities.organizations}
          color="#007bff"
        />

        {/* People */}
        <EntityCard
          title="People"
          icon="👤"
          entities={entities.people}
          color="#28a745"
        />

        {/* Commercial Items */}
        <EntityCard
          title="Products & Technologies"
          icon="💻"
          entities={entities.commercialItems}
          color="#ffc107"
        />

        {/* Locations */}
        <EntityCard
          title="Locations"
          icon="📍"
          entities={entities.locations}
          color="#dc3545"
        />
      </div>
    </div>
  );
}

// Entity Card Component
function EntityCard({ title, icon, entities, color }) {
  if (!entities || entities.length === 0) {
    return (
      <div style={{
        background: '#f8f9fa',
        border: '1px solid #dee2e6',
        borderRadius: '8px',
        padding: '20px'
      }}>
        <h4 style={{ marginTop: 0, color: color }}>
          {icon} {title}
        </h4>
        <p style={{ fontSize: '14px', color: '#6c757d' }}>No entities found</p>
      </div>
    );
  }

  return (
    <div style={{
      background: 'white',
      border: `2px solid ${color}`,
      borderRadius: '8px',
      padding: '20px',
      boxShadow: '0 2px 4px rgba(0,0,0,0.05)'
    }}>
      <h4 style={{ marginTop: 0, color, marginBottom: '15px' }}>
        {icon} {title}
      </h4>
      <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
        {entities.map((entity, i) => (
          <div
            key={i}
            style={{
              padding: '8px 0',
              borderBottom: i < entities.length - 1 ? '1px solid #e9ecef' : 'none',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center'
            }}
          >
            <span style={{ fontWeight: '500', fontSize: '14px' }}>{entity.text}</span>
            <span style={{
              fontSize: '12px',
              color: '#6c757d',
              background: '#f8f9fa',
              padding: '2px 8px',
              borderRadius: '12px'
            }}>
              {entity.count}x
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// Key Phrases Section Component
// eslint-disable-next-line no-unused-vars
function KeyPhrasesSection({ phrases, ticker }) {
  if (!phrases || phrases.length === 0) {
    return <NotAvailablePlaceholder message="Key phrases not available" />;
  }

  return (
    <div style={{
      background: 'white',
      border: '1px solid #dee2e6',
      borderRadius: '8px',
      padding: '25px',
      marginTop: '30px',
      boxShadow: '0 2px 4px rgba(0,0,0,0.05)'
    }}>
      <h3 style={{ marginTop: 0, marginBottom: '15px', color: '#2c3e50' }}>
        Key Phrases - {ticker}
      </h3>
      <p style={{ color: '#6c757d', fontSize: '14px', marginBottom: '20px' }}>
        Important multi-word expressions extracted using AWS Comprehend
      </p>

      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
        gap: '10px'
      }}>
        {phrases.map((phrase, i) => (
          <div
            key={i}
            style={{
              padding: '10px 15px',
              background: `rgba(0, 123, 255, ${Math.max(0.1, phrase.count / phrases[0].count)})`,
              color: phrase.count > phrases[0].count / 2 ? 'white' : '#084298',
              borderRadius: '4px',
              fontSize: '14px',
              fontWeight: '500',
              textAlign: 'center'
            }}
          >
            {phrase.text}
            <span style={{
              display: 'block',
              fontSize: '11px',
              marginTop: '4px',
              opacity: 0.8
            }}>
              {phrase.count}x
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// Sentiment Timeline Table Component (from previous implementation)
function SentimentTimelineTable({ timeline, ticker }) {
  if (!timeline || timeline.length === 0) {
    return <NotAvailablePlaceholder message="Sentiment timeline not available" />;
  }

  return (
    <div style={{
      background: 'white',
      border: '1px solid #dee2e6',
      borderRadius: '8px',
      padding: '25px',
      marginBottom: '30px',
      boxShadow: '0 2px 4px rgba(0,0,0,0.05)'
    }}>
      <h3 style={{ marginTop: 0, marginBottom: '15px', color: '#2c3e50' }}>
        Document-Level Sentiment Details - {ticker}
      </h3>

      <div style={{ overflowX: 'auto' }}>
        <table style={{
          width: '100%',
          borderCollapse: 'collapse',
          minWidth: '700px'
        }}>
          <thead>
            <tr style={{ backgroundColor: '#f8f9fa', borderBottom: '2px solid #dee2e6' }}>
              <th style={{ padding: '12px', textAlign: 'left', fontWeight: 'bold' }}>Date</th>
              <th style={{ padding: '12px', textAlign: 'left', fontWeight: 'bold' }}>Document Type</th>
              <th style={{ padding: '12px', textAlign: 'center', fontWeight: 'bold' }}>Sentiment</th>
              <th style={{ padding: '12px', textAlign: 'right', fontWeight: 'bold' }}>Positive</th>
              <th style={{ padding: '12px', textAlign: 'right', fontWeight: 'bold' }}>Negative</th>
              <th style={{ padding: '12px', textAlign: 'right', fontWeight: 'bold' }}>Neutral</th>
            </tr>
          </thead>
          <tbody>
            {timeline.map((item, i) => {
              const sentiment = item.sentiment;
              const dominantSentiment = getDominantSentiment(sentiment);

              return (
                <tr
                  key={i}
                  style={{
                    borderBottom: '1px solid #dee2e6',
                    backgroundColor: i % 2 === 0 ? '#f8f9fa' : 'white'
                  }}
                >
                  <td style={{ padding: '12px' }}>
                    {new Date(item.date).toLocaleDateString()}
                  </td>
                  <td style={{ padding: '12px' }}>
                    <span style={{
                      padding: '4px 8px',
                      borderRadius: '4px',
                      fontSize: '12px',
                      fontWeight: 'bold',
                      background: item.type.includes('10-') ? '#cfe2ff' : '#d1e7dd',
                      color: item.type.includes('10-') ? '#084298' : '#0f5132'
                    }}>
                      {item.type}
                    </span>
                  </td>
                  <td style={{ padding: '12px', textAlign: 'center' }}>
                    <span style={{
                      padding: '4px 12px',
                      borderRadius: '4px',
                      fontSize: '12px',
                      fontWeight: 'bold',
                      background: dominantSentiment.color + '20',
                      color: dominantSentiment.color
                    }}>
                      {dominantSentiment.label}
                    </span>
                  </td>
                  <td style={{ padding: '12px', textAlign: 'right', color: '#28a745' }}>
                    {(sentiment.Positive * 100).toFixed(1)}%
                  </td>
                  <td style={{ padding: '12px', textAlign: 'right', color: '#dc3545' }}>
                    {(sentiment.Negative * 100).toFixed(1)}%
                  </td>
                  <td style={{ padding: '12px', textAlign: 'right', color: '#6c757d' }}>
                    {(sentiment.Neutral * 100).toFixed(1)}%
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// Helper function to determine dominant sentiment
function getDominantSentiment(sentiment) {
  const values = {
    Positive: sentiment.Positive || 0,
    Negative: sentiment.Negative || 0,
    Neutral: sentiment.Neutral || 0,
    Mixed: sentiment.Mixed || 0
  };

  const max = Math.max(...Object.values(values));

  if (max === values.Positive) {
    return { label: 'Positive', color: '#28a745' };
  } else if (max === values.Negative) {
    return { label: 'Negative', color: '#dc3545' };
  } else if (max === values.Mixed) {
    return { label: 'Mixed', color: '#ffc107' };
  } else {
    return { label: 'Neutral', color: '#6c757d' };
  }
}

// Import other components from original implementation
// (SentimentOverviewCard, WordFrequencySection, DocumentTypeComparison, etc.)

function SentimentOverviewCard({ data }) {
  if (!data) {
    return <NotAvailablePlaceholder message="Overall sentiment data not available" />;
  }

  const { sentiment, documentCount, dateRange } = data;

  const maxSentiment = Math.max(
    sentiment.Positive || 0,
    sentiment.Negative || 0,
    sentiment.Neutral || 0,
    sentiment.Mixed || 0
  );

  let overallLabel = 'Neutral';
  let overallColor = '#6c757d';

  if (maxSentiment === sentiment.Positive) {
    overallLabel = 'Positive';
    overallColor = '#28a745';
  } else if (maxSentiment === sentiment.Negative) {
    overallLabel = 'Negative';
    overallColor = '#dc3545';
  } else if (maxSentiment === sentiment.Mixed) {
    overallLabel = 'Mixed';
    overallColor = '#ffc107';
  }

  return (
    <div style={{
      background: 'white',
      border: '1px solid #dee2e6',
      borderRadius: '8px',
      padding: '25px',
      marginBottom: '30px',
      boxShadow: '0 2px 4px rgba(0,0,0,0.05)'
    }}>
      <h3 style={{ marginTop: 0, marginBottom: '20px', color: '#2c3e50' }}>
        Overall Sentiment Analysis
      </h3>

      <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap' }}>
        <div style={{ flex: '1', minWidth: '200px' }}>
          <div style={{
            textAlign: 'center',
            padding: '20px',
            background: '#f8f9fa',
            borderRadius: '8px'
          }}>
            <div style={{ fontSize: '14px', color: '#6c757d', marginBottom: '10px' }}>
              Overall Sentiment
            </div>
            <div style={{
              fontSize: '32px',
              fontWeight: 'bold',
              color: overallColor
            }}>
              {overallLabel}
            </div>
            <div style={{ fontSize: '12px', color: '#6c757d', marginTop: '10px' }}>
              Based on {documentCount} documents
            </div>
            {dateRange && (
              <div style={{ fontSize: '11px', color: '#999', marginTop: '5px' }}>
                {dateRange.start} to {dateRange.end}
              </div>
            )}
          </div>
        </div>

        <div style={{ flex: '2', minWidth: '300px' }}>
          <div style={{ marginBottom: '15px' }}>
            <SentimentBar label="Positive" value={sentiment.Positive * 100} color="#28a745" />
          </div>
          <div style={{ marginBottom: '15px' }}>
            <SentimentBar label="Negative" value={sentiment.Negative * 100} color="#dc3545" />
          </div>
          <div style={{ marginBottom: '15px' }}>
            <SentimentBar label="Neutral" value={sentiment.Neutral * 100} color="#6c757d" />
          </div>
          <div>
            <SentimentBar label="Mixed" value={sentiment.Mixed * 100} color="#ffc107" />
          </div>
        </div>
      </div>
    </div>
  );
}

function SentimentBar({ label, value, color }) {
  return (
    <div>
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        marginBottom: '5px',
        fontSize: '14px'
      }}>
        <span style={{ fontWeight: '500' }}>{label}</span>
        <span style={{ color: '#6c757d' }}>{value.toFixed(1)}%</span>
      </div>
      <div style={{
        height: '10px',
        background: '#e9ecef',
        borderRadius: '5px',
        overflow: 'hidden'
      }}>
        <div style={{
          width: `${value}%`,
          height: '100%',
          background: color,
          transition: 'width 0.3s ease'
        }} />
      </div>
    </div>
  );
}

function WordFrequencySection({ words, ticker }) {
  if (!words || words.length === 0) {
    return <NotAvailablePlaceholder message="Word frequency data not available" />;
  }

  return (
    <div style={{
      background: 'white',
      border: '1px solid #dee2e6',
      borderRadius: '8px',
      padding: '25px',
      marginBottom: '30px',
      boxShadow: '0 2px 4px rgba(0,0,0,0.05)'
    }}>
      <h3 style={{ marginTop: 0, marginBottom: '15px', color: '#2c3e50' }}>
        Top Keywords - {ticker}
      </h3>
      <p style={{ color: '#6c757d', fontSize: '14px', marginBottom: '20px' }}>
        Most frequently used words across all documents
      </p>

      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ backgroundColor: '#f8f9fa', borderBottom: '2px solid #dee2e6' }}>
            <th style={{ padding: '12px', textAlign: 'left', fontWeight: 'bold' }}>Rank</th>
            <th style={{ padding: '12px', textAlign: 'left', fontWeight: 'bold' }}>Word</th>
            <th style={{ padding: '12px', textAlign: 'right', fontWeight: 'bold' }}>Count</th>
            <th style={{ padding: '12px', textAlign: 'left', fontWeight: 'bold' }}>Frequency</th>
          </tr>
        </thead>
        <tbody>
          {words.slice(0, 20).map((word, i) => {
            const maxValue = words[0].count;
            const percentage = (word.count / maxValue) * 100;

            return (
              <tr
                key={i}
                style={{
                  borderBottom: '1px solid #dee2e6',
                  backgroundColor: i % 2 === 0 ? '#f8f9fa' : 'white'
                }}
              >
                <td style={{ padding: '10px', fontWeight: 'bold', color: '#7f8c8d' }}>
                  #{i + 1}
                </td>
                <td style={{ padding: '10px', fontWeight: '500' }}>
                  {word.text}
                </td>
                <td style={{ padding: '10px', textAlign: 'right' }}>
                  {word.count.toLocaleString()}
                </td>
                <td style={{ padding: '10px' }}>
                  <div style={{
                    width: `${percentage}%`,
                    height: '20px',
                    backgroundColor: '#3498db',
                    borderRadius: '3px',
                    minWidth: '5px'
                  }} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function DocumentTypeComparison({ comparison, ticker }) {
  if (!comparison || !comparison.sec || !comparison.transcripts) {
    return <NotAvailablePlaceholder message="Document comparison data not available" />;
  }

  return (
    <div style={{
      background: 'white',
      border: '1px solid #dee2e6',
      borderRadius: '8px',
      padding: '25px',
      marginBottom: '30px',
      boxShadow: '0 2px 4px rgba(0,0,0,0.05)'
    }}>
      <h3 style={{ marginTop: 0, marginBottom: '15px', color: '#2c3e50' }}>
        SEC Filings vs Earnings Transcripts Comparison
      </h3>
      <p style={{ color: '#6c757d', fontSize: '14px', marginBottom: '25px' }}>
        Comparing sentiment patterns between regulatory filings and earnings calls for {ticker}
      </p>

      <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap' }}>
        <div style={{
          flex: '1',
          minWidth: '250px',
          padding: '20px',
          background: '#f8f9fa',
          borderRadius: '8px',
          border: '2px solid #007bff'
        }}>
          <h4 style={{
            marginTop: 0,
            marginBottom: '15px',
            color: '#007bff'
          }}>
            SEC Filings (10-K/10-Q)
          </h4>

          <div style={{ marginBottom: '10px' }}>
            <div style={{ fontSize: '12px', color: '#6c757d', marginBottom: '5px' }}>
              Document Count: {comparison.sec.documentCount}
            </div>
          </div>

          <div style={{ marginTop: '15px' }}>
            <SentimentBar label="Positive" value={comparison.sec.sentiment.Positive * 100} color="#28a745" />
          </div>
          <div style={{ marginTop: '10px' }}>
            <SentimentBar label="Negative" value={comparison.sec.sentiment.Negative * 100} color="#dc3545" />
          </div>
          <div style={{ marginTop: '10px' }}>
            <SentimentBar label="Neutral" value={comparison.sec.sentiment.Neutral * 100} color="#6c757d" />
          </div>

          {comparison.sec.topWords && comparison.sec.topWords.length > 0 && (
            <div style={{ marginTop: '20px' }}>
              <div style={{ fontSize: '12px', fontWeight: 'bold', marginBottom: '8px' }}>
                Top Keywords:
              </div>
              <div style={{ fontSize: '12px', color: '#495057' }}>
                {comparison.sec.topWords.slice(0, 5).map(w => w.text).join(', ')}
              </div>
            </div>
          )}
        </div>

        <div style={{
          flex: '1',
          minWidth: '250px',
          padding: '20px',
          background: '#f8f9fa',
          borderRadius: '8px',
          border: '2px solid #28a745'
        }}>
          <h4 style={{
            marginTop: 0,
            marginBottom: '15px',
            color: '#28a745'
          }}>
            Earnings Transcripts
          </h4>

          <div style={{ marginBottom: '10px' }}>
            <div style={{ fontSize: '12px', color: '#6c757d', marginBottom: '5px' }}>
              Document Count: {comparison.transcripts.documentCount}
            </div>
          </div>

          <div style={{ marginTop: '15px' }}>
            <SentimentBar label="Positive" value={comparison.transcripts.sentiment.Positive * 100} color="#28a745" />
          </div>
          <div style={{ marginTop: '10px' }}>
            <SentimentBar label="Negative" value={comparison.transcripts.sentiment.Negative * 100} color="#dc3545" />
          </div>
          <div style={{ marginTop: '10px' }}>
            <SentimentBar label="Neutral" value={comparison.transcripts.sentiment.Neutral * 100} color="#6c757d" />
          </div>

          {comparison.transcripts.topWords && comparison.transcripts.topWords.length > 0 && (
            <div style={{ marginTop: '20px' }}>
              <div style={{ fontSize: '12px', fontWeight: 'bold', marginBottom: '8px' }}>
                Top Keywords:
              </div>
              <div style={{ fontSize: '12px', color: '#495057' }}>
                {comparison.transcripts.topWords.slice(0, 5).map(w => w.text).join(', ')}
              </div>
            </div>
          )}
        </div>
      </div>

      {comparison.insights && (
        <div style={{
          marginTop: '20px',
          padding: '15px',
          background: '#fff3cd',
          border: '1px solid #ffc107',
          borderRadius: '4px'
        }}>
          <div style={{ fontWeight: 'bold', marginBottom: '8px', color: '#856404' }}>
            Key Insights:
          </div>
          <ul style={{ margin: 0, paddingLeft: '20px', color: '#856404', fontSize: '14px' }}>
            {comparison.insights.map((insight, i) => (
              <li key={i} style={{ marginBottom: '5px' }}>{insight}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function NotAvailablePlaceholder({ message, subtitle }) {
  return (
    <div style={{
      background: '#f8f9fa',
      border: '2px dashed #dee2e6',
      borderRadius: '8px',
      padding: '40px',
      textAlign: 'center',
      marginBottom: '30px'
    }}>
      <div style={{ fontSize: '48px', marginBottom: '15px' }}>
        ...
      </div>
      <div style={{
        fontSize: '18px',
        fontWeight: '500',
        color: '#495057',
        marginBottom: '8px'
      }}>
        {message || 'Data Not Available'}
      </div>
      {subtitle && (
        <div style={{
          fontSize: '14px',
          color: '#6c757d'
        }}>
          {subtitle}
        </div>
      )}
    </div>
  );
}

export default SentimentAnalysis;
