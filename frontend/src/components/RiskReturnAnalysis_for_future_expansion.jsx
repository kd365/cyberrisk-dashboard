// frontend/src/components/RiskReturnAnalysis.jsx
import React, { useState, useEffect } from 'react';
import { ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, Legend, Cell } from 'recharts';

function RiskReturnAnalysis() {
  const [companies, setCompanies] = useState([]);
  
  useEffect(() => {
    // Get predictions for multiple companies
    fetch('/api/portfolio/analyze')
      .then(res => res.json())
      .then(data => setCompanies(data.companies));
  }, []);
  
  // Color code by recommendation
  const getColor = (recommendation) => {
    if (recommendation.includes('STRONG BUY')) return '#00C49F';
    if (recommendation.includes('BUY')) return '#0088FE';
    if (recommendation.includes('HOLD')) return '#FFBB28';
    return '#FF8042';
  };
  
  return (
    <div className="risk-return-container">
      <h2>Risk-Adjusted Return Analysis</h2>
      
      <ScatterChart width={700} height={400}>
        <CartesianGrid />
        <XAxis 
          type="number" 
          dataKey="current_volatility" 
          name="Risk (Volatility)" 
          label={{ value: 'Risk (Volatility)', position: 'bottom' }}
        />
        <YAxis 
          type="number" 
          dataKey="predicted_30d_return_pct" 
          name="Expected Return %" 
          label={{ value: 'Expected Return (%)', angle: -90, position: 'left' }}
        />
        <Tooltip cursor={{ strokeDasharray: '3 3' }} />
        <Legend />
        
        <Scatter 
          name="Companies" 
          data={companies} 
          fill="#8884d8"
        >
          {companies.map((entry, index) => (
            <Cell key={`cell-${index}`} fill={getColor(entry.recommendation)} />
          ))}
        </Scatter>
      </ScatterChart>
      
      {/* Company Cards */}
      <div className="company-grid">
        {companies.map(company => (
          <div key={company.ticker} className="company-card">
            <h3>{company.ticker}</h3>
            <p className="return">
              Expected Return: <strong>{company.predicted_30d_return_pct.toFixed(2)}%</strong>
            </p>
            <p className="risk">
              Volatility: {(company.current_volatility * 100).toFixed(2)}%
            </p>
            <p className="cyber-risk">
              Cyber Risk Score: {company.cyber_risk_score}/100
            </p>
            <p className={`recommendation ${company.recommendation.split(' ')[0].toLowerCase()}`}>
              {company.recommendation}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

export default RiskReturnAnalysis;