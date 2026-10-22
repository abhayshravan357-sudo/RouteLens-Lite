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
import {
  fetchScenarioTopology,
  toggleScenarioLink,
  updateScenarioRoutes,
} from '../api/routing';
import ProvenanceBadge from './ProvenanceBadge';
import ComparePanel from './ComparePanel';
import TopologyGraphPanel from './TopologyGraph';
import RouteEditor from './RouteEditor';
import ReportPanel from './ReportPanel';
import './ScenarioJourney.css';

interface ScenarioJourneyProps {
  scenario: Scenario | null;
  trace: ScenarioTrace | null;
  loading: boolean;
  error: string | null;
  /** Workspace id from the last route edit, so the edit is traced. */
  workspace?: string | null;
  onTrace: (src: string, dst: string, workspace?: string | null) => void;
  onSelectScenario?: (scenarioId: string) => void;
}

const STATUS_LABELS: Record<TraceStatus, string> = {
  delivered: 'Delivered',
  no_route: 'No route to destination',
  unresolved_next_hop: 'Next hop could not be reached',
  link_down: 'Link is DOWN (connection disabled)',
  not_forwarding: 'Device does not forward packets',
  loop: 'Routing loop detected',
  max_hops: 'Too many hops',
};

const ACTION_LABELS: Record<TraceHop['action'], string> = {
  forward: 'Forwarded',
  delivered: 'Delivered',
  dropped: 'Dropped',
};

function nodeKind(scenario: Scenario | null, nodeId: string): 'host' | 'router' | undefined {
  return scenario?.nodes.find((n) => n.id === nodeId)?.kind;
}

interface ChallengeDef {
  id: string;
  badge: string;
  title: string;
  description: string;
  scenarioId: string;
  src: string;
  dst: string;
  goal: string;
  problem: string;
  hint: string;
  fix?: {
    nodeId: string;
    newRoute: { prefix: string; dev: string; via: string; metric: number };
  };
}

const GUIDED_CHALLENGES: ChallengeDef[] = [
  {
    id: 'broken-gateway',
    badge: '1 • Missing Gateway',
    title: 'Client Cannot Reach Remote Server',
    description: 'The client drops packets immediately. Learn why every host needs a default route (0.0.0.0/0).',
    scenarioId: 'challenge-broken-gateway',
    src: 'client',
    dst: '10.0.2.2',
    goal: 'Deliver packet from client (192.168.1.100) to server (10.0.2.2).',
    problem: 'Client has no route covering 10.0.2.2. It only knows its local LAN (192.168.1.0/24).',
    hint: 'Add a default gateway route (0.0.0.0/0) pointing to router 192.168.1.1 on dev eth0.',
    fix: {
      nodeId: 'client',
      newRoute: { prefix: '0.0.0.0/0', dev: 'eth0', via: '192.168.1.1', metric: 100 },
    },
  },
  {
    id: 'blackhole-route',
    badge: '2 • Route Blackhole',
    title: 'Mid-Network Dropped Packet',
    description: 'Client reaches Router 1, but Router 1 has no route for the destination subnet and drops it.',
    scenarioId: 'challenge-blackhole',
    src: 'client',
    dst: '10.0.1.2',
    goal: 'Forward packet through r1 and r2 to reach server (10.0.1.2).',
    problem: 'Router r1 receives the packet from client, but r1 has no route for 10.0.1.0/24.',
    hint: 'Add route 10.0.1.0/24 via 172.16.0.2 dev eth1 on router r1.',
    fix: {
      nodeId: 'r1',
      newRoute: { prefix: '10.0.1.0/24', dev: 'eth1', via: '172.16.0.2', metric: 20 },
    },
  },
  {
    id: 'cable-outage',
    badge: '3 • Link Failure Drill',
    title: 'Physical Link Sever Drill',
    description: 'Send a successful packet, then toggle a link DOWN to watch the router report connection disabled.',
    scenarioId: 'client-router-server',
    src: 'client',
    dst: '10.0.0.2',
    goal: 'Observe normal delivery, then toggle the router <-> server link DOWN.',
    problem: 'Physical links can fail. When a link is DOWN, the router drops the packet at that hop.',
    hint: 'Trace first (Delivered), then use "Link Controls" below to take the link DOWN and re-trace.',
  },
];

interface ThreeQuestionDiagnosis {
  what: string;
  why: string;
  whatToTry: string;
  actionType: 'add_route' | 'toggle_link' | 'none';
  targetNode?: string;
  targetLink?: { a: string; b: string };
}

function getThreeQuestionExplanation(
  trace: ScenarioTrace | null,
  activeScenario: Scenario | null,
  destination: string
): ThreeQuestionDiagnosis | null {
  if (!trace) return null;
  const status = trace.status;
  const hops = trace.hops;
  const failingHop = hops.length > 0 ? hops[hops.length - 1] : null;
  const failingNode = failingHop?.node ?? 'the router';

  switch (status) {
    case 'delivered':
      return {
        what: `The packet successfully arrived at the destination host (${destination || 'target'}).`,
        why: `Every router on the path found a matching route and forwarded the packet across healthy, active physical links.`,
        whatToTry: `Test network resilience! Try toggling a link DOWN in Link Controls below to simulate a severed cable, or inspect each router's routing table.`,
        actionType: 'none',
      };
    case 'no_route':
      return {
        what: `The packet was dropped at ${failingNode}.`,
        why: `${failingNode} looked up ${destination || 'the destination'} in its routing table, but found no matching subnet or default gateway (0.0.0.0/0).`,
        whatToTry: `Inspect ${failingNode}'s routing table below, then add a route covering ${destination || 'the subnet'} pointing to the next-hop router.`,
        actionType: 'add_route',
        targetNode: failingNode,
      };
    case 'link_down': {
      const downLink = activeScenario?.links.find((l) => l.is_up === false);
      const linkLabel = downLink ? `${downLink.a} <-> ${downLink.b}` : 'the selected connection';
      return {
        what: `The packet was dropped at ${failingNode} because the outgoing cable is disabled.`,
        why: `A valid route was selected, but the physical link (${linkLabel}) is currently marked DOWN.`,
        whatToTry: `Click "Bring Link UP" below to restore the connection, then re-send the packet to verify recovery.`,
        actionType: 'toggle_link',
        targetNode: failingNode,
        targetLink: downLink ? { a: downLink.a, b: downLink.b } : undefined,
      };
    }
    case 'unresolved_next_hop':
      return {
        what: `Forwarding failed at ${failingNode}.`,
        why: `A route matched, but its next-hop gateway address does not exist on any attached subnet.`,
        whatToTry: `Edit the route on ${failingNode} and correct the "via" IP address to a valid gateway on that network.`,
        actionType: 'add_route',
        targetNode: failingNode,
      };
    case 'not_forwarding':
      return {
        what: `The packet stopped at ${failingNode}.`,
        why: `${failingNode} is an end-host, not a router. By standard network design, end-hosts do not route packets between networks.`,
        whatToTry: `Check your network design and route traffic through an intermediate router instead of another host.`,
        actionType: 'none',
      };
    case 'loop':
      return {
        what: `A routing loop was detected!`,
        why: `The packet circulated between the same routers repeatedly, which would cause infinite circulation and packet drop.`,
        whatToTry: `Inspect the routing tables of routers along the path and correct conflicting next-hop routes.`,
        actionType: 'none',
      };
    case 'max_hops':
      return {
        what: `Packet TTL expired (exceeded maximum hops).`,
        why: `The packet traversed too many routers without reaching the destination.`,
        whatToTry: `Check for long sub-optimal routing paths or circular routes.`,
        actionType: 'none',
      };
    default:
      return null;
  }
}

export default function ScenarioJourney({
  scenario,
  trace,
  loading,
  error,
  workspace,
  onTrace,
  onSelectScenario,
}: ScenarioJourneyProps) {
  const [currentHop, setCurrentHop] = useState(0);
  const [source, setSource] = useState('');
  const [destination, setDestination] = useState('');

  // Mode: Beginner vs Expert
  const [userMode, setUserMode] = useState<'beginner' | 'expert'>('beginner');

  const [topology, setTopology] = useState<TopologyGraph | null>(null);
  const [topologyLoading, setTopologyLoading] = useState(false);
  const [topologyError, setTopologyError] = useState<string | null>(null);

  // Guided challenge state
  const [activeChallengeId, setActiveChallengeId] = useState<string | null>(null);
  const [fixingChallenge, setFixingChallenge] = useState(false);

  // Route editing state
  const [editingNode, setEditingNode] = useState<string | null>(null);
  const [editedScenario, setEditedScenario] = useState<Scenario | null>(null);

  // Experiment history stack for safe undo / redo / reset
  const [history, setHistory] = useState<{
    scenario: Scenario;
    workspace?: string | null;
    intervention: string;
  }[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);

  // Before vs After comparison tracking: preserve prior trace
  const [previousTrace, setPreviousTrace] = useState<ScenarioTrace | null>(null);
  const [lastIntervention, setLastIntervention] = useState<string | null>(null);

  // Active router full table inspection drawer
  const [inspectingNodeId, setInspectingNodeId] = useState<string | null>(null);

  // Link toggling feedback
  const [linkToggling, setLinkToggling] = useState(false);
  const [linkError, setLinkError] = useState<string | null>(null);

  // Track scenario switches to reset history safely
  const [lastScenarioId, setLastScenarioId] = useState<string | null>(null);

  useEffect(() => {
    if (scenario && scenario.id !== lastScenarioId) {
      setLastScenarioId(scenario.id);
      setPreviousTrace(null);
      setLastIntervention(null);
      setEditedScenario(null);
      setEditingNode(null);
      setInspectingNodeId(null);
      setHistory([{ scenario, workspace: null, intervention: 'Loaded original scenario' }]);
      setHistoryIndex(0);

      // Auto-prefill endpoints for this scenario
      const hosts = scenario.nodes.filter((n) => n.kind === 'host');
      const defaultSrc = hosts[0]?.id ?? scenario.nodes[0]?.id ?? '';
      setSource(defaultSrc);

      const targetHost = hosts.find((n) => n.id !== defaultSrc) ?? hosts[hosts.length - 1];
      const targetIp = targetHost?.ifaces[0]?.cidr.split('/')[0] ?? '';
      if (targetIp) setDestination(targetIp);
    }
  }, [scenario, lastScenarioId]);

  const pushHistory = (
    newScenario: Scenario,
    newWorkspace: string | null | undefined,
    interventionText: string
  ) => {
    const nextHistory = history.slice(0, historyIndex + 1);
    nextHistory.push({
      scenario: newScenario,
      workspace: newWorkspace,
      intervention: interventionText,
    });
    setHistory(nextHistory);
    setHistoryIndex(nextHistory.length - 1);
  };

  const handleUndo = () => {
    if (historyIndex <= 0) return;
    const target = history[historyIndex - 1];
    setHistoryIndex(historyIndex - 1);
    setEditedScenario(target.scenario);
    setLastIntervention(`Undid: ${history[historyIndex].intervention}`);
    if (trace) setPreviousTrace(trace);
    if (source.trim() && destination.trim()) {
      onTrace(source.trim(), destination.trim(), target.workspace);
    }
  };

  const handleRedo = () => {
    if (historyIndex >= history.length - 1) return;
    const target = history[historyIndex + 1];
    setHistoryIndex(historyIndex + 1);
    setEditedScenario(target.scenario);
    setLastIntervention(`Redid: ${target.intervention}`);
    if (trace) setPreviousTrace(trace);
    if (source.trim() && destination.trim()) {
      onTrace(source.trim(), destination.trim(), target.workspace);
    }
  };

  const handleResetScenario = () => {
    if (!scenario) return;
    setEditedScenario(null);
    setPreviousTrace(null);
    setLastIntervention('Reset scenario to pristine original state');
    setEditingNode(null);
    setInspectingNodeId(null);
    setHistory([{ scenario, workspace: null, intervention: 'Reset to original' }]);
    setHistoryIndex(0);
    if (source.trim() && destination.trim()) {
      onTrace(source.trim(), destination.trim(), null);
    }
  };

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

  const activeChallenge = GUIDED_CHALLENGES.find((c) => c.id === activeChallengeId);

  const handleLaunchChallenge = (ch: ChallengeDef) => {
    setActiveChallengeId(ch.id);
    setSource(ch.src);
    setDestination(ch.dst);
    setCurrentHop(0);
    if (scenario?.id !== ch.scenarioId) {
      if (onSelectScenario) {
        onSelectScenario(ch.scenarioId);
      }
    }
    onTrace(ch.src, ch.dst, workspace);
  };

  const handleApplyChallengeFix = async (ch: ChallengeDef) => {
    if (!activeScenario || !ch.fix) return;
    setFixingChallenge(true);
    try {
      const targetNode = activeScenario.nodes.find((n) => n.id === ch.fix!.nodeId);
      const existingRoutes =
        targetNode?.routes.map((r) => ({
          prefix: r.prefix,
          dev: r.dev,
          via: r.via,
          metric: r.metric,
        })) ?? [];
      const updatedRoutes = [...existingRoutes, ch.fix.newRoute];

      const res = await updateScenarioRoutes(activeScenario.id, ch.fix.nodeId, updatedRoutes);
      setEditedScenario(res.scenario);
      const actionText = `Fixed ${ch.fix.nodeId}: Added route ${ch.fix.newRoute.prefix} via ${ch.fix.newRoute.via}`;
      setLastIntervention(actionText);
      pushHistory(res.scenario, res.workspace, actionText);
      if (trace) {
        setPreviousTrace(trace);
      }
      onTrace(ch.src, ch.dst, res.workspace);
    } catch (err) {
      console.error('Failed to apply challenge fix:', err);
    } finally {
      setFixingChallenge(false);
    }
  };

  const handleLinkToggle = async (linkA: string, linkB: string, currentIsUp: boolean) => {
    if (!activeScenario) return;
    setLinkToggling(true);
    setLinkError(null);
    try {
      const res = await toggleScenarioLink(
        activeScenario.id,
        linkA,
        linkB,
        !currentIsUp,
        workspace
      );
      setEditedScenario(res.scenario);
      const actionText = `Toggled link ${linkA} <-> ${linkB} ${!currentIsUp ? 'UP' : 'DOWN'}`;
      setLastIntervention(actionText);
      pushHistory(res.scenario, res.workspace, actionText);
      if (trace) {
        setPreviousTrace(trace);
      }
      if (source.trim() && destination.trim()) {
        onTrace(source.trim(), destination.trim(), res.workspace);
      }
    } catch (err) {
      setLinkError(err instanceof Error ? err.message : 'Could not change link state');
    } finally {
      setLinkToggling(false);
    }
  };

  const inspectedNode = activeScenario?.nodes.find((n) => n.id === inspectingNodeId);

  // Experiment export bundle for ReportPanel
  const activeExperimentPayload = trace && activeScenario
    ? {
        scenario_id: activeScenario.id,
        scenario_title: activeScenario.title,
        source: source.trim(),
        destination: destination.trim(),
        status: trace.status,
        hops: trace.hops.map((h) => ({
          hop_number: h.hop_number,
          node: h.node,
          action: h.action,
          matched: h.matched ? { prefix: h.matched.prefix, dev: h.matched.dev, via: h.matched.via } : null,
          explanation: h.explanation,
          next_node: h.next_node,
        })),
        comparison: previousTrace
          ? {
              before_status: previousTrace.status,
              after_status: trace.status,
              intervention: lastIntervention ?? 'Route/link configuration update',
              resolved: previousTrace.status !== 'delivered' && trace.status === 'delivered',
            }
          : null,
      }
    : null;

  const diag = getThreeQuestionExplanation(trace, activeScenario, destination.trim());

  return (
    <div className="scenario-journey">
      {/* ─── Header: Title & Beginner / Expert Switch ─── */}
      <div className="scenario-journey-header">
        <div>
          <h2>Packet Journey</h2>
          <p className="scenario-subtitle">
            Send a packet through the scenario and watch each forwarding decision.
          </p>
        </div>
        <div className="header-actions">
          <div className="mode-toggle-group" role="group" aria-label="Explanation detail level">
            <button
              type="button"
              className={`mode-toggle-btn ${userMode === 'beginner' ? 'active' : ''}`}
              onClick={() => setUserMode('beginner')}
            >
              🌱 Beginner Mode
            </button>
            <button
              type="button"
              className={`mode-toggle-btn ${userMode === 'expert' ? 'active' : ''}`}
              onClick={() => setUserMode('expert')}
            >
              🔬 Expert Mode
            </button>
          </div>
          <ProvenanceBadge provenance="simulated" label="Simulated" showDescription />
        </div>
      </div>

      {/* ─── Experiment Controls: Undo / Redo / Reset ─── */}
      <div className="sandbox-controls-bar">
        <div className="history-buttons">
          <button
            type="button"
            className="btn btn-sm btn-secondary history-btn"
            onClick={handleUndo}
            disabled={historyIndex <= 0}
            title="Undo last route or link change"
          >
            ↩ Undo
          </button>
          <button
            type="button"
            className="btn btn-sm btn-secondary history-btn"
            onClick={handleRedo}
            disabled={historyIndex >= history.length - 1}
            title="Redo previously undone change"
          >
            ↪ Redo
          </button>
          <button
            type="button"
            className="btn btn-sm btn-secondary reset-example-btn"
            onClick={handleResetScenario}
            title="Reset this network back to its clean starting state"
          >
            ↺ Reset Example
          </button>
        </div>
        <div className="sandbox-status-text">
          {lastIntervention ? (
            <span>Active change: <strong>{lastIntervention}</strong></span>
          ) : (
            <span>Pristine scenario state</span>
          )}
        </div>
      </div>

      {/* ─── Guided Challenges & Quick Start ─── */}
      <div className="guided-challenges-panel">
        <div className="guided-challenges-title-row">
          <div className="guided-challenges-title">
            <span className="guided-tag">🚀 1-Click Guided Troubleshooting</span>
            <h3>Practice Scenarios & Hands-On Drills</h3>
          </div>
          <span className="guided-sub">Select any challenge to automatically load and trace it:</span>
        </div>
        <div className="guided-challenges-grid">
          {GUIDED_CHALLENGES.map((ch) => {
            const isCurrent = activeChallengeId === ch.id;
            return (
              <div
                key={ch.id}
                className={`guided-card ${isCurrent ? 'active' : ''}`}
                onClick={() => handleLaunchChallenge(ch)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') handleLaunchChallenge(ch);
                }}
              >
                <div className="guided-card-badge">{ch.badge}</div>
                <div className="guided-card-name">{ch.title}</div>
                <div className="guided-card-desc">{ch.description}</div>
                <div className="guided-card-meta">
                  <span className="guided-card-route">
                    <code>{ch.src}</code> ➔ <code>{ch.dst}</code>
                  </span>
                  <button type="button" className={`btn btn-sm ${isCurrent ? 'btn-primary' : 'btn-secondary'}`}>
                    {isCurrent ? 'Active Drill' : 'Start Drill ➔'}
                  </button>
                </div>
              </div>
            );
          })}
        </div>

        {activeChallenge && (
          <div className="active-challenge-callout">
            <div className="active-challenge-top">
              <strong>🎯 Goal:</strong> {activeChallenge.goal}
              <button
                type="button"
                className="btn btn-sm btn-secondary close-challenge-btn"
                onClick={() => setActiveChallengeId(null)}
              >
                Clear Challenge ✕
              </button>
            </div>
            <div className="active-challenge-issue">
              <strong>The Problem:</strong> {activeChallenge.problem}
            </div>
            <div className="active-challenge-hint">
              💡 <strong>Hint:</strong> {activeChallenge.hint}
            </div>
            {activeChallenge.fix && (
              <div className="active-challenge-btn-row">
                <button
                  type="button"
                  className="btn btn-sm btn-success"
                  disabled={fixingChallenge}
                  onClick={() => handleApplyChallengeFix(activeChallenge)}
                >
                  {fixingChallenge ? 'Applying Fix…' : '⚡ 1-Click Fix & Verify Result'}
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-secondary"
                  onClick={() => {
                    setEditingNode(activeChallenge.fix!.nodeId);
                    const el = document.querySelector('.route-editor-section');
                    if (el) el.scrollIntoView({ behavior: 'smooth' });
                  }}
                >
                  ✏️ Edit Route Manually in Route Editor Below
                </button>
              </div>
            )}
          </div>
        )}
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

      {/* Before vs After Comparison Banner */}
      {previousTrace && trace && (
        <div className="trace-comparison-banner" role="region" aria-label="Before vs After Trace Comparison">
          <div className="comparison-header">
            <h4>Troubleshooting Comparison (Before vs After)</h4>
            {lastIntervention && <span className="comparison-intervention">{lastIntervention}</span>}
          </div>
          <div className="comparison-grid">
            <div className={`comparison-col ${previousTrace.status === 'delivered' ? 'success' : 'failure'}`}>
              <span className="comparison-badge">BEFORE</span>
              <strong>{STATUS_LABELS[previousTrace.status]}</strong>
              <span className="comparison-sub">{previousTrace.hops.length} hop(s) traversed</span>
            </div>
            <div className="comparison-arrow" aria-hidden="true">➔</div>
            <div className={`comparison-col ${trace.status === 'delivered' ? 'success' : 'failure'}`}>
              <span className="comparison-badge">AFTER</span>
              <strong>{STATUS_LABELS[trace.status]}</strong>
              <span className="comparison-sub">{trace.hops.length} hop(s) traversed</span>
            </div>
          </div>
          {previousTrace.status !== 'delivered' && trace.status === 'delivered' && (
            <p className="comparison-success-note">
              ✓ Fix Verified: The routing intervention resolved the forwarding failure.
            </p>
          )}
        </div>
      )}

      {trace && (
        <div className="scenario-result">
          {/* ─── 3-Question Plain-English Diagnosis Card ─── */}
          {diag && (
            <div className={`experiment-diagnosis-card ${isFailure ? 'failure' : 'success'}`}>
              <div className="diagnosis-top-row">
                <div className="diagnosis-title-group">
                  <span className="diagnosis-status-icon">{isFailure ? '❌' : '✅'}</span>
                  <div>
                    <h3 className="diagnosis-main-title">
                      {isFailure ? 'Packet Could Not Continue' : 'Packet Successfully Delivered'}
                    </h3>
                    <span className="diagnosis-badge">{STATUS_LABELS[trace.status]}</span>
                  </div>
                </div>
                <ProvenanceBadge provenance="simulated" size="small" />
              </div>

              <div className="diagnosis-grid">
                <div className="diagnosis-card-col">
                  <span className="diagnosis-col-label">1. What happened?</span>
                  <p>{diag.what}</p>
                </div>
                <div className="diagnosis-card-col">
                  <span className="diagnosis-col-label">2. Why did it happen?</span>
                  <p>{diag.why}</p>
                </div>
                <div className="diagnosis-card-col action-col">
                  <span className="diagnosis-col-label">3. What can I try next?</span>
                  <p>{diag.whatToTry}</p>
                </div>
              </div>

              {/* Direct Action Buttons Right at the Explanation */}
              {isFailure && (
                <div className="diagnosis-action-bar">
                  {diag.actionType === 'add_route' && diag.targetNode && (
                    <>
                      <button
                        type="button"
                        className="btn btn-sm btn-primary"
                        onClick={() => {
                          setEditingNode(diag.targetNode!);
                          const el = document.querySelector('.route-editor-section');
                          if (el) el.scrollIntoView({ behavior: 'smooth' });
                        }}
                      >
                        ✏️ Add Route on {diag.targetNode}
                      </button>
                      <button
                        type="button"
                        className="btn btn-sm btn-secondary"
                        onClick={() => setInspectingNodeId(diag.targetNode!)}
                      >
                        🔍 Inspect {diag.targetNode} Routing Table
                      </button>
                    </>
                  )}
                  {diag.actionType === 'toggle_link' && diag.targetLink && (
                    <button
                      type="button"
                      className="btn btn-sm btn-success"
                      disabled={linkToggling}
                      onClick={() => handleLinkToggle(diag.targetLink!.a, diag.targetLink!.b, false)}
                    >
                      ⚡ Bring Link UP & Retest
                    </button>
                  )}
                </div>
              )}
            </div>
          )}

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

                  {/* Route details: always shown if matched, or in expert mode */}
                  {activeHop.matched && (
                    <table className="hop-detail-table">
                      <tbody>
                        <tr>
                          <th scope="row">Route selected</th>
                          <td className="mono">{activeHop.matched.prefix}</td>
                        </tr>
                        {userMode === 'expert' && (
                          <tr>
                            <th scope="row">Prefix length</th>
                            <td className="mono">/{activeHop.matched.prefix.split('/')[1]}</td>
                          </tr>
                        )}
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
                        {userMode === 'expert' && (
                          <>
                            <tr>
                              <th scope="row">Metric</th>
                              <td className="mono">{activeHop.matched.metric}</td>
                            </tr>
                            <tr>
                              <th scope="row">Route source</th>
                              <td>{activeHop.matched.source}</td>
                            </tr>
                          </>
                        )}
                      </tbody>
                    </table>
                  )}

                  {userMode === 'expert' && activeHop.candidates.length > 1 && (
                    <div className="hop-candidates">
                      <h4>Candidate routes evaluated (Longest Prefix Match):</h4>
                      <ul>
                        {activeHop.candidates.map((cand, i) => (
                          <li
                            key={i}
                            className={cand.prefix === activeHop.matched?.prefix ? 'winner' : ''}
                          >
                            <span className="mono">{cand.prefix}</span>
                            {cand.prefix === activeHop.matched?.prefix && (
                              <span className="candidate-badge">selected winner</span>
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

          <ComparePanel
            scenarioId={scenario?.id ?? null}
            src={source.trim()}
            dst={destination.trim()}
          />
        </div>
      )}

      <TopologyGraphPanel
        graph={topology}
        loading={topologyLoading}
        error={topologyError}
        pathNodeNames={trace ? trace.hops.map((hop) => hop.node) : []}
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
                if (trace) {
                  setPreviousTrace(trace);
                }
                const actionText = `Updated routes on ${editingNode}`;
                setLastIntervention(actionText);
                setEditedScenario(updated);
                pushHistory(updated, updatedWorkspace, actionText);
                // Re-run the same trace so the effect of the edit is visible.
                if (source.trim() && destination.trim()) {
                  onTrace(source.trim(), destination.trim(), updatedWorkspace);
                }
              }}
            />
          )}
        </div>
      )}

      {/* Link Controls */}
      {activeScenario && activeScenario.links.length > 0 && (
        <div className="link-controls-section">
          <h3 className="link-controls-heading">Link Controls</h3>
          <p className="link-controls-desc">
            Toggle individual links UP or DOWN. The next trace will respect the new state.
          </p>
          {linkError && (
            <div className="error-message" role="alert">
              <span aria-hidden="true">⚠</span> {linkError}
            </div>
          )}
          <ul className="link-controls-list">
            {activeScenario.links.map((link) => {
              const isUp = link.is_up ?? true;
              return (
                <li key={`${link.a}-${link.b}`} className="link-control-item">
                  <span className="link-control-label">
                    <code>{link.a}</code> ↔ <code>{link.b}</code>
                  </span>
                  <span className={`link-status-badge ${isUp ? 'up' : 'down'}`}>
                    {isUp ? 'UP' : 'DOWN'}
                  </span>
                  <button
                    type="button"
                    className={`btn btn-sm ${isUp ? 'btn-warning' : 'btn-success'}`}
                    disabled={linkToggling}
                    onClick={() => handleLinkToggle(link.a, link.b, isUp)}
                  >
                    {linkToggling ? '…' : isUp ? 'Take DOWN' : 'Bring UP'}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {/* Full Routing Table Inspector */}
      {inspectedNode && (
        <div className="node-inspector">
          <div className="node-inspector-header">
            <h3>Routing Table — {inspectedNode.id}</h3>
            <button
              type="button"
              className="btn btn-sm btn-secondary"
              onClick={() => setInspectingNodeId(null)}
            >
              Close ✕
            </button>
          </div>
          {inspectedNode.routes.length === 0 ? (
            <p className="node-inspector-empty">No routes configured on this device.</p>
          ) : (
            <table className="node-inspector-table">
              <thead>
                <tr>
                  <th>Prefix</th>
                  <th>Via</th>
                  <th>Dev</th>
                  <th>Metric</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {inspectedNode.routes.map((r, i) => (
                  <tr key={i}>
                    <td className="mono">{r.prefix}</td>
                    <td className="mono">{r.via ?? '—'}</td>
                    <td className="mono">{r.dev}</td>
                    <td className="mono">{r.metric}</td>
                    <td>{r.source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Inspect buttons for hop nodes */}
      {trace && trace.hops.length > 0 && activeScenario && (
        <div className="node-inspect-row">
          <span className="node-inspect-label">Inspect routing table:</span>
          {trace.hops
            .filter((h, i, arr) => arr.findIndex((x) => x.node === h.node) === i)
            .map((h) => (
              <button
                key={h.node}
                type="button"
                className={`btn btn-sm btn-secondary ${inspectingNodeId === h.node ? 'active' : ''}`}
                onClick={() =>
                  setInspectingNodeId(inspectingNodeId === h.node ? null : h.node)
                }
              >
                {h.node}
              </button>
            ))}
        </div>
      )}

      {/* Active Experiment Report Export */}
      {activeExperimentPayload && (
        <div className="experiment-report-section">
          <ReportPanel activeExperiment={activeExperimentPayload} />
        </div>
      )}
    </div>
  );
}
