/**
 * RouterDiscoveryPage
 *
 * A map of the routers on a network, and what each of them says.
 *
 * This is not the ICMP host sweep in Network Diagnostics. That one pings
 * addresses and reports the hosts that answer. This one walks a network of
 * *routers*: it asks each device for its neighbours where the device will
 * say (LLDP, CDP), reads its routing table where it can, and deduces the
 * links between devices where it cannot.
 *
 * The difference matters, and the page is built around it. A link the
 * device itself reported is an **observation**. A link the backend worked
 * out from a next hop or a shared subnet is an **inference**. They are
 * drawn differently and labelled differently, because a student looking at
 * a map should be able to tell at a glance which is which.
 *
 * Nothing is drawn that the backend did not report. A run that failed says
 * it failed. A device with no routes says it has no routes. There is no
 * example topology here to fall back on.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  BackgroundVariant,
  Handle,
  Position,
  type Node,
  type Edge,
  type NodeTypes,
  type ReactFlowInstance,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import dagre from 'dagre';
import {
  ApiError,
  TimeoutError,
  startRouterDiscoveryRun,
  fetchRouterDiscoveryRun,
  fetchRouterDiscoveryGraph,
  fetchRouterDiscoveryDevice,
  fetchRouterDiscoveryFindings,
  fetchRouterDiscoveryDiff,
} from '../api/routing';
import type {
  RouterDiscoveryRun,
  RouterDiscoveryRunRequest,
  RouterDiscoveryGraph,
  RouterDiscoveryNode,
  RouterDiscoveryEdge,
  RouterDiscoveryFinding,
  RouterDiscoveryDevice,
  RouterDiscoveryDiff,
  RouteEntry,
} from '../types/routing';
import ProvenanceBadge, { type Provenance } from './ProvenanceBadge';
import './RouterDiscoveryPage.css';

/* ==========================================================================
   The map
   ========================================================================== */

/**
 * The colours carry the same meaning they carry everywhere else in the
 * application: green is what was measured, amber is what was deduced.
 *
 * The *shape* carries it too — an observed link is solid and an inferred
 * one is dashed — so a reader who cannot rely on colour alone can still
 * tell them apart. A map that drew an inferred link as if it had been
 * observed would be lying in the most visible place in the product.
 */
const EDGE_COLORS: Record<string, string> = {
  observed: '#48D597',
  inferred: '#F6C76A',
  simulated: '#9B8CFF',
  unknown: '#94A3B8',
};

const NODE_COLORS: Record<string, string> = {
  observed: '#48D597',
  inferred: '#F6C76A',
  simulated: '#9B8CFF',
  unknown: '#94A3B8',
};

/** A device that refused, timed out, or returned something unreadable. */
const FAILED_COLOR = '#FF727C';

const EDGE_KIND_LABELS: Record<string, string> = {
  lldp: 'LLDP',
  cdp: 'CDP',
  l3_next_hop: 'next hop',
  shared_subnet: 'shared subnet',
};

interface DiscoveryNodeData {
  node: RouterDiscoveryNode;
  /** The device was reached and read. */
  collected: boolean;
  /** The device refused, timed out, or came back unreadable. */
  failed: boolean;
  /** The device was never reached at all. */
  notReached: boolean;
  dimmed: boolean;
}

/**
 * A device on the map.
 *
 * Three states are told apart, because they mean different things:
 *
 *   - **collected** — the device was reached and read. Ordinary node.
 *   - **not collected** — it refused, timed out, or came back unreadable.
 *     Red, with the reason on it.
 *   - **never reached** — nothing was heard from it at all. It is shown
 *     grey and says so, rather than pretending to be an ordinary device
 *     with nothing to show.
 */
function DiscoveryNode({
  data,
  selected,
}: {
  data: DiscoveryNodeData;
  selected?: boolean;
}) {
  const { node, collected, failed, notReached, dimmed } = data;
  const provenance = node.provenance ?? 'unknown';
  const color = failed
    ? FAILED_COLOR
    : collected
    ? NODE_COLORS[provenance] ?? NODE_COLORS.unknown
    : NODE_COLORS.unknown;
  // The device's own name is what the map shows; the id is the key.
  const displayName = node.hostname || node.device_id;

  return (
    <div
      className={`dnode ${failed ? 'failed' : ''} ${
        notReached ? 'not-reached' : ''
      } ${selected ? 'selected' : ''} ${dimmed ? 'dimmed' : ''}`}
      style={{ borderColor: color }}
    >
      {/* React Flow attaches the links to these. Without them the edges
          have nothing to join to. */}
      <Handle type="target" position={Position.Left} className="dnode-handle" />
      <Handle type="source" position={Position.Right} className="dnode-handle" />

      <span className="dnode-dot" style={{ background: color }} aria-hidden="true" />
      <span className="dnode-label" title={displayName}>
        {displayName}
      </span>
      {node.hostname && node.hostname !== node.device_id && (
        <span className="dnode-id" title={node.device_id}>
          {node.device_id}
        </span>
      )}

      {failed && (
        <span className="dnode-state failed" title={node.errors.join('; ')}>
          not collected
        </span>
      )}
      {!failed && notReached && (
        <span className="dnode-state not-reached">never reached</span>
      )}
      {!failed && !notReached && (
        <ProvenanceBadge provenance={provenance} size="small" />
      )}
    </div>
  );
}

const NODE_TYPES: NodeTypes = { discovery: DiscoveryNode as never };

/**
 * Lay the devices out in layers, left to right.
 *
 * dagre ranks them so a device sits before the ones it points at, which is
 * the direction traffic travels. Only links the backend reported constrain
 * the layout, so the map never implies a relationship that is not there.
 */
function layoutDiscovery(
  nodes: RouterDiscoveryNode[],
  edges: RouterDiscoveryEdge[]
): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  if (nodes.length === 0) return positions;

  const graph = new dagre.graphlib.Graph();
  graph.setDefaultEdgeLabel(() => ({}));
  graph.setGraph({
    rankdir: 'LR',
    nodesep: 30,
    ranksep: 110,
    marginx: 24,
    marginy: 24,
  });

  for (const node of nodes) {
    graph.setNode(node.device_id, { width: 190, height: 76 });
  }
  for (const edge of edges) {
    if (edge.a === edge.b) continue;
    graph.setEdge(edge.a, edge.b);
  }

  dagre.layout(graph);

  for (const node of nodes) {
    const laid = graph.node(node.device_id);
    if (laid) positions.set(node.device_id, { x: laid.x, y: laid.y });
  }

  // A device the backend reported but could not place still appears.
  let orphanY = 0;
  for (const node of nodes) {
    if (positions.has(node.device_id)) continue;
    positions.set(node.device_id, { x: 120, y: orphanY });
    orphanY += 110;
  }

  return positions;
}

/* ==========================================================================
   Helpers
   ========================================================================== */

/** Whether a string looks like a CIDR network the backend would accept. */
function looksLikeCidr(value: string): boolean {
  const trimmed = value.trim();
  if (!trimmed || !trimmed.includes('/')) return false;
  const [address, prefix] = trimmed.split('/');
  if (!/^[0-9.]+$/.test(address)) return false;
  const bits = Number(prefix);
  if (!Number.isInteger(bits) || bits < 0 || bits > 32) return false;
  return address.split('.').length === 4;
}

/** Whether a string looks like an address or a hostname a seed could be. */
function looksLikeSeed(value: string): boolean {
  const trimmed = value.trim();
  if (!trimmed) return false;
  if (/^[0-9.]+$/.test(trimmed)) {
    return trimmed.split('.').length === 4;
  }
  // A hostname, or a URL the backend may take.
  return /^[A-Za-z0-9._:/-]+$/.test(trimmed);
}

/**
 * Map whatever the backend sent onto the four words the badge knows.
 *
 * A value outside the vocabulary is not silently accepted as one of
 * them: it reads as "unknown", which is the honest reading of a
 * provenance nobody has established.
 */
function toProvenance(value: string | null | undefined): Provenance {
  if (
    value === 'observed' ||
    value === 'inferred' ||
    value === 'simulated' ||
    value === 'unknown'
  ) {
    return value;
  }
  return 'unknown';
}

/**
 * Say what went wrong in terms the reader can act on.
 *
 * A 404 in particular means this backend does not have the router
 * discovery endpoints yet, which is worth saying plainly rather than
 * showing a bare status code.
 */
function describeApiError(error: unknown, what: string): string {
  if (error instanceof ApiError) {
    if (error.status === 404) {
      return `This backend does not have the router discovery endpoints yet, so ${what} could not be started.`;
    }
    if (error.status === 503) {
      return `The backend is not able to ${what} right now.`;
    }
    return error.message;
  }
  if (error instanceof TimeoutError) {
    return `The request to ${what} timed out.`;
  }
  return error instanceof Error ? error.message : `Could not ${what}.`;
}

function describeFailure(value: unknown): string {
  if (typeof value === 'string') return value;
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    for (const key of ['error', 'message', 'reason', 'detail'] as const) {
      if (typeof record[key] === 'string') return record[key];
    }
    try {
      return JSON.stringify(value);
    } catch {
      return 'The device could not be collected.';
    }
  }
  return String(value);
}

/* ==========================================================================
   The page
   ========================================================================== */

export default function RouterDiscoveryPage() {
  // --- The run form ---
  const [seedsText, setSeedsText] = useState('');
  const [scope, setScope] = useState('');
  const [method, setMethod] = useState('lldp');
  const [maxDepth, setMaxDepth] = useState(3);
  const [maxDevices, setMaxDevices] = useState(25);
  const [formError, setFormError] = useState<string | null>(null);

  // --- The run ---
  const [run, setRun] = useState<RouterDiscoveryRun | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [polling, setPolling] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  // --- What the run found ---
  const [graph, setGraph] = useState<RouterDiscoveryGraph | null>(null);
  const [findings, setFindings] = useState<RouterDiscoveryFinding[]>([]);
  /**
   * How the analysis was done, in the backend's own words.
   *
   * This is the honest answer to "how do I know this is right". It is
   * shown only if the API carries it — an absent field is not filled in
   * with a guess.
   */
  const [methodDescription, setMethodDescription] = useState<string | null>(null);
  const [loadingGraph, setLoadingGraph] = useState(false);
  const [graphError, setGraphError] = useState<string | null>(null);

  // --- The device drawer ---
  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null);
  const [device, setDevice] = useState<RouterDiscoveryDevice | null>(null);
  const [deviceLoading, setDeviceLoading] = useState(false);
  const [deviceError, setDeviceError] = useState<string | null>(null);
  const [routeFilter, setRouteFilter] = useState('');
  const [protocolFilter, setProtocolFilter] = useState('all');

  // --- History and comparison ---
  const [history, setHistory] = useState<{ run_id: string; status: string }[]>([]);
  const [compareA, setCompareA] = useState('');
  const [compareB, setCompareB] = useState('');
  const [diff, setDiff] = useState<RouterDiscoveryDiff | null>(null);
  const [diffError, setDiffError] = useState<string | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);

  const canvasRef = useRef<HTMLDivElement>(null);
  const instance = useRef<ReactFlowInstance | null>(null);
  const [canvasWidth, setCanvasWidth] = useState(0);
  const pollTimer = useRef<number | null>(null);

  /* ---------------------------------------------------------------------
     The map
     --------------------------------------------------------------------- */

  const positions = useMemo(
    () => layoutDiscovery(graph?.nodes ?? [], graph?.edges ?? []),
    [graph]
  );

  const flowNodes: Node[] = useMemo(
    () =>
      (graph?.nodes ?? []).map((node) => {
        // Three states, told apart because they mean different things: the
        // device was read, it refused or timed out, or nothing was heard
        // from it at all. The `errors` list is the authoritative record.
        const failed =
          (node.errors?.length ?? 0) > 0 || Boolean(node.error);
        const provenance = node.provenance ?? 'unknown';
        const notReached = !failed && provenance === 'unknown';
        const collected = !failed && !notReached;
        return {
          id: node.device_id,
          type: 'discovery',
          position: positions.get(node.device_id) ?? { x: 0, y: 0 },
          data: {
            node,
            collected,
            failed,
            notReached,
            dimmed: false,
          } satisfies DiscoveryNodeData,
          selected: selectedDeviceId === node.device_id,
          draggable: true,
        };
      }),
    [graph, positions, selectedDeviceId]
  );

  const flowEdges: Edge[] = useMemo(
    () =>
      (graph?.edges ?? []).map((edge, index) => ({
        id: `${edge.a}-${edge.b}-${index}`,
        source: edge.a,
        target: edge.b,
        label: EDGE_KIND_LABELS[edge.kind] ?? edge.kind,
        className: `dedge prov-${edge.provenance}`,
        style: {
          stroke: EDGE_COLORS[edge.provenance] ?? EDGE_COLORS.unknown,
          strokeWidth: 2,
          // An inferred link is dashed, so it reads as a deduction even in
          // a print-out or for a reader who cannot rely on colour.
          strokeDasharray: edge.provenance === 'inferred' ? '8 5' : undefined,
          opacity: 0.9,
        },
        labelStyle: {
          fill: 'var(--color-text-muted)',
          fontSize: 10,
          fontFamily: 'var(--font-mono)',
        },
        labelBgStyle: { fill: 'var(--color-bg)', fillOpacity: 0.9 },
        labelBgPadding: [4, 2] as [number, number],
        labelBgBorderRadius: 3,
      })),
    [graph]
  );

  useEffect(() => {
    const element = canvasRef.current;
    if (!element) return;
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width ?? 0;
      setCanvasWidth((current) =>
        Math.abs(current - width) > 8 ? width : current
      );
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [graph]);

  useEffect(() => {
    if (canvasWidth === 0) return;
    if (canvasWidth >= 720) {
      instance.current?.fitView({ padding: 0.2, maxZoom: 1 });
    } else {
      instance.current?.setViewport({ x: 12, y: 12, zoom: 0.8 });
    }
  }, [canvasWidth, graph]);

  /* ---------------------------------------------------------------------
     Running a discovery
     --------------------------------------------------------------------- */

  const isRunning = starting || polling;

  const handleStart = useCallback(async () => {
    const seeds = seedsText
      .split(/[\s,]+/)
      .map((s) => s.trim())
      .filter(Boolean);

    // The form refuses what the backend would certainly refuse, and says
    // why, rather than letting it fail with a generic error.
    if (seeds.length === 0) {
      setFormError('At least one seed is needed — the address or name to start from.');
      return;
    }
    const badSeed = seeds.find((s) => !looksLikeSeed(s));
    if (badSeed) {
      setFormError(`"${badSeed}" is not an address or a host name the backend could start from.`);
      return;
    }
    if (!scope.trim()) {
      setFormError('A scope is needed — the network the walk must stay inside.');
      return;
    }
    if (!looksLikeCidr(scope)) {
      setFormError(`"${scope}" is not a network in CIDR form, for example 192.168.1.0/24.`);
      return;
    }
    if (!Number.isInteger(maxDepth) || maxDepth < 1) {
      setFormError('The depth must be at least 1.');
      return;
    }
    if (!Number.isInteger(maxDevices) || maxDevices < 1) {
      setFormError('The device limit must be at least 1.');
      return;
    }

    setFormError(null);
    setRunError(null);
    setStarting(true);
    setGraph(null);
    setFindings([]);
    setDiff(null);
    setSelectedDeviceId(null);
    setDevice(null);

    const request: RouterDiscoveryRunRequest = {
      seeds,
      scope: scope.trim(),
      method,
      max_depth: maxDepth,
      max_devices: maxDevices,
    };

    try {
      const started = await startRouterDiscoveryRun(request);
      setRunId(started.run_id);
      setRun({
        run_id: started.run_id,
        status: started.status,
        progress: [],
        failures: {},
      });
      setHistory((current) => [
        { run_id: started.run_id, status: started.status },
        ...current.filter((r) => r.run_id !== started.run_id),
      ]);
    } catch (err) {
      setRunError(describeApiError(err, 'a discovery run'));
    } finally {
      setStarting(false);
    }
  }, [seedsText, scope, method, maxDepth, maxDevices]);

  // The run is polled while it is going, and the graph and findings are
  // fetched once it has finished.
  useEffect(() => {
    if (!runId) return;
    let cancelled = false;

    const poll = async () => {
      setPolling(true);
      try {
        const status = await fetchRouterDiscoveryRun(runId);
        if (cancelled) return;
        setRun(status);

        const finished = ['done', 'complete', 'completed', 'failed', 'error', 'finished'].includes(
          status.status.toLowerCase()
        );

        if (finished) {
          setPolling(false);
          setLoadingGraph(true);
          try {
            const [foundGraph, foundFindings] = await Promise.all([
              fetchRouterDiscoveryGraph(runId),
              fetchRouterDiscoveryFindings(runId),
            ]);
            if (cancelled) return;
            setGraph(foundGraph);
            setFindings(foundFindings.findings ?? []);
            setMethodDescription(foundFindings.method_description ?? null);
            setGraphError(null);
          } catch (err) {
            if (!cancelled) {
              setGraphError(describeApiError(err, 'read the results'));
            }
          } finally {
            if (!cancelled) setLoadingGraph(false);
          }
          return;
        }
      } catch (err) {
        if (cancelled) return;
        setRunError(describeApiError(err, 'read the run status'));
        setPolling(false);
        return;
      }

      pollTimer.current = window.setTimeout(poll, 2000);
    };

    poll();

    return () => {
      cancelled = true;
      if (pollTimer.current !== null) window.clearTimeout(pollTimer.current);
    };
  }, [runId]);

  // A run that failed is shown as failed, and its graph is not drawn.
  const runFailed =
    run !== null && ['failed', 'error'].includes(run.status.toLowerCase());

  /* ---------------------------------------------------------------------
     The device drawer
     --------------------------------------------------------------------- */

  const handleSelectDevice = useCallback(
    (deviceId: string) => {
      setSelectedDeviceId((current) => (current === deviceId ? null : deviceId));
      setRouteFilter('');
      setProtocolFilter('all');
    },
    []
  );

  useEffect(() => {
    if (!runId || !selectedDeviceId) {
      setDevice(null);
      setDeviceError(null);
      return;
    }
    let cancelled = false;
    setDeviceLoading(true);
    setDeviceError(null);

    fetchRouterDiscoveryDevice(runId, selectedDeviceId)
      .then((found) => {
        if (!cancelled) setDevice(found);
      })
      .catch((err) => {
        if (!cancelled) {
          setDevice(null);
          setDeviceError(describeApiError(err, 'read this device'));
        }
      })
      .finally(() => {
        if (!cancelled) setDeviceLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [runId, selectedDeviceId]);

  /**
   * Whether the selected device was actually read.
   *
   * The map's node carries the failure; the device the backend returns may
   * not. The node is the authority, so the drawer never claims an
   * uncollected device's empty table is a real reading.
   */
  const selectedNode = useMemo(
    () =>
      (graph?.nodes ?? []).find((node) => node.device_id === selectedDeviceId) ??
      null,
    [graph, selectedDeviceId]
  );

  const selectedNodeWasNotCollected = useMemo(() => {
    if (!selectedNode) return false;
    return (
      (selectedNode.errors?.length ?? 0) > 0 || Boolean(selectedNode.error)
    );
  }, [selectedNode]);

  const selectedNodeFailureReason = useMemo(() => {
    if (!selectedNode) return null;
    // The list is authoritative; the summary string is a convenience.
    if (selectedNode.errors && selectedNode.errors.length > 0) {
      return selectedNode.errors.join('; ');
    }
    return selectedNode.error ?? null;
  }, [selectedNode]);

  /**
   * Whether the run stopped at a limit rather than finishing.
   *
   * The backend does not report this yet, so nothing is claimed until it
   * does. The check is deliberately loose, because a run that was cut
   * short must never be drawn as a complete one — but it can only ever
   * *add* a notice, never remove one. When the backend names the field,
   * it can be wired to that name exactly.
   */
  const runWasTruncated = useMemo(() => {
    if (!run) return false;
    const status = (run.status ?? '').toLowerCase();
    if (status.includes('truncat') || status.includes('limit')) return true;
    const flags = run as unknown as Record<string, unknown>;
    return Boolean(
      flags.truncated ??
        flags.limit_reached ??
        flags.depth_limit_reached ??
        flags.truncated_at_limit
    );
  }, [run]);

  const filteredRoutes = useMemo(() => {
    if (!device) return [];
    const needle = routeFilter.trim().toLowerCase();
    return device.routes.filter((route: RouteEntry) => {
      if (
        protocolFilter !== 'all' &&
        (route.protocol ?? '').toLowerCase() !== protocolFilter.toLowerCase()
      ) {
        return false;
      }
      if (!needle) return true;
      return (
        route.prefix.toLowerCase().includes(needle) ||
        (route.next_hop ?? '').toLowerCase().includes(needle) ||
        (route.interface ?? '').toLowerCase().includes(needle)
      );
    });
  }, [device, routeFilter, protocolFilter]);

  const availableProtocols = useMemo(() => {
    if (!device) return [];
    const found = new Set<string>();
    for (const route of device.routes) {
      if (route.protocol) found.add(route.protocol);
    }
    return [...found].sort();
  }, [device]);

  /* ---------------------------------------------------------------------
     Comparing two runs
     --------------------------------------------------------------------- */

  const handleCompare = useCallback(async () => {
    if (!compareA || !compareB) {
      setDiffError('Two runs have to be chosen before they can be compared.');
      return;
    }
    setDiffLoading(true);
    setDiffError(null);
    try {
      const result = await fetchRouterDiscoveryDiff(compareA, compareB);
      setDiff(result);
    } catch (err) {
      setDiff(null);
      setDiffError(describeApiError(err, 'compare the two runs'));
    } finally {
      setDiffLoading(false);
    }
  }, [compareA, compareB]);

  /* ---------------------------------------------------------------------
     Render
     --------------------------------------------------------------------- */

  const failureEntries = run ? Object.entries(run.failures ?? {}) : [];

  return (
    <div className="router-discovery">
      {/* ================= The run form ================= */}
      <section className="card">
        <div className="card-header">
          <div>
            <span className="eyebrow">01 · Start</span>
            <h2>Walk a network of routers</h2>
          </div>
          <span className="card-subtitle">
            Reads each device's table and neighbour list
          </span>
        </div>
        <div className="card-body">
          <aside className="discovery-safety-note" aria-label="Router discovery prerequisites">
            <strong>Before you start:</strong> provide devices and a CIDR scope you are authorised to inspect. Discovery may need protocol access (LLDP, CDP, SNMP, or SSH) and can return partial results; it never turns missing responses into confirmed topology.
          </aside>
          <form
            className="discovery-form"
            onSubmit={(e) => {
              e.preventDefault();
              handleStart();
            }}
          >
            <div className="discovery-field discovery-field-wide">
              <label htmlFor="discovery-seeds">Seeds</label>
              <input
                id="discovery-seeds"
                type="text"
                value={seedsText}
                onChange={(e) => setSeedsText(e.target.value)}
                placeholder="192.168.1.1, 192.168.2.1"
                spellCheck={false}
                disabled={isRunning}
              />
              <span className="field-hint">
                Where to start from. Separate several with commas or spaces.
              </span>
            </div>

            <div className="discovery-field">
              <label htmlFor="discovery-scope">Scope</label>
              <input
                id="discovery-scope"
                type="text"
                value={scope}
                onChange={(e) => setScope(e.target.value)}
                placeholder="192.168.1.0/24"
                spellCheck={false}
                disabled={isRunning}
                aria-invalid={scope.length > 0 && !looksLikeCidr(scope)}
              />
              <span className="field-hint">The network the walk stays inside.</span>
            </div>

            <div className="discovery-field discovery-field-narrow">
              <label htmlFor="discovery-method">Method</label>
              <select
                id="discovery-method"
                value={method}
                onChange={(e) => setMethod(e.target.value)}
                disabled={isRunning}
              >
                <option value="lldp">LLDP</option>
                <option value="cdp">CDP</option>
                <option value="snmp">SNMP</option>
                <option value="ssh">SSH</option>
              </select>
            </div>

            <div className="discovery-field discovery-field-narrow">
              <label htmlFor="discovery-depth">Max depth</label>
              <input
                id="discovery-depth"
                type="number"
                min={1}
                value={maxDepth}
                onChange={(e) => setMaxDepth(Number(e.target.value))}
                disabled={isRunning}
              />
            </div>

            <div className="discovery-field discovery-field-narrow">
              <label htmlFor="discovery-devices">Max devices</label>
              <input
                id="discovery-devices"
                type="number"
                min={1}
                value={maxDevices}
                onChange={(e) => setMaxDevices(Number(e.target.value))}
                disabled={isRunning}
              />
            </div>

            <div className="discovery-submit">
              <button
                type="submit"
                className="btn btn-primary"
                disabled={isRunning}
                aria-busy={isRunning}
              >
                {isRunning ? 'Running…' : 'Start discovery'}
              </button>
            </div>
          </form>

          {formError && (
            <div className="error-message" role="alert">
              <span aria-hidden="true">⚠</span>
              {formError}
            </div>
          )}

          {runError && (
            <div className="error-message" role="alert">
              <span aria-hidden="true">⚠</span>
              {runError}
            </div>
          )}

          {/* Progress, as the backend reports it. */}
          {run && (
            <div className="discovery-progress" role="status" aria-live="polite">
              <div className="discovery-progress-head">
                <span
                  className={`status-badge ${
                    runFailed
                      ? 'disconnected'
                      : isRunning
                      ? 'checking'
                      : 'connected'
                  }`}
                >
                  <span className="dot" aria-hidden="true" />
                  {run.status}
                </span>
                {runId && <span className="discovery-run-id mono">{runId}</span>}
              </div>

              {run.progress.length > 0 && (
                <ol className="discovery-progress-list">
                  {run.progress.map((step, i) => (
                    <li key={i}>{step}</li>
                  ))}
                </ol>
              )}

              {runWasTruncated && (
                <div className="discovery-truncated" role="status">
                  <span aria-hidden="true">⚠</span>
                  <span>
                    This run stopped at a limit, so what is shown is only part
                    of what was reached. It is not a complete picture of the
                    network.
                  </span>
                </div>
              )}

              {failureEntries.length > 0 && (
                <div className="discovery-failures">
                  <h4>What could not be collected</h4>
                  <ul>
                    {failureEntries.map(([key, value]) => (
                      <li key={key}>
                        <span className="mono">{key}</span> —{' '}
                        {describeFailure(value)}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      </section>

      {/* ================= The map ================= */}
      <section className="card">
        <div className="card-header">
          <div>
            <span className="eyebrow">02 · Map</span>
            <h2>The routers that were found</h2>
          </div>
          <span className="card-subtitle">
            {graph
              ? `${graph.nodes.length} device${graph.nodes.length === 1 ? '' : 's'}, ${graph.edges.length} link${graph.edges.length === 1 ? '' : 's'}`
              : 'Nothing to draw yet'}
          </span>
        </div>
        <div className="card-body">
          {loadingGraph && (
            <div className="loading">
              <span className="spinner" aria-hidden="true" />
              Reading what the run found…
            </div>
          )}

          {graphError && (
            <div className="error-message" role="alert">
              <span aria-hidden="true">⚠</span>
              {graphError}
            </div>
          )}

          {runFailed && !loadingGraph && (
            <div className="empty-state">
              <p>The run failed, so there is no map to draw.</p>
              <p className="empty-state-hint">
                What went wrong is listed above. Nothing is shown here because
                the backend did not report any devices.
              </p>
            </div>
          )}

          {!run && !loadingGraph && !graphError && (
            <div className="empty-state">
              <p>No discovery has been run yet.</p>
              <p className="empty-state-hint">
                Start one above and the map will fill in with the devices the
                backend actually found.
              </p>
            </div>
          )}

          {run &&
            !loadingGraph &&
            !graphError &&
            !runFailed &&
            graph &&
            graph.nodes.length === 0 && (
              <div className="empty-state">
                <p>The run finished but found no devices.</p>
                <p className="empty-state-hint">
                  That is what the backend reported. Nothing is drawn, because
                  there is nothing to draw.
                </p>
              </div>
            )}

          {graph && graph.nodes.length > 0 && (
            <>
              <div className="discovery-legend">
                <span className="legend-item">
                  <span className="legend-swatch observed" aria-hidden="true" />
                  <strong>Observed</strong> — the device reported the
                  neighbour itself (LLDP or CDP). Solid.
                </span>
                <span className="legend-item">
                  <span className="legend-swatch inferred" aria-hidden="true" />
                  <strong>Inferred</strong> — the backend worked it out from a
                  next hop or a shared subnet. Dashed.
                </span>
                <span className="legend-item">
                  <span className="legend-swatch failed" aria-hidden="true" />
                  <strong>Not collected</strong> — the device refused, timed
                  out, or came back unreadable.
                </span>
                <span className="legend-item">
                  <span className="legend-swatch not-reached" aria-hidden="true" />
                  <strong>Never reached</strong> — nothing was heard from the
                  device at all.
                </span>
              </div>

              <div className="discovery-canvas" ref={canvasRef}>
                <ReactFlow
                  nodes={flowNodes}
                  edges={flowEdges}
                  nodeTypes={NODE_TYPES}
                  onNodeClick={(_, node) => handleSelectDevice(node.id)}
                  onPaneClick={() => setSelectedDeviceId(null)}
                  onInit={(flow) => {
                    instance.current = flow;
                  }}
                  defaultViewport={{ x: 12, y: 12, zoom: 0.8 }}
                  minZoom={0.25}
                  maxZoom={2}
                  nodesDraggable
                  nodesConnectable={false}
                  elementsSelectable
                  aria-label="Discovered routers and the links between them"
                >
                  <Background
                    variant={BackgroundVariant.Dots}
                    gap={22}
                    size={1}
                    color="rgba(138, 216, 255, 0.12)"
                  />
                  <Controls showInteractive={false} />
                  <MiniMap
                    pannable
                    zoomable
                    nodeColor={(node) => {
                      const data = node.data as unknown as
                        | DiscoveryNodeData
                        | undefined;
                      if (!data) return '#94A3B8';
                      if (data.failed) return FAILED_COLOR;
                      if (data.notReached) return '#64748B';
                      return (
                        NODE_COLORS[data.node.provenance ?? 'unknown'] ??
                        NODE_COLORS.unknown
                      );
                    }}
                    maskColor="rgba(11, 16, 32, 0.72)"
                  />
                </ReactFlow>
              </div>
            </>
          )}
        </div>
      </section>

      {/* ================= The device drawer ================= */}
      {selectedDeviceId && (
        <section className="card">
          <div className="card-header">
            <div>
              <span className="eyebrow">03 · Device</span>
              <h2>
                {device?.hostname ?? device?.device_id ?? selectedDeviceId}
              </h2>
            </div>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => setSelectedDeviceId(null)}
            >
              Close
            </button>
          </div>
          <div className="card-body">
            {deviceLoading && (
              <div className="loading">
                <span className="spinner" aria-hidden="true" />
                Reading this device…
              </div>
            )}

            {deviceError && (
              <div className="error-message" role="alert">
                <span aria-hidden="true">⚠</span>
                {deviceError}
              </div>
            )}

            {device && !deviceLoading && (
              <>
                <div className="device-facts">
                  <div className="detail-item">
                    <span className="detail-label">Device id</span>
                    <span className="detail-value mono">{device.device_id}</span>
                  </div>
                  <div className="detail-item">
                    <span className="detail-label">Hostname</span>
                    <span className="detail-value mono">
                      {device.hostname || 'not reported'}
                    </span>
                  </div>
                  <div className="detail-item">
                    <span className="detail-label">Management target</span>
                    <span className="detail-value mono">
                      {device.mgmt_target || 'not reported'}
                    </span>
                  </div>
                  <div className="detail-item">
                    <span className="detail-label">Collected by</span>
                    <span className="detail-value">
                      {device.method || 'not reported'}
                    </span>
                  </div>
                  <div className="detail-item">
                    <span className="detail-label">Collected at</span>
                    <span className="detail-value mono">
                      {device.collected_at || 'not reported'}
                    </span>
                  </div>
                  <div className="detail-item">
                    <span className="detail-label">Provenance</span>
                    <span className="detail-value">
                      <ProvenanceBadge
                        provenance={toProvenance(device.provenance)}
                        size="small"
                      />
                    </span>
                  </div>
                </div>

                {device.errors.length > 0 && (
                  <div className="error-message" role="status">
                    <span aria-hidden="true">⚠</span>
                    <span>
                      Part of this device could not be read:{' '}
                      {device.errors.join('; ')}
                    </span>
                  </div>
                )}

                {/* Interfaces */}
                <h3 className="panel-title">
                  Interfaces ({device.interfaces.length})
                </h3>
                {device.interfaces.length === 0 ? (
                  <p className="device-muted">
                    The backend reported no interfaces for this device.
                  </p>
                ) : (
                  <div className="table-container">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th scope="col">Interface</th>
                          <th scope="col">Addresses</th>
                          <th scope="col">Up</th>
                        </tr>
                      </thead>
                      <tbody>
                        {device.interfaces.map((iface) => (
                          <tr key={iface.name}>
                            <td className="mono">{iface.name}</td>
                            <td className="mono">
                              {iface.addresses.length > 0
                                ? iface.addresses.join(', ')
                                : 'none reported'}
                            </td>
                            <td>
                              {iface.up ? 'yes' : 'no'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* Neighbours */}
                <h3 className="panel-title">
                  Neighbours ({device.neighbors.length})
                </h3>
                {device.neighbors.length === 0 ? (
                  <p className="device-muted">
                    The backend reported no neighbours for this device.
                  </p>
                ) : (
                  <div className="table-container">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th scope="col">Local interface</th>
                          <th scope="col">Remote name</th>
                          <th scope="col">Remote interface</th>
                          <th scope="col">Remote address</th>
                          <th scope="col">Via</th>
                        </tr>
                      </thead>
                      <tbody>
                        {device.neighbors.map((neighbour, i) => (
                          <tr key={i}>
                            <td className="mono">{neighbour.local_if || '—'}</td>
                            <td className="mono">
                              {neighbour.remote_name ?? '—'}
                            </td>
                            <td className="mono">
                              {neighbour.remote_if ?? '—'}
                            </td>
                            <td className="mono">
                              {neighbour.remote_ip ?? '—'}
                            </td>
                            <td className="mono">{neighbour.via ?? '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* The routing table, with where the numbers came from. */}
                <h3 className="panel-title">
                  Routing table ({device.routes.length})
                </h3>

                {/*
                  Whether this device was actually read decides what may be
                  said about its routes.

                  The map already knows: the node carries the failure. The
                  device the backend returns cannot always carry it, and a
                  404 would be indistinguishable from a wrong id. So the
                  node is the authority, and an uncollected device never gets
                  a sentence claiming its empty table is a real reading.
                */}
                {selectedNodeWasNotCollected ? (
                  <div className="error-message" role="status">
                    <span aria-hidden="true">⚠</span>
                    <span>
                      This device was not collected, so nothing can be said
                      about its routing table.{' '}
                      {selectedNodeFailureReason
                        ? `The backend reported: ${selectedNodeFailureReason}`
                        : 'The backend did not say why.'}{' '}
                      The table below is empty because there was nothing to
                      read, not because the device has no routes.
                    </span>
                  </div>
                ) : (
                  <p className="device-routes-source">
                    Read from{' '}
                    <strong>{device.method ?? 'an unreported method'}</strong>{' '}
                    on <span className="mono">{device.device_id}</span>
                    {device.collected_at ? ` at ${device.collected_at}` : ''}.{' '}
                    {device.provenance === 'observed'
                      ? 'These are the numbers the device itself reported.'
                      : device.provenance === 'inferred'
                      ? 'These are the backend’s reading, deduced from other data — not the device’s own numbers.'
                      : 'It is not known whether these came from the device or were deduced.'}
                  </p>
                )}

                {device.routes.length === 0 ? (
                  selectedNodeWasNotCollected ? (
                    <p className="device-muted">
                      No routes were read, because the device was not read.
                    </p>
                  ) : (
                    <p className="device-muted">
                      This device reported no routes. That is a real reading,
                      not a missing one.
                    </p>
                  )
                ) : (
                  <>
                    <div className="device-route-toolbar">
                      <input
                        type="search"
                        value={routeFilter}
                        onChange={(e) => setRouteFilter(e.target.value)}
                        placeholder="Filter by prefix, next hop or interface"
                        aria-label="Filter this device's routes"
                        spellCheck={false}
                      />
                      <select
                        value={protocolFilter}
                        onChange={(e) => setProtocolFilter(e.target.value)}
                        aria-label="Filter this device's routes by protocol"
                      >
                        <option value="all">All protocols</option>
                        {availableProtocols.map((protocol) => (
                          <option key={protocol} value={protocol}>
                            {protocol}
                          </option>
                        ))}
                      </select>
                      <span className="device-route-count">
                        {filteredRoutes.length} of {device.routes.length}
                      </span>
                    </div>

                    {filteredRoutes.length === 0 ? (
                      <p className="device-muted">
                        No route matches that filter.
                      </p>
                    ) : (
                      <div className="table-container">
                        <table className="data-table">
                          <thead>
                            <tr>
                              <th scope="col">Prefix</th>
                              <th scope="col">Next hop</th>
                              <th scope="col">Interface</th>
                              <th scope="col">Protocol</th>
                              <th scope="col">Metric</th>
                              <th scope="col">Admin distance</th>
                            </tr>
                          </thead>
                          <tbody>
                            {filteredRoutes.map((route, i) => (
                              <tr
                                key={`${route.prefix}-${route.interface}-${i}`}
                                className={route.selected ? 'selected-route' : undefined}
                              >
                                <td className="mono">{route.prefix}</td>
                                <td className="mono">{route.next_hop ?? 'direct'}</td>
                                <td className="mono">{route.interface ?? '—'}</td>
                                <td>{route.protocol ?? '—'}</td>
                                <td className="mono">{route.metric}</td>
                                <td className="mono">
                                  {route.admin_distance ?? '—'}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </>
                )}
              </>
            )}
          </div>
        </section>
      )}

      {/* ================= Findings ================= */}
      {run && (
        <section className="card">
          <div className="card-header">
            <div>
              <span className="eyebrow">04 · Findings</span>
              <h2>What the backend noticed</h2>
            </div>
            <span className="card-subtitle">
              {findings.length} finding{findings.length === 1 ? '' : 's'}
            </span>
          </div>
          <div className="card-body">
            {methodDescription && (
              <div className="discovery-method-description">
                <span className="discovery-method-label">
                  How this was worked out
                </span>
                <p>{methodDescription}</p>
              </div>
            )}

            {findings.length === 0 ? (
              <div className="empty-state">
                <p>The backend reported no findings for this run.</p>
                <p className="empty-state-hint">
                  Nothing is listed because there was nothing to list.
                </p>
              </div>
            ) : (
              <ul className="discovery-findings">
                {findings.map((finding, i) => (
                  <li className="discovery-finding" key={i}>
                    <div className="discovery-finding-head">
                      <span className="discovery-finding-title">
                        {finding.title}
                      </span>
                      <span className="discovery-finding-tags">
                        {/*
                          A finding that rests on an inference has to say so
                          in the finding. A backend that does not send a
                          provenance has not established one, so the honest
                          reading is "unknown" — not a blank space that a
                          reader might mistake for "observed".
                        */}
                        <ProvenanceBadge
                          provenance={toProvenance(finding.provenance)}
                          size="small"
                        />
                        <span className="discovery-finding-severity">
                          {finding.severity}
                        </span>
                      </span>
                    </div>
                    <p className="discovery-finding-detail">{finding.detail}</p>
                    {finding.evidence && (
                      <p className="discovery-finding-evidence">
                        {finding.evidence}
                      </p>
                    )}

                    {/*
                      A finding that could not be represented rests on a
                      partial view. That is a limit on the finding itself,
                      not a detail a reader can afford to miss.
                    */}
                    {finding.representable === false && (
                      <p className="discovery-finding-partial">
                        <span aria-hidden="true">⚠</span> This finding rests on
                        a partial view of the network, so it may not be
                        complete.
                      </p>
                    )}

                    {finding.devices && finding.devices.length > 0 && (
                      <div className="discovery-finding-devices">
                        <span className="discovery-finding-devices-label">
                          About
                        </span>
                        {finding.devices.map((deviceId) => (
                          <button
                            key={deviceId}
                            type="button"
                            className="discovery-finding-device"
                            onClick={() => handleSelectDevice(deviceId)}
                          >
                            {deviceId}
                          </button>
                        ))}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      )}

      {/* ================= History and comparison ================= */}
      <section className="card">
        <div className="card-header">
          <div>
            <span className="eyebrow">05 · History</span>
            <h2>The runs so far</h2>
          </div>
          <span className="card-subtitle">
            {history.length} run{history.length === 1 ? '' : 's'} in this session
          </span>
        </div>
        <div className="card-body">
          {history.length === 0 ? (
            <div className="empty-state">
              <p>No run has been started in this session.</p>
              <p className="empty-state-hint">
                Runs are listed here so two of them can be compared.
              </p>
            </div>
          ) : (
            <>
              <div className="table-container">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th scope="col">Run</th>
                      <th scope="col">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((entry) => (
                      <tr key={entry.run_id}>
                        <td className="mono">{entry.run_id}</td>
                        <td>{entry.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="discovery-compare">
                <div className="discovery-field discovery-field-narrow">
                  <label htmlFor="discovery-compare-a">Compare</label>
                  <select
                    id="discovery-compare-a"
                    value={compareA}
                    onChange={(e) => setCompareA(e.target.value)}
                  >
                    <option value="">First run…</option>
                    {history.map((entry) => (
                      <option key={entry.run_id} value={entry.run_id}>
                        {entry.run_id}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="discovery-field discovery-field-narrow">
                  <label htmlFor="discovery-compare-b">with</label>
                  <select
                    id="discovery-compare-b"
                    value={compareB}
                    onChange={(e) => setCompareB(e.target.value)}
                  >
                    <option value="">Second run…</option>
                    {history.map((entry) => (
                      <option key={entry.run_id} value={entry.run_id}>
                        {entry.run_id}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="discovery-submit">
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={handleCompare}
                    disabled={diffLoading}
                    aria-busy={diffLoading}
                  >
                    {diffLoading ? 'Comparing…' : 'Compare'}
                  </button>
                </div>
              </div>

              {diffError && (
                <div className="error-message" role="alert">
                  <span aria-hidden="true">⚠</span>
                  {diffError}
                </div>
              )}

              {diff && (
                <div className="discovery-diff">
                  <div className="discovery-diff-group">
                    <h4>Added</h4>
                    {diff.added.length === 0 ? (
                      <p className="device-muted">Nothing was added.</p>
                    ) : (
                      <ul>
                        {diff.added.map((item, i) => (
                          <li key={i}>{String(item)}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <div className="discovery-diff-group">
                    <h4>Removed</h4>
                    {diff.removed.length === 0 ? (
                      <p className="device-muted">Nothing was removed.</p>
                    ) : (
                      <ul>
                        {diff.removed.map((item, i) => (
                          <li key={i}>{String(item)}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <div className="discovery-diff-group">
                    <h4>Changed</h4>
                    {diff.changed.length === 0 ? (
                      <p className="device-muted">Nothing changed.</p>
                    ) : (
                      <ul>
                        {diff.changed.map((item, i) => (
                          <li key={i}>{String(item)}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </section>
    </div>
  );
}
