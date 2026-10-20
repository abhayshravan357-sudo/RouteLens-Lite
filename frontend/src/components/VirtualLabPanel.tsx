/**
 * VirtualLabPanel
 *
 * Shows the isolated Linux lab exactly as the backend reports it: whether
 * the namespaces are up, the addresses and interfaces the router actually
 * has, and the routing table the lab actually holds.
 *
 * Nothing here is drawn from a template. If the lab is unavailable, the
 * panel says so and explains why.
 */

import type { LabStatusResponse, LabState } from '../types/routing';
import './VirtualLabPanel.css';

interface VirtualLabPanelProps {
  status: LabStatusResponse | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}

const STATE_LABELS: Record<LabState, string> = {
  idle: 'Idle',
  ready: 'Ready',
  simulating: 'Simulating',
  transmitting: 'Transmitting',
  capturing: 'Capturing',
  verifying: 'Verifying',
  completed: 'Completed',
  error: 'Failed',
  timeout: 'Timed out',
  unavailable: 'Unavailable',
};

const STATE_TONE: Record<LabState, string> = {
  idle: 'neutral',
  ready: 'success',
  simulating: 'info',
  transmitting: 'info',
  capturing: 'info',
  verifying: 'info',
  completed: 'success',
  error: 'error',
  timeout: 'warning',
  unavailable: 'error',
};

export default function VirtualLabPanel({
  status,
  loading,
  error,
  onRetry,
}: VirtualLabPanelProps) {
  if (loading && !status) {
    return (
      <div className="loading">
        <span className="spinner" aria-hidden="true" />
        Asking the lab whether it is ready…
      </div>
    );
  }

  if (error) {
    return (
      <div className="error-message" role="alert">
        <span aria-hidden="true">⚠</span>
        <span>{error}</span>
        <button type="button" className="btn btn-secondary btn-sm" onClick={onRetry}>
          Try again
        </button>
      </div>
    );
  }

  if (!status) {
    return (
      <div className="empty-state">
        <p>The lab has not been checked yet.</p>
        <button type="button" className="btn btn-secondary btn-sm" onClick={onRetry}>
          Check the lab
        </button>
      </div>
    );
  }

  const info = status.router_info;
  const available = status.available;

  return (
    <div className="virtual-lab">
      <div className="lab-state-row">
        <span className={`status-badge ${STATE_TONE[status.state] ?? 'neutral'}`}>
          <span className="dot" aria-hidden="true" />
          {STATE_LABELS[status.state] ?? status.state}
        </span>
        <p className="lab-state-message">{status.message}</p>
      </div>

      {!available && (
        <div className="error-message" role="status">
          <span aria-hidden="true">⚠</span>
          <span>
            The namespaces could not be reached, so nothing below is a live
            reading. The topology shown is the one the lab is configured with.
            {status.error ? ` The backend reported: ${status.error}.` : ''}
          </span>
        </div>
      )}

      {/* The lab topology, drawn from the router's own interfaces. */}
      <div
        className={`lab-topology ${available ? 'lab-topology-live' : ''}`}
        aria-label="Client, router and server topology"
      >
        <div className="lab-node client">
          <span className="lab-node-icon" aria-hidden="true">
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
              <rect x="2.5" y="4" width="19" height="12.5" rx="1.5" />
              <path d="M8 20h8M12 16.5V20" />
            </svg>
          </span>
          <span className="lab-node-label">Client</span>
          <span className="lab-node-detail">
            namespace <code>rl260-client</code>
          </span>
          <span className="lab-node-address">
            {info?.client_ip ?? <em className="lab-unknown">address not read</em>}
          </span>
        </div>

        <div className="lab-link" aria-hidden="true">
          <span className="lab-link-track">
            <span className="lab-link-line" />
            <span className="lab-link-label">192.168.10.0/24</span>
            <span className="lab-link-line" />
          </span>
          <span className="lab-link-ports">
            <span>rlc0</span>
            <span className="lab-link-arrow">↔</span>
            <span>rlr0c</span>
          </span>
        </div>

        <div className="lab-node router">
          <span className="lab-node-icon" aria-hidden="true">
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 2.5 20.5 7v10L12 21.5 3.5 17V7L12 2.5Z" />
              <path d="M12 7.5v4M12 11.5 9.5 14M12 11.5 14.5 14" />
            </svg>
          </span>
          <span className="lab-node-label">Virtual Router</span>
          <span className="lab-node-detail">
            namespace <code>rl260-router</code>
          </span>
          <span className="lab-node-address">
            {info?.interfaces?.length ? (
              info.interfaces.join(' · ')
            ) : (
              <em className="lab-unknown">interfaces not read</em>
            )}
          </span>
        </div>

        <div className="lab-link" aria-hidden="true">
          <span className="lab-link-track">
            <span className="lab-link-line" />
            <span className="lab-link-label">192.168.20.0/24</span>
            <span className="lab-link-line" />
          </span>
          <span className="lab-link-ports">
            <span>rlr0s</span>
            <span className="lab-link-arrow">↔</span>
            <span>rls0</span>
          </span>
        </div>

        <div className="lab-node server">
          <span className="lab-node-icon" aria-hidden="true">
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3.5" width="18" height="7" rx="1.5" />
              <rect x="3" y="13.5" width="18" height="7" rx="1.5" />
              <path d="M7 7h.01M7 17h.01" />
            </svg>
          </span>
          <span className="lab-node-label">Server</span>
          <span className="lab-node-detail">
            namespace <code>rl260-server</code>
          </span>
          <span className="lab-node-address">
            {info?.server_ip ?? <em className="lab-unknown">address not read</em>}
          </span>
        </div>
      </div>

      <p className="lab-subnets">
        Client side <code>192.168.10.0/24</code> · Server side{' '}
        <code>192.168.20.0/24</code>
      </p>

      {/* What the router actually holds, when it could be read. */}
      {info && info.routing_table.length > 0 && (
        <div className="lab-routing">
          <h3 className="panel-title">Router's own routing table</h3>
          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Destination</th>
                  <th scope="col">Next hop</th>
                  <th scope="col">Interface</th>
                </tr>
              </thead>
              <tbody>
                {info.routing_table.map((route, i) => (
                  <tr key={`${route.destination}-${route.interface}-${i}`}>
                    <td className="mono">{route.destination}</td>
                    <td className="mono">{route.next_hop ?? '—'}</td>
                    <td className="mono">{route.interface || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {info && info.routing_table.length === 0 && available && (
        <p className="lab-muted">
          The router was reachable but reported no routes. That is a real
          reading, not a missing one.
        </p>
      )}

      <div className="lab-note">
        <strong>How this lab differs from the routing table.</strong> The
        routing table in the analyser is a teaching sample using networks such
        as 192.168.1.0/24. The lab is a real, isolated set of Linux network
        namespaces on 192.168.10.0/24 and 192.168.20.0/24. A packet traced in
        one does not travel in the other.
      </div>
    </div>
  );
}
