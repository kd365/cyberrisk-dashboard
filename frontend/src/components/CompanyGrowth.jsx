import React, { useState, useEffect } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, LineChart, Line, Legend
} from 'recharts';

// Company colors for charts
const COMPANY_COLORS = {
  'CRWD': '#e74c3c',
  'ZS': '#3498db',
  'NET': '#f39c12',
  'PANW': '#9b59b6',
  'FTNT': '#1abc9c',
  'OKTA': '#2ecc71',
  'S': '#e91e63',
  'CYBR': '#00bcd4',
  'TENB': '#ff5722',
  'SPLK': '#607d8b'
};

const FUNCTION_COLORS = ['#667eea', '#764ba2', '#00C49F', '#FFBB28', '#FF8042', '#8884d8'];
const SENIORITY_COLORS = ['#2ecc71', '#3498db', '#9b59b6', '#e74c3c', '#f39c12'];

// Valid tickers for growth analysis
const VALID_GROWTH_TICKERS = ['CRWD', 'ZS', 'NET', 'PANW', 'FTNT', 'OKTA', 'S', 'CYBR', 'TENB', 'SPLK'];

function CompanyGrowth({ ticker }) {
  // Only use the passed ticker if it's in our valid list, otherwise default to CRWD
  const initialTicker = VALID_GROWTH_TICKERS.includes(ticker) ? ticker : 'CRWD';

  const [mode, setMode] = useState('single'); // 'single' or 'compare'
  const [selectedTickers, setSelectedTickers] = useState([initialTicker]);
  const [availableCompanies, setAvailableCompanies] = useState([]);
  const [growthData, setGrowthData] = useState(null);
  const [comparisonData, setComparisonData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activePanel, setActivePanel] = useState(1);

  // Fetch available companies on mount
  useEffect(() => {
    fetch('/api/company-growth/available')
      .then(res => res.json())
      .then(data => setAvailableCompanies(data.companies || []))
      .catch(err => console.error('Error fetching available companies:', err));
  }, []);

  // Fetch data when ticker or mode changes
  useEffect(() => {
    if (mode === 'single' && selectedTickers[0]) {
      fetchSingleCompany(selectedTickers[0]);
    } else if (mode === 'compare' && selectedTickers.length > 1) {
      fetchComparison(selectedTickers);
    }
  }, [selectedTickers, mode]);

  const fetchSingleCompany = async (tickerSymbol) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/company-growth/${tickerSymbol}`);
      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.error || 'Failed to fetch growth data');
      }
      const data = await res.json();
      setGrowthData(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const fetchComparison = async (tickers) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/company-growth/compare?tickers=${tickers.join(',')}`);
      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.error || 'Failed to fetch comparison data');
      }
      const data = await res.json();
      setComparisonData(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const toggleCompany = (tickerSymbol) => {
    if (mode === 'single') {
      setSelectedTickers([tickerSymbol]);
    } else {
      if (selectedTickers.includes(tickerSymbol)) {
        if (selectedTickers.length > 1) {
          setSelectedTickers(selectedTickers.filter(t => t !== tickerSymbol));
        }
      } else if (selectedTickers.length < 3) {
        setSelectedTickers([...selectedTickers, tickerSymbol]);
      }
    }
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '60px' }}>
        <div style={{ fontSize: '48px', marginBottom: '20px' }}>...</div>
        <p>Loading growth data...</p>
        <p style={{ fontSize: '12px', color: '#888' }}>Powered by CoreSignal</p>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{
        textAlign: 'center', padding: '40px',
        background: '#fff3cd', borderRadius: '8px', border: '1px solid #ffc107'
      }}>
        <h3>Unable to Load Growth Data</h3>
        <p>{error}</p>
      </div>
    );
  }

  return (
    <div>
      {/* Company Selector */}
      <div style={{ marginBottom: '20px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '15px' }}>
          <h3 style={{ margin: 0 }}>Employee Growth & Hiring Analysis</h3>
          <div style={{ display: 'flex', gap: '10px' }}>
            <button
              onClick={() => { setMode('single'); setSelectedTickers([selectedTickers[0]]); }}
              style={{
                padding: '8px 16px', borderRadius: '6px', border: 'none',
                background: mode === 'single' ? '#667eea' : '#e9ecef',
                color: mode === 'single' ? 'white' : '#333',
                cursor: 'pointer', fontWeight: '500'
              }}
            >
              Single View
            </button>
            <button
              onClick={() => setMode('compare')}
              style={{
                padding: '8px 16px', borderRadius: '6px', border: 'none',
                background: mode === 'compare' ? '#667eea' : '#e9ecef',
                color: mode === 'compare' ? 'white' : '#333',
                cursor: 'pointer', fontWeight: '500'
              }}
            >
              Compare (up to 3)
            </button>
          </div>
        </div>

        {/* Company chips */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
          {availableCompanies.map(company => (
            <button
              key={company.ticker}
              onClick={() => toggleCompany(company.ticker)}
              style={{
                padding: '6px 14px', borderRadius: '20px',
                border: selectedTickers.includes(company.ticker) ? '2px solid #667eea' : '1px solid #ddd',
                background: selectedTickers.includes(company.ticker) ? '#667eea' : 'white',
                color: selectedTickers.includes(company.ticker) ? 'white' : '#333',
                cursor: 'pointer', fontSize: '13px', fontWeight: '500',
                opacity: company.has_coresignal_id ? 1 : 0.5
              }}
              disabled={!company.has_coresignal_id && !['CRWD', 'ZS', 'NET'].includes(company.ticker)}
              title={company.name}
            >
              {company.ticker}
            </button>
          ))}
        </div>
        {mode === 'compare' && (
          <p style={{ fontSize: '12px', color: '#888', marginTop: '8px' }}>
            Selected: {selectedTickers.join(', ')} {selectedTickers.length < 2 && '(select at least 2 companies)'}
          </p>
        )}
      </div>

      {/* Panel Navigation */}
      <div style={{ display: 'flex', gap: '10px', marginBottom: '20px', flexWrap: 'wrap' }}>
        {[
          { id: 1, title: 'Hiring Priorities' },
          { id: 2, title: 'Hiring Intensity' },
          { id: 3, title: 'Employee Growth' },
          { id: 4, title: 'Workforce Composition' }
        ].map(panel => (
          <button
            key={panel.id}
            onClick={() => setActivePanel(panel.id)}
            style={{
              flex: 1, minWidth: '150px', padding: '12px', borderRadius: '8px',
              border: activePanel === panel.id ? '2px solid #667eea' : '1px solid #ddd',
              background: activePanel === panel.id ? '#667eea' : 'white',
              color: activePanel === panel.id ? 'white' : '#333',
              cursor: 'pointer', fontWeight: '600', fontSize: '14px'
            }}
          >
            Panel {panel.id}: {panel.title}
          </button>
        ))}
      </div>

      {/* Panel Content */}
      {mode === 'single' && growthData && (
        <>
          {activePanel === 1 && <Panel1Single data={growthData} />}
          {activePanel === 2 && <Panel2Single data={growthData} />}
          {activePanel === 3 && <Panel3Single data={growthData} />}
          {activePanel === 4 && <Panel4Single data={growthData} />}
        </>
      )}

      {mode === 'compare' && comparisonData && selectedTickers.length > 1 && (
        <>
          {activePanel === 1 && <Panel1Compare data={comparisonData} tickers={selectedTickers} />}
          {activePanel === 2 && <Panel2Compare data={comparisonData} tickers={selectedTickers} />}
          {activePanel === 3 && <Panel3Compare data={comparisonData} tickers={selectedTickers} />}
          {activePanel === 4 && <Panel4Compare data={comparisonData} tickers={selectedTickers} />}
        </>
      )}

      {mode === 'compare' && selectedTickers.length < 2 && (
        <div style={{ textAlign: 'center', padding: '40px', background: '#f8f9fa', borderRadius: '8px' }}>
          <p>Select at least 2 companies to compare</p>
        </div>
      )}

      {/* Data source footer */}
      <div style={{ marginTop: '20px', textAlign: 'right', fontSize: '11px', color: '#888' }}>
        Data from CoreSignal API | {growthData?.data_freshness || comparisonData?.tickers?.join(', ')}
      </div>
    </div>
  );
}

// ============================================================================
// Panel 1: Current Hiring Priorities (Single Company)
// ============================================================================
function Panel1Single({ data }) {
  const jobsByFunction = Object.entries(data.jobs_by_function || {})
    .map(([name, value]) => ({ name, value }))
    .filter(d => d.value > 0)
    .sort((a, b) => b.value - a.value)
    .slice(0, 6);

  const jobsBySeniority = Object.entries(data.jobs_by_seniority || {})
    .map(([name, value]) => ({ name, value }))
    .filter(d => d.value > 0)
    .sort((a, b) => b.value - a.value);

  return (
    <div>
      <div style={{ background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', color: 'white', padding: '20px', borderRadius: '8px', marginBottom: '20px' }}>
        <h2 style={{ margin: 0 }}>{data.company?.name || data.ticker}</h2>
        <p style={{ margin: '5px 0 0', opacity: 0.9 }}>
          {data.employee_count?.toLocaleString()} employees | {data.total_jobs} active job postings
        </p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
        {/* Jobs by Function */}
        <div style={{ background: '#f8f9fa', padding: '20px', borderRadius: '8px' }}>
          <h4 style={{ marginTop: 0 }}>Active Jobs by Function (Top 6)</h4>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={jobsByFunction} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" />
              <YAxis dataKey="name" type="category" width={120} tick={{ fontSize: 11 }} />
              <Tooltip />
              <Bar dataKey="value" fill="#667eea" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Jobs by Seniority */}
        <div style={{ background: '#f8f9fa', padding: '20px', borderRadius: '8px' }}>
          <h4 style={{ marginTop: 0 }}>Active Jobs by Seniority</h4>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={jobsBySeniority} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" />
              <YAxis dataKey="name" type="category" width={120} tick={{ fontSize: 11 }} />
              <Tooltip />
              <Bar dataKey="value" fill="#764ba2" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Summary Table */}
      <div style={{ background: '#f8f9fa', padding: '20px', borderRadius: '8px', marginTop: '20px' }}>
        <h4 style={{ marginTop: 0 }}>Current Open Positions Summary</h4>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: '#e9ecef' }}>
              <th style={thStyle}>Metric</th>
              <th style={thStyle}>Value</th>
              <th style={thStyle}>% of Total</th>
            </tr>
          </thead>
          <tbody>
            <tr><td style={tdStyle}>Total Jobs</td><td style={tdStyle}>{data.total_jobs}</td><td style={tdStyle}>100%</td></tr>
            {jobsByFunction.slice(0, 4).map((item, idx) => (
              <tr key={idx}>
                <td style={tdStyle}>{item.name}</td>
                <td style={tdStyle}>{item.value}</td>
                <td style={tdStyle}>{((item.value / data.total_jobs) * 100).toFixed(1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ============================================================================
// Panel 2: Hiring Intensity (Single Company)
// ============================================================================
function Panel2Single({ data }) {
  const hiringIntensity = data.hiring_intensity || 0;
  const employeeCount = data.employee_count || 1;
  const totalJobs = data.total_jobs || 0;

  const intensityByFunction = Object.entries(data.jobs_by_function || {})
    .map(([name, count]) => ({
      name,
      jobs: count,
      intensity: ((count / employeeCount) * 100).toFixed(2)
    }))
    .filter(d => d.jobs > 0)
    .sort((a, b) => b.intensity - a.intensity)
    .slice(0, 6);

  return (
    <div>
      {/* Key Metrics */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '15px', marginBottom: '20px' }}>
        <MetricCard title="Total Employees" value={employeeCount.toLocaleString()} />
        <MetricCard title="Active Job Postings" value={totalJobs} />
        <MetricCard
          title="Hiring Intensity"
          value={`${hiringIntensity}%`}
          subtitle="Jobs / Employees"
          color={hiringIntensity > 10 ? '#28a745' : hiringIntensity > 5 ? '#ffc107' : '#6c757d'}
        />
      </div>

      {/* Intensity by Function */}
      <div style={{ background: '#f8f9fa', padding: '20px', borderRadius: '8px' }}>
        <h4 style={{ marginTop: 0 }}>Hiring Intensity by Function</h4>
        <p style={{ fontSize: '12px', color: '#666', marginBottom: '15px' }}>
          Active jobs as percentage of total workforce
        </p>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={intensityByFunction}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="name" tick={{ fontSize: 10 }} angle={-45} textAnchor="end" height={80} />
            <YAxis unit="%" />
            <Tooltip formatter={(value) => `${value}%`} />
            <Bar dataKey="intensity" fill="#667eea" name="Hiring Intensity %" />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Interpretation */}
      <div style={{ background: '#e7f3ff', border: '1px solid #b3d9ff', borderRadius: '8px', padding: '15px', marginTop: '20px' }}>
        <h4 style={{ marginTop: 0, color: '#004085' }}>Interpretation</h4>
        <p style={{ margin: 0, fontSize: '13px', color: '#004085' }}>
          {hiringIntensity > 10
            ? `Strong expansion mode with ${hiringIntensity}% hiring intensity. The company is aggressively growing its workforce.`
            : hiringIntensity > 5
            ? `Moderate hiring activity with ${hiringIntensity}% intensity. Steady growth with selective hiring.`
            : `Conservative hiring with ${hiringIntensity}% intensity. Focus on backfills or strategic roles.`
          }
        </p>
      </div>
    </div>
  );
}

// ============================================================================
// Panel 3: Employee Growth (Single Company)
// ============================================================================
function Panel3Single({ data }) {
  const headcountHistory = (data.headcount_history || []).map(item => ({
    date: item.snapshot_date?.slice(0, 7),
    employees: item.employee_count
  }));

  // Calculate YoY growth
  const latestCount = headcountHistory.length > 0 ? headcountHistory[headcountHistory.length - 1].employees : 0;
  const yearAgoIdx = headcountHistory.length - 12;
  const yearAgoCount = yearAgoIdx >= 0 ? headcountHistory[yearAgoIdx].employees : headcountHistory[0]?.employees || 0;
  const yoyGrowth = yearAgoCount ? (((latestCount - yearAgoCount) / yearAgoCount) * 100).toFixed(1) : 'N/A';

  return (
    <div>
      {/* Summary Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '15px', marginBottom: '20px' }}>
        <MetricCard title="Current Headcount" value={latestCount.toLocaleString()} />
        <MetricCard title="YoY Growth" value={`${yoyGrowth}%`} color={yoyGrowth > 0 ? '#28a745' : '#dc3545'} />
        <MetricCard title="Data Points" value={headcountHistory.length} subtitle="Monthly snapshots" />
      </div>

      {/* Headcount Timeline */}
      <div style={{ background: '#f8f9fa', padding: '20px', borderRadius: '8px' }}>
        <h4 style={{ marginTop: 0 }}>Headcount Over Time</h4>
        <ResponsiveContainer width="100%" height={350}>
          <LineChart data={headcountHistory}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{ fontSize: 10 }} />
            <YAxis tickFormatter={(val) => val.toLocaleString()} />
            <Tooltip formatter={(value) => value.toLocaleString()} />
            <Line type="monotone" dataKey="employees" stroke="#667eea" strokeWidth={2} dot={{ r: 3 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ============================================================================
// Panel 1: Hiring Priorities (Comparison)
// ============================================================================
function Panel1Compare({ data, tickers }) {
  // Prepare grouped data for functions
  const functions = Object.keys(data.jobs_by_function || {});
  const functionData = functions.slice(0, 6).map(func => {
    const item = { name: func };
    tickers.forEach(t => {
      item[t] = data.jobs_by_function[func]?.[t] || 0;
    });
    return item;
  });

  return (
    <div>
      <h3 style={{ marginBottom: '20px' }}>Hiring Priorities Comparison: {tickers.join(' vs ')}</h3>

      <div style={{ background: '#f8f9fa', padding: '20px', borderRadius: '8px', marginBottom: '20px' }}>
        <h4 style={{ marginTop: 0 }}>Active Jobs by Function</h4>
        <ResponsiveContainer width="100%" height={350}>
          <BarChart data={functionData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="name" tick={{ fontSize: 10 }} angle={-45} textAnchor="end" height={80} />
            <YAxis />
            <Tooltip />
            <Legend />
            {tickers.map((t, idx) => (
              <Bar key={t} dataKey={t} fill={COMPANY_COLORS[t] || FUNCTION_COLORS[idx]} name={t} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Summary Table */}
      <div style={{ background: '#f8f9fa', padding: '20px', borderRadius: '8px' }}>
        <h4 style={{ marginTop: 0 }}>Company Comparison Summary</h4>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: '#e9ecef' }}>
              <th style={thStyle}>Company</th>
              <th style={thStyle}>Employees</th>
              <th style={thStyle}>Total Jobs</th>
              <th style={thStyle}>Top Function</th>
            </tr>
          </thead>
          <tbody>
            {tickers.map(t => {
              const company = data.companies?.[t] || {};
              const topFunc = Object.entries(data.jobs_by_function || {})
                .filter(([, counts]) => counts[t] > 0)
                .sort(([, a], [, b]) => (b[t] || 0) - (a[t] || 0))[0];
              return (
                <tr key={t}>
                  <td style={tdStyle}><strong>{t}</strong> - {company.name}</td>
                  <td style={tdStyle}>{company.employee_count?.toLocaleString() || 'N/A'}</td>
                  <td style={tdStyle}>{company.total_jobs || 0}</td>
                  <td style={tdStyle}>{topFunc ? topFunc[0] : 'N/A'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ============================================================================
// Panel 2: Hiring Intensity (Comparison)
// ============================================================================
function Panel2Compare({ data, tickers }) {
  const intensityData = tickers.map(t => ({
    name: t,
    intensity: data.hiring_intensity?.overall?.[t] || 0
  }));

  return (
    <div>
      <h3 style={{ marginBottom: '20px' }}>Hiring Intensity Comparison: {tickers.join(' vs ')}</h3>

      <div style={{ background: '#f8f9fa', padding: '20px', borderRadius: '8px', marginBottom: '20px' }}>
        <h4 style={{ marginTop: 0 }}>Overall Hiring Rate (Jobs / Employees %)</h4>
        <ResponsiveContainer width="100%" height={250}>
          <BarChart data={intensityData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="name" />
            <YAxis unit="%" />
            <Tooltip formatter={(value) => `${value}%`} />
            {tickers.map((t, idx) => (
              <Bar key={t} dataKey="intensity" fill={COMPANY_COLORS[t] || FUNCTION_COLORS[idx]} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Insights */}
      {data.insights && data.insights.length > 0 && (
        <div style={{ background: '#e7f3ff', border: '1px solid #b3d9ff', borderRadius: '8px', padding: '15px' }}>
          <h4 style={{ marginTop: 0, color: '#004085' }}>Key Insights</h4>
          <ul style={{ margin: 0, paddingLeft: '20px' }}>
            {data.insights.map((insight, idx) => (
              <li key={idx} style={{ marginBottom: '8px', color: '#004085' }}>{insight}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Panel 3: Employee Growth (Comparison)
// ============================================================================
function Panel3Compare({ data, tickers }) {
  const headcountHistory = data.headcount_history || [];
  const indexedGrowth = data.indexed_growth || [];

  return (
    <div>
      <h3 style={{ marginBottom: '20px' }}>Employee Growth Comparison: {tickers.join(' vs ')}</h3>

      {/* Headcount over time */}
      <div style={{ background: '#f8f9fa', padding: '20px', borderRadius: '8px', marginBottom: '20px' }}>
        <h4 style={{ marginTop: 0 }}>Total Headcount Over Time</h4>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={headcountHistory}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{ fontSize: 10 }} />
            <YAxis tickFormatter={(val) => val.toLocaleString()} />
            <Tooltip formatter={(value) => value?.toLocaleString()} />
            <Legend />
            {tickers.map((t, idx) => (
              <Line
                key={t}
                type="monotone"
                dataKey={t}
                stroke={COMPANY_COLORS[t] || FUNCTION_COLORS[idx]}
                strokeWidth={2}
                dot={{ r: 2 }}
                name={t}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Indexed Growth */}
      <div style={{ background: '#f8f9fa', padding: '20px', borderRadius: '8px' }}>
        <h4 style={{ marginTop: 0 }}>Indexed Growth (First Date = 100)</h4>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={indexedGrowth}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{ fontSize: 10 }} />
            <YAxis domain={['auto', 'auto']} />
            <Tooltip />
            <Legend />
            {tickers.map((t, idx) => (
              <Line
                key={t}
                type="monotone"
                dataKey={t}
                stroke={COMPANY_COLORS[t] || FUNCTION_COLORS[idx]}
                strokeWidth={2}
                dot={{ r: 2 }}
                name={t}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ============================================================================
// Panel 4: Workforce Composition (Single Company)
// ============================================================================
function Panel4Single({ data }) {
  // Get department and seniority data from headcount history
  const headcountHistory = data.headcount_history || [];

  // Extract department breakdown over time from history (if available)
  const deptOverTime = headcountHistory
    .filter(h => h.by_department && Object.keys(h.by_department).length > 0)
    .map(h => ({
      date: h.snapshot_date?.slice(0, 7),
      ...h.by_department
    }));

  // Extract seniority breakdown over time from history (if available)
  const seniorityOverTime = headcountHistory
    .filter(h => h.by_seniority && Object.keys(h.by_seniority).length > 0)
    .map(h => ({
      date: h.snapshot_date?.slice(0, 7),
      ...h.by_seniority
    }));

  // Get unique department names for chart lines
  const departments = deptOverTime.length > 0
    ? [...new Set(deptOverTime.flatMap(d => Object.keys(d).filter(k => k !== 'date')))]
    : [];

  // Get unique seniority levels
  const seniorityLevels = seniorityOverTime.length > 0
    ? [...new Set(seniorityOverTime.flatMap(d => Object.keys(d).filter(k => k !== 'date')))]
    : [];

  // Current breakdown from jobs data (as fallback)
  const currentByDept = Object.entries(data.jobs_by_function || {})
    .map(([name, value]) => ({ name, value }))
    .filter(d => d.value > 0)
    .sort((a, b) => b.value - a.value);

  const currentBySeniority = Object.entries(data.jobs_by_seniority || {})
    .map(([name, value]) => ({ name, value }))
    .filter(d => d.value > 0);

  // Department colors
  const DEPT_COLORS = ['#667eea', '#764ba2', '#00C49F', '#FFBB28', '#FF8042', '#8884d8', '#82ca9d', '#ffc658'];

  return (
    <div>
      <div style={{ background: 'linear-gradient(135deg, #1abc9c 0%, #16a085 100%)', color: 'white', padding: '20px', borderRadius: '8px', marginBottom: '20px' }}>
        <h2 style={{ margin: 0 }}>Workforce Composition - {data.company?.name || data.ticker}</h2>
        <p style={{ margin: '5px 0 0', opacity: 0.9 }}>
          Employee distribution by department and seniority level
        </p>
      </div>

      {/* Department Distribution */}
      <div style={{ display: 'grid', gridTemplateColumns: deptOverTime.length > 0 ? '1fr' : '1fr 1fr', gap: '20px', marginBottom: '20px' }}>
        {deptOverTime.length > 0 ? (
          <div style={{ background: '#f8f9fa', padding: '20px', borderRadius: '8px' }}>
            <h4 style={{ marginTop: 0 }}>Employee Count by Department Over Time</h4>
            <ResponsiveContainer width="100%" height={350}>
              <LineChart data={deptOverTime}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" tick={{ fontSize: 10 }} />
                <YAxis tickFormatter={(val) => val.toLocaleString()} />
                <Tooltip formatter={(value) => value?.toLocaleString()} />
                <Legend wrapperStyle={{ fontSize: '11px' }} />
                {departments.slice(0, 8).map((dept, idx) => (
                  <Line
                    key={dept}
                    type="monotone"
                    dataKey={dept}
                    stroke={DEPT_COLORS[idx % DEPT_COLORS.length]}
                    strokeWidth={2}
                    dot={{ r: 1 }}
                    name={dept}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <>
            <div style={{ background: '#f8f9fa', padding: '20px', borderRadius: '8px' }}>
              <h4 style={{ marginTop: 0 }}>Current Hiring by Department</h4>
              <p style={{ fontSize: '12px', color: '#666' }}>Based on active job postings</p>
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={currentByDept.slice(0, 6)} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis type="number" />
                  <YAxis dataKey="name" type="category" width={100} tick={{ fontSize: 10 }} />
                  <Tooltip />
                  <Bar dataKey="value" fill="#1abc9c" />
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div style={{ background: '#f8f9fa', padding: '20px', borderRadius: '8px' }}>
              <h4 style={{ marginTop: 0 }}>Current Hiring by Seniority</h4>
              <p style={{ fontSize: '12px', color: '#666' }}>Based on active job postings</p>
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={currentBySeniority} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis type="number" />
                  <YAxis dataKey="name" type="category" width={100} tick={{ fontSize: 10 }} />
                  <Tooltip />
                  <Bar dataKey="value" fill="#16a085" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </>
        )}
      </div>

      {/* Seniority Over Time */}
      {seniorityOverTime.length > 0 && (
        <div style={{ background: '#f8f9fa', padding: '20px', borderRadius: '8px', marginBottom: '20px' }}>
          <h4 style={{ marginTop: 0 }}>Employee Count by Seniority Over Time</h4>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={seniorityOverTime}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" tick={{ fontSize: 10 }} />
              <YAxis tickFormatter={(val) => val.toLocaleString()} />
              <Tooltip formatter={(value) => value?.toLocaleString()} />
              <Legend wrapperStyle={{ fontSize: '11px' }} />
              {seniorityLevels.map((level, idx) => (
                <Line
                  key={level}
                  type="monotone"
                  dataKey={level}
                  stroke={SENIORITY_COLORS[idx % SENIORITY_COLORS.length]}
                  strokeWidth={2}
                  dot={{ r: 1 }}
                  name={level}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Key Insights */}
      <div style={{ background: '#e7f3ff', border: '1px solid #b3d9ff', borderRadius: '8px', padding: '15px' }}>
        <h4 style={{ marginTop: 0, color: '#004085' }}>Workforce Insights</h4>
        <ul style={{ margin: 0, paddingLeft: '20px' }}>
          {currentByDept.length > 0 && (
            <li style={{ marginBottom: '8px', color: '#004085' }}>
              Top hiring focus: <strong>{currentByDept[0]?.name}</strong> ({currentByDept[0]?.value} open positions)
            </li>
          )}
          {currentBySeniority.find(s => s.name === 'Mid-Senior level') && (
            <li style={{ marginBottom: '8px', color: '#004085' }}>
              Mid-Senior level hiring represents {((currentBySeniority.find(s => s.name === 'Mid-Senior level')?.value / data.total_jobs) * 100).toFixed(0)}% of all openings
            </li>
          )}
          <li style={{ marginBottom: '8px', color: '#004085' }}>
            Historical data shows workforce composition trends over {headcountHistory.length} months
          </li>
        </ul>
      </div>
    </div>
  );
}

// ============================================================================
// Panel 4: Workforce Composition (Comparison)
// ============================================================================
function Panel4Compare({ data, tickers }) {
  // Build department comparison data from jobs_by_function
  const departments = Object.keys(data.jobs_by_function || {});
  const deptCompareData = departments.slice(0, 6).map(dept => {
    const item = { name: dept };
    tickers.forEach(t => {
      item[t] = data.jobs_by_function[dept]?.[t] || 0;
    });
    return item;
  }).sort((a, b) => {
    const sumA = tickers.reduce((sum, t) => sum + (a[t] || 0), 0);
    const sumB = tickers.reduce((sum, t) => sum + (b[t] || 0), 0);
    return sumB - sumA;
  });

  // Build seniority comparison data
  const seniorityLevels = Object.keys(data.jobs_by_seniority || {});
  const senCompareData = seniorityLevels.map(level => {
    const item = { name: level };
    tickers.forEach(t => {
      item[t] = data.jobs_by_seniority[level]?.[t] || 0;
    });
    return item;
  });

  // Calculate department focus percentages
  const deptFocusData = tickers.map(t => {
    const company = data.companies?.[t] || {};
    const totalJobs = company.total_jobs || 1;
    return {
      ticker: t,
      name: company.name,
      technical: ((data.jobs_by_function?.['Engineering']?.[t] || 0) + (data.jobs_by_function?.['Information Technology']?.[t] || 0)) / totalJobs * 100,
      sales: (data.jobs_by_function?.['Sales and Business Development']?.[t] || 0) / totalJobs * 100,
      other: 100 - (((data.jobs_by_function?.['Engineering']?.[t] || 0) + (data.jobs_by_function?.['Information Technology']?.[t] || 0) + (data.jobs_by_function?.['Sales and Business Development']?.[t] || 0)) / totalJobs * 100)
    };
  });

  return (
    <div>
      <h3 style={{ marginBottom: '20px' }}>Workforce Composition Comparison: {tickers.join(' vs ')}</h3>

      {/* Department Breakdown */}
      <div style={{ background: '#f8f9fa', padding: '20px', borderRadius: '8px', marginBottom: '20px' }}>
        <h4 style={{ marginTop: 0 }}>Active Hiring by Department</h4>
        <ResponsiveContainer width="100%" height={350}>
          <BarChart data={deptCompareData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="name" tick={{ fontSize: 10 }} angle={-45} textAnchor="end" height={80} />
            <YAxis />
            <Tooltip />
            <Legend />
            {tickers.map((t, idx) => (
              <Bar key={t} dataKey={t} fill={COMPANY_COLORS[t] || FUNCTION_COLORS[idx]} name={t} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Seniority Mix */}
      <div style={{ background: '#f8f9fa', padding: '20px', borderRadius: '8px', marginBottom: '20px' }}>
        <h4 style={{ marginTop: 0 }}>Hiring by Seniority Level</h4>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={senCompareData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="name" tick={{ fontSize: 11 }} />
            <YAxis />
            <Tooltip />
            <Legend />
            {tickers.map((t, idx) => (
              <Bar key={t} dataKey={t} fill={COMPANY_COLORS[t] || FUNCTION_COLORS[idx]} name={t} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Focus Analysis Table */}
      <div style={{ background: '#f8f9fa', padding: '20px', borderRadius: '8px' }}>
        <h4 style={{ marginTop: 0 }}>Hiring Focus Analysis</h4>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: '#e9ecef' }}>
              <th style={thStyle}>Company</th>
              <th style={thStyle}>Technical %</th>
              <th style={thStyle}>Sales %</th>
              <th style={thStyle}>Other %</th>
              <th style={thStyle}>Focus</th>
            </tr>
          </thead>
          <tbody>
            {deptFocusData.map(row => (
              <tr key={row.ticker}>
                <td style={tdStyle}><strong>{row.ticker}</strong></td>
                <td style={tdStyle}>{row.technical.toFixed(1)}%</td>
                <td style={tdStyle}>{row.sales.toFixed(1)}%</td>
                <td style={tdStyle}>{row.other.toFixed(1)}%</td>
                <td style={tdStyle}>
                  <span style={{
                    padding: '4px 8px', borderRadius: '4px', fontSize: '11px', fontWeight: '600',
                    background: row.technical > 50 ? '#d4edda' : row.sales > 30 ? '#cce5ff' : '#f8f9fa',
                    color: row.technical > 50 ? '#155724' : row.sales > 30 ? '#004085' : '#333'
                  }}>
                    {row.technical > 50 ? 'Tech-Heavy' : row.sales > 30 ? 'Sales-Heavy' : 'Balanced'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ============================================================================
// Helper Components
// ============================================================================
function MetricCard({ title, value, subtitle, color }) {
  return (
    <div style={{
      background: '#f8f9fa', padding: '20px', borderRadius: '8px', textAlign: 'center'
    }}>
      <div style={{ fontSize: '28px', fontWeight: 'bold', color: color || '#2c3e50' }}>
        {value}
      </div>
      <div style={{ fontSize: '13px', color: '#333', marginTop: '8px', fontWeight: '500' }}>{title}</div>
      {subtitle && (
        <div style={{ fontSize: '11px', color: '#888', marginTop: '4px' }}>{subtitle}</div>
      )}
    </div>
  );
}

// Table styles
const thStyle = {
  padding: '12px', textAlign: 'left', borderBottom: '2px solid #dee2e6',
  fontSize: '12px', fontWeight: 'bold'
};

const tdStyle = {
  padding: '10px 12px', fontSize: '13px', borderBottom: '1px solid #e9ecef'
};

export default CompanyGrowth;
