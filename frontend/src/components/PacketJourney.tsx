import type { RoutingEntry, LabState, PacketDetails } from '../types/routing';

interface PacketJourneyProps {
  route: RoutingEntry;
  labState: LabState;
  labError: string | null;
  onSimulate: () => void;
  disabled: boolean;
}

const STATE_LABELS: Record<LabState, string> = {
  idle: 'Ready to Simulate',
  ready: 'Lab Ready',
  simulating: 'Simulating Decision…',
  transmitting: 'Transmitting Packet…',
  capturing: 'Capturing Response…',
  verifying: 'Verifying Capture…',
  completed: 'Simulation Complete',
  error: 'Simulation Error',
  timeout: 'Simulation Timeout',
  unavailable: 'Lab Unavailable',
};

const STATE_DESCRIPTIONS: Record<LabState, string> = {
  idle: 'Click "Simulate Packet" to begin the packet journey visualization.',
  ready: 'Packet lab is ready. Preparing to transmit test packet.',
  simulating: 'Applying longest-prefix match to determine forwarding decision.',
  transmitting: 'Sending packet through virtual router to next hop.',
  capturing: 'Waiting for response capture from simulated destination.',
  verifying: 'Comparing captured packet with expected forwarding behavior.',
  completed: 'Packet journey completed successfully. Capture verified.',
  error: 'An error occurred during simulation.',
  timeout: 'Simulation timed out. The lab may be overloaded.',
  unavailable: 'Packet lab service is currently unavailable.',
};

const STATE_ICONS: Record<LabState, string> = {
  idle: '▶',
  ready: '✓',
  simulating: '⟳',
  transmitting: '↑',
  capturing: '↓',
  verifying: '⟳',
  completed: '✓',
  error: '✕',
  timeout: '⏱',
  unavailable: '⚠',
};

const ACTIVE_STATES: LabState[] = ['simulating', 'transmitting', 'capturing', 'verifying'];

function getProgress(state: LabState): number {
  const states: LabState[] = ['ready', 'simulating', 'transmitting', 'capturing', 'verifying'];
  const index = states.indexOf(state);
  if (index === -1) return 0;
  return ((index + 1) / states.length) * 100;
}

export default function PacketJourney({
  route,
  labState,
  labError,
  onSimulate,
  disabled,
}: PacketJourneyProps) {
  const isActive = ACTIVE_STATES.includes(labState);
  const isTerminal = ['completed', 'error', 'timeout', 'unavailable'].includes(labState);
  const progress = getProgress(labState);

  // Sample packet details based on the selected route (placeholder for real API data)
  const packetDetails: PacketDetails = {
    source_ip: '192.168.1.100',
    destination_ip: route.destination.split('/')[0].replace(/\.\d+$/, '.50'),
    protocol: 'icmp',
    ttl: 64,
    length: 84,
    forwarding_info: {
      ingress_interface: 'eth0',
      egress_interface: route.next_hop_type === 'direct' ? route.interface : null,
      next_hop: route.next_hop,
      route_matched: route.destination,
      action: route.next_hop_type === 'direct' ? 'forward' : 'forward',
    },
  };

  return (
    <div className="packet-journey">
      {/* State Progress Indicator */}
      <div className="journey-state" role="status" aria-live="polite">
        <div className="state-header">
          <span className="state-icon" aria-hidden="true">{STATE_ICONS[labState]}</span>
          <div className="state-info">
            <span className="state-label">{STATE_LABELS[labState]}</span>
            <span className="state-description">{STATE_DESCRIPTIONS[labState]}</span>
          </div>
        </div>
        {isActive && (
          <div className="progress-bar" role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}>
            <div className="progress-fill" style={{ width: `${progress}%` }} />
          </div>
        )}
        {labError && (
          <div className="error-message" role="alert">
            <span aria-hidden="true">⚠</span>
            {labError}
          </div>
        )}
      </div>

      {/* Action Button */}
      <div className="journey-actions">
        {!isActive && !isTerminal && (
          <button
            type="button"
            className="btn btn-primary"
            onClick={onSimulate}
            disabled={disabled}
            aria-busy={false}
          >
            Simulate Packet
          </button>
        )}
        {isTerminal && labState !== 'completed' && (
          <button
            type="button"
            className="btn btn-secondary"
            onClick={onSimulate}
            disabled={disabled}
          >
            Try Again
          </button>
        )}
        {labState === 'completed' && (
          <button
            type="button"
            className="btn btn-secondary"
            onClick={onSimulate}
          >
            Simulate Another Packet
          </button>
        )}
      </div>

      {/* Packet Details Panel */}
      <div className="packet-details-panel">
        <h3 className="panel-title">Packet Details</h3>
        <div className="details-grid">
          <div className="detail-row">
            <span className="detail-label">Source IP</span>
            <span className="detail-value">{packetDetails.source_ip}</span>
          </div>
          <div className="detail-row">
            <span className="detail-label">Destination IP</span>
            <span className="detail-value">{packetDetails.destination_ip}</span>
          </div>
          <div className="detail-row">
            <span className="detail-label">Protocol</span>
            <span className="detail-value">{packetDetails.protocol.toUpperCase()}</span>
          </div>
          <div className="detail-row">
            <span className="detail-label">TTL</span>
            <span className="detail-value">{packetDetails.ttl}</span>
          </div>
          <div className="detail-row">
            <span className="detail-label">Length</span>
            <span className="detail-value">{packetDetails.length} bytes</span>
          </div>
        </div>
      </div>

      {/* Forwarding Information Panel */}
      {packetDetails.forwarding_info && (
        <div className="packet-details-panel">
          <h3 className="panel-title">Forwarding Decision</h3>
          <div className="details-grid">
            <div className="detail-row">
              <span className="detail-label">Ingress Interface</span>
              <span className="detail-value">{packetDetails.forwarding_info.ingress_interface}</span>
            </div>
            {packetDetails.forwarding_info.egress_interface && (
              <div className="detail-row">
                <span className="detail-label">Egress Interface</span>
                <span className="detail-value">{packetDetails.forwarding_info.egress_interface}</span>
              </div>
            )}
            {packetDetails.forwarding_info.next_hop && (
              <div className="detail-row">
                <span className="detail-label">Next Hop</span>
                <span className="detail-value">{packetDetails.forwarding_info.next_hop}</span>
              </div>
            )}
            <div className="detail-row">
              <span className="detail-label">Route Matched</span>
              <span className="detail-value">{packetDetails.forwarding_info.route_matched}</span>
            </div>
            <div className="detail-row">
              <span className="detail-label">Action</span>
              <span className={`detail-value ${packetDetails.forwarding_info.action}`}>
                {packetDetails.forwarding_info.action}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Network Topology Visualization */}
      <div className="journey-topology">
        <h3 className="panel-title">Network Topology</h3>
        <div className="topology">
          <div className="topology-node client">
            <div className="node-icon" aria-hidden="true">💻</div>
            <div className="node-label">Client</div>
            <div className="node-ip">{packetDetails.source_ip}</div>
          </div>

          <div className="topology-link" aria-hidden="true">
            <span className="link-arrow">→</span>
            {isActive && labState !== 'ready' && <span className="link-pulse" aria-hidden="true" />}
          </div>

          <div className="topology-node router">
            <div className="node-icon" aria-hidden="true">🔀</div>
            <div className="node-label">Virtual Router</div>
            <div className="node-interface">{route.interface}</div>
          </div>

          {route.next_hop && (
            <>
              <div className="topology-link" aria-hidden="true">
                <span className="link-arrow">→</span>
                {isActive && ['transmitting', 'capturing'].includes(labState) && (
                  <span className="link-pulse" aria-hidden="true" />
                )}
              </div>
              <div className="topology-node next-hop">
                <div className="node-icon" aria-hidden="true">🌐</div>
                <div className="node-label">Next Hop</div>
                <div className="node-ip">{route.next_hop}</div>
              </div>
            </>
          )}

          {route.next_hop_type === 'direct' && (
            <>
              <div className="topology-link" aria-hidden="true">
                <span className="link-arrow">→</span>
                {isActive && ['transmitting', 'capturing'].includes(labState) && (
                  <span className="link-pulse" aria-hidden="true" />
                )}
              </div>
              <div className="topology-node destination">
                <div className="node-icon" aria-hidden="true">🖥️</div>
                <div className="node-label">Destination</div>
                <div className="node-ip">{packetDetails.destination_ip}</div>
              </div>
            </>
          )}
        </div>
        <p className="topology-legend">
          {route.next_hop_type === 'direct'
            ? 'Directly connected network — packet delivered locally'
            : 'Routed via gateway — packet forwarded to next hop'}
        </p>
      </div>

      {/* Capture Verification Panel */}
      {(
        labState === 'verifying' ||
        labState === 'completed' ||
        labState === 'error' ||
        labState === 'timeout' ||
        labState === 'unavailable'
      ) && (
        <div className="packet-details-panel verification-panel">
          <h3 className="panel-title">Capture Verification</h3>
          <div className="verification-status">
            <span
              className={`verification-badge ${
                labState === 'completed'
                  ? 'success'
                  : labState === 'error'
                  ? 'error'
                  : labState === 'timeout'
                  ? 'warning'
                  : labState === 'unavailable'
                  ? 'warning'
                  : 'pending'
              }`}
            >
              {labState === 'completed'
                ? 'Verified'
                : labState === 'error'
                ? 'Failed'
                : labState === 'timeout'
                ? 'Timeout'
                : labState === 'unavailable'
                ? 'Unavailable'
                : 'Verifying…'}
            </span>
            <p className="verification-message">
              {labState === 'completed'
                ? 'Captured packet matches expected forwarding behavior. TTL decremented, checksum valid.'
                : labState === 'error'
                ? 'Capture verification failed. Packet may have been dropped or corrupted.'
                : labState === 'timeout'
                ? 'No response captured within timeout window. Check lab connectivity.'
                : labState === 'unavailable'
                ? 'Packet lab service is unavailable. Cannot verify capture.'
                : 'Comparing captured packet headers with simulated forwarding decision…'}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}