/**
 * TopologyGraph
 *
 * The network as a spatial map, and the same network as a list.
 *
 * The graph is for exploring relationships: zoom, pan, click a node to see
 * what it is connected to. The list is for reading: every node and every
 * relationship, in a table, reachable by keyboard, with the same provenance
 * shown. Neither replaces the other.
 *
 * Two rules hold in both views:
 *
 *   - A relationship is drawn only when the backend reported one. Nothing
 *     is connected to fill a gap.
 *   - A node keeps its provenance. A simulated node never looks observed.
 */

import { lazy, Suspense, useCallback, useMemo, useState } from 'react';
import type {
  TopologyGraph as TopologyGraphData,
  TopologyNode,
  TopologyEdge,
  TopologyProvenance,
} from '../types/routing';
import ProvenanceBadge from './ProvenanceBadge';
import './TopologyGraph.css';

/**
 * The graph renderer is a large dependency and is only needed once a reader
 * asks for the graph. It is fetched on demand, so the list view — and the
 * first paint of the page — do not pay for it.
 */
const TopologyCanvas = lazy(() => import('./TopologyCanvas'));

interface TopologyGraphProps {
  graph: TopologyGraphData | null;
  loading: boolean;
  error: string | null;
  /**
   * The device names the traced packet actually visited, in order.
   *
   * These are scenario device names. The topology records scenario devices
   * with a `sim:` prefix, so a name is matched only when that exact node
   * exists. A name with no matching node is ignored: the path is never
   * guessed at, and an observed device is never marked as if the packet
   * had travelled through it.
   */
  pathNodeNames?: string[];
}

type ViewMode = 'graph' | 'list';

const PROVENANCE_ORDER: TopologyProvenance[] = [
  'observed',
  'inferred',
  'simulated',
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

export default function TopologyGraphPanel({
  graph,
  loading,
  error,
  pathNodeNames = [],
}: TopologyGraphProps) {
  const [mode, setMode] = useState<ViewMode>('graph');
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeKey, setSelectedEdgeKey] = useState<string | null>(null);

  /**
   * The traced path, matched to the topology.
   *
   * Only a device that is present in the graph is marked. The result is
   * empty when the backend reported a path through devices the topology
   * does not contain, and then nothing is highlighted.
   */
  const path = useMemo(() => {
    if (!graph || pathNodeNames.length === 0) {
      return { nodeIds: new Set<string>(), edgeKeys: new Set<string>(), matched: 0 };
    }

    const nodeIds = new Set<string>();
    const ordered: string[] = [];
    for (const name of pathNodeNames) {
      const candidate = `sim:${name}`;
      if (graph.nodes.some((node) => node.id === candidate)) {
        nodeIds.add(candidate);
        ordered.push(candidate);
      }
    }

    // The relationships between consecutive devices on the path. Only
    // relationships the backend reported are used.
    const edgeKeys = new Set<string>();
    for (let i = 0; i < ordered.length - 1; i++) {
      const from = ordered[i];
      const to = ordered[i + 1];
      graph.edges.forEach((edge, index) => {
        if (edge.source === from && edge.target === to) {
          edgeKeys.add(`${edge.source}-${edge.target}-${index}`);
        }
      });
    }

    return { nodeIds, edgeKeys, matched: nodeIds.size };
  }, [graph, pathNodeNames]);

  /** The node the reader is looking at, and the edges that touch it. */
  const selection = useMemo(() => {
    if (!graph) return { node: null, edges: [] as TopologyEdge[], nodeIds: new Set<string>() };

    if (selectedNodeId) {
      const node = graph.nodes.find((n) => n.id === selectedNodeId) ?? null;
      const edges = graph.edges.filter(
        (e) => e.source === selectedNodeId || e.target === selectedNodeId
      );
      const nodeIds = new Set<string>([selectedNodeId]);
      for (const edge of edges) {
        nodeIds.add(edge.source);
        nodeIds.add(edge.target);
      }
      return { node, edges, nodeIds };
    }

    if (selectedEdgeKey) {
      const edge = graph.edges.find(
        (e, i) => `${e.source}-${e.target}-${i}` === selectedEdgeKey
      );
      if (!edge) return { node: null, edges: [], nodeIds: new Set<string>() };
      return {
        node: null,
        edges: [edge],
        nodeIds: new Set([edge.source, edge.target]),
      };
    }

    return { node: null, edges: [], nodeIds: new Set<string>() };
  }, [graph, selectedNodeId, selectedEdgeKey]);

  /** The edge keys belonging to the current selection, for the renderer. */
  const highlightedEdgeKeys = useMemo(() => {
    const keys = new Set<string>();
    if (!graph) return keys;
    graph.edges.forEach((edge, index) => {
      if (selection.edges.includes(edge)) {
        keys.add(`${edge.source}-${edge.target}-${index}`);
      }
    });
    return keys;
  }, [graph, selection.edges]);

  const handleNodeSelect = useCallback((nodeId: string) => {
    setSelectedEdgeKey(null);
    setSelectedNodeId((current) => (current === nodeId ? null : nodeId));
  }, []);

  const handleEdgeSelect = useCallback((edgeKey: string) => {
    setSelectedNodeId(null);
    setSelectedEdgeKey((current) => (current === edgeKey ? null : edgeKey));
  }, []);

  const handlePaneClick = useCallback(() => {
    setSelectedNodeId(null);
    setSelectedEdgeKey(null);
  }, []);

  const selectedEdge = useMemo(() => {
    if (!selectedEdgeKey || !graph) return null;
    const index = graph.edges.findIndex(
      (e, i) => `${e.source}-${e.target}-${i}` === selectedEdgeKey
    );
    return index === -1 ? null : graph.edges[index];
  }, [selectedEdgeKey, graph]);

  const nodeById = useMemo(() => {
    const map = new Map<string, TopologyNode>();
    for (const node of graph?.nodes ?? []) map.set(node.id, node);
    return map;
  }, [graph]);

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

  if (!graph) return null;

  const observed = graph.nodes.filter((n) => n.provenance === 'observed').length;
  const simulated = graph.nodes.filter((n) => n.provenance === 'simulated').length;
  const inferredEdges = graph.edges.filter((e) => e.provenance === 'inferred').length;

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
          {path.matched > 0 && (
            <span className="topology-path-legend">
              traced path
            </span>
          )}
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
          <strong>{inferredEdges}</strong> inferred relationship
          {inferredEdges === 1 ? '' : 's'}
        </span>
        <span className="topology-timestamp">
          Read at {new Date(graph.observed_at).toLocaleTimeString()}
        </span>
      </div>

      {graph.nodes.length === 0 ? (
        <div className="topology-empty" role="status">
          <p>Nothing was observed.</p>
          <p className="topology-empty-hint">
            No interfaces, routes, or neighbours could be read, and no scenario
            is loaded.
          </p>
        </div>
      ) : (
        <>
          {/* List | Graph switch */}
          <div className="topology-switch" role="group" aria-label="View mode">
            <button
              type="button"
              className={`view-chip ${mode === 'graph' ? 'active' : ''}`}
              onClick={() => setMode('graph')}
              aria-pressed={mode === 'graph'}
            >
              Graph
            </button>
            <button
              type="button"
              className={`view-chip ${mode === 'list' ? 'active' : ''}`}
              onClick={() => setMode('list')}
              aria-pressed={mode === 'list'}
            >
              List
            </button>
          </div>

          {mode === 'graph' ? (
            <Suspense
              fallback={
                <div className="topology-canvas topology-canvas-loading">
                  <span className="spinner" aria-hidden="true" />
                  Loading the graph renderer…
                </div>
              }
            >
              <TopologyCanvas
                graph={graph}
                selectedNodeId={selectedNodeId}
                selectedEdgeKey={selectedEdgeKey}
                highlightedIds={selection.nodeIds}
                highlightedEdgeKeys={highlightedEdgeKeys}
                pathNodeIds={path.nodeIds}
                pathEdgeKeys={path.edgeKeys}
                onNodeSelect={handleNodeSelect}
                onEdgeSelect={handleEdgeSelect}
                onPaneClick={handlePaneClick}
              />
            </Suspense>
          ) : (
            <div className="topology-list">
              <h4 className="topology-list-heading">
                Nodes ({graph.nodes.length})
              </h4>
              <div className="table-container">
                <table className="topology-node-table">
                  <caption className="visually-hidden">
                    Every device in the topology, with its provenance
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col">Device</th>
                      <th scope="col">Kind</th>
                      <th scope="col">Addresses</th>
                      <th scope="col">Provenance</th>
                      <th scope="col">Links</th>
                    </tr>
                  </thead>
                  <tbody>
                    {graph.nodes.map((node) => {
                      const links = graph.edges.filter(
                        (e) => e.source === node.id || e.target === node.id
                      ).length;
                      const onPath = path.nodeIds.has(node.id);
                      return (
                        <tr
                          key={node.id}
                          className={
                            selectedNodeId === node.id ? 'selected' : undefined
                          }
                        >
                          <td>
                            <button
                              type="button"
                              className="topology-node-button"
                              onClick={() => {
                                setSelectedEdgeKey(null);
                                setSelectedNodeId((current) =>
                                  current === node.id ? null : node.id
                                );
                              }}
                              aria-pressed={selectedNodeId === node.id}
                            >
                              {node.label}
                            </button>
                            {onPath && (
                              <span className="list-path-flag">on path</span>
                            )}
                          </td>
                          <td>{KIND_LABELS[node.kind]}</td>
                          <td className="mono topology-list-addresses">
                            {node.addresses.length > 0
                              ? node.addresses.join(', ')
                              : '—'}
                          </td>
                          <td>
                            <ProvenanceBadge
                              provenance={node.provenance}
                              size="small"
                            />
                          </td>
                          <td className="mono">
                            {links > 0 ? links : 'none'}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <h4 className="topology-list-heading">
                Relationships ({graph.edges.length})
              </h4>
              {graph.edges.length === 0 ? (
                <p className="topology-empty-hint">
                  No relationships were reported. Nothing is connected to fill
                  the gap.
                </p>
              ) : (
                <div className="table-container">
                  <table className="topology-edge-table">
                    <caption className="visually-hidden">
                      Every relationship in the topology
                    </caption>
                    <thead>
                      <tr>
                        <th scope="col">From</th>
                        <th scope="col">To</th>
                        <th scope="col">Relationship</th>
                        <th scope="col">Provenance</th>
                      </tr>
                    </thead>
                    <tbody>
                      {graph.edges.map((edge, index) => {
                        const key = `${edge.source}-${edge.target}-${index}`;
                        return (
                          <tr
                            key={key}
                            className={
                              selectedEdgeKey === key ? 'selected' : undefined
                            }
                          >
                            <td className="mono">
                              {nodeById.get(edge.source)?.label ?? edge.source}
                            </td>
                            <td className="mono">
                              {nodeById.get(edge.target)?.label ?? edge.target}
                            </td>
                            <td>
                              <button
                                type="button"
                                className="topology-edge-button"
                                onClick={() => {
                                  setSelectedNodeId(null);
                                  setSelectedEdgeKey((current) =>
                                    current === key ? null : key
                                  );
                                }}
                                aria-pressed={selectedEdgeKey === key}
                              >
                                {edge.label}
                              </button>
                            </td>
                            <td>
                              <ProvenanceBadge
                                provenance={edge.provenance}
                                size="small"
                              />
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* Selection details */}
          {selection.node && (
            <div className="topology-details-panel">
              <div className="topology-detail">
                <h4>
                  {KIND_LABELS[selection.node.kind]}: {selection.node.label}
                  <ProvenanceBadge
                    provenance={selection.node.provenance}
                    size="small"
                  />
                </h4>
                {selection.node.addresses.length > 0 && (
                  <p className="topology-addresses">
                    Addresses: {selection.node.addresses.join(', ')}
                  </p>
                )}
                {selection.node.detail && (
                  <p className="topology-node-note">{selection.node.detail}</p>
                )}
                <h5>Connections</h5>
                <ul className="topology-connection-list">
                  {selection.edges.map((edge, i) => (
                    <li key={i}>
                      {edge.source === selection.node?.id ? '→' : '←'}{' '}
                      {nodeById.get(
                        edge.source === selection.node?.id
                          ? edge.target
                          : edge.source
                      )?.label ?? 'unknown'}
                      <span className="mono"> ({edge.kind})</span>
                      <ProvenanceBadge
                        provenance={edge.provenance}
                        size="small"
                      />
                      {edge.detail && (
                        <span className="edge-detail"> — {edge.detail}</span>
                      )}
                    </li>
                  ))}
                  {selection.edges.length === 0 && (
                    <li className="no-connections">
                      No evidence of connection to other nodes.
                    </li>
                  )}
                </ul>
              </div>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={handlePaneClick}
              >
                Clear Selection
              </button>
            </div>
          )}

          {selectedEdge && (
            <div className="topology-details-panel">
              <div className="topology-detail">
                <h4>Relationship: {selectedEdge.label}</h4>
                <p className="topology-addresses">
                  <span className="mono">
                    {nodeById.get(selectedEdge.source)?.label ?? selectedEdge.source}
                  </span>{' '}
                  →{' '}
                  <span className="mono">
                    {nodeById.get(selectedEdge.target)?.label ?? selectedEdge.target}
                  </span>
                </p>
                <p>
                  <ProvenanceBadge
                    provenance={selectedEdge.provenance}
                    size="medium"
                    showDescription
                  />
                </p>
                <p className="topology-node-note">
                  {selectedEdge.detail ||
                    'No additional details available.'}
                </p>
              </div>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={handlePaneClick}
              >
                Clear Selection
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
