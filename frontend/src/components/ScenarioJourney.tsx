/**
 * ScenarioJourney
 *
 * Shows a packet's path through a scenario, one hop at a time, with
 * controls to step forward, step back, and replay.
 *
 * The trace comes from the backend. This component never works out a route
 * itself; it only presents what the engine decided and explains it.
 */

import { useEffect, useState } from 'react';
import type {
  Scenario,
  ScenarioTrace,
  TraceHop,
  TraceStatus,
  TopologyGraph,
} from '../types/routing';
import { fetchScenarioTopology } from '../api/routing';
import ProvenanceBadge from './ProvenanceBadge';
import ComparePanel from './ComparePanel';
import TopologyGraphPanel from './TopologyGraph';
import RouteEditor from './RouteEditor';
import './ScenarioJourney.css';

interface ScenarioJourneyProps {
  scenario: Scenario | null;
  trace: ScenarioTrace | null;
  loading: boolean;
  error: string | null;
  /** Workspace id from the last route edit, so the edit is traced. */
  workspace?: string | null;
  onTrace: (src: string, dst: string, workspace?: string | null) => void;
}

const STATUS_LABELS: Record<TraceStatus, string> = {
  delivered: 'Delivered',
  no_route: 'No route to destination',
  unresolved_next_hop: 'Next hop could not be reached',
  not_forwarding: 'Device does not forward packets',
  loop: 'Routing loop detected',
  max_hops: 'Too many hops',
};

const STATUS_EXPLANATIONS: Record<TraceStatus, string> = {
  delivered: 'The packet reached the destination host.',
  no_route:
    'The packet was dropped because no route in the table covers the destination. A default route (0.0.0.0/0) would catch anything else.',
  unresolved_next_hop:
    'A route was chosen, but the next hop it points to is not on the outgoing network, so the packet cannot be delivered.',
  not_forwarding:
    'The packet reached a host, and hosts do not forward packets. Only routers do.',
  loop:
    'The path returned to a router it had already visited, so the packet would circulate forever.',
  max_hops:
    'The packet travelled through many routers without reaching the destination.',
};

const ACTION_LABELS: Record<TraceHop['action'], string> = {
  forward: 'Forwarded',
  delivered: 'Delivered',
  dropped: 'Dropped',
};

function nodeKind(scenario: Scenario | null, nodeId: string): 'host' | 'router' | undefined {
  return scenario?.nodes.find((n) => n.id === nodeId)?.kind;
}

export default function ScenarioJourney({
  scenario,
  trace,
  loading,
  error,
  workspace,
  onTrace,
}: ScenarioJourneyProps) {
  const [currentHop, setCurrentHop] = useState(0);
  const [source, setSource] = useState('');
  const [destination, setDestination] = useState('');

  const [topology, setTopology] = useState<TopologyGraph | null>(null);
  const [topologyLoading, setTopologyLoading] = useState(false);
  const [topologyError, setTopologyError] = useState<string | null>(null);

  // Which node's routes are being edited, and the local copy of the
  // scenario that reflects the last saved edit.
  const [editingNode, setEditingNode] = useState<string | null>(null);
  const [editedScenario, setEditedScenario] = useState<Scenario | null>(null);

  // The scenario currently shown is the edited copy when there is one.
  const activeScenario = editedScenario ?? scenario;

  // Load the topology whenever the scenario changes.
  useEffect(() => {
    if (!activeScenario) {
      setTopology(null);
      return;
    }
    let cancelled = false;
    setTopologyLoading(true);
    setTopologyError(null);
    fetchScenarioTopology(activeScenario.id, workspace)
      .then((graph) => {
        if (!cancelled) setTopology(graph);
      })
      .catch((err) => {
        if (!cancelled) {
          setTopologyError(
            err instanceof Error ? err.message : 'Could not read the topology'
          );
        }
      })
      .finally(() => {
        if (!cancelled) setTopologyLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeScenario, workspace]);

  const hops = trace?.hops ?? [];
  const activeIndex = Math.min(currentHop, Math.max(0, hops.length - 1));
  const activeHop = hops[activeIndex];

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!source.trim() || !destination.trim()) return;
    setCurrentHop(0);
    onTrace(source.trim(), destination.trim(), workspace);
  };

  const handleReplay = () => {
    if (!source.trim() || !destination.trim()) return;
    setCurrentHop(0);
    onTrace(source.trim(), destination.trim(), workspace);
  };

  const isFailure = trace ? trace.status !== 'delivered' : false;

  return (
    <div className="scenario-journey">
      <div className="scenario-journey-header">
        <div>
          <h2>Packet Journey</h2>
          <p className="scenario-subtitle">
            Send a packet through the scenario and watch each forwarding decision.
          </p>
        </div>
        <ProvenanceBadge provenance="simulated" label="Simulated" showDescription />
      </div>

      <form className="scenario-form" onSubmit={handleSubmit}>
        <div className="scenario-form-fields">
          <div className="scenario-field">
            <label htmlFor="scenario-src">From device</label>
            <select
              id="scenario-src"
              value={source}
              onChange={(e) => setSource(e.target.value)}
              required
            >
              <option value="">Choose a device…</option>
              {activeScenario?.nodes.map((node) => (
                <option key={node.id} value={node.id}>
                  {node.id} ({node.kind})
                </option>
              ))}
            </select>
          </div>

          <div className="scenario-field">
            <label htmlFor="scenario-dst">To IP address</label>
            <input
              id="scenario-dst"
              type="text"
              value={destination}
              onChange={(e) => setDestination(e.target.value)}
              placeholder="e.g. 10.0.0.2"
              spellCheck={false}
              required
            />
          </div>

          <button type="submit" className="btn btn-primary" disabled={loading}>
            {loading ? 'Tracing…' : 'Send Packet'}
          </button>
        </div>
      </form>

      {error && (
        <div className="error-message" role="alert">
          <span aria-hidden="true">⚠</span>
          {error}
        </div>
      )}

      {trace && (
        <div className="scenario-result">
          <div className={`scenario-status ${isFailure ? 'failure' : 'success'}`}>
            <div className="status-heading">
              <span className="status-text">{STATUS_LABELS[trace.status]}</span>
              <ProvenanceBadge provenance="simulated" size="small" />
            </div>
            <p className="status-explanation">{STATUS_EXPLANATIONS[trace.status]}</p>
          </div>

          {hops.length > 0 && (
            <>
              <div className="hop-controls">
                <button
                  type="button"
                  className="btn btn-sm btn-secondary"
                  onClick={() => setCurrentHop(0)}
                  disabled={activeIndex === 0}
                >
                  ⏮ Start
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-secondary"
                  onClick={() => setCurrentHop((i) => Math.max(0, i - 1))}
                  disabled={activeIndex === 0}
                >
                  ← Previous
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-secondary"
                  onClick={() => setCurrentHop((i) => Math.min(hops.length - 1, i + 1))}
                  disabled={activeIndex >= hops.length - 1}
                >
                  Next →
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-secondary"
                  onClick={handleReplay}
                >
                  ↻ Replay
                </button>
                <span className="hop-position">
                  Hop {activeIndex + 1} of {hops.length}
                </span>
              </div>

              <ol className="hop-timeline">
                {hops.map((hop, index) => (
                  <li
                    key={index}
                    className={`hop-entry ${hop.action} ${
                      index === activeIndex ? 'active' : ''
                    } ${index < activeIndex ? 'passed' : ''}`}
                  >
                    <button
                      type="button"
                      className="hop-entry-button"
                      onClick={() => setCurrentHop(index)}
                      aria-current={index === activeIndex}
                    >
                      <span className="hop-entry-number">Hop {hop.hop_number}</span>
                      <span className="hop-entry-node">{hop.node}</span>
                      <span className={`hop-entry-action ${hop.action}`}>
                        {ACTION_LABELS[hop.action]}
                      </span>
                    </button>
                  </li>
                ))}
              </ol>

              {activeHop && (
                <div className="hop-detail">
                  <div className="hop-detail-header">
                    <h3>
                      Hop {activeHop.hop_number} — {activeHop.node}
                    </h3>
                    <span className={`node-kind ${nodeKind(scenario, activeHop.node) ?? ''}`}>
                      {nodeKind(scenario, activeHop.node) ?? 'device'}
                    </span>
                  </div>

                  <p className="hop-detail-explanation">{activeHop.explanation}</p>

                  {activeHop.matched && (
                    <table className="hop-detail-table">
                      <tbody>
                        <tr>
                          <th scope="row">Route selected</th>
                          <td className="mono">{activeHop.matched.prefix}</td>
                        </tr>
                        <tr>
                          <th scope="row">Prefix length</th>
                          <td className="mono">/{activeHop.matched.prefix.split('/')[1]}</td>
                        </tr>
                        <tr>
                          <th scope="row">Next hop</th>
                          <td className="mono">
                            {activeHop.matched.via ?? 'directly connected'}
                          </td>
                        </tr>
                        <tr>
                          <th scope="row">Outgoing interface</th>
                          <td className="mono">{activeHop.matched.dev}</td>
                        </tr>
                        <tr>
                          <th scope="row">Metric</th>
                          <td className="mono">{activeHop.matched.metric}</td>
                        </tr>
                        <tr>
                          <th scope="row">Route source</th>
                          <td>{activeHop.matched.source}</td>
                        </tr>
                      </tbody>
                    </table>
                  )}

                  {activeHop.candidates.length > 1 && (
                    <div className="hop-candidates">
                      <h4>Routes that matched, and why this one won</h4>
                      <ul>
                        {activeHop.candidates.map((cand, i) => (
                          <li
                            key={i}
                            className={cand.prefix === activeHop.matched?.prefix ? 'winner' : ''}
                          >
                            <span className="mono">{cand.prefix}</span>
                            {cand.prefix === activeHop.matched?.prefix && (
                              <span className="candidate-badge">selected</span>
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {activeHop.next_node && (
                    <p className="hop-next">
                      Handed to <strong>{activeHop.next_node}</strong> next.
                    </p>
                  )}
                </div>
              )}
            </>
          )}

          {trace && (
            <ComparePanel
              scenarioId={scenario?.id ?? null}
              src={source.trim()}
              dst={destination.trim()}
            />
          )}

          <TopologyGraphPanel
            graph={topology}
            loading={topologyLoading}
            error={topologyError}
          />

          {activeScenario && (
            <div className="route-editor-section">
              <div className="route-editor-picker">
                <label htmlFor="route-editor-node">Edit routes on:</label>
                <select
                  id="route-editor-node"
                  value={editingNode ?? ''}
                  onChange={(e) => setEditingNode(e.target.value || null)}
                >
                  <option value="">Choose a device…</option>
                  {activeScenario.nodes.map((node) => (
                    <option key={node.id} value={node.id}>
                      {node.id} ({node.kind})
                    </option>
                  ))}
                </select>
              </div>

              {editingNode && (
                <RouteEditor
                  scenario={activeScenario}
                  nodeId={editingNode}
                  onSaved={(updated, updatedWorkspace) => {
                    setEditedScenario(updated);
                    // Re-run the same trace so the effect of the edit is visible.
                    if (source.trim() && destination.trim()) {
                      onTrace(source.trim(), destination.trim(), updatedWorkspace);
                    }
                  }}
                />
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
