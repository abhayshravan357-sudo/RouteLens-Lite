import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  checkHealth,
  fetchRoutes,
  lookupRoute,
  checkLabStatus,
  tracePacketJourney,
  fetchScenarios,
  fetchScenario,
  traceScenario,
  ApiError,
  TimeoutError,
  LabUnavailableError,
} from './api/routing';
import type {
  RoutingEntry,
  RouteLookupResult,
  LookupComparison,
  LabState,
  LabStatusResponse,
  PacketJourneyRequest,
  PacketJourneyResponse,
  Scenario,
  ScenarioSummary,
  ScenarioTrace,
} from './types/routing';
import AppShell, { type ViewId } from './components/AppShell';
import DecisionChain from './components/DecisionChain';
import KernelTable from './components/KernelTable';
import RoutingTable from './components/RoutingTable';
import LookupForm from './components/LookupForm';
import ResultDisplay from './components/ResultDisplay';
import Visualization from './components/Visualization';
import PacketJourney from './components/PacketJourney';
import VirtualLabPanel from './components/VirtualLabPanel';
import NetworkDiagnostics from './components/NetworkDiagnostics';
import ScenarioJourney from './components/ScenarioJourney';
import LearningLab from './components/LearningLab';
import Overview from './components/Overview';
import ReportPanel from './components/ReportPanel';
import './index.css';

function App() {
  const [view, setView] = useState<ViewId>('overview');

  // --- Backend health ---
  const [backendConnected, setBackendConnected] = useState<boolean | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);

  // --- Routing table ---
  const [routes, setRoutes] = useState<RoutingEntry[]>([]);
  const [routesLoading, setRoutesLoading] = useState(true);
  const [routesError, setRoutesError] = useState<string | null>(null);

  // --- Route lookup ---
  const [lookupResult, setLookupResult] = useState<RouteLookupResult | null>(null);
  const [lookupLoading, setLookupLoading] = useState(false);
  const [lookupError, setLookupError] = useState<string | null>(null);
  /** The address the student actually typed, kept for the decision chain. */
  const [queriedAddress, setQueriedAddress] = useState<string | null>(null);
  /**
   * The lookup answer before and after the routing table was changed, so
   * the student can see what their edit did.
   */
  const [lookupComparison, setLookupComparison] = useState<LookupComparison | null>(null);
  /**
   * Mirrors of the two values above, so a table change always compares
   * against the answer that is on screen right now.
   */
  const lookupResultRef = useRef<RouteLookupResult | null>(null);
  const queriedAddressRef = useRef<string | null>(null);

  // --- Virtual lab ---
  const [labStatus, setLabStatus] = useState<LabStatusResponse | null>(null);
  const [labLoading, setLabLoading] = useState(false);
  const [labError, setLabError] = useState<string | null>(null);
  const [labState, setLabState] = useState<LabState>('idle');
  const [labRunError, setLabRunError] = useState<string | null>(null);
  const [simulationResponse, setSimulationResponse] = useState<PacketJourneyResponse | null>(null);

  // --- Scenario engine ---
  const [scenarios, setScenarios] = useState<ScenarioSummary[]>([]);
  const [selectedScenario, setSelectedScenario] = useState<Scenario | null>(null);
  const [scenarioTrace, setScenarioTrace] = useState<ScenarioTrace | null>(null);
  const [scenarioLoading, setScenarioLoading] = useState(false);
  const [scenarioError, setScenarioError] = useState<string | null>(null);
  const [scenarioWorkspace, setScenarioWorkspace] = useState<string | null>(null);

  // ---------------------------------------------------------------------------
  // Loading
  // ---------------------------------------------------------------------------

  const loadHealth = useCallback(async () => {
    try {
      await checkHealth();
      setBackendConnected(true);
      setHealthError(null);
    } catch (err) {
      setBackendConnected(false);
      setHealthError(err instanceof Error ? err.message : 'Backend is not reachable');
    }
  }, []);

  const loadRoutes = useCallback(async () => {
    setRoutesLoading(true);
    setRoutesError(null);
    try {
      const data = await fetchRoutes();
      setRoutes(data);
    } catch (err) {
      setRoutes([]);
      setRoutesError(
        err instanceof Error ? err.message : 'Could not load the routing table'
      );
    } finally {
      setRoutesLoading(false);
    }
  }, []);

  const loadLabStatus = useCallback(async () => {
    setLabLoading(true);
    setLabError(null);
    try {
      const status = await checkLabStatus();
      setLabStatus(status);
      setLabState(status.available ? 'ready' : 'unavailable');
    } catch (err) {
      if (err instanceof LabUnavailableError) {
        setLabStatus({
          available: false,
          state: 'unavailable',
          message: err.message,
          router_info: null,
          error: err.message,
        });
        setLabState('unavailable');
      } else {
        setLabError(
          err instanceof Error ? err.message : 'Could not reach the lab'
        );
        setLabState('unavailable');
      }
    } finally {
      setLabLoading(false);
    }
  }, []);

  const loadScenarios = useCallback(async () => {
    try {
      const list = await fetchScenarios();
      setScenarios(list);
      if (list.length > 0) {
        const first = await fetchScenario(list[0].id);
        setSelectedScenario(first);
      }
    } catch (err) {
      setScenarioError(
        err instanceof Error ? err.message : 'Could not load scenarios'
      );
    }
  }, []);

  // Health is polled, but gently: the backend is local and this is not a
  // page that needs a live dashboard.
  useEffect(() => {
    loadHealth();
    const interval = setInterval(loadHealth, 30000);
    return () => clearInterval(interval);
  }, [loadHealth]);

  useEffect(() => {
    if (backendConnected !== true) return;
    loadRoutes();
    loadLabStatus();
    loadScenarios();
  }, [backendConnected, loadRoutes, loadLabStatus, loadScenarios]);

  // ---------------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------------

  const handleLookup = useCallback(async (destination: string) => {
    setLookupLoading(true);
    setLookupResult(null);
    setLookupError(null);
    setQueriedAddress(destination);
    // A fresh lookup replaces the before-and-after comparison: the
    // student is asking a new question now.
    setLookupComparison(null);
    queriedAddressRef.current = destination;
    try {
      const result = await lookupRoute(destination);
      setLookupResult(result);
      lookupResultRef.current = result;
    } catch (error) {
      if (error instanceof TimeoutError) {
        setLookupError(
          'The lookup timed out. Check the backend is still running and try again.'
        );
      } else if (error instanceof ApiError) {
        setLookupError(error.message);
      } else {
        setLookupError(
          error instanceof Error ? error.message : 'The lookup failed'
        );
      }
      const failed: RouteLookupResult = {
        matched: false,
        route: null,
        explanation: '',
        error: error instanceof Error ? error.message : 'The lookup failed',
        transmitted: false,
      };
      setLookupResult(failed);
      lookupResultRef.current = failed;
    } finally {
      setLookupLoading(false);
    }
  }, []);

  /**
   * The routing table changed. Refresh it, then run the same lookup again
   * so the student can see the new answer beside the old one.
   */
  const handleTableChanged = useCallback(async () => {
    try {
      const data = await fetchRoutes();
      setRoutes(data);
    } catch (error) {
      console.error('Failed to refresh routes:', error);
    }

    const before = lookupResultRef.current;
    const destination = queriedAddressRef.current;
    if (!destination) return;

    try {
      const after = await lookupRoute(destination);
      setLookupResult(after);
      lookupResultRef.current = after;
      setLookupComparison({ destination, before, after });
    } catch (error) {
      setLookupError(
        error instanceof Error ? error.message : 'Could not run the lookup again.'
      );
    }
  }, []);

  // Show one real lookup as soon as the table is available, so the analyzer
  // is never an empty page.
  useEffect(() => {
    if (backendConnected === true && routes.length > 0 && !lookupResult && !lookupLoading) {
      handleLookup('192.168.1.50');
    }
  }, [backendConnected, routes.length, lookupResult, lookupLoading, handleLookup]);

  const handleScenarioTrace = useCallback(
    async (src: string, dst: string, workspace?: string | null) => {
      if (!selectedScenario) return;

      setScenarioLoading(true);
      setScenarioError(null);
      setScenarioTrace(null);
      try {
        const result = await traceScenario(selectedScenario.id, {
          src,
          dst,
          workspace: workspace ?? undefined,
        });
        setScenarioTrace(result);
        if (workspace) setScenarioWorkspace(workspace);
      } catch (error) {
        if (error instanceof TimeoutError) {
          setScenarioError('The trace request timed out.');
        } else if (error instanceof ApiError) {
          setScenarioError(error.message);
        } else {
          setScenarioError(
            error instanceof Error ? error.message : 'The trace failed'
          );
        }
      } finally {
        setScenarioLoading(false);
      }
    },
    [selectedScenario]
  );

  const handleSimulatePacket = useCallback(async () => {
    if (!lookupResult?.matched || !lookupResult.route) return;

    setLabState('simulating');
    setLabRunError(null);
    setSimulationResponse(null);

    try {
      const request: PacketJourneyRequest = {
        source_ip: '192.168.1.10',
        destination_ip: lookupResult.route.destination.split('/')[0],
      };

      const response = await tracePacketJourney(request);
      setSimulationResponse(response);
      setLabState(response.success ? 'completed' : 'error');
      if (!response.success) {
        setLabRunError(response.error || 'The packet journey failed');
      }
    } catch (error) {
      setLabState('error');
      if (error instanceof LabUnavailableError) {
        setLabRunError(error.message);
      } else if (error instanceof TimeoutError) {
        setLabRunError('The packet journey timed out. The lab may be overloaded.');
      } else if (error instanceof ApiError) {
        setLabRunError(error.message);
      } else {
        setLabRunError(
          error instanceof Error ? error.message : 'The packet journey failed'
        );
      }
    }
  }, [lookupResult]);

  // A new route means the previous trace no longer describes this question.
  useEffect(() => {
    setLabState('idle');
    setLabRunError(null);
    setSimulationResponse(null);
  }, [lookupResult]);

  // ---------------------------------------------------------------------------
  // Derived
  // ---------------------------------------------------------------------------

  const isOnline = backendConnected === true;

  /**
   * The instrument strip. Every value here is a real reading or an honest
   * statement that the source is unavailable. Nothing is estimated.
   */
  const readouts = useMemo(() => {
    const v4 = routes.filter((r) => !r.destination.includes(':')).length;
    const v6 = routes.length - v4;

    return [
      {
        label: 'Routes',
        value: routesLoading ? '···' : routesError ? 'n/a' : String(routes.length),
        tone: routesError ? ('off' as const) : ('normal' as const),
      },
      {
        label: 'IPv4',
        value: routesLoading ? '···' : String(v4),
        tone: 'normal' as const,
      },
      {
        label: 'IPv6',
        value: routesLoading ? '···' : String(v6),
        tone: 'normal' as const,
      },
      {
        label: 'Lab',
        value: labLoading ? '···' : labStatus?.available ? 'ready' : 'down',
        tone: labStatus?.available ? ('live' as const) : ('off' as const),
      },
      {
        label: 'Match',
        value: lookupResult?.route?.destination ?? (lookupResult ? 'none' : '—'),
        tone: lookupResult?.route ? ('live' as const) : ('off' as const),
      },
    ];
  }, [
    routes,
    routesLoading,
    routesError,
    labLoading,
    labStatus,
    lookupResult,
  ]);

  const handleRefresh = useCallback(() => {
    loadHealth();
    if (isOnline) {
      loadRoutes();
      loadLabStatus();
      loadScenarios();
    }
  }, [loadHealth, loadRoutes, loadLabStatus, loadScenarios, isOnline]);

  // ---------------------------------------------------------------------------
  // Views
  // ---------------------------------------------------------------------------

  const renderOverview = () => (
    <div className="view-stack">
      <section className="card">
        <div className="card-body">
          <Overview
            scenario={selectedScenario}
            trace={scenarioTrace}
            legacyJourney={simulationResponse}
            lookupResult={lookupResult}
          />
        </div>
      </section>

      <section className="card">
        <div className="card-header">
          <div>
            <span className="eyebrow">04 · Evidence</span>
            <h2>Measured report</h2>
          </div>
          <span className="card-subtitle">
            Export what was actually observed, with its evidence and limits
          </span>
        </div>
        <div className="card-body">
          <ReportPanel />
        </div>
      </section>
    </div>
  );

  const renderRouting = () => (
    <div className="view-stack">
      <section className="card">
        <div className="card-header">
          <div>
            <span className="eyebrow">01 · Query</span>
            <h2>Route lookup</h2>
          </div>
          <span className="card-subtitle">
            Longest-prefix match against the routing table
          </span>
        </div>
        <div className="card-body">
          <LookupForm
            onSubmit={handleLookup}
            disabled={lookupLoading || !isOnline}
            defaultValue="192.168.1.50"
          />
          {lookupError && (
            <div className="error-message" role="alert">
              <span aria-hidden="true">⚠</span>
              {lookupError}
            </div>
          )}
          {lookupLoading && !lookupResult && (
            <div className="loading">
              <span className="spinner" aria-hidden="true" />
              Analysing the route…
            </div>
          )}
          {lookupResult && <ResultDisplay result={lookupResult} />}
        </div>
      </section>

      {lookupResult && (
        <section className="card hud hud-lit">
          <div className="card-body">
            <DecisionChain result={lookupResult} queriedAddress={queriedAddress} />
          </div>
        </section>
      )}

      {lookupResult?.matched && lookupResult.route && (
        <section className="card">
          <div className="card-header">
            <div>
              <span className="eyebrow">02 · Decision</span>
              <h2>Why that route won</h2>
            </div>
            <span className="card-subtitle">
              Every matching prefix, longest first
            </span>
          </div>
          <div className="card-body">
            <Visualization
              routes={routes}
              selectedRoute={lookupResult.route}
              destination={lookupResult.route.destination}
            />
          </div>
        </section>
      )}

      <section className="card">
        <div className="card-header">
          <div>
            <span className="eyebrow">03 · Table</span>
            <h2>Routing table</h2>
          </div>
          <span className="card-subtitle">
            {routesLoading
              ? 'Loading…'
              : routesError
              ? 'Unavailable'
              : `${routes.length} entries`}
          </span>
        </div>
        <div className="card-body flush">
          {routesLoading ? (
            <div className="loading">
              <span className="spinner" aria-hidden="true" />
              Loading routes…
            </div>
          ) : routesError ? (
            <div className="error-message" role="alert" style={{ margin: '20px' }}>
              <span aria-hidden="true">⚠</span>
              {routesError}
            </div>
          ) : (
            <RoutingTable
              routes={routes}
              onTableChanged={handleTableChanged}
              comparison={lookupComparison}
              lookupResult={lookupResult}
              lookupDestination={queriedAddress ?? ''}
              bestMatch={lookupResult?.route?.destination ?? null}
            />
          )}
        </div>
      </section>
    </div>
  );

  const renderKernel = () => (
    <div className="view-stack">
      <section className="card">
        <div className="card-header">
          <div>
            <span className="eyebrow">01 · Observed</span>
            <h2>This machine's real routing table</h2>
          </div>
          <span className="card-subtitle">
            Read from the kernel, not from a sample
          </span>
        </div>
        <div className="card-body">
          <KernelTable />
        </div>
      </section>
    </div>
  );

  const renderJourney = () => (
    <div className="view-stack">
      {scenarios.length > 1 && (
        <section className="card">
          <div className="card-body">
            <div className="scenario-picker">
              <label htmlFor="scenario-select">Network</label>
              <select
                id="scenario-select"
                value={selectedScenario?.id ?? ''}
                onChange={async (e) => {
                  setScenarioTrace(null);
                  setScenarioError(null);
                  try {
                    const next = await fetchScenario(e.target.value);
                    setSelectedScenario(next);
                  } catch (err) {
                    setScenarioError(
                      err instanceof Error
                        ? err.message
                        : 'Could not load the scenario'
                    );
                  }
                }}
              >
                {scenarios.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.title}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </section>
      )}

      <section className="card">
        <div className="card-body">
          <ScenarioJourney
            scenario={selectedScenario}
            trace={scenarioTrace}
            loading={scenarioLoading}
            error={scenarioError}
            workspace={scenarioWorkspace}
            onTrace={handleScenarioTrace}
          />
        </div>
      </section>
    </div>
  );
  const renderLab = () => (
    <div className="view-stack">
      <section className="card">
        <div className="card-header">
          <div>
            <span className="eyebrow">01 · Facility</span>
            <h2>Lab state</h2>
          </div>
          <span className="card-subtitle">
            Read from the backend, not assumed
          </span>
        </div>
        <div className="card-body">
          <VirtualLabPanel
            status={labStatus}
            loading={labLoading}
            error={labError}
            onRetry={loadLabStatus}
          />
        </div>
      </section>

      {lookupResult?.matched && lookupResult.route && (
        <section className="card">
          <div className="card-header">
            <div>
              <span className="eyebrow">02 · Trace</span>
              <h2>Trace against the routing table</h2>
            </div>
            <span className="card-subtitle">
              The software forwarding decision for the address you looked up
            </span>
          </div>
          <div className="card-body">
            <div className="topology-warning">
              <span className="warning-icon" aria-hidden="true">⚠</span>
              <div className="warning-content">
                <strong>Different topologies.</strong> The routing table uses
                sample networks (192.168.1.0/24, 10.0.0.0/8). The isolated lab
                is built from a scenario, so it uses that scenario&rsquo;s own
                networks. The trace below follows the routing table, not the
                physical lab.
              </div>
            </div>
            <PacketJourney
              labState={labState}
              labError={labRunError}
              simulationResponse={simulationResponse}
              onSimulate={handleSimulatePacket}
              disabled={
                labState !== 'idle' &&
                labState !== 'completed' &&
                labState !== 'error' &&
                labState !== 'timeout' &&
                labState !== 'unavailable'
              }
            />
          </div>
        </section>
      )}
    </div>
  );

  const renderDiagnostics = () => (
    <div className="view-stack">
      <section className="card">
        <div className="card-body">
          <NetworkDiagnostics embedded />
        </div>
      </section>
    </div>
  );

  const renderLearning = () => (
    <div className="view-stack">
      <section className="card">
        <div className="card-body">
          <LearningLab workspace={scenarioWorkspace} />
        </div>
      </section>
    </div>
  );

  const views: Record<ViewId, () => React.ReactNode> = {
    overview: renderOverview,
    routing: renderRouting,
    kernel: renderKernel,
    journey: renderJourney,
    lab: renderLab,
    diagnostics: renderDiagnostics,
    learning: renderLearning,
  };

  return (
    <AppShell
      activeView={view}
      onViewChange={setView}
      backendOnline={backendConnected}
      backendError={healthError}
      onRefresh={handleRefresh}
      refreshing={routesLoading || labLoading}
      readouts={readouts}
    >
      {views[view]()}
    </AppShell>
  );
}

export default App;
