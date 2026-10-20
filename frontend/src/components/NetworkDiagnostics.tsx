import { useEffect, useState } from 'react';
import {
  fetchInterfaces,
  fetchNetworkRoutes,
  fetchNeighbors,
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
import './NetworkDiagnostics.css';

type TabType = 'all' | 'interfaces' | 'routes' | 'neighbors' | 'dns' | 'connectivity' | 'traceroute';

export default function NetworkDiagnostics() {
  const [activeTab, setActiveTab] = useState<TabType>('all');
  const [interfacesData, setInterfacesData] = useState<InterfacesResult | null>(null);
  const [routesData, setRoutesData] = useState<RoutesResult | null>(null);
  const [neighborsData, setNeighborsData] = useState<NeighborsResult | null>(null);
  const [loading, setLoading] = useState<Record<string, boolean>>({
    all: false,
    interfaces: false,
    routes: false,
    neighbors: false,
    dns: false,
    connectivity: false,
    traceroute: false,
  });
  const [error, setError] = useState<Record<string, string | null>>({
    all: null,
    interfaces: null,
    routes: null,
    neighbors: null,
    dns: null,
    connectivity: null,
    traceroute: null,
  });
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);

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
          <NetworkRoutes
            data={routesData}
            loading={loading.routes}
            error={error.routes}
          />
        )}

        {activeTab === 'neighbors' && (
          <NetworkNeighbors
            data={neighborsData}
            loading={loading.neighbors}
            error={error.neighbors}
          />
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
              <ConnectivityPanel />
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
              <ConnectivityPanel />
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
              <ConnectivityPanel />
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
