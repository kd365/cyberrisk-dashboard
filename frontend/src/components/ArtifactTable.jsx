import React, { useState, useEffect } from 'react';

function ArtifactTable({ selectedTicker }) {
  const [allArtifacts, setAllArtifacts] = useState([]);
  const [filteredArtifacts, setFilteredArtifacts] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage] = useState(10);
  const [typeFilter, setTypeFilter] = useState('all');
  const [selectedCompanyTicker, setSelectedCompanyTicker] = useState('');
  const [companies, setCompanies] = useState([]);
  const [companyNameMap, setCompanyNameMap] = useState({});
  const [sortBy, setSortBy] = useState('date');
  const [sortOrder, setSortOrder] = useState('desc');

  useEffect(() => {
    fetchAllArtifacts();
  }, []);

  const fetchAllArtifacts = async () => {
    setIsLoading(true);
    setError(null);
    try {
      // Fetch both artifacts and companies
      const [artifactsRes, companiesRes] = await Promise.all([
        fetch(`/api/all-artifacts`),
        fetch(`/api/companies`)
      ]);
      
      if (!artifactsRes.ok || !companiesRes.ok) {
        throw new Error(`API error`);
      }
      
      const artifactData = await artifactsRes.json();
      const companiesData = await companiesRes.json();
      
      const artifactsList = Array.isArray(artifactData) ? artifactData : (artifactData.artifacts || []);
      
      // Create company name lookup map
      const nameMap = {};
      companiesData.forEach(company => {
        nameMap[company.ticker] = company.name;
      });
      setCompanyNameMap(nameMap);
      
      setAllArtifacts(artifactsList);
      
      // Extract unique companies from artifacts
      const uniqueCompanies = [...new Set(artifactsList.map(a => a.ticker))].map(ticker => {
        return {
          ticker,
          name: nameMap[ticker] || ticker
        };
      });
      setCompanies(uniqueCompanies);
      
      // Don't auto-select - let user see all companies
      setSelectedCompanyTicker('');
    } catch (error) {
      console.error('Error fetching artifacts:', error);
      setError(error.message);
      setAllArtifacts([]);
    } finally {
      setIsLoading(false);
    }
  };

  // Apply filters and sorting
  useEffect(() => {
    let filtered = allArtifacts;
    
    // Filter by type
    if (typeFilter !== 'all') {
      filtered = filtered.filter(a => a.type === typeFilter);
    }
    
    // Filter by selected company
    if (selectedCompanyTicker) {
      filtered = filtered.filter(a => a.ticker === selectedCompanyTicker);
    }
    
    // Sort
    const sorted = [...filtered].sort((a, b) => {
      let aVal, bVal;
      
      if (sortBy === 'date') {
        aVal = new Date(a.date || '0');
        bVal = new Date(b.date || '0');
      } else if (sortBy === 'ticker') {
        aVal = a.ticker || '';
        bVal = b.ticker || '';
      } else if (sortBy === 'name') {
        aVal = (companyNameMap[a.ticker] || a.ticker).toLowerCase();
        bVal = (companyNameMap[b.ticker] || b.ticker).toLowerCase();
      } else if (sortBy === 'type') {
        aVal = a.type || '';
        bVal = b.type || '';
      }
      
      if (aVal < bVal) return sortOrder === 'asc' ? -1 : 1;
      if (aVal > bVal) return sortOrder === 'asc' ? 1 : -1;
      return 0;
    });
    
    setFilteredArtifacts(sorted);
    setCurrentPage(1);
  }, [allArtifacts, typeFilter, selectedCompanyTicker, sortBy, sortOrder, companyNameMap]);

  // Pagination
  const totalPages = Math.ceil(filteredArtifacts.length / itemsPerPage);
  const startIdx = (currentPage - 1) * itemsPerPage;
  const endIdx = startIdx + itemsPerPage;
  const paginatedArtifacts = filteredArtifacts.slice(startIdx, endIdx);

  const handleOpenUrl = async (artifact) => {
    // Use the artifact-url API to get presigned S3 URLs
    // The s3_key or document_link contains the S3 object key
    const s3Key = artifact.s3_key || artifact.document_link;

    if (s3Key) {
      try {
        // Fetch the presigned URL from the API as JSON
        const response = await fetch(`/api/artifact-url?key=${encodeURIComponent(s3Key)}`);
        const data = await response.json();

        if (data.url) {
          window.open(data.url, '_blank');
        } else {
          alert(data.error || 'Could not get document URL');
        }
      } catch (error) {
        console.error('Error getting presigned URL:', error);
        alert('Error opening document. Please try again.');
      }
    } else if (artifact.url && artifact.url.startsWith('http')) {
      // If there's a full URL (e.g., external link), use it directly
      window.open(artifact.url, '_blank');
    } else {
      alert('No document URL available for this artifact');
    }
  };

  if (isLoading) {
    return <div className="artifact-table">Loading artifacts...</div>;
  }

  return (
    <div className="artifact-table">
      <h3>SEC Filings & Documents</h3>
      
      {error && (
        <div style={{ 
          background: '#f8d7da', 
          color: '#721c24', 
          padding: '12px', 
          borderRadius: '4px',
          marginBottom: '15px'
        }}>
          Error: {error}
        </div>
      )}
      
      {allArtifacts.length === 0 ? (
        <p className="no-data">
          No artifacts found. 
          <br />
          Use the Scraping Interface to fetch SEC filings and transcripts.
        </p>
      ) : (
        <>
          {/* Filters */}
          <div style={{ display: 'flex', gap: '15px', marginBottom: '20px', alignItems: 'center', flexWrap: 'wrap' }}>
            <div style={{ flex: 1, minWidth: '150px' }}>
              <label style={{ display: 'block', marginBottom: '5px', fontSize: '12px', fontWeight: 'bold' }}>
                Select Company:
              </label>
              <select
                value={selectedCompanyTicker}
                onChange={(e) => setSelectedCompanyTicker(e.target.value)}
                style={{
                  width: '100%',
                  padding: '8px',
                  border: '1px solid #ddd',
                  borderRadius: '4px'
                }}
              >
                <option value="">-- All Companies --</option>
                {companies.map(company => (
                  <option key={company.ticker} value={company.ticker}>
                    {company.ticker} - {company.name}
                  </option>
                ))}
              </select>
            </div>
            
            <div style={{ minWidth: '150px' }}>
              <label style={{ display: 'block', marginBottom: '5px', fontSize: '12px', fontWeight: 'bold' }}>
                Document Type:
              </label>
              <select
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
                style={{
                  width: '100%',
                  padding: '8px',
                  border: '1px solid #ddd',
                  borderRadius: '4px'
                }}
              >
                <option value="all">All Types</option>
                <option value="10-K">10-K Only</option>
                <option value="10-Q">10-Q Only</option>
                <option value="transcript">Transcripts Only</option>
              </select>
            </div>
          </div>

          {/* Results Info */}
          <div style={{ 
            background: '#f8f9fa', 
            padding: '10px', 
            borderRadius: '4px', 
            marginBottom: '15px',
            fontSize: '12px',
            color: '#666'
          }}>
            Showing {startIdx + 1} to {Math.min(endIdx, filteredArtifacts.length)} of {filteredArtifacts.length} artifacts
          </div>

          {/* Table Container with Horizontal Scroll */}
          <div style={{ overflowX: 'auto', marginBottom: '20px' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '800px' }}>
              <thead>
                <tr style={{ background: '#f8f9fa', borderBottom: '2px solid #dee2e6' }}>
                <th 
                  onClick={() => { setSortBy('ticker'); setSortOrder(sortBy === 'ticker' && sortOrder === 'asc' ? 'desc' : 'asc'); }}
                  style={{ padding: '12px', textAlign: 'left', fontWeight: 'bold', cursor: 'pointer', userSelect: 'none' }}>
                  Ticker {sortBy === 'ticker' && (sortOrder === 'asc' ? '↑' : '↓')}
                </th>
                <th 
                  onClick={() => { setSortBy('name'); setSortOrder(sortBy === 'name' && sortOrder === 'asc' ? 'desc' : 'asc'); }}
                  style={{ padding: '12px', textAlign: 'left', fontWeight: 'bold', cursor: 'pointer', userSelect: 'none' }}>
                  Company Name {sortBy === 'name' && (sortOrder === 'asc' ? '↑' : '↓')}
                </th>
                <th 
                  onClick={() => { setSortBy('type'); setSortOrder(sortBy === 'type' && sortOrder === 'asc' ? 'desc' : 'asc'); }}
                  style={{ padding: '12px', textAlign: 'left', fontWeight: 'bold', cursor: 'pointer', userSelect: 'none' }}>
                  Document Type {sortBy === 'type' && (sortOrder === 'asc' ? '↑' : '↓')}
                </th>
                <th 
                  onClick={() => { setSortBy('date'); setSortOrder(sortBy === 'date' && sortOrder === 'asc' ? 'desc' : 'asc'); }}
                  style={{ padding: '12px', textAlign: 'left', fontWeight: 'bold', cursor: 'pointer', userSelect: 'none' }}>
                  Date {sortBy === 'date' && (sortOrder === 'asc' ? '↑' : '↓')}
                </th>
                <th style={{ padding: '12px', textAlign: 'center', fontWeight: 'bold' }}>Action</th>
              </tr>
            </thead>
            <tbody>
              {paginatedArtifacts.map((artifact, index) => (
                <tr key={startIdx + index} style={{ borderBottom: '1px solid #dee2e6' }}>
                  <td style={{ padding: '12px' }}>
                    <strong>{artifact.ticker}</strong>
                  </td>
                  <td style={{ padding: '12px' }}>
                    {companyNameMap[artifact.ticker] || artifact.ticker}
                  </td>
                  <td style={{ padding: '12px' }}>
                    <span style={{
                      background: artifact.type === '10-K' ? '#cfe2ff' : 
                                   artifact.type === '10-Q' ? '#d1e7dd' : '#fff3cd',
                      color: artifact.type === '10-K' ? '#084298' : 
                             artifact.type === '10-Q' ? '#0f5132' : '#664d03',
                      padding: '4px 8px',
                      borderRadius: '4px',
                      fontSize: '12px',
                      fontWeight: 'bold'
                    }}>
                      {artifact.type}
                    </span>
                  </td>
                  <td style={{ padding: '12px' }}>
                    {artifact.date ? new Date(artifact.date).toLocaleDateString() : 'N/A'}
                  </td>
                  <td style={{ padding: '12px', textAlign: 'center' }}>
                    <button
                      onClick={() => handleOpenUrl(artifact)}
                      style={{
                        background: '#007bff',
                        color: 'white',
                        border: 'none',
                        padding: '6px 12px',
                        borderRadius: '4px',
                        cursor: 'pointer',
                        fontSize: '12px'
                      }}
                    >
                      View
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div style={{
              display: 'flex',
              justifyContent: 'center',
              alignItems: 'center',
              gap: '10px',
              marginTop: '20px',
              padding: '15px',
              background: '#f8f9fa',
              borderRadius: '4px',
              flexWrap: 'wrap'
            }}>
              <button
                onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
                disabled={currentPage === 1}
                style={{
                  padding: '6px 12px',
                  border: '1px solid #ddd',
                  borderRadius: '4px',
                  background: currentPage === 1 ? '#e9ecef' : 'white',
                  cursor: currentPage === 1 ? 'not-allowed' : 'pointer'
                }}
              >
                ← Previous
              </button>

              <div style={{ display: 'flex', gap: '5px', alignItems: 'center', flexWrap: 'wrap' }}>
                {/* Show page number input for quick navigation */}
                <span style={{ fontSize: '14px', color: '#666' }}>
                  Page
                </span>
                <input
                  type="number"
                  min="1"
                  max={totalPages}
                  value={currentPage}
                  onChange={(e) => {
                    const page = parseInt(e.target.value);
                    if (page >= 1 && page <= totalPages) {
                      setCurrentPage(page);
                    }
                  }}
                  style={{
                    width: '60px',
                    padding: '6px',
                    border: '2px solid #007bff',
                    borderRadius: '4px',
                    textAlign: 'center',
                    fontWeight: 'bold'
                  }}
                />
                <span style={{ fontSize: '14px', color: '#666' }}>
                  of {totalPages}
                </span>
              </div>

              <button
                onClick={() => setCurrentPage(Math.min(totalPages, currentPage + 1))}
                disabled={currentPage === totalPages}
                style={{
                  padding: '6px 12px',
                  border: '1px solid #ddd',
                  borderRadius: '4px',
                  background: currentPage === totalPages ? '#e9ecef' : 'white',
                  cursor: currentPage === totalPages ? 'not-allowed' : 'pointer'
                }}
              >
                Next →
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default ArtifactTable;
