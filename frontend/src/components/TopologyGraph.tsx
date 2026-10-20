/**
 * TopologyGraph
 *
 * Interactive SVG-based network topology graph.
 * Nodes are laid out automatically; edges show relationships.
 * Click a node to highlight it and its connections.
 * Click an edge to see its details.
 */

import { useState, useEffect, useRef, useMemo } from 'react';
import type { TopologyGraph, TopologyNode, TopologyEdge, TopologyProvenance } from '../types/routing';
import ProvenanceBadge from './ProvenanceBadge';
import './TopologyGraph.css';

interface TopologyGraphProps {
  graph: TopologyGraph | null;
  loading: boolean;
  error: string | null;
}

const KIND_LABELS: Record<TopologyNode['kind'], string> = {
  interface: 'Interface',
  gateway: 'Gateway',
  neighbor: 'Neighbour',
  router: 'Router',
  host: 'Host',
  unknown: 'Unknown',
};

const PROVENANCE_ORDER: TopologyProvenance[] = [
  'observed',
  'inferred',
  'simulated',
  'unknown',
];

const PROVENANCE_COLORS: Record<TopologyProvenance, { node: string; edge: string }> = {
  observed: { node: '#16a34a', edge: '#16a34a' },
  inferred: { node: '#d97706', edge: '#d97706' },
  simulated: { node: '#7c3aed', edge: '#7c3aed' },
  unknown: { node: '#64748b', edge: '#64748b' },
};

const NODE_RADIUS = 28;

function computeLayout(
  nodes: TopologyNode[],
  width: number,
  height: number
): Map<string, { x: number; y: number }> {
  if (nodes.length === 0) return new Map();

  const positions = new Map<string, { x: number; y: number }>();

  // Simple circular layout by kind, then by provenance
  const nodesByKind = new Map<TopologyNode['kind'], TopologyNode[]>();
  for (const node of nodes) {
    const arr = nodesByKind.get(node.kind) || [];
    arr.push(node);
    nodesByKind.set(node.kind, arr);
  }

  const kinds = ['interface', 'gateway', 'neighbor', 'router', 'host', 'unknown'] as TopologyNode['kind'][];
  let angleOffset = -Math.PI / 2; // Start at top
  const centerX = width / 2;
  const centerY = height / 2;
  const maxRadius = Math.min(width, height) / 2 - 80;

  for (const kind of kinds) {
    const kindNodes = nodesByKind.get(kind) || [];
    if (kindNodes.length === 0) continue;

    // Sort by provenance priority
    kindNodes.sort((a, b) => PROVENANCE_ORDER.indexOf(a.provenance) - PROVENANCE_ORDER.indexOf(b.provenance));

    const ringRadius = maxRadius * (0.25 + 0.6 * (kinds.indexOf(kind) / (kinds.length - 1 || 1)));
    const angleStep = (2 * Math.PI) / Math.max(kindNodes.length, 1);

    for (let i = 0; i < kindNodes.length; i++) {
      const angle = angleOffset + i * angleStep;
      positions.set(kindNodes[i].id, {
        x: centerX + ringRadius * Math.cos(angle),
        y: centerY + ringRadius * Math.sin(angle),
      });
    }
  }

  // For single node, center it
  if (nodes.length === 1) {
    positions.set(nodes[0].id, { x: centerX, y: centerY });
  }

  return positions;
}

function getEdgePath(
  source: { x: number; y: number },
  target: { x: number; y: number },
  curvature = 0.3
): string {
  const dx = target.x - source.x;
  const dy = target.y - source.y;
  const distance = Math.sqrt(dx * dx + dy * dy);

  if (distance === 0) return '';

  // Perpendicular vector for curve
  const mx = -dy / distance;
  const my = dx / distance;

  // Control point offset
  const offset = Math.min(distance * curvature, 50);
  const cx = (source.x + target.x) / 2 + mx * offset;
  const cy = (source.y + target.y) / 2 + my * offset;

  return `M ${source.x} ${source.y} Q ${cx} ${cy} ${target.x} ${target.y}`;
}

export default function TopologyGraphPanel({
  graph,
  loading,
  error,
}: TopologyGraphProps) {
  const [selectedNode, setSelectedNode] = useState<TopologyNode | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<TopologyEdge | null>(null);
  const [highlightedNodes, setHighlightedNodes] = useState<Set<string>>(new Set());
  const [highlightedEdges, setHighlightedEdges] = useState<Set<string>>(new Set());
  const [svgSize, setSvgSize] = useState({ width: 600, height: 450 });
  const svgRef = useRef<SVGSVGElement>(null);

  const layout = useMemo(() => {
    if (!graph || graph.nodes.length === 0) return new Map();
    return computeLayout(graph.nodes, svgSize.width, svgSize.height);
  }, [graph, svgSize]);

  // Update highlight when selection changes
  useEffect(() => {
    if (selectedNode) {
      const nodeIds = new Set<string>([selectedNode.id]);
      const edgeIds = new Set<string>();

      graph?.edges.forEach((edge, i) => {
        if (edge.source === selectedNode.id || edge.target === selectedNode.id) {
          nodeIds.add(edge.source);
          nodeIds.add(edge.target);
          edgeIds.add(`${edge.source}-${edge.target}-${i}`);
        }
      });

      setHighlightedNodes(nodeIds);
      setHighlightedEdges(edgeIds);
    } else {
      setHighlightedNodes(new Set());
      setHighlightedEdges(new Set());
    }
  }, [selectedNode, graph]);

  // Update highlight when edge selected
  useEffect(() => {
    if (selectedEdge) {
      const edgeIds = new Set<string>([`${selectedEdge.source}-${selectedEdge.target}-${graph?.edges.indexOf(selectedEdge) ?? 0}`]);
      const nodeIds = new Set<string>([selectedEdge.source, selectedEdge.target]);
      setHighlightedEdges(edgeIds);
      setHighlightedNodes(nodeIds);
    }
  }, [selectedEdge, graph]);

  const handleNodeClick = (node: TopologyNode, e: React.MouseEvent) => {
    e.stopPropagation();
    setSelectedNode(selectedNode?.id === node.id ? null : node);
    setSelectedEdge(null);
  };

  const handleEdgeClick = (edge: TopologyEdge, _index: number, e: React.MouseEvent) => {
    e.stopPropagation();
    setSelectedEdge(selectedEdge?.source === edge.source && selectedEdge.target === edge.target ? null : edge);
    setSelectedNode(null);
  };

  const handleBackgroundClick = () => {
    setSelectedNode(null);
    setSelectedEdge(null);
  };

  const getNodeStyle = (node: TopologyNode) => {
    const isHighlighted = highlightedNodes.has(node.id);
    const isSelected = selectedNode?.id === node.id;
    const isDimmed = selectedNode && !isHighlighted;
    const prov = PROVENANCE_COLORS[node.provenance];

    return {
      fill: isDimmed ? '#e0e0e0' : prov.node,
      stroke: isSelected ? '#2563eb' : (isDimmed ? '#999' : prov.node),
      strokeWidth: isSelected ? 3 : (isDimmed ? 1 : 2),
      opacity: isDimmed ? 0.4 : 1,
    };
  };

  const getEdgeStyle = (edge: TopologyEdge, _index: number) => {
    const isHighlighted = highlightedEdges.has(`${edge.source}-${edge.target}-${_index}`);
    const isSelected = selectedEdge?.source === edge.source && selectedEdge.target === edge.target;
    const isDimmed = selectedNode && !isHighlighted;
    const prov = PROVENANCE_COLORS[edge.provenance];

    return {
      stroke: isDimmed ? '#e0e0e0' : prov.edge,
      strokeWidth: isSelected ? 3 : (isDimmed ? 1 : 2),
      strokeDasharray: edge.provenance === 'inferred' ? '8 4' : edge.provenance === 'simulated' ? '4 4' : 'none',
      opacity: isDimmed ? 0.3 : 1,
      markerEnd: `url(#arrowhead-${edge.provenance})`,
    };
  };

  if (loading) {
    return (
      <div className="topology-loading">
        <span className="spinner" aria-hidden="true" />
        Reading the host's network…
      </div>
    );
  }

  if (error) {
    return (
      <div className="error-message" role="alert">
        <span aria-hidden="true">⚠</span>
        {error}
      </div>
    );
  }

  if (!graph) {
    return null;
  }

  const observed = graph.nodes.filter((n) => n.provenance === 'observed').length;
  const simulated = graph.nodes.filter((n) => n.provenance === 'simulated').length;
  const inferredEdges = graph.edges.filter((e) => e.provenance === 'inferred').length;

  return (
    <div className="topology-graph" onClick={handleBackgroundClick}>
      <div className="topology-header">
        <div>
          <h3>Network Topology</h3>
          <p className="topology-explanation">{graph.explanation}</p>
        </div>
        <div className="topology-legend">
          {PROVENANCE_ORDER.map((p) => (
            <ProvenanceBadge key={p} provenance={p} size="small" />
          ))}
        </div>
      </div>

      <div className="topology-summary">
        <span>
          <strong>{observed}</strong> observed node{observed === 1 ? '' : 's'}
        </span>
        <span>
          <strong>{simulated}</strong> simulated node{simulated === 1 ? '' : 's'}
        </span>
        <span>
          <strong>{inferredEdges}</strong> inferred relationship{inferredEdges === 1 ? '' : 's'}
        </span>
        <span className="topology-timestamp">
          Read at {new Date(graph.observed_at).toLocaleTimeString()}
        </span>
      </div>

      {graph.nodes.length === 0 ? (
        <div className="topology-empty" role="status">
          <p>Nothing was observed.</p>
          <p className="topology-empty-hint">
            No interfaces, routes, or neighbors could be read, and no scenario is loaded.
          </p>
        </div>
      ) : (
        <>
          <svg
            ref={svgRef}
            className="topology-svg"
            width={svgSize.width}
            height={svgSize.height}
            viewBox={`0 0 ${svgSize.width} ${svgSize.height}`}
            onLoad={(e) => {
              const target = e.target as SVGSVGElement;
              const rect = target.getBoundingClientRect();
              if (rect.width !== svgSize.width || rect.height !== svgSize.height) {
                setSvgSize({ width: rect.width, height: rect.height });
              }
            }}
            role="img"
            aria-label="Network topology graph showing devices and their relationships"
          >
            <defs>
              {PROVENANCE_ORDER.map((p) => {
                const color = PROVENANCE_COLORS[p].edge;
                return (
                  <marker
                    key={`arrowhead-${p}`}
                    id={`arrowhead-${p}`}
                    markerWidth={10}
                    markerHeight={7}
                    refX={9}
                    refY={3.5}
                    orient="auto"
                    markerUnits="strokeWidth"
                  >
                    <path d="M0,0 L10,3.5 L0,7 Z" fill={color} />
                  </marker>
                );
              })}
            </defs>

            {/* Edges */}
            <g className="topology-edges-layer">
              {graph.edges.map((edge, index) => {
                const sourcePos = layout.get(edge.source);
                const targetPos = layout.get(edge.target);
                if (!sourcePos || !targetPos) return null;

                const path = getEdgePath(sourcePos, targetPos);
                const style = getEdgeStyle(edge, index);

                return (
                  <g key={index} onClick={(e) => handleEdgeClick(edge, index, e)} className="topology-edge-group">
                    <path
                      d={path}
                      fill="none"
                      style={style as React.CSSProperties}
                      className="topology-edge-path"
                      aria-label={`${edge.kind} from ${edge.source} to ${edge.target}, ${edge.provenance}`}
                    />
                    <title>{edge.label}: {edge.detail || 'No details'}</title>
                  </g>
                );
              })}
            </g>

            {/* Nodes */}
            <g className="topology-nodes-layer">
              {graph.nodes.map((node) => {
                const pos = layout.get(node.id);
                if (!pos) return null;

                const style = getNodeStyle(node);
                const isSelected = selectedNode?.id === node.id;
                const isHighlighted = highlightedNodes.has(node.id);

                return (
                  <g
                    key={node.id}
                    onClick={(e) => handleNodeClick(node, e)}
                    className={`topology-node-group ${isSelected ? 'selected' : ''} ${isHighlighted ? 'highlighted' : ''}`}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') handleNodeClick(node, e as any); }}
                    aria-label={`${KIND_LABELS[node.kind]} ${node.label}, ${node.provenance}, ${node.addresses.join(', ') || 'no addresses'}`}
                    aria-pressed={isSelected}
                    aria-expanded={isSelected}
                  >
                    <circle
                      cx={pos.x}
                      cy={pos.y}
                      r={NODE_RADIUS}
                      style={style as React.CSSProperties}
                      className="topology-node-circle"
                    />
                    <text
                      x={pos.x}
                      y={pos.y + 4}
                      textAnchor="middle"
                      dominantBaseline="middle"
                      className="topology-node-icon"
                      fontSize={NODE_RADIUS * 0.7}
                      fill="white"
                      aria-hidden="true"
                    >
                      {node.provenance === 'observed' ? '●' : node.provenance === 'inferred' ? '◐' : node.provenance === 'simulated' ? '◇' : '○'}
                    </text>
                    <text
                      x={pos.x}
                      y={pos.y + NODE_RADIUS + 16}
                      textAnchor="middle"
                      className="topology-node-label"
                      fontSize={11}
                      fill={selectedNode && !highlightedNodes.has(node.id) ? '#999' : 'var(--color-text)'}
                      fontWeight={isSelected ? 600 : 400}
                    >
                      {node.label}
                    </text>
                    {node.addresses.length > 0 && (
                      <text
                        x={pos.x}
                        y={pos.y + NODE_RADIUS + 30}
                        textAnchor="middle"
                        className="topology-node-address"
                        fontSize={9}
                        fill="var(--color-text-muted)"
                        fontFamily="var(--font-mono)"
                      >
                        {node.addresses[0]}
                      </text>
                    )}
                    <ProvenanceBadge
                      provenance={node.provenance}
                      size="small"
                    />
                  </g>
                );
              })}
            </g>
          </svg>

          {/* Selection Details Panel */}
          {(selectedNode || selectedEdge) && (
            <div className="topology-details-panel">
              {selectedNode && (
                <div className="topology-detail">
                  <h4>
                    {KIND_LABELS[selectedNode.kind]}: {selectedNode.label}
                    <ProvenanceBadge provenance={selectedNode.provenance} size="small" />
                  </h4>
                  {selectedNode.addresses.length > 0 && (
                    <p className="topology-addresses">
                      Addresses: {selectedNode.addresses.join(', ')}
                    </p>
                  )}
                  {selectedNode.detail && (
                    <p className="topology-node-note">{selectedNode.detail}</p>
                  )}
                  <h5>Connections</h5>
                  <ul className="topology-connection-list">
                    {graph.edges
                      .filter((e) => e.source === selectedNode.id || e.target === selectedNode.id)
                      .map((e, i) => (
                        <li key={i}>
                          {e.source === selectedNode.id ? '→' : '←'} {e.target}
                          <span className="mono"> ({e.kind})</span>
                          <ProvenanceBadge provenance={e.provenance} size="small" />
                          {e.detail && <span className="edge-detail"> — {e.detail}</span>}
                        </li>
                      ))}
                    {graph.edges.filter((e) => e.source === selectedNode.id || e.target === selectedNode.id).length === 0 && (
                      <li className="no-connections">No evidence of connection to other nodes.</li>
                    )}
                  </ul>
                </div>
              )}

              {selectedEdge && (
                <div className="topology-detail">
                  <h4>Relationship: {selectedEdge.label}</h4>
                  <p className="topology-addresses">
                    <span className="mono">{selectedEdge.source}</span> → <span className="mono">{selectedEdge.target}</span>
                  </p>
                  <p>
                    <ProvenanceBadge provenance={selectedEdge.provenance} size="medium" showDescription />
                  </p>
                  <p className="topology-node-note">{selectedEdge.detail || 'No additional details available.'}</p>
                </div>
              )}

              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => { setSelectedNode(null); setSelectedEdge(null); }}
              >
                Clear Selection
              </button>
            </div>
          )}
        </>
      )}

      {graph.edges.length > 0 && (
        <details className="topology-edges">
          <summary>
            All {graph.edges.length} relationship{graph.edges.length === 1 ? '' : 's'}
          </summary>
          <table className="topology-edge-table">
            <thead>
              <tr>
                <th scope="col">From</th>
                <th scope="col">To</th>
                <th scope="col">Kind</th>
                <th scope="col">Provenance</th>
              </tr>
            </thead>
            <tbody>
              {graph.edges.map((edge: TopologyEdge, i) => (
                <tr key={i}>
                  <td className="mono">{edge.source}</td>
                  <td className="mono">{edge.target}</td>
                  <td>{edge.kind}</td>
                  <td>
                    <ProvenanceBadge provenance={edge.provenance} size="small" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  );
}