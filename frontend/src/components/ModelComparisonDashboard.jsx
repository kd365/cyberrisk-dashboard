import React, { useState, useEffect } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, Cell, RadarChart, Radar, PolarGrid,
  PolarAngleAxis, PolarRadiusAxis
} from 'recharts';

const MODEL_COLORS = {
  prophet: '#007bff',
  chronos: '#9b59b6',
  xgboost: '#e74c3c',
  lightgbm: '#2ecc71',
  random_forest: '#f39c12',
  lstm: '#1abc9c',
  ensemble: '#e67e22',
};

const MODEL_NAMES = {
  prophet: 'Prophet',
  chronos: 'Chronos-Bolt',
  xgboost: 'XGBoost',
  lightgbm: 'LightGBM',
  random_forest: 'Random Forest',
  lstm: 'LSTM',
  ensemble: 'Ensemble',
};

function ModelComparisonDashboard({ ticker }) {
  const [leaderboard, setLeaderboard] = useState(null);
  const [featureImportance, setFeatureImportance] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loadingFeatures, setLoadingFeatures] = useState(false);
  const [error, setError] = useState(null);
  const [selectedMetric, setSelectedMetric] = useState('mape');
  const [testDays, setTestDays] = useState(30);

  const fetchLeaderboard = (refresh = false) => {
    if (!ticker) return;
    setLoading(true);
    setError(null);

    const refreshParam = refresh ? '&refresh=true' : '';
    fetch(`/api/forecast/leaderboard?ticker=${ticker}&days=${testDays}${refreshParam}`)
      .then(res => res.json())
      .then(data => {
        if (data.error) {
          setError(data.error);
        } else {
          setLeaderboard(data);
        }
        setLoading(false);
      })
      .catch(err => {
        setError(err.message);
        setLoading(false);
      });
  };

  const fetchFeatureImportance = () => {
    if (!ticker) return;
    setLoadingFeatures(true);

    fetch(`/api/forecast/feature-importance?ticker=${ticker}&model=xgboost`)
      .then(res => res.json())
      .then(data => {
        setFeatureImportance(data);
        setLoadingFeatures(false);
      })
      .catch(err => {
        console.error('Error fetching feature importance:', err);
        setLoadingFeatures(false);
      });
  };

  useEffect(() => {
    fetchLeaderboard();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker, testDays]);

  const styles = {
    container: { padding: '20px' },
    header: {
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      marginBottom: '20px', flexWrap: 'wrap', gap: '10px',
    },
    title: { fontSize: '24px', fontWeight: '700', color: '#1e293b', margin: 0 },
    controls: { display: 'flex', gap: '10px', alignItems: 'center' },
    select: {
      padding: '8px 12px', borderRadius: '6px', border: '1px solid #d1d5db',
      fontSize: '13px', background: 'white',
    },
    button: {
      padding: '8px 16px', borderRadius: '6px', border: 'none',
      background: '#3b82f6', color: 'white', cursor: 'pointer',
      fontSize: '13px', fontWeight: '600',
    },
    grid: {
      display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(350px, 1fr))',
      gap: '20px', marginBottom: '20px',
    },
    card: {
      background: 'white', borderRadius: '12px', padding: '20px',
      boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
    },
    cardTitle: { fontSize: '16px', fontWeight: '600', color: '#1e293b', marginBottom: '15px' },
    table: { width: '100%', borderCollapse: 'collapse', fontSize: '13px' },
    th: {
      textAlign: 'left', padding: '10px 12px', background: '#f8fafc',
      color: '#64748b', fontWeight: '600', borderBottom: '2px solid #e2e8f0',
    },
    td: { padding: '10px 12px', borderBottom: '1px solid #f1f5f9', color: '#334155' },
    rankBadge: (rank) => ({
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      width: '24px', height: '24px', borderRadius: '50%', fontSize: '12px', fontWeight: '700',
      background: rank === 1 ? '#fef3c7' : rank === 2 ? '#f1f5f9' : rank === 3 ? '#fef2f2' : '#f8fafc',
      color: rank === 1 ? '#92400e' : rank === 2 ? '#475569' : rank === 3 ? '#991b1b' : '#64748b',
    }),
    modelBadge: (model) => ({
      display: 'inline-flex', alignItems: 'center', gap: '6px',
    }),
    modelDot: (model) => ({
      width: '8px', height: '8px', borderRadius: '50%',
      background: MODEL_COLORS[model] || '#94a3b8',
    }),
    metricTab: (active) => ({
      padding: '6px 12px', borderRadius: '6px', border: 'none', cursor: 'pointer',
      background: active ? '#3b82f6' : '#f1f5f9',
      color: active ? 'white' : '#64748b',
      fontSize: '12px', fontWeight: '600',
    }),
    loadingOverlay: {
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: '60px', color: '#64748b', fontSize: '14px',
    },
    errorBox: {
      padding: '15px', background: '#fef2f2', border: '1px solid #fecaca',
      borderRadius: '8px', color: '#991b1b', fontSize: '13px',
    },
  };

  if (!ticker) {
    return <div style={styles.container}><p>Select a company to view model comparison.</p></div>;
  }

  const successful = leaderboard?.leaderboard?.filter(m => m.status === 'success') || [];
  const failed = leaderboard?.leaderboard?.filter(m => m.status !== 'success') || [];

  // Prepare chart data
  const chartData = successful.map(m => ({
    model: MODEL_NAMES[m.model_type] || m.model_type,
    mape: m.mape ? parseFloat(m.mape.toFixed(2)) : null,
    rmse: m.rmse ? parseFloat(m.rmse.toFixed(2)) : null,
    mae: m.mae ? parseFloat(m.mae.toFixed(2)) : null,
    directional_accuracy: m.directional_accuracy ? parseFloat(m.directional_accuracy.toFixed(1)) : null,
    color: MODEL_COLORS[m.model_type] || '#94a3b8',
    model_type: m.model_type,
  }));

  // Prepare feature importance data (top 15)
  const importanceData = featureImportance?.builtin_importance
    ? Object.entries(featureImportance.builtin_importance)
        .slice(0, 15)
        .map(([name, value]) => ({
          feature: name.replace(/_/g, ' '),
          importance: parseFloat((value * 100).toFixed(2)),
        }))
    : [];

  return (
    <div style={styles.container}>
      {/* Header */}
      <div style={styles.header}>
        <h2 style={styles.title}>Model Comparison - {ticker}</h2>
        <div style={styles.controls}>
          <select
            style={styles.select}
            value={testDays}
            onChange={(e) => setTestDays(parseInt(e.target.value))}
          >
            <option value={15}>15-day backtest</option>
            <option value={30}>30-day backtest</option>
            <option value={60}>60-day backtest</option>
          </select>
          <button
            style={{ ...styles.button, opacity: loading ? 0.7 : 1 }}
            onClick={() => fetchLeaderboard(true)}
            disabled={loading}
          >
            {loading ? 'Running...' : 'Run Backtests'}
          </button>
          <button
            style={{ ...styles.button, background: '#10b981', opacity: loadingFeatures ? 0.7 : 1 }}
            onClick={fetchFeatureImportance}
            disabled={loadingFeatures}
          >
            {loadingFeatures ? 'Loading...' : 'Feature Importance'}
          </button>
        </div>
      </div>

      {error && <div style={styles.errorBox}>{error}</div>}

      {loading && (
        <div style={styles.loadingOverlay}>
          Running backtests across all models... This may take a minute.
        </div>
      )}

      {!loading && leaderboard && (
        <>
          {/* Leaderboard Table */}
          <div style={{ ...styles.card, marginBottom: '20px' }}>
            <h3 style={styles.cardTitle}>
              Leaderboard
              {leaderboard.from_cache && (
                <span style={{ fontSize: '11px', color: '#94a3b8', fontWeight: '400', marginLeft: '8px' }}>
                  (cached)
                </span>
              )}
            </h3>
            <table style={styles.table}>
              <thead>
                <tr>
                  <th style={styles.th}>Rank</th>
                  <th style={styles.th}>Model</th>
                  <th style={styles.th}>MAPE (%)</th>
                  <th style={styles.th}>RMSE ($)</th>
                  <th style={styles.th}>MAE ($)</th>
                  <th style={styles.th}>Direction Acc (%)</th>
                  <th style={styles.th}>Time (s)</th>
                </tr>
              </thead>
              <tbody>
                {successful.map((m, i) => (
                  <tr key={m.model_type} style={{ background: i === 0 ? '#f0fdf4' : 'transparent' }}>
                    <td style={styles.td}>
                      <span style={styles.rankBadge(m.rank || i + 1)}>{m.rank || i + 1}</span>
                    </td>
                    <td style={styles.td}>
                      <span style={styles.modelBadge(m.model_type)}>
                        <span style={styles.modelDot(m.model_type)} />
                        <strong>{MODEL_NAMES[m.model_type] || m.model_type}</strong>
                      </span>
                    </td>
                    <td style={styles.td}>{m.mape?.toFixed(2)}</td>
                    <td style={styles.td}>{m.rmse?.toFixed(2)}</td>
                    <td style={styles.td}>{m.mae?.toFixed(2)}</td>
                    <td style={styles.td}>{m.directional_accuracy?.toFixed(1)}</td>
                    <td style={styles.td}>{m.elapsed_seconds?.toFixed(1)}</td>
                  </tr>
                ))}
                {failed.map(m => (
                  <tr key={m.model_type} style={{ opacity: 0.5 }}>
                    <td style={styles.td}>-</td>
                    <td style={styles.td}>
                      <span style={styles.modelBadge(m.model_type)}>
                        <span style={styles.modelDot(m.model_type)} />
                        {MODEL_NAMES[m.model_type] || m.model_type}
                      </span>
                    </td>
                    <td style={styles.td} colSpan={5}>
                      <span style={{ color: '#ef4444' }}>Error: {m.error}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Charts Grid */}
          <div style={styles.grid}>
            {/* Metric Bar Chart */}
            <div style={styles.card}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '15px' }}>
                <h3 style={{ ...styles.cardTitle, marginBottom: 0 }}>Model Performance</h3>
                <div style={{ display: 'flex', gap: '4px' }}>
                  {[
                    { key: 'mape', label: 'MAPE' },
                    { key: 'rmse', label: 'RMSE' },
                    { key: 'directional_accuracy', label: 'Direction' },
                  ].map(m => (
                    <button
                      key={m.key}
                      style={styles.metricTab(selectedMetric === m.key)}
                      onClick={() => setSelectedMetric(m.key)}
                    >
                      {m.label}
                    </button>
                  ))}
                </div>
              </div>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={chartData} layout="vertical" margin={{ left: 20, right: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                  <XAxis type="number" tick={{ fontSize: 11 }} />
                  <YAxis type="category" dataKey="model" width={100} tick={{ fontSize: 11 }} />
                  <Tooltip
                    formatter={(value, name) => [
                      selectedMetric === 'mape' ? `${value}%` :
                      selectedMetric === 'directional_accuracy' ? `${value}%` : `$${value}`,
                      selectedMetric === 'mape' ? 'MAPE' :
                      selectedMetric === 'rmse' ? 'RMSE' : 'Direction Accuracy'
                    ]}
                  />
                  <Bar dataKey={selectedMetric} radius={[0, 4, 4, 0]}>
                    {chartData.map((entry, index) => (
                      <Cell key={index} fill={entry.color} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
              <p style={{ fontSize: '11px', color: '#94a3b8', textAlign: 'center', marginTop: '8px' }}>
                {selectedMetric === 'directional_accuracy' ? 'Higher is better' : 'Lower is better'}
              </p>
            </div>

            {/* Feature Importance */}
            <div style={styles.card}>
              <h3 style={styles.cardTitle}>Feature Importance (XGBoost)</h3>
              {importanceData.length > 0 ? (
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart data={importanceData} layout="vertical" margin={{ left: 40, right: 20 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                    <XAxis type="number" tick={{ fontSize: 11 }} />
                    <YAxis type="category" dataKey="feature" width={120} tick={{ fontSize: 10 }} />
                    <Tooltip formatter={(value) => [`${value}%`, 'Importance']} />
                    <Bar dataKey="importance" fill="#e74c3c" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div style={{ ...styles.loadingOverlay, padding: '40px' }}>
                  {loadingFeatures
                    ? 'Computing feature importance...'
                    : 'Click "Feature Importance" to analyze which features drive predictions.'}
                </div>
              )}
            </div>
          </div>

          {/* Best Model Summary */}
          {leaderboard.best_model && (
            <div style={{
              ...styles.card,
              borderLeft: `4px solid ${MODEL_COLORS[leaderboard.best_model]}`,
              background: '#f0fdf4',
            }}>
              <h3 style={{ ...styles.cardTitle, color: '#166534' }}>
                Best Model: {MODEL_NAMES[leaderboard.best_model]}
              </h3>
              <p style={{ color: '#475569', fontSize: '13px', lineHeight: '1.6', margin: 0 }}>
                Based on {testDays}-day backtest, <strong>{MODEL_NAMES[leaderboard.best_model]}</strong> achieved
                the lowest MAPE of <strong>{successful[0]?.mape?.toFixed(2)}%</strong> with
                a directional accuracy of <strong>{successful[0]?.directional_accuracy?.toFixed(1)}%</strong>.
                {successful.length > 1 && (
                  <> The runner-up was <strong>{MODEL_NAMES[successful[1]?.model_type]}</strong> with
                  MAPE of <strong>{successful[1]?.mape?.toFixed(2)}%</strong>.</>
                )}
              </p>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default ModelComparisonDashboard;
