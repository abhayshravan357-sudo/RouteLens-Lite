/**
 * TopologyGraph
 *
 * Draws the network as a set of nodes and relationships, each marked with
 * where it came from.
 *
 * This is deliberately not a pretty picture. The colours answer one
 * question: was this measured on this machine, worked out from other
 * measurements, produced by the simulator, or simply unknown?
 */

import { useState } from 'react';
import type { TopologyGraph, TopologyNode, TopologyEdge, TopologyProvenance } from '../types/routing';
import ProvenanceBadge from './ProvenanceBadge';
import './TopologyGraph.css';

interface TopologyGraphProps {
  graph: TopologyGraph | null;
  loading: boolean;
  error: string | null;
}

const KIND_ORDER: TopologyNode['kind'][] = [
  'interface',
  'gateway',
  'neighbor',
  'router',
  'host',
  'unknown',
];

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

export default function TopologyGraphPanel({
  graph,
  loading,
  error,
}: TopologyGraphProps) {
  const [selectedNode, setSelectedNode] = useState<TopologyNode | null>(null);

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
  const inferred = graph.edges.filter((e) => e.provenance === 'inferred').length;

  const edgesFrom = (nodeId: string) => graph.edges.filter((e) => e.source === nodeId);
  const edgesTo = (nodeId: string) => graph.edges.filter((e) => e.target === nodeId);

  return (
    <div className="topology-graph">
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
          <strong>{inferred}</strong> inferred relationship{inferred === 1 ? '' : 's'}
        </span>
        <span className="topology-timestamp">
          Read at {new Date(graph.observed_at).toLocaleTimeString()}
        </span>
      </div>

      {graph.nodes.length === 0 ? (
        <p className="topology-empty">
          Nothing could be read from this machine and no scenario was loaded.
        </p>
      ) : (
        <div className="topology-columns">
          {KIND_ORDER.map((kind) => {
            const nodes = graph.nodes.filter((n) => n.kind === kind);
            if (nodes.length === 0) return null;
            return (
              <div key={kind} className="topology-group">
                <h4 className="topology-group-title">{KIND_LABELS[kind]}</h4>
                <ul className="topology-node-list">
                  {nodes.map((node) => (
                    <li key={node.id}>
                      <button
                        type="button"
                        className={`topology-node ${node.provenance} ${
                          selectedNode?.id === node.id ? 'selected' : ''
                        }`}
                        onClick={() => setSelectedNode(node)}
                        aria-expanded={selectedNode?.id === node.id}
                      >
                        <span className="topology-node-label">{node.label}</span>
                        <ProvenanceBadge
                          provenance={node.provenance}
                          size="small"
                        />
                      </button>
                      {selectedNode?.id === node.id && (
                        <div className="topology-node-detail">
                          {node.addresses.length > 0 && (
                            <p className="topology-addresses">
                              {node.addresses.join(', ')}
                            </p>
                          )}
                          {node.detail && (
                            <p className="topology-node-note">{node.detail}</p>
                          )}
                          {edgesFrom(node.id).map((e) => (
                            <p key={`${e.kind}-${e.target}`} className="topology-edge">
                              → <span className="mono">{e.target}</span>{' '}
                              <em>{e.label}</em>{' '}
                              <ProvenanceBadge
                                provenance={e.provenance}
                                size="small"
                              />
                            </p>
                          ))}
                          {edgesTo(node.id).map((e) => (
                            <p key={`${e.kind}-${e.source}`} className="topology-edge">
                              ← <span className="mono">{e.source}</span>{' '}
                              <em>{e.label}</em>{' '}
                              <ProvenanceBadge
                                provenance={e.provenance}
                                size="small"
                              />
                            </p>
                          ))}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
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
