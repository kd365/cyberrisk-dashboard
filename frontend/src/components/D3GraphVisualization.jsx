import React, { useEffect, useRef, useState, useCallback } from 'react';
import * as d3 from 'd3';

/**
 * D3.js Force-directed graph visualization with draggable nodes
 * Features:
 * - Physics-based force simulation
 * - Drag nodes to reposition
 * - Zoom and pan
 * - Node selection with details panel
 */
const D3GraphVisualization = ({
  ticker,
  onNodeClick,
  width = 800,
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
  const svgRef = useRef(null);
  const containerRef = useRef(null);
  const simulationRef = useRef(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [graphData, setGraphData] = useState({ nodes: [], links: [] });
  const [selectedNode, setSelectedNode] = useState(null);
  const [dimensions, setDimensions] = useState({ width, height });

  // Responsive sizing
  useEffect(() => {
    const updateDimensions = () => {
      if (containerRef.current) {
        const rect = containerRef.current.getBoundingClientRect();
        setDimensions({
          width: rect.width || width,
          height: typeof height === 'number' ? height : rect.height || 500
        });
      }
    };

    updateDimensions();
    window.addEventListener('resize', updateDimensions);
    return () => window.removeEventListener('resize', updateDimensions);
  }, [width, height]);

  // Load graph data
  const loadGraph = useCallback(async () => {
    if (!ticker) return;

    setLoading(true);
    setError(null);

    try {
      const url = `/api/knowledge-graph/${ticker}?depth=2&limit=75&include_documents=true`;
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

      // Process nodes and links for D3
      const nodes = (data.nodes || []).map(node => ({
        ...node,
        id: node.id,
        radius: node.type === 'Organization' ? 20 : 12
      }));

      // Create link references using node IDs
      const nodeIds = new Set(nodes.map(n => n.id));
      const links = (data.links || [])
        .filter(link => nodeIds.has(link.source) && nodeIds.has(link.target))
        .map(link => ({
          ...link,
          source: link.source,
          target: link.target
        }));

      setGraphData({ nodes, links });
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

  // D3 visualization
  useEffect(() => {
    if (loading || error || graphData.nodes.length === 0 || !svgRef.current) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const { width: w, height: h } = dimensions;

    // Create zoom behavior
    const zoom = d3.zoom()
      .scaleExtent([0.3, 3])
      .on('zoom', (event) => {
        g.attr('transform', event.transform);
      });

    svg.call(zoom);

    // Create main group for zoom/pan
    const g = svg.append('g');

    // Create force simulation
    const simulation = d3.forceSimulation(graphData.nodes)
      .force('link', d3.forceLink(graphData.links)
        .id(d => d.id)
        .distance(80)
        .strength(0.5))
      .force('charge', d3.forceManyBody()
        .strength(-200)
        .distanceMax(300))
      .force('center', d3.forceCenter(w / 2, h / 2))
      .force('collision', d3.forceCollide()
        .radius(d => d.radius + 5));

    simulationRef.current = simulation;

    // Draw links
    const link = g.append('g')
      .attr('class', 'links')
      .selectAll('line')
      .data(graphData.links)
      .enter()
      .append('line')
      .attr('stroke', '#cbd5e1')
      .attr('stroke-width', 1.5)
      .attr('stroke-opacity', 0.6);

    // Draw link labels (relationship types)
    const linkLabel = g.append('g')
      .attr('class', 'link-labels')
      .selectAll('text')
      .data(graphData.links)
      .enter()
      .append('text')
      .attr('font-size', '8px')
      .attr('fill', '#94a3b8')
      .attr('text-anchor', 'middle')
      .text(d => d.type || '');

    // Create node groups
    const node = g.append('g')
      .attr('class', 'nodes')
      .selectAll('g')
      .data(graphData.nodes)
      .enter()
      .append('g')
      .attr('class', 'node')
      .style('cursor', 'grab');

    // Drag behavior
    const drag = d3.drag()
      .on('start', (event, d) => {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
        d3.select(event.sourceEvent.target.parentNode).style('cursor', 'grabbing');
      })
      .on('drag', (event, d) => {
        d.fx = event.x;
        d.fy = event.y;
      })
      .on('end', (event, d) => {
        if (!event.active) simulation.alphaTarget(0);
        // Keep node fixed after dragging (comment out next two lines to release)
        // d.fx = null;
        // d.fy = null;
        d3.select(event.sourceEvent.target.parentNode).style('cursor', 'grab');
      });

    node.call(drag);

    // Draw circles
    node.append('circle')
      .attr('r', d => d.radius)
      .attr('fill', d => nodeColors[d.type] || '#94a3b8')
      .attr('stroke', '#fff')
      .attr('stroke-width', 2)
      .on('click', (event, d) => {
        event.stopPropagation();
        setSelectedNode(d);
        if (onNodeClick) onNodeClick(d);

        // Highlight selected node
        node.selectAll('circle')
          .attr('stroke', n => n.id === d.id ? '#1e293b' : '#fff')
          .attr('stroke-width', n => n.id === d.id ? 3 : 2);
      })
      .on('mouseover', function(event, d) {
        d3.select(this)
          .transition()
          .duration(150)
          .attr('r', d.radius * 1.2);
      })
      .on('mouseout', function(event, d) {
        d3.select(this)
          .transition()
          .duration(150)
          .attr('r', d.radius);
      });

    // Draw labels
    node.append('text')
      .attr('dy', d => d.radius + 12)
      .attr('text-anchor', 'middle')
      .attr('font-size', '10px')
      .attr('font-weight', '500')
      .attr('fill', '#1e293b')
      .attr('pointer-events', 'none')
      .text(d => {
        const name = d.name || '';
        return name.length > 15 ? name.substring(0, 15) + '...' : name;
      });

    // Update positions on tick
    simulation.on('tick', () => {
      link
        .attr('x1', d => d.source.x)
        .attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x)
        .attr('y2', d => d.target.y);

      linkLabel
        .attr('x', d => (d.source.x + d.target.x) / 2)
        .attr('y', d => (d.source.y + d.target.y) / 2);

      node.attr('transform', d => `translate(${d.x},${d.y})`);
    });

    // Click on background to deselect
    svg.on('click', () => {
      setSelectedNode(null);
      node.selectAll('circle')
        .attr('stroke', '#fff')
        .attr('stroke-width', 2);
    });

    // Cleanup
    return () => {
      simulation.stop();
    };
  }, [graphData, dimensions, loading, error, nodeColors, onNodeClick]);

  // Reset zoom
  const handleResetZoom = () => {
    if (svgRef.current) {
      const svg = d3.select(svgRef.current);
      svg.transition()
        .duration(500)
        .call(d3.zoom().transform, d3.zoomIdentity);
    }
  };

  // Release all fixed nodes
  const handleReleaseNodes = () => {
    if (simulationRef.current && graphData.nodes) {
      graphData.nodes.forEach(d => {
        d.fx = null;
        d.fy = null;
      });
      simulationRef.current.alpha(0.3).restart();
    }
  };

  const getNodeColor = (type) => nodeColors[type] || '#94a3b8';

  // Get unique node types for legend
  const nodeTypes = [...new Set(graphData.nodes.map(n => n.type))];

  const styles = {
    container: {
      position: 'relative',
      width: '100%',
      height: typeof height === 'number' ? `${height}px` : height,
      background: '#f8fafc',
      borderRadius: '8px',
      overflow: 'hidden'
    },
    svg: {
      width: '100%',
      height: '100%'
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
    controls: {
      position: 'absolute',
      top: '10px',
      left: '10px',
      display: 'flex',
      gap: '8px'
    },
    button: {
      padding: '6px 12px',
      fontSize: '12px',
      background: 'rgba(255,255,255,0.95)',
      border: '1px solid #e2e8f0',
      borderRadius: '4px',
      cursor: 'pointer',
      color: '#475569'
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
    },
    hint: {
      position: 'absolute',
      bottom: '10px',
      left: '50%',
      transform: 'translateX(-50%)',
      background: 'rgba(255,255,255,0.9)',
      padding: '4px 10px',
      borderRadius: '4px',
      fontSize: '11px',
      color: '#94a3b8'
    }
  };

  if (loading) {
    return (
      <div ref={containerRef} style={styles.container}>
        <div style={styles.loading}>Loading graph...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div ref={containerRef} style={styles.container}>
        <div style={styles.error}>{error}</div>
      </div>
    );
  }

  if (graphData.nodes.length === 0) {
    return (
      <div ref={containerRef} style={styles.container}>
        <div style={styles.emptyState}>
          <p style={{ marginBottom: '8px', fontWeight: '500' }}>No graph data available</p>
          <p style={{ fontSize: '13px' }}>Try using the Cypher Console to query the graph directly.</p>
        </div>
      </div>
    );
  }

  return (
    <div ref={containerRef} style={styles.container}>
      <svg ref={svgRef} style={styles.svg} />

      {/* Controls */}
      <div style={styles.controls}>
        <button style={styles.button} onClick={handleResetZoom}>
          Reset View
        </button>
        <button style={styles.button} onClick={handleReleaseNodes}>
          Release Nodes
        </button>
        <button style={styles.button} onClick={loadGraph}>
          Refresh
        </button>
      </div>

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

      {/* Hint */}
      <div style={styles.hint}>
        Drag nodes to reposition • Scroll to zoom • Drag background to pan
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
            <div style={{ color: '#64748b', marginBottom: '4px' }}>
              Ticker: {selectedNode.properties.ticker}
            </div>
          )}
          {selectedNode.properties?.category && (
            <div style={{ color: '#64748b', marginBottom: '4px' }}>
              Category: {selectedNode.properties.category}
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

export default D3GraphVisualization;
