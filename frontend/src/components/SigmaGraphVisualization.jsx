import React, { useEffect, useState, useCallback } from 'react';

/**
 * Lightweight SVG-based graph visualization
 * Simple and fast - won't crash the browser
 */
const SigmaGraphVisualization = ({
  ticker,
  onNodeClick,
  width = '100%',
  height = 500,
  nodeColors = {
    Organization: '#10b981',
    Person: '#f59e0b',
    Concept: '#8b5cf6',
    Document: '#64748b',
    Location: '#06b6d4',
    Event: '#ec4899',
    Patent: '#ef4444'
  }
}) => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [graphData, setGraphData] = useState({ nodes: [], links: [] });
  const [selectedNode, setSelectedNode] = useState(null);

  // Load graph data
  const loadGraph = useCallback(async () => {
    if (!ticker) return;

    setLoading(true);
    setError(null);

    try {
      const url = `/api/knowledge-graph/${ticker}?depth=2&limit=50&include_documents=true`;
      const response = await fetch(url);

      if (!response.ok) {
        setError(`API error: ${response.status}`);
        return;
      }

      const data = await response.json();

      if (data.error) {
        setError(data.message || data.error);
        return;
      }

      // Simple circular layout
      const nodes = (data.nodes || []).map((node, i) => {
        const angle = (2 * Math.PI * i) / (data.nodes?.length || 1);
        const radius = 150;
        return {
          ...node,
          x: 250 + radius * Math.cos(angle),
          y: 200 + radius * Math.sin(angle)
        };
      });

      setGraphData({ nodes, links: data.links || [] });
    } catch (err) {
      console.error('Failed to load graph:', err);
      setError('Failed to load graph data');
    } finally {
      setLoading(false);
    }
  }, [ticker]);

  useEffect(() => {
    loadGraph();
  }, [loadGraph]);

  const handleNodeClick = (node) => {
    setSelectedNode(node);
    if (onNodeClick) onNodeClick(node);
  };

  const getNodeColor = (type) => nodeColors[type] || '#94a3b8';

  const styles = {
    container: {
      position: 'relative',
      width: width,
      height: typeof height === 'number' ? `${height}px` : height,
      background: '#f8fafc',
      borderRadius: '8px',
      overflow: 'hidden'
    },
    loading: {
      position: 'absolute',
      top: '50%',
      left: '50%',
      transform: 'translate(-50%, -50%)',
      color: '#64748b',
      fontSize: '14px'
    },
    error: {
      position: 'absolute',
      top: '50%',
      left: '50%',
      transform: 'translate(-50%, -50%)',
      color: '#ef4444',
      fontSize: '14px',
      textAlign: 'center',
      padding: '20px'
    },
    stats: {
      position: 'absolute',
      bottom: '10px',
      left: '10px',
      background: 'rgba(255,255,255,0.9)',
      padding: '6px 12px',
      borderRadius: '4px',
      fontSize: '12px',
      color: '#64748b'
    },
    legend: {
      position: 'absolute',
      top: '10px',
      right: '10px',
      background: 'rgba(255,255,255,0.95)',
      padding: '10px',
      borderRadius: '6px',
      fontSize: '11px'
    },
    legendItem: {
      display: 'flex',
      alignItems: 'center',
      marginBottom: '4px'
    },
    legendColor: {
      width: '10px',
      height: '10px',
      borderRadius: '50%',
      marginRight: '6px'
    },
    selectedNode: {
      position: 'absolute',
      bottom: '10px',
      right: '10px',
      background: 'rgba(255,255,255,0.95)',
      padding: '12px',
      borderRadius: '6px',
      fontSize: '12px',
      maxWidth: '250px',
      boxShadow: '0 2px 8px rgba(0,0,0,0.15)'
    },
    emptyState: {
      position: 'absolute',
      top: '50%',
      left: '50%',
      transform: 'translate(-50%, -50%)',
      textAlign: 'center',
      color: '#64748b'
    }
  };

  if (loading) {
    return (
      <div style={styles.container}>
        <div style={styles.loading}>Loading graph...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={styles.container}>
        <div style={styles.error}>{error}</div>
      </div>
    );
  }

  if (graphData.nodes.length === 0) {
    return (
      <div style={styles.container}>
        <div style={styles.emptyState}>
          <p style={{ marginBottom: '8px', fontWeight: '500' }}>No graph data available</p>
          <p style={{ fontSize: '13px' }}>Try using the Cypher Console to query the graph directly.</p>
        </div>
      </div>
    );
  }

  // Build node lookup for links
  const nodeMap = {};
  graphData.nodes.forEach(n => { nodeMap[n.id] = n; });

  // Get unique node types for legend
  const nodeTypes = [...new Set(graphData.nodes.map(n => n.type))];

  return (
    <div style={styles.container}>
      <svg width="100%" height="100%" viewBox="0 0 500 400">
        {/* Draw links */}
        {graphData.links.map((link, i) => {
          const source = nodeMap[link.source];
          const target = nodeMap[link.target];
          if (!source || !target) return null;
          return (
            <line
              key={`link-${i}`}
              x1={source.x}
              y1={source.y}
              x2={target.x}
              y2={target.y}
              stroke="#cbd5e1"
              strokeWidth="1"
              opacity="0.6"
            />
          );
        })}

        {/* Draw nodes */}
        {graphData.nodes.map((node) => (
          <g
            key={node.id}
            transform={`translate(${node.x}, ${node.y})`}
            style={{ cursor: 'pointer' }}
            onClick={() => handleNodeClick(node)}
          >
            <circle
              r={node.type === 'Organization' ? 20 : 12}
              fill={getNodeColor(node.type)}
              stroke={selectedNode?.id === node.id ? '#1e293b' : 'white'}
              strokeWidth={selectedNode?.id === node.id ? 3 : 2}
            />
            <text
              y={node.type === 'Organization' ? 32 : 24}
              textAnchor="middle"
              fontSize="10"
              fill="#1e293b"
              fontWeight="500"
            >
              {(node.name || '').substring(0, 15)}
              {(node.name || '').length > 15 ? '...' : ''}
            </text>
          </g>
        ))}
      </svg>

      {/* Stats */}
      <div style={styles.stats}>
        {graphData.nodes.length} nodes • {graphData.links.length} relationships
      </div>

      {/* Legend */}
      <div style={styles.legend}>
        {nodeTypes.map(type => (
          <div key={type} style={styles.legendItem}>
            <div style={{ ...styles.legendColor, background: getNodeColor(type) }} />
            <span>{type}</span>
          </div>
        ))}
      </div>

      {/* Selected node info */}
      {selectedNode && (
        <div style={styles.selectedNode}>
          <div style={{ fontWeight: '600', marginBottom: '6px' }}>
            {selectedNode.name}
          </div>
          <div style={{ color: '#64748b', marginBottom: '4px' }}>
            Type: {selectedNode.type}
          </div>
          {selectedNode.properties?.ticker && (
            <div style={{ color: '#64748b' }}>
              Ticker: {selectedNode.properties.ticker}
            </div>
          )}
          <button
            onClick={() => setSelectedNode(null)}
            style={{
              marginTop: '8px',
              padding: '4px 8px',
              fontSize: '11px',
              background: '#f1f5f9',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer'
            }}
          >
            Close
          </button>
        </div>
      )}
    </div>
  );
};

export default SigmaGraphVisualization;
