import { useEffect, useState } from 'react';
import {
  checkHealth,
  fetchRoutes,
  lookupRoute,
  ApiError,
  TimeoutError,
} from './api/routing';
import type { RoutingEntry, RouteLookupResult, LabState } from './types/routing';
import RoutingTable from './components/RoutingTable';
import LookupForm from './components/LookupForm';
import ResultDisplay from './components/ResultDisplay';
import Visualization from './components/Visualization';
import PacketJourney from './components/PacketJourney';
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

  // Handle packet lab simulation (placeholder for packet-lab API integration)
  const handleSimulatePacket = async () => {
    if (!lookupResult?.matched || !lookupResult.route) return;

    setLabState('simulating');
    setLabError(null);

    // TODO: Replace with actual packet-lab API call when Agent B provides the contract
    // This is a placeholder structure showing the intended flow:
    // 1. Simulated decision (route lookup already done)
    // 2. Lab readiness check
    // 3. Packet transmission
    // 4. Capture verification

    try {
      // Simulate the state progression for demonstration
      await new Promise((resolve) => setTimeout(resolve, 500));
      setLabState('ready');

      await new Promise((resolve) => setTimeout(resolve, 800));
      setLabState('transmitting');

      await new Promise((resolve) => setTimeout(resolve, 1000));
      setLabState('capturing');

      await new Promise((resolve) => setTimeout(resolve, 800));
      setLabState('verifying');

      await new Promise((resolve) => setTimeout(resolve, 500));
      setLabState('completed');
    } catch {
      setLabState('error');
      setLabError('Packet simulation failed');
    }
  };

  // Reset lab state when lookup changes
  useEffect(() => {
    setLabState('idle');
    setLabError(null);
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
                <h2>Packet Journey</h2>
              </div>
              <div className="card-body">
                <PacketJourney
                  route={lookupResult.route}
                  labState={labState}
                  labError={labError}
                  onSimulate={handleSimulatePacket}
                  disabled={labState !== 'idle' && labState !== 'completed' && labState !== 'error'}
                />
              </div>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}

export default App;