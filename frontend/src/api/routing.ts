/**
 * API module for communicating with the RouteLens Lite backend.
 * All requests are proxied through Vite to http://localhost:8000.
 */

import type {
  RoutingEntry,
  RouteLookupResult,
  LabStatusResponse,
  SimulateRequest,
  SimulateResponse,
  InterfacesResult,
  RoutesResult,
  NeighborsResult,
  AllNetworkResult,
  DnsResolveRequest,
  DnsResolveResponse,
  ConnectivityCheckRequest,
  ConnectivityCheckResponse,
  TracerouteRequest,
  TracerouteResponse,
  PacketJourneyRequest,
  PacketJourneyResponse,
  Scenario,
  ScenarioSummary,
  ScenarioTrace,
  ScenarioTraceRequest,
  ScenarioRoute,
  LabRunResult,
  ScenarioCompare,
  TopologyGraph,
  ExerciseSummary,
  ExerciseDetail,
  ExerciseState,
  HostExerciseSummary,
  HostExerciseDetail,
  HostExerciseState,
  DiscoveryScopePreview,
  DiscoveryResult,
  DiscoveryAuditEntry,
  PcapAnalyzeRequest,
  PcapAnalysisResult,
  RouteAnalysisReport,
  RouteRequest,
  RoutesSummary,
  RouterDiscoveryRunRequest,
  RouterDiscoveryRunStart,
  RouterDiscoveryRun,
  RouterDiscoveryGraph,
  RouterDiscoveryDevice,
  RouterDiscoveryDeviceRoutes,
  RouterDiscoveryFindings,
  RouterDiscoveryDiff,
  RouterDiscoveryTraceRequest,
  TraceResult,
} from '../types/routing';

const API_BASE = '';
const DEFAULT_TIMEOUT = 10000;
const LAB_TIMEOUT = 30000; // Longer timeout for lab operations
const NETWORK_TIMEOUT = 15000; // Timeout for network collection
const DIAGNOSTICS_TIMEOUT = 30000; // Longer timeout for diagnostics

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code?: string
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export class TimeoutError extends Error {
  constructor(message = 'Request timed out') {
    super(message);
    this.name = 'TimeoutError';
  }
}

export class LabUnavailableError extends Error {
  constructor(message = 'Packet lab is currently unavailable') {
    super(message);
    this.name = 'LabUnavailableError';
  }
}

/**
 * Turn a FastAPI error body into something a person can read.
 *
 * `detail` is a string for HTTPException, but a list of objects for
 * request-validation errors, and an object for a few other cases. Passing
 * any of those straight to `new Error()` renders "[object Object]", so
 * they are unpacked here.
 */
function formatDetail(detail: unknown, fallback: string): string {
  if (typeof detail === 'string' && detail.trim()) return detail;

  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (typeof item === 'string') return item;
        if (item && typeof item === 'object') {
          const record = item as Record<string, unknown>;
          const loc = Array.isArray(record.loc)
            ? record.loc.filter((p) => p !== 'body').join('.')
            : '';
          const msg = typeof record.msg === 'string' ? record.msg : 'invalid value';
          return loc ? `${loc}: ${msg}` : msg;
        }
        return String(item);
      })
      .filter(Boolean);
    if (parts.length) return parts.join('; ');
  }

  if (detail && typeof detail === 'object') {
    const record = detail as Record<string, unknown>;
    for (const key of ['message', 'error', 'reason'] as const) {
      const value = record[key];
      if (typeof value === 'string' && value.trim()) return value;
    }
    try {
      return JSON.stringify(detail);
    } catch {
      return fallback;
    }
  }

  return fallback;
}

async function fetchWithTimeout<T>(
  endpoint: string,
  timeoutMs = DEFAULT_TIMEOUT,
  options: RequestInit & { params?: Record<string, string> } = {}
): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  const { params, ...init } = options;
  let url = `${API_BASE}${endpoint}`;
  if (params) {
    const query = new URLSearchParams(params).toString();
    if (query) url += `?${query}`;
  }

  try {
    const response = await fetch(url, {
      signal: controller.signal,
      ...init,
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: null }));

      if (response.status === 503) {
        throw new LabUnavailableError(
          formatDetail(error.detail, 'Lab unavailable')
        );
      }

      if (response.status === 408) {
        throw new TimeoutError('Simulation timed out. The lab may be overloaded.');
      }

      throw new ApiError(
        formatDetail(error.detail, `Request failed: ${response.status}`),
        response.status,
        error.code
      );
    }

    return response.json();
  } catch (error) {
    clearTimeout(timeoutId);

    if (error instanceof ApiError || error instanceof LabUnavailableError || error instanceof TimeoutError) {
      throw error;
    }

    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new TimeoutError();
    }

    throw new ApiError(
      error instanceof Error ? error.message : 'Network error',
      0,
      'NETWORK_ERROR'
    );
  }
}

export async function checkHealth(): Promise<{ status: string; service: string }> {
  return fetchWithTimeout<{ status: string; service: string }>('/health', 5000);
}

export async function fetchRoutes(): Promise<RoutingEntry[]> {
  return fetchWithTimeout<RoutingEntry[]>('/routes');
}

/**
 * A request against the live routing table.
 *
 * Separate from the shared helper because deleting a route answers 204
 * with no body, which has no JSON to read.
 */
async function routingTableRequest<T>(
  endpoint: string,
  method: 'POST' | 'PUT' | 'DELETE',
  body?: unknown
): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), DEFAULT_TIMEOUT);

  try {
    const response = await fetch(`${API_BASE}${endpoint}`, {
      method,
      signal: controller.signal,
      headers:
        body === undefined
          ? undefined
          : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      const detail = (payload as { detail?: unknown } | null)?.detail;
      throw new ApiError(
        formatDetail(detail, `The backend refused the change (HTTP ${response.status}).`),
        response.status
      );
    }

    if (response.status === 204) {
      return undefined as T;
    }

    return (await response.json()) as T;
  } catch (error) {
    clearTimeout(timeoutId);

    if (error instanceof ApiError) {
      throw error;
    }

    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new TimeoutError('The backend did not answer in time.');
    }

    throw new ApiError(
      error instanceof Error ? error.message : 'Network error',
      0,
      'NETWORK_ERROR'
    );
  }
}

/** Add a route to the live table. The backend validates it and refuses bad ones. */
export async function addRoute(route: RouteRequest): Promise<RoutingEntry> {
  return routingTableRequest<RoutingEntry>('/routes', 'POST', route);
}

/** Replace the route at an index. The backend refuses an out-of-range index. */
export async function updateRoute(
  index: number,
  route: RouteRequest
): Promise<RoutingEntry> {
  return routingTableRequest<RoutingEntry>(`/routes/${index}`, 'PUT', route);
}

/** Remove the route at an index. The backend refuses an out-of-range index. */
export async function deleteRoute(index: number): Promise<void> {
  return routingTableRequest<void>(`/routes/${index}`, 'DELETE');
}

/** Put the original sample table back. */
export async function resetRoutes(): Promise<RoutingEntry[]> {
  return routingTableRequest<RoutingEntry[]>('/routes/reset', 'POST');
}

/** Counts and statistics for the live table. */
export async function fetchRoutesSummary(): Promise<RoutesSummary> {
  return fetchWithTimeout<RoutesSummary>('/routes/summary');
}

export async function lookupRoute(destination: string): Promise<RouteLookupResult> {
  const encoded = encodeURIComponent(destination);
  return fetchWithTimeout<RouteLookupResult>(`/lookup?destination=${encoded}`);
}

export async function checkLabStatus(): Promise<LabStatusResponse> {
  return fetchWithTimeout<LabStatusResponse>('/api/lab/status', 10000);
}

/**
 * Analyse the routing table the running kernel actually holds.
 *
 * `ipVersion` is sent as `ip_version`. A backend that predates per-family
 * analysis ignores it and returns the IPv4 table; the caller is expected to
 * notice that from the response rather than to assume it worked.
 */
export async function fetchRouteAnalysis(
  destination?: string | null,
  ipVersion: 'ipv4' | 'ipv6' = 'ipv4'
): Promise<RouteAnalysisReport> {
  const params: Record<string, string> = { ip_version: ipVersion };
  if (destination && destination.trim()) {
    params.destination = destination.trim();
  }
  return fetchWithTimeout<RouteAnalysisReport>(
    '/network/routes/analysis',
    NETWORK_TIMEOUT,
    { params }
  );
}

export async function simulatePacket(request: SimulateRequest): Promise<SimulateResponse> {
  return fetchWithTimeout<SimulateResponse>(
    '/api/lab/simulate',
    LAB_TIMEOUT,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    }
  );
}

// Network Collector API
export async function fetchInterfaces(): Promise<InterfacesResult> {
  return fetchWithTimeout<InterfacesResult>('/network/interfaces', NETWORK_TIMEOUT);
}

export async function fetchNetworkRoutes(): Promise<RoutesResult> {
  return fetchWithTimeout<RoutesResult>('/network/routes', NETWORK_TIMEOUT);
}

export async function fetchNeighbors(): Promise<NeighborsResult> {
  return fetchWithTimeout<NeighborsResult>('/network/neighbors', NETWORK_TIMEOUT);
}

export async function fetchAllNetworkInfo(): Promise<AllNetworkResult> {
  return fetchWithTimeout<AllNetworkResult>('/network/all', NETWORK_TIMEOUT);
}

// Network Diagnostics API
export async function resolveDns(request: DnsResolveRequest): Promise<DnsResolveResponse> {
  return fetchWithTimeout<DnsResolveResponse>(
    '/network/dns-resolve',
    DIAGNOSTICS_TIMEOUT,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    }
  );
}

/**
 * Check whether a target is reachable.
 *
 * An unreachable target is a result, not a fault. The backend answers with
 * an error status in that case, but sends the whole result in the
 * `X-RouteLens-Result` header so the verdict is not lost. It is read from
 * there, and the panel can then say "Unreachable" instead of showing a
 * raw error.
 */
export async function checkConnectivity(
  request: ConnectivityCheckRequest
): Promise<ConnectivityCheckResponse> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), DIAGNOSTICS_TIMEOUT);

  try {
    const response = await fetch(`${API_BASE}/network/connectivity`, {
      method: 'POST',
      signal: controller.signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });

    clearTimeout(timeoutId);

    const carried = response.headers.get('X-RouteLens-Result');
    if (carried) {
      try {
        return JSON.parse(carried) as ConnectivityCheckResponse;
      } catch {
        // A header that will not parse is not a result; carry on with the
        // status code below.
      }
    }

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: null }));
      throw new ApiError(
        formatDetail(error.detail, `Request failed: ${response.status}`),
        response.status,
        error.code
      );
    }

    return (await response.json()) as ConnectivityCheckResponse;
  } catch (error) {
    clearTimeout(timeoutId);

    if (error instanceof ApiError) {
      throw error;
    }

    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new TimeoutError('The check did not finish in time.');
    }

    throw new ApiError(
      error instanceof Error ? error.message : 'Network error',
      0,
      'NETWORK_ERROR'
    );
  }
}

export async function runTraceroute(request: TracerouteRequest): Promise<TracerouteResponse> {
  return fetchWithTimeout<TracerouteResponse>(
    '/network/traceroute',
    DIAGNOSTICS_TIMEOUT,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    }
  );
}

export async function tracePacketJourney(request: PacketJourneyRequest): Promise<PacketJourneyResponse> {
  return fetchWithTimeout<PacketJourneyResponse>(
    '/packet-journey',
    DIAGNOSTICS_TIMEOUT,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    }
  );
}

// Scenario engine API
export async function fetchScenarios(): Promise<ScenarioSummary[]> {
  return fetchWithTimeout<ScenarioSummary[]>('/api/scenarios', 10000);
}

export async function fetchScenario(scenarioId: string): Promise<Scenario> {
  return fetchWithTimeout<Scenario>(`/api/scenarios/${encodeURIComponent(scenarioId)}`, 10000);
}

export async function traceScenario(
  scenarioId: string,
  request: ScenarioTraceRequest
): Promise<ScenarioTrace> {
  return fetchWithTimeout<ScenarioTrace>(
    `/api/scenarios/${encodeURIComponent(scenarioId)}/trace`,
    15000,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    }
  );
}

export interface ScenarioRouteUpdate {
  scenario: Scenario;
  workspace: string;
}

export interface ScenarioLinkUpdate {
  scenario: Scenario;
  workspace: string;
  link_a: string;
  link_b: string;
  is_up: boolean;
}

export async function toggleScenarioLink(
  scenarioId: string,
  linkA: string,
  linkB: string,
  isUp: boolean,
  workspace?: string | null
): Promise<ScenarioLinkUpdate> {
  return fetchWithTimeout<ScenarioLinkUpdate>(
    `/api/scenarios/${encodeURIComponent(scenarioId)}/links`,
    10000,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        link_a: linkA,
        link_b: linkB,
        is_up: isUp,
        workspace: workspace ?? null,
      }),
    }
  );
}

export async function updateScenarioRoutes(
  scenarioId: string,
  nodeId: string,
  routes: Partial<ScenarioRoute>[]
): Promise<ScenarioRouteUpdate> {
  return fetchWithTimeout<ScenarioRouteUpdate>(
    `/api/scenarios/${encodeURIComponent(scenarioId)}/nodes/${encodeURIComponent(nodeId)}/routes`,
    10000,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ routes }),
    }
  );
}

export async function applyScenarioLab(
  scenarioId: string,
  dryRun = true
): Promise<LabRunResult> {
  return fetchWithTimeout<LabRunResult>(
    `/api/scenarios/${encodeURIComponent(scenarioId)}/lab/apply`,
    60000,
    { method: 'POST', params: { dry_run: String(dryRun) } }
  );
}

export async function teardownScenarioLab(
  scenarioId: string,
  dryRun = true
): Promise<LabRunResult> {
  return fetchWithTimeout<LabRunResult>(
    `/api/scenarios/${encodeURIComponent(scenarioId)}/lab/teardown`,
    60000,
    { method: 'POST', params: { dry_run: String(dryRun) } }
  );
}

export async function compareScenarioWithLab(
  scenarioId: string,
  request: ScenarioTraceRequest
): Promise<ScenarioCompare> {
  return fetchWithTimeout<ScenarioCompare>(
    `/api/scenarios/${encodeURIComponent(scenarioId)}/compare`,
    30000,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    }
  );
}

export async function fetchScenarioTopology(
  scenarioId: string,
  workspace?: string | null
): Promise<TopologyGraph> {
  const query = workspace ? `?workspace=${encodeURIComponent(workspace)}` : '';
  return fetchWithTimeout<TopologyGraph>(
    `/api/scenarios/${encodeURIComponent(scenarioId)}/topology${query}`,
    15000
  );
}

// Learning Lab API
export async function fetchExercises(): Promise<ExerciseSummary[]> {
  return fetchWithTimeout<ExerciseSummary[]>('/api/exercises', 10000);
}

export async function fetchExercise(exerciseId: string): Promise<ExerciseDetail> {
  return fetchWithTimeout<ExerciseDetail>(
    `/api/exercises/${encodeURIComponent(exerciseId)}`,
    10000
  );
}

export async function checkExercise(
  exerciseId: string,
  scenarioId: string,
  workspace?: string | null
): Promise<ExerciseState> {
  return fetchWithTimeout<ExerciseState>(
    `/api/exercises/${encodeURIComponent(exerciseId)}/check`,
    15000,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scenario_id: scenarioId, workspace: workspace ?? undefined }),
    }
  );
}

// The exercises that work against the routing table of the machine the
// student is sitting at. They are a separate set from the modelled ones,
// because they read a real table rather than a scenario.
export async function fetchHostExercises(): Promise<HostExerciseSummary[]> {
  return fetchWithTimeout<HostExerciseSummary[]>('/api/host-exercises', 10000);
}

export async function fetchHostExercise(
  exerciseId: string
): Promise<HostExerciseDetail> {
  return fetchWithTimeout<HostExerciseDetail>(
    `/api/host-exercises/${encodeURIComponent(exerciseId)}`,
    10000
  );
}

/**
 * Check a host exercise.
 *
 * `destination` is the address the student picked, and `answer` is what
 * they think the answer is. Both are optional: the backend picks an
 * address from the machine's own table when none is given.
 */
export async function checkHostExercise(
  exerciseId: string,
  destination?: string | null,
  answer?: string | null
): Promise<HostExerciseState> {
  return fetchWithTimeout<HostExerciseState>(
    `/api/host-exercises/${encodeURIComponent(exerciseId)}/check`,
    15000,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        destination: destination?.trim() || undefined,
        answer: answer?.trim() || undefined,
      }),
    }
  );
}

export async function previewDiscoveryScope(
  target: string,
  maxHosts: number,
  interval: number,
  timeout: number
): Promise<DiscoveryScopePreview> {
  return fetchWithTimeout<DiscoveryScopePreview>(
    '/api/discovery/scope',
    15000,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        target,
        max_hosts: maxHosts,
        interval,
        timeout,
      }),
    }
  );
}

export async function runDiscovery(
  target: string,
  confirmation: string,
  maxHosts: number,
  interval: number,
  timeout: number
): Promise<DiscoveryResult> {
  return fetchWithTimeout<DiscoveryResult>(
    '/api/discovery/run',
    300000,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        target,
        max_hosts: maxHosts,
        interval,
        timeout,
        confirmed: true,
        confirmation,
      }),
    }
  );
}

export async function cancelDiscovery(scanId: string): Promise<{ cancelled: boolean }> {
  return fetchWithTimeout<{ cancelled: boolean }>(
    `/api/discovery/cancel?scan_id=${encodeURIComponent(scanId)}`,
    10000,
    { method: 'POST' }
  );
}

export async function fetchDiscoveryAudit(): Promise<DiscoveryAuditEntry[]> {
  return fetchWithTimeout<DiscoveryAuditEntry[]>('/api/discovery/audit', 10000);
}

// Report export
export async function fetchReportJson(): Promise<unknown> {
  return fetchWithTimeout<unknown>('/api/report?format=json', 30000);
}

export async function fetchReportMarkdown(activeExperiment?: Record<string, unknown> | null): Promise<string> {
  const url = '/api/report';
  let response: Response;
  if (activeExperiment) {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        format: 'markdown',
        active_experiment: activeExperiment,
      }),
    });
  } else {
    response = await fetch('/api/report?format=markdown');
  }
  if (!response.ok) {
    throw new ApiError(
      `Could not build the report: ${response.status}`,
      response.status
    );
  }
  return response.text();
}

// PCAP Analysis API
export async function analyzeCaptureFile(filename: string, dataBase64: string): Promise<PcapAnalysisResult> {
  const request: PcapAnalyzeRequest = { filename, data_base64: dataBase64 };
  return fetchWithTimeout<PcapAnalysisResult>(
    '/api/pcap/analyze',
    60000,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    }
  );
}

/**
 * Router discovery.
 *
 * A different thing from the ICMP host sweep in `/api/discovery/`: that
 * one pings a network for hosts, this one walks a network of routers and
 * reads their tables and their neighbour lists.
 */
export async function startRouterDiscoveryRun(
  request: RouterDiscoveryRunRequest
): Promise<RouterDiscoveryRunStart> {
  return fetchWithTimeout<RouterDiscoveryRunStart>(
    '/api/router-discovery/runs',
    DIAGNOSTICS_TIMEOUT,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    }
  );
}

export async function fetchRouterDiscoveryRun(
  runId: string
): Promise<RouterDiscoveryRun> {
  return fetchWithTimeout<RouterDiscoveryRun>(
    `/api/router-discovery/runs/${encodeURIComponent(runId)}`,
    DIAGNOSTICS_TIMEOUT
  );
}

export async function fetchRouterDiscoveryGraph(
  runId: string
): Promise<RouterDiscoveryGraph> {
  return fetchWithTimeout<RouterDiscoveryGraph>(
    `/api/router-discovery/runs/${encodeURIComponent(runId)}/graph`,
    DIAGNOSTICS_TIMEOUT
  );
}

export async function fetchRouterDiscoveryDeviceRoutes(
  runId: string,
  deviceId: string
): Promise<RouterDiscoveryDeviceRoutes> {
  return fetchWithTimeout<RouterDiscoveryDeviceRoutes>(
    `/api/router-discovery/runs/${encodeURIComponent(runId)}/devices/${encodeURIComponent(deviceId)}/routes`,
    DIAGNOSTICS_TIMEOUT
  );
}

export async function fetchRouterDiscoveryDevice(
  runId: string,
  deviceId: string
): Promise<RouterDiscoveryDevice> {
  return fetchWithTimeout<RouterDiscoveryDevice>(
    `/api/router-discovery/runs/${encodeURIComponent(runId)}/devices/${encodeURIComponent(deviceId)}`,
    DIAGNOSTICS_TIMEOUT
  );
}

export async function fetchRouterDiscoveryFindings(
  runId: string
): Promise<RouterDiscoveryFindings> {
  return fetchWithTimeout<RouterDiscoveryFindings>(
    `/api/router-discovery/runs/${encodeURIComponent(runId)}/findings`,
    DIAGNOSTICS_TIMEOUT
  );
}

export async function traceRouterDiscovery(
  runId: string,
  request: RouterDiscoveryTraceRequest
): Promise<TraceResult> {
  return fetchWithTimeout<TraceResult>(
    `/api/router-discovery/runs/${encodeURIComponent(runId)}/trace`,
    DIAGNOSTICS_TIMEOUT,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    }
  );
}

export async function fetchRouterDiscoveryDiff(
  runA: string,
  runB: string
): Promise<RouterDiscoveryDiff> {
  return fetchWithTimeout<RouterDiscoveryDiff>(
    '/api/router-discovery/diff',
    DIAGNOSTICS_TIMEOUT,
    { params: { a: runA, b: runB } }
  );
}
