import { useEffect, useState } from 'react';
import {
  fetchInterfaces,
  fetchNetworkRoutes,
  fetchNeighbors,
  fetchAllNetworkInfo,
} from '../api/routing';
import type {
  InterfacesResult,
  RoutesResult,
  NeighborsResult,
} from '../types/routing';
import NetworkInterfaces from './NetworkInterfaces';
import NetworkRoutes from './NetworkRoutes';
import NetworkNeighbors from './NetworkNeighbors';
import ConnectivityPanel from './ConnectivityPanel';
import DiscoveryPanel from './DiscoveryPanel';
import PCAPPanel from './PCAPPanel';
import './NetworkDiagnostics.css';

type TabType =
  | 'all'
  | 'interfaces'
  | 'routes'
  | 'neighbors'
  | 'dns'
  | 'connectivity'
  | 'traceroute'
  | 'discovery'
  | 'capture';

type Family = 'ipv4' | 'ipv6';

/**
 * A switch between the two address families the kernel keeps apart.
 *
 * A family that has no data is still offered: "there is no IPv6 table on
 * this machine" is a finding, and it should be visible rather than hidden
 * behind a tab that does not exist.
 */
function FamilySwitch({
  family,
  onChange,
  v4Available,
  v6Available,
}: {
  family: Family;
  onChange: (family: Family) => void;
  v4Available: boolean;
  v6Available: boolean;
}) {
  return (
    <div className="family-switch" role="group" aria-label="Address family">
      <button
        type="button"
        className={`family-chip ${family === 'ipv4' ? 'active' : ''}`}
        onClick={() => onChange('ipv4')}
        aria-pressed={family === 'ipv4'}
      >
        IPv4
        {!v4Available && <span className="family-missing">no data</span>}
      </button>
      <button
        type="button"
        className={`family-chip ${family === 'ipv6' ? 'active' : ''}`}
        onClick={() => onChange('ipv6')}
        aria-pressed={family === 'ipv6'}
      >
        IPv6
        {!v6Available && <span className="family-missing">no data</span>}
      </button>
    </div>
  );
}

interface NetworkDiagnosticsProps {
  /**
   * When true the component drops its own title bar, because the page shell
   * already shows the name, the description and a refresh control.
   */
  embedded?: boolean;
}

export default function NetworkDiagnostics({ embedded = false }: NetworkDiagnosticsProps = {}) {
  const [activeTab, setActiveTab] = useState<TabType>('all');
  const [family, setFamily] = useState<Family>('ipv4');
  const [interfacesData, setInterfacesData] = useState<InterfacesResult | null>(null);
  const [routesData, setRoutesData] = useState<RoutesResult | null>(null);
  const [routesDataV6, setRoutesDataV6] = useState<RoutesResult | null>(null);
  const [neighborsData, setNeighborsData] = useState<NeighborsResult | null>(null);
  const [neighborsDataV6, setNeighborsDataV6] = useState<NeighborsResult | null>(null);
  const [loading, setLoading] = useState<Record<string, boolean>>({
    all: false,
    interfaces: false,
    routes: false,
    neighbors: false,
    dns: false,
    connectivity: false,
    traceroute: false,
    discovery: false,
    capture: false,
  });
  const [error, setError] = useState<Record<string, string | null>>({
    all: null,
    interfaces: null,
    routes: null,
    neighbors: null,
    dns: null,
    connectivity: null,
    traceroute: null,
    discovery: null,
    capture: null,
  });
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);

  // The host's own IPv4 address, used to suggest a sensible scan scope.
  const localAddress =
    interfacesData?.data?.find((i) => i.state === 'UP' && i.ipv4_addresses.length > 0)
      ?.ipv4_addresses[0] ?? null;

  const loadTab = async (tab: string) => {
    setLoading(prev => ({ ...prev, [tab]: true }));
    setError(prev => ({ ...prev, [tab]: null }));

    try {
      if (tab === 'all' || tab === 'interfaces') {
        const result = await fetchInterfaces();
        setInterfacesData(result);
        if (!result.success) throw new Error(result.error || 'Failed to load interfaces');
      }
      if (tab === 'all' || tab === 'routes') {
        const result = await fetchNetworkRoutes();
        setRoutesData(result);
        if (!result.success) throw new Error(result.error || 'Failed to load routes');
      }
      if (tab === 'all' || tab === 'neighbors') {
        const result = await fetchNeighbors();
        setNeighborsData(result);
        if (!result.success) throw new Error(result.error || 'Failed to load neighbors');
      }
      // The kernel keeps the IPv6 routing table and neighbour cache
      // separately, and only /network/all returns them. They are fetched
      // together with the rest so the two families can be compared.
      if (tab === 'all' || tab === 'routes' || tab === 'neighbors') {
        const all = await fetchAllNetworkInfo();
        if (all.routes_ipv6) setRoutesDataV6(all.routes_ipv6);
        if (all.neighbors_ipv6) setNeighborsDataV6(all.neighbors_ipv6);
      }
      setLastRefreshed(new Date());
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      setError(prev => ({ ...prev, [activeTab]: message }));
    } finally {
      setLoading(prev => ({ ...prev, [tab]: false }));
    }
  };

  const handleRefresh = () => {
    loadTab(activeTab);
  };

  const handleTabChange = (tab: string) => {
    setActiveTab(tab as TabType);
    // Load data for the new tab if not already loaded
    if (tab === 'interfaces' && !interfacesData) loadTab('interfaces');
    else if (tab === 'routes' && !routesData) loadTab('routes');
    else if (tab === 'neighbors' && !neighborsData) loadTab('neighbors');
    else if (tab === 'dns') loadTab('dns');
    else if (tab === 'connectivity') loadTab('connectivity');
    else if (tab === 'traceroute') loadTab('traceroute');
  };

  // Load all on initial mount
  useEffect(() => {
    loadTab('all');
  }, []);

  return (
    <div className="network-diagnostics">
      {!embedded && (
        <div className="diagnostics-header">
          <div className="header-content">
            <h2>Network Diagnostics</h2>
            <p className="header-description">
              Real-time collection from the host system using <code>ip -j</code> commands.
              All operations are read-only and require no elevated privileges.
            </p>
          </div>
          <div className="header-actions">
            {lastRefreshed && (
              <span className="last-refreshed">
                Last refreshed: {lastRefreshed.toLocaleTimeString()}
              </span>
            )}
            <button
              className="btn btn-secondary"
              onClick={handleRefresh}
              disabled={loading[activeTab]}
              aria-busy={loading[activeTab]}
            >
              {loading[activeTab] ? (
                <>
                  <span className="spinner" aria-hidden="true"></span>
                  Refreshing...
                </>
              ) : (
                'Refresh'
              )}
            </button>
          </div>
        </div>
      )}

      <aside className="diagnostics-guidance" aria-label="About network diagnostics">
        <strong>Read-only host checks.</strong> These results come from the machine running the backend, not automatically from the computer viewing this page. Start with Interfaces or Routes; choose Connectivity, Traceroute, Discovery, or Capture only when you understand their scope and environment requirements.
      </aside>

      <div className="tab-navigation" role="tablist" aria-label="Network data tabs">
        <button
          role="tab"
          aria-selected={activeTab === 'all'}
          onClick={() => handleTabChange('all')}
          className={`tab-button ${activeTab === 'all' ? 'active' : ''}`}
        >
          All
        </button>
        <button
          role="tab"
          aria-selected={activeTab === 'interfaces'}
          onClick={() => handleTabChange('interfaces')}
          className={`tab-button ${activeTab === 'interfaces' ? 'active' : ''}`}
        >
          Interfaces
        </button>
        <button
          role="tab"
          aria-selected={activeTab === 'routes'}
          onClick={() => handleTabChange('routes')}
          className={`tab-button ${activeTab === 'routes' ? 'active' : ''}`}
        >
          Routes
        </button>
        <button
          role="tab"
          aria-selected={activeTab === 'neighbors'}
          onClick={() => handleTabChange('neighbors')}
          className={`tab-button ${activeTab === 'neighbors' ? 'active' : ''}`}
        >
          Neighbors
        </button>
        <button
          role="tab"
          aria-selected={activeTab === 'dns'}
          onClick={() => handleTabChange('dns')}
          className={`tab-button ${activeTab === 'dns' ? 'active' : ''}`}
        >
          DNS
        </button>
        <button
          role="tab"
          aria-selected={activeTab === 'connectivity'}
          onClick={() => handleTabChange('connectivity')}
          className={`tab-button ${activeTab === 'connectivity' ? 'active' : ''}`}
        >
          Connectivity
        </button>
        <button
          role="tab"
          aria-selected={activeTab === 'traceroute'}
          onClick={() => handleTabChange('traceroute')}
          className={`tab-button ${activeTab === 'traceroute' ? 'active' : ''}`}
        >
          Traceroute
        </button>
        <button
          role="tab"
          aria-selected={activeTab === 'discovery'}
          onClick={() => handleTabChange('discovery')}
          className={`tab-button ${activeTab === 'discovery' ? 'active' : ''}`}
        >
          Discovery
        </button>
        <button
          role="tab"
          aria-selected={activeTab === 'capture'}
          onClick={() => handleTabChange('capture')}
          className={`tab-button ${activeTab === 'capture' ? 'active' : ''}`}
        >
          Capture file
        </button>
      </div>

      <div className="tab-panels" role="tabpanel">
        {activeTab === 'all' && (
          <>
            <section className="diagnostics-section">
              <div className="section-header">
                <h3>Interfaces</h3>
                <button
                  className="btn btn-sm btn-secondary"
                  onClick={() => handleTabChange('interfaces')}
                  disabled={loading.interfaces}
                >
                  View Details
                </button>
              </div>
              <NetworkInterfaces
                data={interfacesData}
                loading={loading.interfaces}
                error={error.interfaces}
              />
            </section>

            <section className="diagnostics-section">
              <div className="section-header">
                <h3>Routes</h3>
                <button
                  className="btn btn-sm btn-secondary"
                  onClick={() => handleTabChange('routes')}
                  disabled={loading.routes}
                >
                  View Details
                </button>
              </div>
              <NetworkRoutes
                data={routesData}
                loading={loading.routes}
                error={error.routes}
              />
            </section>

            <section className="diagnostics-section">
              <div className="section-header">
                <h3>Neighbors</h3>
                <button
                  className="btn btn-sm btn-secondary"
                  onClick={() => handleTabChange('neighbors')}
                  disabled={loading.neighbors}
                >
                  View Details
                </button>
              </div>
              <NetworkNeighbors
                data={neighborsData}
                loading={loading.neighbors}
                error={error.neighbors}
              />
            </section>

            {/* The kernel keeps the IPv6 tables apart from the IPv4 ones.
                Both are shown, because a machine can route on one family
                and not the other. */}
            {routesDataV6?.success && (
              <section className="diagnostics-section">
                <div className="section-header">
                  <h3>
                    Routes <span className="family-tag ipv6">IPv6</span>
                  </h3>
                  <button
                    className="btn btn-sm btn-secondary"
                    onClick={() => {
                      setFamily('ipv6');
                      handleTabChange('routes');
                    }}
                    disabled={loading.routes}
                  >
                    View Details
                  </button>
                </div>
                <NetworkRoutes
                  data={routesDataV6}
                  loading={loading.routes}
                  error={error.routes}
                />
              </section>
            )}

            {neighborsDataV6?.success && (
              <section className="diagnostics-section">
                <div className="section-header">
                  <h3>
                    Neighbors <span className="family-tag ipv6">IPv6</span>
                  </h3>
                  <button
                    className="btn btn-sm btn-secondary"
                    onClick={() => {
                      setFamily('ipv6');
                      handleTabChange('neighbors');
                    }}
                    disabled={loading.neighbors}
                  >
                    View Details
                  </button>
                </div>
                <NetworkNeighbors
                  data={neighborsDataV6}
                  loading={loading.neighbors}
                  error={error.neighbors}
                />
              </section>
            )}
          </>
        )}

        {activeTab === 'interfaces' && (
          <NetworkInterfaces
            data={interfacesData}
            loading={loading.interfaces}
            error={error.interfaces}
          />
        )}

        {activeTab === 'routes' && (
          <>
            <FamilySwitch
              family={family}
              onChange={setFamily}
              v4Available={routesData?.success ?? false}
              v6Available={routesDataV6?.success ?? false}
            />
            <NetworkRoutes
              data={family === 'ipv4' ? routesData : routesDataV6}
              loading={loading.routes}
              error={error.routes}
            />
          </>
        )}

        {activeTab === 'neighbors' && (
          <>
            <FamilySwitch
              family={family}
              onChange={setFamily}
              v4Available={neighborsData?.success ?? false}
              v6Available={neighborsDataV6?.success ?? false}
            />
            <NetworkNeighbors
              data={family === 'ipv4' ? neighborsData : neighborsDataV6}
              loading={loading.neighbors}
              error={error.neighbors}
            />
          </>
        )}

        {activeTab === 'dns' && (
          <div className="diagnostics-section">
            <div className="section-header">
              <h3>DNS Resolution</h3>
              <button
                className="btn btn-sm btn-secondary"
                onClick={() => handleTabChange('dns')}
                disabled={loading.dns}
              >
                View Details
              </button>
            </div>
            <div style={{ padding: '20px' }}>
              <ConnectivityPanel initialTab="dns" />
            </div>
          </div>
        )}

        {activeTab === 'connectivity' && (
          <div className="diagnostics-section">
            <div className="section-header">
              <h3>Connectivity Check</h3>
              <button
                className="btn btn-sm btn-secondary"
                onClick={() => handleTabChange('connectivity')}
                disabled={loading.connectivity}
              >
                View Details
              </button>
            </div>
            <div style={{ padding: '20px' }}>
              <ConnectivityPanel initialTab="connectivity" />
            </div>
          </div>
        )}

        {activeTab === 'discovery' && (
          <div className="diagnostics-section">
            <div className="section-header">
              <h3>Host Discovery</h3>
            </div>
            <div style={{ padding: '20px' }}>
              <DiscoveryPanel localAddress={localAddress} />
            </div>
          </div>
        )}

        {activeTab === 'traceroute' && (
          <div className="diagnostics-section">
            <div className="section-header">
              <h3>Traceroute</h3>
              <button
                className="btn btn-sm btn-secondary"
                onClick={() => handleTabChange('traceroute')}
                disabled={loading.traceroute}
              >
                View Details
              </button>
            </div>
            <div style={{ padding: '20px' }}>
              <ConnectivityPanel initialTab="traceroute" />
            </div>
          </div>
        )}

        {activeTab === 'capture' && (
          <div className="diagnostics-section">
            <div className="section-header">
              <h3>Capture File Analysis</h3>
            </div>
            <div style={{ padding: '20px' }}>
              <PCAPPanel />
            </div>
          </div>
        )}

        {Object.values(error).some(e => e) && (
          <div className="error-banner" role="alert">
            <span aria-hidden="true">⚠</span>
            Some data failed to load. Check individual tabs for details.
          </div>
        )}
      </div>
    </div>
  );
}
