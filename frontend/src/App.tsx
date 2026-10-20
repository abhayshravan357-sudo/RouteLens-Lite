import { useEffect, useState } from 'react';
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
  LabState,
  PacketJourneyRequest,
  PacketJourneyResponse,
  Scenario,
  ScenarioSummary,
  ScenarioTrace,
} from './types/routing';
import RoutingTable from './components/RoutingTable';
import LookupForm from './components/LookupForm';
import ResultDisplay from './components/ResultDisplay';
import Visualization from './components/Visualization';
import PacketJourney from './components/PacketJourney';
import NetworkDiagnostics from './components/NetworkDiagnostics';
import ScenarioJourney from './components/ScenarioJourney';
import './index.css';

function App() {
  const [backendConnected, setBackendConnected] = useState(false);
  const [routes, setRoutes] = useState<RoutingEntry[]>([]);
  const [routesLoading, setRoutesLoading] = useState(true);
  const [lookupResult, setLookupResult] = useState<RouteLookupResult | null>(null);
  const [lookupLoading, setLookupLoading] = useState(false);
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [labState, setLabState] = useState<LabState>('idle');
  const [labError, setLabError] = useState<string | null>(null);
  const [simulationResponse, setSimulationResponse] = useState<PacketJourneyResponse | null>(null);

  // Scenario engine state
  const [scenarios, setScenarios] = useState<ScenarioSummary[]>([]);
  const [selectedScenario, setSelectedScenario] = useState<Scenario | null>(null);
  const [scenarioTrace, setScenarioTrace] = useState<ScenarioTrace | null>(null);
  const [scenarioLoading, setScenarioLoading] = useState(false);
  const [scenarioError, setScenarioError] = useState<string | null>(null);

  // Check backend health on mount
  useEffect(() => {
    const check = async () => {
      try {
        await checkHealth();
        setBackendConnected(true);
      } catch {
        setBackendConnected(false);
      }
    };
    check();

    // Poll health every 30 seconds
    const interval = setInterval(check, 30000);
    return () => clearInterval(interval);
  }, []);

  // Check lab availability on mount and when backend connects
  useEffect(() => {
    if (!backendConnected) return;

    const checkLab = async () => {
      try {
        const status = await checkLabStatus();
        setLabState(status.available ? 'ready' : 'unavailable');
        if (!status.available) {
          setLabError(status.error || 'Virtual router not ready');
        }
      } catch {
        setLabState('unavailable');
        setLabError('Failed to check lab status');
      }
    };
    checkLab();
  }, [backendConnected]);

  // Fetch routes on mount and when backend connects
  useEffect(() => {
    if (!backendConnected) return;

    const loadRoutes = async () => {
      setRoutesLoading(true);
      try {
        const data = await fetchRoutes();
        setRoutes(data);
      } catch (error) {
        console.error('Failed to fetch routes:', error);
        setRoutes([]);
      } finally {
        setRoutesLoading(false);
      }
    };

    loadRoutes();
  }, [backendConnected]);

  // Load the scenario list once the backend is reachable
  useEffect(() => {
    if (!backendConnected) return;

    const loadScenarios = async () => {
      try {
        const list = await fetchScenarios();
        setScenarios(list);
        if (list.length > 0) {
          const first = await fetchScenario(list[0].id);
          setSelectedScenario(first);
        }
      } catch (error) {
        setScenarioError(
          error instanceof Error ? error.message : 'Could not load scenarios'
        );
      }
    };

    loadScenarios();
  }, [backendConnected]);

  // Trace a packet through the selected scenario
  const handleScenarioTrace = async (src: string, dst: string) => {
    if (!selectedScenario) return;

    setScenarioLoading(true);
    setScenarioError(null);
    setScenarioTrace(null);
    try {
      const result = await traceScenario(selectedScenario.id, { src, dst });
      setScenarioTrace(result);
    } catch (error) {
      if (error instanceof TimeoutError) {
        setScenarioError('The trace request timed out.');
      } else if (error instanceof ApiError) {
        setScenarioError(error.message);
      } else {
        setScenarioError(error instanceof Error ? error.message : 'Trace failed');
      }
    } finally {
      setScenarioLoading(false);
    }
  };

  // Handle route lookup
  const handleLookup = async (destination: string) => {
    setLookupLoading(true);
    setLookupResult(null);
    setLookupError(null);
    try {
      const result = await lookupRoute(destination);
      setLookupResult(result);
    } catch (error) {
      if (error instanceof TimeoutError) {
        setLookupError('Request timed out. Please check your connection and try again.');
      } else if (error instanceof ApiError) {
        setLookupError(error.message);
      } else {
        setLookupError(error instanceof Error ? error.message : 'Unknown error');
      }
      setLookupResult({
        matched: false,
        route: null,
        explanation: '',
        error: error instanceof Error ? error.message : 'Unknown error',
        transmitted: false,
      });
    } finally {
      setLookupLoading(false);
    }
  };

  // Initial lookup with sample destination
  useEffect(() => {
    if (backendConnected && routes.length > 0 && !lookupResult && !lookupLoading) {
      handleLookup('192.168.1.50');
    }
  }, [backendConnected, routes.length, lookupResult, lookupLoading]);

  // Handle packet journey trace - uses routing lookup result
  const handleSimulatePacket = async () => {
    if (!lookupResult?.matched || !lookupResult.route) return;

    setLabState('simulating');
    setLabError(null);
    setSimulationResponse(null);

    try {
      // Use the routing lookup result to determine the packet journey
      // The source is the device that would send the packet, destination is the lookup target
      const request: PacketJourneyRequest = {
        source_ip: '192.168.1.10', // Client device in the lab
        destination_ip: lookupResult.route.destination.split('/')[0], // Use the network address from the matched route
      };

      const response = await tracePacketJourney(request);
      setSimulationResponse(response);
      setLabState(response.success ? 'completed' : 'error');

      if (!response.success) {
        setLabError(response.error || 'Packet journey failed');
      }
    } catch (error) {
      setLabState('error');
      if (error instanceof LabUnavailableError) {
        setLabError(error.message);
      } else if (error instanceof TimeoutError) {
        setLabError('Packet journey timed out. The lab may be overloaded.');
      } else if (error instanceof ApiError) {
        setLabError(error.message);
      } else {
        setLabError(error instanceof Error ? error.message : 'Packet journey failed');
      }
    }
  };

  // Reset lab state when lookup changes
  useEffect(() => {
    setLabState('idle');
    setLabError(null);
    setSimulationResponse(null);
  }, [lookupResult]);

  return (
    <div className="app">
      <header className="header">
        <div className="header-content">
          <div className="header-title">
            <h1>RouteLens Lite</h1>
          </div>
          <div className="header-status">
            <span className={`status-badge ${backendConnected ? 'connected' : 'disconnected'}`}>
              <span className="dot" aria-hidden="true"></span>
              {backendConnected ? 'Backend Connected' : 'Backend Disconnected'}
            </span>
            <span className="route-count">
              {routesLoading ? 'Loading...' : `${routes.length} route${routes.length !== 1 ? 's' : ''} available`}
            </span>
          </div>
        </div>
      </header>

      <main className="main-content">
        <section className="section">
          <div className="card">
            <div className="card-header">
              <h2>Routing Table</h2>
            </div>
            <div className="card-body">
              {routesLoading ? (
                <div className="loading"><span className="spinner" aria-hidden="true"></span>Loading routes...</div>
              ) : (
                <RoutingTable routes={routes} />
              )}
            </div>
          </div>
        </section>

        <section className="section">
          <div className="card">
            <div className="card-header">
              <h2>Route Lookup</h2>
            </div>
            <div className="card-body">
              <LookupForm
                onSubmit={handleLookup}
                disabled={lookupLoading || !backendConnected}
                defaultValue="192.168.1.50"
              />
              {lookupError && (
                <div className="error-message" role="alert">
                  <span aria-hidden="true">⚠</span>
                  {lookupError}
                </div>
              )}
              {lookupResult && (
                <ResultDisplay result={lookupResult} />
              )}
              {lookupLoading && !lookupResult && (
                <div className="loading"><span className="spinner" aria-hidden="true"></span>Analyzing route...</div>
              )}
            </div>
          </div>
        </section>

        {lookupResult && lookupResult.matched && lookupResult.route && (
          <section className="section">
            <div className="card">
              <div className="card-header">
                <h2>Route Decision Visualization</h2>
              </div>
              <div className="card-body">
                <Visualization
                  routes={routes}
                  selectedRoute={lookupResult.route}
                  destination={lookupResult.route.destination}
                />
              </div>
            </div>
          </section>
        )}

        {/* Packet Journey Section - shows when a route is found */}
        {lookupResult && lookupResult.matched && lookupResult.route && (
          <section className="section">
            <div className="card">
              <div className="card-header">
                <h2>Packet Journey (Virtual Lab)</h2>
              </div>
              <div className="card-body">
                {/* Topology Mismatch Warning */}
                <div className="topology-warning">
                  <span className="warning-icon" aria-hidden="true">⚠</span>
                  <div className="warning-content">
                    <strong>Topology Mismatch:</strong> The routing table above uses sample networks
                    (192.168.1.0/24, 10.0.0.0/8), but the virtual packet lab uses isolated networks
                    (192.168.10.0/24 client↔router, 192.168.20.0/24 router↔server). The simulation below uses the LAB topology, NOT your routing decision.
                  </div>
                </div>
                <PacketJourney
                  labState={labState}
                  labError={labError}
                  simulationResponse={simulationResponse}
                  onSimulate={handleSimulatePacket}
                  disabled={labState !== 'idle' && labState !== 'completed' && labState !== 'error' && labState !== 'timeout' && labState !== 'unavailable'}
                />
              </div>
            </div>
          </section>
        )}

        {/* Scenario Packet Journey - the multi-router teaching tool */}
        {backendConnected && (
          <section className="section">
            <div className="card">
              <div className="card-header">
                <h2>Scenario Lab</h2>
              </div>
              <div className="card-body">
                {scenarios.length > 1 && (
                  <div className="scenario-picker">
                    <label htmlFor="scenario-select">Choose a network:</label>
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
                            err instanceof Error ? err.message : 'Could not load scenario'
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
                )}
                {selectedScenario && (
                  <p className="scenario-description">{selectedScenario.title}</p>
                )}
                <ScenarioJourney
                  scenario={selectedScenario}
                  trace={scenarioTrace}
                  loading={scenarioLoading}
                  error={scenarioError}
                  onTrace={handleScenarioTrace}
                />
              </div>
            </div>
          </section>
        )}

        {/* Network Diagnostics Section - always visible */}
        <section className="section">
          <div className="card">
            <div className="card-body">
              <NetworkDiagnostics />
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}

export default App;