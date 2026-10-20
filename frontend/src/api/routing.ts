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
      const error = await response.json().catch(() => ({ detail: 'Unknown error' }));

      if (response.status === 503) {
        throw new LabUnavailableError(error.detail || 'Lab unavailable');
      }

      if (response.status === 408) {
        throw new TimeoutError('Simulation timed out. The lab may be overloaded.');
      }

      throw new ApiError(
        error.detail || `Request failed: ${response.status}`,
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

export async function lookupRoute(destination: string): Promise<RouteLookupResult> {
  const encoded = encodeURIComponent(destination);
  return fetchWithTimeout<RouteLookupResult>(`/lookup?destination=${encoded}`);
}

export async function checkLabStatus(): Promise<LabStatusResponse> {
  return fetchWithTimeout<LabStatusResponse>('/api/lab/status', 10000);
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

export async function checkConnectivity(request: ConnectivityCheckRequest): Promise<ConnectivityCheckResponse> {
  return fetchWithTimeout<ConnectivityCheckResponse>(
    '/network/connectivity',
    DIAGNOSTICS_TIMEOUT,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    }
  );
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
