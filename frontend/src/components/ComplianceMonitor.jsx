import React, { useState, useEffect, useCallback } from 'react';
import { useAuth } from './AuthProvider';

// ============================================================================
// Compliance Monitor - Regulatory Alert Dashboard
// ============================================================================

// Icons
const Icons = {
  Shield: () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    </svg>
  ),
  Alert: () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  ),
  Calendar: () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
      <line x1="16" y1="2" x2="16" y2="6" />
      <line x1="8" y1="2" x2="8" y2="6" />
      <line x1="3" y1="10" x2="21" y2="10" />
    </svg>
  ),
  Chart: () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="18" y1="20" x2="18" y2="10" />
      <line x1="12" y1="20" x2="12" y2="4" />
      <line x1="6" y1="20" x2="6" y2="14" />
    </svg>
  ),
  Check: () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  ),
  ExternalLink: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
      <polyline points="15 3 21 3 21 9" />
      <line x1="10" y1="14" x2="21" y2="3" />
    </svg>
  ),
  Refresh: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="23 4 23 10 17 10" />
      <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
    </svg>
  )
};

// Severity colors
const SEVERITY_COLORS = {
  CRITICAL: '#dc2626',
  HIGH: '#f59e0b',
  MEDIUM: '#3b82f6',
  LOW: '#22c55e',
  INFO: '#6b7280'
};

const IMPACT_COLORS = {
  CRITICAL: '#dc2626',
  HIGH: '#f59e0b',
  MEDIUM: '#3b82f6',
  LOW: '#22c55e'
};

// ============================================================================
// Alert Overview Tab
// ============================================================================

function AlertOverview({ summary, alerts, onRefresh, loading, onAcknowledge }) {
  const pendingAlerts = alerts?.filter(a => a.status === 'UNACKNOWLEDGED') || [];

  // Count unique regulations that have alerts
  const uniqueRegulations = summary?.total_regulations || 0;

  return (
    <div style={{ padding: '20px' }}>
      {/* Primary Metric: Regulations (not alerts) */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', marginBottom: '16px' }}>
        <div style={{ ...styles.summaryCard, borderLeft: '4px solid #3b82f6' }}>
          <div style={{ fontSize: '36px', fontWeight: '700', color: '#3b82f6' }}>
            {uniqueRegulations}
          </div>
          <div style={{ color: '#1e293b', marginTop: '4px', fontWeight: '600' }}>Active Regulations</div>
          <div style={{ color: '#64748b', fontSize: '12px', marginTop: '2px' }}>From tracked agencies</div>
        </div>
        <div style={styles.summaryCard}>
          <div style={{ fontSize: '32px', fontWeight: '700', color: '#dc2626' }}>
            {summary?.alerts_by_impact?.CRITICAL || 0}
          </div>
          <div style={{ color: '#64748b', marginTop: '4px' }}>Critical Impact</div>
        </div>
        <div style={styles.summaryCard}>
          <div style={{ fontSize: '32px', fontWeight: '700', color: '#f59e0b' }}>
            {summary?.alerts_by_impact?.HIGH || 0}
          </div>
          <div style={{ color: '#64748b', marginTop: '4px' }}>High Impact</div>
        </div>
        <div style={styles.summaryCard}>
          <div style={{ fontSize: '32px', fontWeight: '700', color: '#22c55e' }}>
            {summary?.alerts_by_status?.ACKNOWLEDGED || 0}
          </div>
          <div style={{ color: '#64748b', marginTop: '4px' }}>Acknowledged</div>
        </div>
      </div>

      {/* Note explaining alerts vs regulations */}
      <div style={{
        marginBottom: '16px',
        padding: '8px 12px',
        background: '#f0f9ff',
        borderRadius: '6px',
        fontSize: '12px',
        color: '#0369a1',
        display: 'flex',
        alignItems: 'center',
        gap: '8px'
      }}>
        <Icons.Alert />
        <span>
          <strong>{summary?.total_active_alerts || 0} company-specific alerts</strong> generated from {uniqueRegulations} regulations × tracked companies (only shown when relevance score ≥50%)
        </span>
      </div>

      {/* Agency Breakdown */}
      <div style={{ marginBottom: '24px' }}>
        <h3 style={{ margin: '0 0 12px 0', color: '#1e293b', fontSize: '16px' }}>Regulations by Agency</h3>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
          {Object.entries(summary?.regulations_by_agency || {}).map(([agency, count]) => (
            <div key={agency} style={styles.agencyBadge}>
              <span style={{ fontWeight: '600' }}>{agency}</span>
              <span style={styles.agencyCount}>{count}</span>
            </div>
          ))}
          {Object.keys(summary?.regulations_by_agency || {}).length === 0 && (
            <div style={{ color: '#64748b', fontStyle: 'italic' }}>No regulations ingested yet</div>
          )}
        </div>
      </div>

      {/* Impact Rating & Relevance Legend */}
      <div style={{ marginBottom: '24px', padding: '12px 16px', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '32px' }}>
          <div>
            <div style={{ fontSize: '13px', fontWeight: '600', color: '#475569', marginBottom: '8px' }}>Impact Rating</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span style={{ ...styles.impactBadge, backgroundColor: '#dc2626' }}>CRITICAL</span>
                <span style={{ fontSize: '12px', color: '#64748b' }}>Immediate action required</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span style={{ ...styles.impactBadge, backgroundColor: '#f59e0b' }}>HIGH</span>
                <span style={{ fontSize: '12px', color: '#64748b' }}>Review promptly</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span style={{ ...styles.impactBadge, backgroundColor: '#3b82f6' }}>MEDIUM</span>
                <span style={{ fontSize: '12px', color: '#64748b' }}>Monitor</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span style={{ ...styles.impactBadge, backgroundColor: '#22c55e' }}>LOW</span>
                <span style={{ fontSize: '12px', color: '#64748b' }}>Informational</span>
              </div>
            </div>
          </div>
          <div>
            <div style={{ fontSize: '13px', fontWeight: '600', color: '#475569', marginBottom: '8px' }}>Relevance Score (%)</div>
            <div style={{ fontSize: '12px', color: '#64748b', lineHeight: '1.6' }}>
              <div><strong>Calculation:</strong> Agency Relevance (40%) + Keywords (40%) + Base (10%)</div>
              <div style={{ marginTop: '4px', paddingLeft: '8px', borderLeft: '2px solid #e2e8f0' }}>
                • <strong>Agency:</strong> SEC=high for all, FCC=low for software<br/>
                • <strong>Keywords:</strong> 15% per business-relevant match<br/>
                • <strong>Threshold:</strong> ≥50% required to generate alert
              </div>
              <div style={{ marginTop: '6px' }}>
                <strong>70%+</strong> → CRITICAL | <strong>60-70%</strong> → HIGH | <strong>50-60%</strong> → MEDIUM
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Pending Alerts List */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
          <h3 style={{ margin: 0, color: '#1e293b', fontSize: '16px' }}>Pending Alerts ({pendingAlerts.length})</h3>
          <button onClick={onRefresh} disabled={loading} style={styles.refreshButton}>
            <Icons.Refresh /> {loading ? 'Loading...' : 'Refresh'}
          </button>
        </div>

        {pendingAlerts.length === 0 ? (
          <div style={styles.emptyState}>
            <Icons.Check />
            <p>No pending alerts. All caught up!</p>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {pendingAlerts.slice(0, 10).map(alert => (
              <AlertCard key={alert.id} alert={alert} onAcknowledge={onAcknowledge} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function AlertCard({ alert: alertData, onAcknowledge }) {
  const [acknowledging, setAcknowledging] = useState(false);
  const isAcknowledged = alertData.status === 'ACKNOWLEDGED';

  const handleAcknowledge = async () => {
    if (isAcknowledged || acknowledging) return;
    setAcknowledging(true);
    try {
      const response = await fetch(`/api/regulatory/alerts/${alertData.id}/acknowledge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      if (response.ok) {
        if (onAcknowledge) onAcknowledge(alertData.id);
      } else {
        console.error('Failed to acknowledge alert');
      }
    } catch (error) {
      console.error('Error acknowledging alert:', error);
    }
    setAcknowledging(false);
  };

  return (
    <div style={styles.alertCard}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
            <span style={{ ...styles.impactBadge, backgroundColor: IMPACT_COLORS[alertData.impact_level] || '#6b7880' }}>
              {alertData.impact_level}
            </span>
            <span style={styles.agencyTag}>{alertData.agency}</span>
            {isAcknowledged && (
              <span style={styles.acknowledgedBadge}>
                <Icons.Check /> Acknowledged
              </span>
            )}
          </div>
          <div style={{ fontWeight: '500', color: '#1e293b', marginBottom: '4px' }}>
            {alertData.regulation_title?.substring(0, 100)}{alertData.regulation_title?.length > 100 ? '...' : ''}
          </div>
          <div style={{ fontSize: '13px', color: '#64748b' }}>
            Affects: <strong>{alertData.ticker}</strong> ({alertData.company_name}) |
            Relevance: {(alertData.relevance_score * 100).toFixed(0)}%
            {alertData.effective_date && ` | Effective: ${alertData.effective_date}`}
          </div>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          {!isAcknowledged && (
            <button
              onClick={handleAcknowledge}
              disabled={acknowledging}
              style={styles.acknowledgeButton}
              title="Mark as acknowledged"
            >
              {acknowledging ? '...' : <Icons.Check />}
            </button>
          )}
          {alertData.source_url && (
            <a href={alertData.source_url} target="_blank" rel="noopener noreferrer" style={styles.linkButton}>
              <Icons.ExternalLink />
            </a>
          )}
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// Regulation Timeline Tab
// ============================================================================

function RegulationTimeline({ regulations, summary }) {
  const upcoming = summary?.upcoming_regulations || [];

  return (
    <div style={{ padding: '20px' }}>
      <h3 style={{ margin: '0 0 16px 0', color: '#1e293b', fontSize: '16px' }}>
        Upcoming Effective Dates
      </h3>

      {upcoming.length === 0 ? (
        <div style={styles.emptyState}>
          <Icons.Calendar />
          <p>No upcoming regulation effective dates</p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginBottom: '32px' }}>
          {upcoming.map(reg => (
            <div key={reg.id} style={styles.timelineItem}>
              <div style={styles.timelineDate}>
                {reg.effective_date || 'TBD'}
              </div>
              <div style={styles.timelineDot(reg.severity)} />
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span style={styles.agencyTag}>{reg.agency}</span>
                  <span style={{ ...styles.severityBadge, backgroundColor: SEVERITY_COLORS[reg.severity] || '#6b7280' }}>
                    {reg.severity}
                  </span>
                </div>
                <div style={{ fontWeight: '500', color: '#1e293b', marginTop: '4px' }}>
                  {reg.title}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      <h3 style={{ margin: '24px 0 16px 0', color: '#1e293b', fontSize: '16px' }}>
        Recent Regulations ({regulations?.length || 0})
      </h3>

      {(regulations || []).length === 0 ? (
        <div style={styles.emptyState}>
          <Icons.Shield />
          <p>No regulations in database. Use "Ingest Regulations" to fetch from Federal Register.</p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {(regulations || []).slice(0, 15).map(reg => (
            <div key={reg.id} style={styles.regulationCard}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                    <span style={styles.agencyTag}>{reg.agency}</span>
                    <span style={{ ...styles.severityBadge, backgroundColor: SEVERITY_COLORS[reg.severity] || '#6b7280' }}>
                      {reg.severity}
                    </span>
                  </div>
                  <div style={{ fontWeight: '500', color: '#1e293b' }}>{reg.title}</div>
                  {reg.summary && (
                    <div style={{ fontSize: '13px', color: '#64748b', marginTop: '4px' }}>
                      {reg.summary.substring(0, 200)}{reg.summary.length > 200 ? '...' : ''}
                    </div>
                  )}
                  <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '4px' }}>
                    Published: {reg.publication_date || 'N/A'}
                    {reg.effective_date && ` | Effective: ${reg.effective_date}`}
                  </div>
                </div>
                {reg.source_url && (
                  <a href={reg.source_url} target="_blank" rel="noopener noreferrer" style={styles.linkButton}>
                    <Icons.ExternalLink />
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Impact Analysis - Company Risk Exposure
// ============================================================================

function ImpactAnalysis({ alerts, companies }) {
  // Aggregate by company - show meaningful metrics
  const companyStats = {};

  (alerts || []).forEach(alert => {
    const ticker = alert.ticker;
    if (!companyStats[ticker]) {
      companyStats[ticker] = {
        ticker,
        companyName: alert.company_name,
        totalAlerts: 0,
        criticalCount: 0,
        highCount: 0,
        mediumCount: 0,
        lowCount: 0,
        avgRelevance: 0,
        maxRelevance: 0,
        agencies: new Set(),
        relevanceSum: 0
      };
    }
    const stats = companyStats[ticker];
    stats.totalAlerts++;
    stats.relevanceSum += alert.relevance_score || 0;
    stats.maxRelevance = Math.max(stats.maxRelevance, alert.relevance_score || 0);
    stats.agencies.add(alert.agency);

    if (alert.impact_level === 'CRITICAL') stats.criticalCount++;
    else if (alert.impact_level === 'HIGH') stats.highCount++;
    else if (alert.impact_level === 'MEDIUM') stats.mediumCount++;
    else stats.lowCount++;
  });

  // Calculate averages and convert to array
  const companyData = Object.values(companyStats)
    .map(stats => ({
      ...stats,
      avgRelevance: stats.totalAlerts > 0 ? stats.relevanceSum / stats.totalAlerts : 0,
      agencyCount: stats.agencies.size,
      agencies: Array.from(stats.agencies)
    }))
    .sort((a, b) => (b.criticalCount + b.highCount) - (a.criticalCount + a.highCount));

  const getRiskLevel = (stats) => {
    if (stats.criticalCount > 0) return { level: 'CRITICAL', color: '#dc2626' };
    if (stats.highCount > 0) return { level: 'HIGH', color: '#f59e0b' };
    if (stats.mediumCount > 0) return { level: 'MEDIUM', color: '#3b82f6' };
    return { level: 'LOW', color: '#22c55e' };
  };

  return (
    <div style={{ padding: '20px' }}>
      <h3 style={{ margin: '0 0 8px 0', color: '#1e293b', fontSize: '16px' }}>
        Company Regulatory Exposure
      </h3>
      <p style={{ color: '#64748b', fontSize: '13px', marginBottom: '16px' }}>
        Aggregated view of regulatory impact by company. Sorted by critical + high impact alerts.
      </p>

      {companyData.length === 0 ? (
        <div style={styles.emptyState}>
          <Icons.Chart />
          <p>No regulatory impact data available. Ingest regulations to generate impact analysis.</p>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '16px' }}>
          {companyData.slice(0, 20).map(stats => {
            const risk = getRiskLevel(stats);
            return (
              <div key={stats.ticker} style={{
                background: '#fff',
                border: '1px solid #e2e8f0',
                borderRadius: '8px',
                padding: '16px',
                borderLeft: `4px solid ${risk.color}`
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                  <div>
                    <div style={{ fontWeight: '700', fontSize: '16px', color: '#1e293b' }}>{stats.ticker}</div>
                    <div style={{ fontSize: '12px', color: '#64748b' }}>{stats.companyName}</div>
                  </div>
                  <div style={{
                    padding: '4px 8px',
                    borderRadius: '4px',
                    fontSize: '11px',
                    fontWeight: '600',
                    backgroundColor: `${risk.color}15`,
                    color: risk.color
                  }}>
                    {risk.level} RISK
                  </div>
                </div>

                {/* Impact breakdown bar */}
                <div style={{ marginBottom: '12px' }}>
                  <div style={{ fontSize: '12px', color: '#64748b', marginBottom: '4px' }}>
                    Impact Distribution ({stats.totalAlerts} alerts)
                  </div>
                  <div style={{ display: 'flex', height: '8px', borderRadius: '4px', overflow: 'hidden', background: '#f1f5f9' }}>
                    {stats.criticalCount > 0 && (
                      <div style={{ width: `${(stats.criticalCount / stats.totalAlerts) * 100}%`, background: '#dc2626' }} title={`Critical: ${stats.criticalCount}`} />
                    )}
                    {stats.highCount > 0 && (
                      <div style={{ width: `${(stats.highCount / stats.totalAlerts) * 100}%`, background: '#f59e0b' }} title={`High: ${stats.highCount}`} />
                    )}
                    {stats.mediumCount > 0 && (
                      <div style={{ width: `${(stats.mediumCount / stats.totalAlerts) * 100}%`, background: '#3b82f6' }} title={`Medium: ${stats.mediumCount}`} />
                    )}
                    {stats.lowCount > 0 && (
                      <div style={{ width: `${(stats.lowCount / stats.totalAlerts) * 100}%`, background: '#22c55e' }} title={`Low: ${stats.lowCount}`} />
                    )}
                  </div>
                </div>

                {/* Stats row */}
                <div style={{ display: 'flex', gap: '16px', fontSize: '12px' }}>
                  <div>
                    <span style={{ color: '#64748b' }}>Avg Relevance: </span>
                    <span style={{ fontWeight: '600', color: '#1e293b' }}>{(stats.avgRelevance * 100).toFixed(0)}%</span>
                  </div>
                  <div>
                    <span style={{ color: '#64748b' }}>Agencies: </span>
                    <span style={{ fontWeight: '600', color: '#1e293b' }}>{stats.agencyCount}</span>
                  </div>
                </div>

                {/* Agency tags */}
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginTop: '8px' }}>
                  {stats.agencies.slice(0, 4).map(agency => (
                    <span key={agency} style={{
                      fontSize: '10px',
                      padding: '2px 6px',
                      background: '#f1f5f9',
                      borderRadius: '4px',
                      color: '#475569'
                    }}>
                      {agency}
                    </span>
                  ))}
                  {stats.agencies.length > 4 && (
                    <span style={{ fontSize: '10px', color: '#94a3b8' }}>+{stats.agencies.length - 4} more</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Legend */}
      <div style={{ display: 'flex', gap: '16px', marginTop: '20px', flexWrap: 'wrap', padding: '12px', background: '#f8fafc', borderRadius: '6px' }}>
        <span style={{ fontSize: '12px', color: '#64748b', fontWeight: '500' }}>Impact Legend:</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <div style={{ width: '12px', height: '12px', backgroundColor: '#dc2626', borderRadius: '2px' }} />
          <span style={{ fontSize: '12px', color: '#64748b' }}>Critical</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <div style={{ width: '12px', height: '12px', backgroundColor: '#f59e0b', borderRadius: '2px' }} />
          <span style={{ fontSize: '12px', color: '#64748b' }}>High</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <div style={{ width: '12px', height: '12px', backgroundColor: '#3b82f6', borderRadius: '2px' }} />
          <span style={{ fontSize: '12px', color: '#64748b' }}>Medium</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <div style={{ width: '12px', height: '12px', backgroundColor: '#22c55e', borderRadius: '2px' }} />
          <span style={{ fontSize: '12px', color: '#64748b' }}>Low</span>
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// Compliance Status Tab
// ============================================================================

function ComplianceStatus({ alerts, companies, selectedTicker, onAcknowledge }) {
  const [ticker, setTicker] = useState(selectedTicker || '');
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);

  const fetchStatus = useCallback(async (t) => {
    if (!t) return;
    setLoading(true);
    try {
      const response = await fetch(`/api/regulatory/company/${t}/alerts`);
      const data = await response.json();
      setStatus(data);
    } catch (error) {
      console.error('Error fetching compliance status:', error);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    if (ticker) {
      fetchStatus(ticker);
    }
  }, [ticker, fetchStatus]);

  const companyAlerts = status?.alerts || [];
  const criticalCount = companyAlerts.filter(a => a.impact_level === 'CRITICAL').length;
  const highCount = companyAlerts.filter(a => a.impact_level === 'HIGH').length;

  return (
    <div style={{ padding: '20px' }}>
      <div style={{ marginBottom: '20px' }}>
        <label style={{ display: 'block', marginBottom: '8px', fontWeight: '500', color: '#1e293b' }}>
          Select Company
        </label>
        <select
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          style={styles.select}
        >
          <option value="">-- Select a company --</option>
          {(companies || []).map(c => (
            <option key={c.ticker} value={c.ticker}>
              {c.ticker} - {c.company_name}
            </option>
          ))}
        </select>
      </div>

      {loading && <div style={{ color: '#64748b' }}>Loading compliance status...</div>}

      {ticker && status && !loading && (
        <>
          {/* Risk Summary */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '12px', marginBottom: '24px' }}>
            <div style={{ ...styles.summaryCard, borderLeft: `4px solid ${IMPACT_COLORS.CRITICAL}` }}>
              <div style={{ fontSize: '24px', fontWeight: '700', color: IMPACT_COLORS.CRITICAL }}>{criticalCount}</div>
              <div style={{ color: '#64748b', fontSize: '13px' }}>Critical</div>
            </div>
            <div style={{ ...styles.summaryCard, borderLeft: `4px solid ${IMPACT_COLORS.HIGH}` }}>
              <div style={{ fontSize: '24px', fontWeight: '700', color: IMPACT_COLORS.HIGH }}>{highCount}</div>
              <div style={{ color: '#64748b', fontSize: '13px' }}>High</div>
            </div>
            <div style={{ ...styles.summaryCard, borderLeft: `4px solid ${IMPACT_COLORS.MEDIUM}` }}>
              <div style={{ fontSize: '24px', fontWeight: '700', color: IMPACT_COLORS.MEDIUM }}>{companyAlerts.length - criticalCount - highCount}</div>
              <div style={{ color: '#64748b', fontSize: '13px' }}>Medium/Low</div>
            </div>
            <div style={{ ...styles.summaryCard, borderLeft: '4px solid #22c55e' }}>
              <div style={{ fontSize: '24px', fontWeight: '700', color: '#1e293b' }}>{companyAlerts.length}</div>
              <div style={{ color: '#64748b', fontSize: '13px' }}>Total Alerts</div>
            </div>
          </div>

          {/* Alert List */}
          <h3 style={{ margin: '0 0 12px 0', color: '#1e293b', fontSize: '16px' }}>
            Regulatory Alerts for {ticker}
          </h3>

          {companyAlerts.length === 0 ? (
            <div style={styles.emptyState}>
              <Icons.Check />
              <p>No regulatory alerts for {ticker}</p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {companyAlerts.map(alert => (
                <AlertCard key={alert.id} alert={alert} onAcknowledge={onAcknowledge} />
              ))}
            </div>
          )}
        </>
      )}

      {!ticker && (
        <div style={styles.emptyState}>
          <Icons.Shield />
          <p>Select a company to view compliance status</p>
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Main Component
// ============================================================================

function ComplianceMonitor({ ticker = null }) {
  const { authenticatedFetch } = useAuth();
  const [activeSubTab, setActiveSubTab] = useState('overview');
  const [summary, setSummary] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [regulations, setRegulations] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [ingesting, setIngesting] = useState(false);
  const [ingestionProgress, setIngestionProgress] = useState(null);

  const subTabs = [
    { id: 'overview', label: 'Alert Overview', icon: Icons.Alert },
    { id: 'timeline', label: 'Regulation Timeline', icon: Icons.Calendar },
    { id: 'impact', label: 'Impact Analysis', icon: Icons.Chart },
    { id: 'status', label: 'Compliance Status', icon: Icons.Check }
  ];

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [summaryRes, alertsRes, regulationsRes, companiesRes] = await Promise.all([
        fetch('/api/regulatory/dashboard/summary'),
        fetch('/api/regulatory/alerts?limit=100'),
        fetch('/api/regulatory/regulations?limit=50'),
        fetch('/api/companies/db')
      ]);

      const summaryData = await summaryRes.json();
      const alertsData = await alertsRes.json();
      const regulationsData = await regulationsRes.json();
      const companiesData = await companiesRes.json();

      setSummary(summaryData);
      setAlerts(alertsData.alerts || []);
      setRegulations(regulationsData.regulations || []);
      setCompanies(companiesData || []);
    } catch (error) {
      console.error('Error fetching regulatory data:', error);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleAcknowledge = useCallback((alertId) => {
    // Refresh data after acknowledging
    fetchData();
  }, [fetchData]);

  const pollIngestionStatus = useCallback(async () => {
    try {
      const response = await authenticatedFetch('/api/regulatory/ingest/status');
      const status = await response.json();
      setIngestionProgress(status);

      if (status.status === 'completed') {
        setIngesting(false);
        let message = `Ingestion complete!\n`;
        if (status.stats) {
          message += `Created: ${status.stats.regulations_created || 0} regulations\n`;
          message += `Negative filtered: ${status.stats.negative_filtered || 0}\n`;
          message += `LLM filtered: ${status.stats.regulations_skipped || 0}\n`;
          message += `Alerts: ${status.stats.alerts_created || 0}`;
        }
        alert(message);
        setIngestionProgress(null);
        fetchData();
        return true; // Stop polling
      } else if (status.status === 'error') {
        setIngesting(false);
        alert(`Ingestion failed: ${status.error || 'Unknown error'}`);
        setIngestionProgress(null);
        return true; // Stop polling
      }
      return false; // Continue polling
    } catch (error) {
      console.error('Error polling ingestion status:', error);
      return false; // Continue polling on error
    }
  }, [authenticatedFetch, fetchData]);

  const handleIngest = async () => {
    const clearExisting = window.confirm(
      'Clear existing regulatory data before ingesting?\n\n' +
      'Click OK to clear and re-fetch (recommended for fresh start)\n' +
      'Click Cancel to add to existing data'
    );

    if (!window.confirm('This will fetch regulations from Federal Register API (runs in background). Continue?')) {
      return;
    }

    setIngesting(true);
    setIngestionProgress({ status: 'starting', progress: 0, message: 'Starting ingestion...' });

    try {
      const response = await authenticatedFetch('/api/regulatory/ingest', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ clear_existing: clearExisting })
      });

      const result = await response.json();

      if (response.status === 202) {
        // Ingestion started - begin polling
        const pollInterval = setInterval(async () => {
          const shouldStop = await pollIngestionStatus();
          if (shouldStop) {
            clearInterval(pollInterval);
          }
        }, 2000); // Poll every 2 seconds
      } else if (response.status === 409) {
        // Already running
        alert('Ingestion is already in progress. Please wait for it to complete.');
        setIngesting(false);
        setIngestionProgress(null);
      } else {
        alert(`Failed to start ingestion: ${result.error || result.message || 'Unknown error'}`);
        setIngesting(false);
        setIngestionProgress(null);
      }
    } catch (error) {
      alert(`Ingestion error: ${error.message}`);
      setIngesting(false);
      setIngestionProgress(null);
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
            {tab.label}
          </div>
        ))}
        <div style={{ flex: 1 }} />
        {ingesting && ingestionProgress && (
          <div style={styles.progressContainer}>
            <div style={styles.progressBar}>
              <div style={{ ...styles.progressFill, width: `${ingestionProgress.progress || 0}%` }} />
            </div>
            <span style={styles.progressText}>
              {ingestionProgress.progress || 0}% - {ingestionProgress.message || 'Processing...'}
            </span>
          </div>
        )}
        <button
          onClick={handleIngest}
          disabled={ingesting}
          style={styles.ingestButton}
        >
          {ingesting ? 'Ingesting...' : 'Ingest Regulations'}
        </button>
      </div>

      {/* Content */}
      <div style={styles.content}>
        {loading ? (
          <div style={{ padding: '40px', textAlign: 'center', color: '#64748b' }}>
            Loading regulatory data...
          </div>
        ) : (
          <>
            {activeSubTab === 'overview' && (
              <AlertOverview
                summary={summary}
                alerts={alerts}
                onRefresh={fetchData}
                loading={loading}
                onAcknowledge={handleAcknowledge}
              />
            )}
            {activeSubTab === 'timeline' && (
              <RegulationTimeline
                regulations={regulations}
                summary={summary}
              />
            )}
            {activeSubTab === 'impact' && (
              <ImpactAnalysis
                alerts={alerts}
                companies={companies}
              />
            )}
            {activeSubTab === 'status' && (
              <ComplianceStatus
                alerts={alerts}
                companies={companies}
                selectedTicker={ticker}
                onAcknowledge={handleAcknowledge}
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// Styles
// ============================================================================

const styles = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: 'calc(100vh - 300px)',
    minHeight: '500px',
    background: '#fff',
    borderRadius: '8px',
    border: '1px solid #e2e8f0'
  },
  tabBar: {
    display: 'flex',
    gap: '4px',
    padding: '8px',
    background: '#f8fafc',
    borderRadius: '8px 8px 0 0',
    borderBottom: '1px solid #e2e8f0',
    alignItems: 'center',
    flexWrap: 'wrap'
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
  content: {
    flex: 1,
    overflow: 'auto'
  },
  summaryCard: {
    background: '#f8fafc',
    borderRadius: '8px',
    padding: '16px',
    border: '1px solid #e2e8f0'
  },
  agencyBadge: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '6px',
    padding: '6px 12px',
    background: '#f1f5f9',
    borderRadius: '6px',
    fontSize: '13px',
    color: '#1e293b'
  },
  agencyCount: {
    background: '#3b82f6',
    color: '#fff',
    borderRadius: '4px',
    padding: '2px 6px',
    fontSize: '11px',
    fontWeight: '600'
  },
  agencyTag: {
    display: 'inline-block',
    padding: '2px 8px',
    background: '#e2e8f0',
    borderRadius: '4px',
    fontSize: '11px',
    fontWeight: '600',
    color: '#475569'
  },
  impactBadge: {
    display: 'inline-block',
    padding: '2px 8px',
    borderRadius: '4px',
    fontSize: '11px',
    fontWeight: '600',
    color: '#fff'
  },
  severityBadge: {
    display: 'inline-block',
    padding: '2px 8px',
    borderRadius: '4px',
    fontSize: '11px',
    fontWeight: '600',
    color: '#fff'
  },
  alertCard: {
    background: '#fff',
    border: '1px solid #e2e8f0',
    borderRadius: '8px',
    padding: '16px',
    boxShadow: '0 1px 2px rgba(0,0,0,0.05)'
  },
  regulationCard: {
    background: '#fff',
    border: '1px solid #e2e8f0',
    borderRadius: '8px',
    padding: '16px',
    boxShadow: '0 1px 2px rgba(0,0,0,0.05)'
  },
  refreshButton: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    padding: '8px 12px',
    background: '#f1f5f9',
    border: '1px solid #e2e8f0',
    borderRadius: '6px',
    cursor: 'pointer',
    fontSize: '13px',
    color: '#475569'
  },
  ingestButton: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    padding: '8px 16px',
    background: '#3b82f6',
    border: 'none',
    borderRadius: '6px',
    cursor: 'pointer',
    fontSize: '13px',
    color: '#fff',
    fontWeight: '500'
  },
  linkButton: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: '32px',
    height: '32px',
    background: '#f1f5f9',
    borderRadius: '6px',
    color: '#475569',
    textDecoration: 'none'
  },
  acknowledgeButton: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: '32px',
    height: '32px',
    background: '#22c55e',
    border: 'none',
    borderRadius: '6px',
    color: '#fff',
    cursor: 'pointer',
    transition: 'background 150ms ease'
  },
  acknowledgedBadge: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '4px',
    padding: '2px 8px',
    background: '#dcfce7',
    borderRadius: '4px',
    fontSize: '11px',
    fontWeight: '500',
    color: '#166534'
  },
  emptyState: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '40px',
    color: '#64748b',
    textAlign: 'center'
  },
  select: {
    width: '100%',
    maxWidth: '400px',
    padding: '10px 12px',
    borderRadius: '6px',
    border: '1px solid #e2e8f0',
    fontSize: '14px',
    color: '#1e293b'
  },
  timelineItem: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: '12px',
    padding: '12px',
    background: '#f8fafc',
    borderRadius: '8px'
  },
  timelineDate: {
    minWidth: '100px',
    fontSize: '13px',
    fontWeight: '600',
    color: '#1e293b'
  },
  timelineDot: (severity) => ({
    width: '12px',
    height: '12px',
    borderRadius: '50%',
    backgroundColor: SEVERITY_COLORS[severity] || '#6b7280',
    marginTop: '4px'
  }),
  heatMapTable: {
    width: '100%',
    borderCollapse: 'collapse',
    fontSize: '12px'
  },
  heatMapHeader: {
    padding: '8px',
    background: '#f1f5f9',
    border: '1px solid #e2e8f0',
    textAlign: 'left',
    fontWeight: '600',
    color: '#475569'
  },
  heatMapCell: {
    padding: '8px',
    border: '1px solid #e2e8f0',
    fontSize: '12px'
  },
  progressContainer: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
    marginRight: '12px'
  },
  progressBar: {
    width: '150px',
    height: '8px',
    background: '#e2e8f0',
    borderRadius: '4px',
    overflow: 'hidden'
  },
  progressFill: {
    height: '100%',
    background: '#3b82f6',
    transition: 'width 300ms ease'
  },
  progressText: {
    fontSize: '12px',
    color: '#64748b',
    maxWidth: '300px',
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis'
  }
};

export default ComplianceMonitor;
