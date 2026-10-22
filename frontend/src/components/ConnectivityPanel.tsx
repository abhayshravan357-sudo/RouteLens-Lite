import { useState } from 'react';
import {
  resolveDns,
  checkConnectivity,
  runTraceroute,
} from '../api/routing';
import type {
  DnsResolveResponse,
  ConnectivityCheckResponse,
  TracerouteResponse,
  ConnectivityCheckRequest,
} from '../types/routing';
import './ConnectivityPanel.css';

type TabType = 'dns' | 'connectivity' | 'traceroute';

interface DnsFormState {
  hostname: string;
  timeout: number;
  ipv6: boolean;
}

interface ConnectivityFormState {
  target: string;
  port: string;
  protocol: 'icmp' | 'tcp';
  timeout: number;
  count: number;
  interval: number;
}

interface TracerouteFormState {
  target: string;
  max_hops: number;
  timeout_per_hop: number;
  probes_per_hop: number;
  overall_timeout: number;
}

export default function ConnectivityPanel() {
  const [activeTab, setActiveTab] = useState<TabType>('dns');
  
  const [dnsForm, setDnsForm] = useState<DnsFormState>({
    hostname: 'google.com',
    timeout: 5,
    ipv6: false,
  });
  const [dnsResult, setDnsResult] = useState<DnsResolveResponse | null>(null);
  const [dnsLoading, setDnsLoading] = useState(false);
  const [dnsError, setDnsError] = useState<string | null>(null);

  const [connForm, setConnForm] = useState<ConnectivityFormState>({
    target: '8.8.8.8',
    port: '',
    protocol: 'icmp',
    timeout: 5,
    count: 3,
    interval: 0.2,
  });
  const [connResult, setConnResult] = useState<ConnectivityCheckResponse | null>(null);
  const [connLoading, setConnLoading] = useState(false);
  const [connError, setConnError] = useState<string | null>(null);

  const [traceForm, setTraceForm] = useState<TracerouteFormState>({
    target: '8.8.8.8',
    max_hops: 30,
    timeout_per_hop: 2,
    probes_per_hop: 1,
    overall_timeout: 60,
  });
  const [traceResult, setTraceResult] = useState<TracerouteResponse | null>(null);
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceError, setTraceError] = useState<string | null>(null);

  const handleDnsSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setDnsLoading(true);
    setDnsResult(null);
    setDnsError(null);
    try {
      const result = await resolveDns(dnsForm);
      setDnsResult(result);
    } catch (err) {
      setDnsError(err instanceof Error ? err.message : 'DNS resolution failed');
    } finally {
      setDnsLoading(false);
    }
  };

  const handleConnSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setConnLoading(true);
    setConnResult(null);
    setConnError(null);
    try {
      const request: ConnectivityCheckRequest = {
        target: connForm.target,
        port: connForm.protocol === 'tcp' ? parseInt(connForm.port, 10) : undefined,
        protocol: connForm.protocol,
        timeout: connForm.timeout,
        count: connForm.count,
        interval: connForm.interval,
      };
      const result = await checkConnectivity(request);
      setConnResult(result);
    } catch (err) {
      setConnError(err instanceof Error ? err.message : 'Connectivity check failed');
    } finally {
      setConnLoading(false);
    }
  };

  const handleTraceSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setTraceLoading(true);
    setTraceResult(null);
    setTraceError(null);
    try {
      const result = await runTraceroute(traceForm);
      setTraceResult(result);
    } catch (err) {
      setTraceError(err instanceof Error ? err.message : 'Traceroute failed');
    } finally {
      setTraceLoading(false);
    }
  };

  return (
    <div className="connectivity-panel">
      <div className="panel-header">
        <h2>Network Diagnostics</h2>
        <p className="panel-description">
          Real-time network connectivity testing. All operations run from the backend server.
        </p>
      </div>

      <div className="tab-navigation" role="tablist" aria-label="Diagnostic tools">
        <button
          role="tab"
          aria-selected={activeTab === 'dns'}
          onClick={() => setActiveTab('dns')}
          className={`tab-button ${activeTab === 'dns' ? 'active' : ''}`}
        >
          DNS Resolution
        </button>
        <button
          role="tab"
          aria-selected={activeTab === 'connectivity'}
          onClick={() => setActiveTab('connectivity')}
          className={`tab-button ${activeTab === 'connectivity' ? 'active' : ''}`}
        >
          Connectivity Check
        </button>
        <button
          role="tab"
          aria-selected={activeTab === 'traceroute'}
          onClick={() => setActiveTab('traceroute')}
          className={`tab-button ${activeTab === 'traceroute' ? 'active' : ''}`}
        >
          Traceroute
        </button>
      </div>

      <div className="tab-panels" role="tabpanel">
        {activeTab === 'dns' && (
          <div className="tab-panel">
            <form onSubmit={handleDnsSubmit} className="diagnostic-form">
              <div className="form-row">
                <div className="form-group">
                  <label htmlFor="dns-hostname">Hostname</label>
                  <input
                    id="dns-hostname"
                    type="text"
                    value={dnsForm.hostname}
                    onChange={(e) => setDnsForm({ ...dnsForm, hostname: e.target.value })}
                    placeholder="e.g., google.com"
                    required
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="dns-timeout">Timeout (seconds)</label>
                  <input
                    id="dns-timeout"
                    type="number"
                    value={dnsForm.timeout}
                    onChange={(e) => setDnsForm({ ...dnsForm, timeout: parseFloat(e.target.value) || 5 })}
                    min="0.5"
                    max="30"
                    step="0.5"
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="dns-ipv6">Include IPv6</label>
                  <label className="checkbox-label">
                    <input
                      id="dns-ipv6"
                      type="checkbox"
                      checked={dnsForm.ipv6}
                      onChange={(e) => setDnsForm({ ...dnsForm, ipv6: e.target.checked })}
                    />
                    <span>Resolve IPv6 (AAAA) records</span>
                  </label>
                </div>
              </div>
              <button
                type="submit"
                className="btn btn-primary"
                disabled={dnsLoading || !dnsForm.hostname.trim()}
              >
                {dnsLoading ? 'Resolving...' : 'Resolve'}
              </button>
            </form>

            {dnsError && (
              <div className="error-message" role="alert">
                <span aria-hidden="true">⚠</span>
                {dnsError}
              </div>
            )}

            {dnsResult && (
              <div className="result-card">
                <div className="result-header">
                  <span className={`result-status ${dnsResult.error ? 'error' : 'success'}`}>
                    {dnsResult.error ? 'Failed' : 'Resolved'}
                  </span>
                  <span className="result-hostname">{dnsResult.hostname}</span>
                </div>
                <div className="result-meta">
                  <span>Latency: {dnsResult.latency_ms.toFixed(2)}ms</span>
                </div>
                {dnsResult.error && (
                  <div className="result-error">{dnsResult.error}</div>
                )}
                {(dnsResult.addresses.length > 0) && (
                  <div className="address-list">
                    <h4>Resolved Addresses</h4>
                    <ul>
                      {dnsResult.addresses.map((record, i) => (
                        <li key={i} className={record.type === 'A' ? 'ipv4' : 'ipv6'}>
                          {record.address} ({record.type}){record.ttl !== undefined ? ` TTL: ${record.ttl}` : ''}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {activeTab === 'connectivity' && (
          <div className="tab-panel">
            <form onSubmit={handleConnSubmit} className="diagnostic-form">
              <div className="form-row">
                <div className="form-group">
                  <label htmlFor="conn-target">Target</label>
                  <input
                    id="conn-target"
                    type="text"
                    value={connForm.target}
                    onChange={(e) => setConnForm({ ...connForm, target: e.target.value })}
                    placeholder="e.g., 8.8.8.8 or google.com"
                    required
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="conn-protocol">Protocol</label>
                  <select
                    id="conn-protocol"
                    value={connForm.protocol}
                    onChange={(e) => setConnForm({ ...connForm, protocol: e.target.value as 'icmp' | 'tcp' })}
                  >
                    <option value="icmp">ICMP (Ping)</option>
                    <option value="tcp">TCP Connect</option>
                  </select>
                </div>
              </div>
              <div className="form-row">
                <div className="form-group">
                  <label htmlFor="conn-port">Port (TCP only)</label>
                  <input
                    id="conn-port"
                    type="number"
                    value={connForm.port}
                    onChange={(e) => setConnForm({ ...connForm, port: e.target.value })}
                    min="1"
                    max="65535"
                    disabled={connForm.protocol === 'icmp'}
                    placeholder="e.g., 443"
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="conn-timeout">Timeout (seconds)</label>
                  <input
                    id="conn-timeout"
                    type="number"
                    value={connForm.timeout}
                    onChange={(e) => setConnForm({ ...connForm, timeout: parseFloat(e.target.value) || 5 })}
                    min="0.5"
                    max="30"
                    step="0.5"
                  />
                </div>
              </div>
              <div className="form-row">
                <div className="form-group">
                  <label htmlFor="conn-count">Count</label>
                  <input
                    id="conn-count"
                    type="number"
                    value={connForm.count}
                    onChange={(e) => setConnForm({ ...connForm, count: parseInt(e.target.value, 10) || 3 })}
                    min="1"
                    max="10"
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="conn-interval">Interval (seconds)</label>
                  <input
                    id="conn-interval"
                    type="number"
                    value={connForm.interval}
                    onChange={(e) => setConnForm({ ...connForm, interval: parseFloat(e.target.value) || 0.2 })}
                    min="0.1"
                    max="5"
                    step="0.1"
                  />
                </div>
              </div>
              <button
                type="submit"
                className="btn btn-primary"
                disabled={connLoading || !connForm.target.trim() || (connForm.protocol === 'tcp' && !connForm.port)}
              >
                {connLoading ? 'Checking...' : 'Check Connectivity'}
              </button>
            </form>

            {connError && (
              <div className="error-message" role="alert">
                <span aria-hidden="true">⚠</span>
                {connError}
              </div>
            )}

            {connResult && (
              <div className="result-card">
                <div className="result-header">
                  <span className={`result-status ${connResult.reachable ? 'success' : 'error'}`}>
                    {connResult.reachable ? 'Reachable' : 'Unreachable'}
                  </span>
                  <span className="result-target">
                    {connResult.target}{connResult.port ? `:${connResult.port}` : ''} ({connResult.protocol.toUpperCase()})
                  </span>
                </div>
                <div className="result-meta">
                  {connResult.latency_ms !== null && (
                    <span>Latency: {connResult.latency_ms.toFixed(2)}ms</span>
                  )}
                  {connResult.packets_sent !== undefined && (
                    <span>Sent: {connResult.packets_sent} | Received: {connResult.packets_received} | Loss: {connResult.packet_loss_percent?.toFixed(1)}%</span>
                  )}
                  {connResult.rtt_avg_ms !== undefined && (
                    <span>RTT min/avg/max/mdev: {connResult.rtt_min_ms?.toFixed(2)}/{connResult.rtt_avg_ms?.toFixed(2)}/{connResult.rtt_max_ms?.toFixed(2)}/{connResult.rtt_mdev_ms?.toFixed(2)} ms</span>
                  )}
                </div>
                {connResult.error && (
                  <div className="result-error">{connResult.error}</div>
                )}
              </div>
            )}
          </div>
        )}

        {activeTab === 'traceroute' && (
          <div className="tab-panel">
            <form onSubmit={handleTraceSubmit} className="diagnostic-form">
              <div className="form-row">
                <div className="form-group">
                  <label htmlFor="trace-target">Target</label>
                  <input
                    id="trace-target"
                    type="text"
                    value={traceForm.target}
                    onChange={(e) => setTraceForm({ ...traceForm, target: e.target.value })}
                    placeholder="e.g., 8.8.8.8 or google.com"
                    required
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="trace-max-hops">Max Hops</label>
                  <input
                    id="trace-max-hops"
                    type="number"
                    value={traceForm.max_hops}
                    onChange={(e) => setTraceForm({ ...traceForm, max_hops: parseInt(e.target.value, 10) || 30 })}
                    min="1"
                    max="64"
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="trace-timeout-per-hop">Per-hop Timeout (seconds)</label>
                  <input
                    id="trace-timeout-per-hop"
                    type="number"
                    value={traceForm.timeout_per_hop}
                    onChange={(e) => setTraceForm({ ...traceForm, timeout_per_hop: parseFloat(e.target.value) || 2 })}
                    min="0.5"
                    max="10"
                    step="0.5"
                  />
                </div>
              </div>
              <div className="form-row">
                <div className="form-group">
                  <label htmlFor="trace-probes">Probes per Hop</label>
                  <input
                    id="trace-probes"
                    type="number"
                    value={traceForm.probes_per_hop}
                    onChange={(e) => setTraceForm({ ...traceForm, probes_per_hop: parseInt(e.target.value, 10) || 1 })}
                    min="1"
                    max="3"
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="trace-overall-timeout">Overall Timeout (seconds)</label>
                  <input
                    id="trace-overall-timeout"
                    type="number"
                    value={traceForm.overall_timeout}
                    onChange={(e) => setTraceForm({ ...traceForm, overall_timeout: parseFloat(e.target.value) || 60 })}
                    min="5"
                    max="300"
                    step="5"
                  />
                </div>
              </div>
              <button
                type="submit"
                className="btn btn-primary"
                disabled={traceLoading || !traceForm.target.trim()}
              >
                {traceLoading ? 'Tracing...' : 'Run Traceroute'}
              </button>
            </form>

            {traceError && (
              <div className="error-message" role="alert">
                <span aria-hidden="true">⚠</span>
                {traceError}
              </div>
            )}

            {traceResult && (
              <div className="result-card">
                <div className="result-header">
                  <span className={`result-status ${traceResult.error ? 'warning' : 'success'}`}>
                    {traceResult.error ? 'Partial' : 'Complete'}
                  </span>
                  <span className="result-target">{traceResult.target}</span>
                </div>
                <div className="result-meta">
                  <span>Max Hops: {traceResult.max_hops}</span>
                  <span>Timeout/Hop: {traceResult.timeout_per_hop}s</span>
                  <span>Probes/Hop: {traceResult.probes_per_hop}</span>
                  <span>Hops Found: {traceResult.hops.length}</span>
                  <span>Total Time: {traceResult.total_time_ms.toFixed(0)}ms</span>
                </div>
                {traceResult.error && (
                  <div className="result-error">{traceResult.error}</div>
                )}
                {traceResult.hops.length > 0 && (
                  <div className="traceroute-hops">
                    <table className="hops-table">
                      <thead>
                        <tr>
                          <th scope="col">TTL</th>
                          <th scope="col">Address</th>
                          <th scope="col">Hostname</th>
                          <th scope="col">RTT</th>
                          <th scope="col">Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {traceResult.hops.map((hop, index) => (
                          <tr key={index}>
                            <td className="cell-ttl">{hop.ttl}</td>
                            <td className="cell-address">
                              {hop.address || (
                                <span className="timeout">*</span>
                              )}
                            </td>
                            <td className="cell-hostname">{hop.hostname || '-'}</td>
                            <td className="cell-rtt">
                              {hop.rtt_ms !== null ? `${hop.rtt_ms.toFixed(2)} ms` : '-'}
                            </td>
                            <td>
                              {hop.error ? (
                                <span className="hop-error">{hop.error}</span>
                              ) : (
                                <span className="hop-ok">OK</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <p className="traceroute-note">
                      <em>Note: Only shows responding Layer 3 hops (routers that send ICMP TTL Exceeded). 
                      Does not reveal physical topology, switches, or silent devices.</em>
                    </p>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
