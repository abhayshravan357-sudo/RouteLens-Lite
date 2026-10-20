import type { LabState, PacketJourneyResponse } from '../types/routing';

interface PacketJourneyProps {
  labState: LabState;
  labError: string | null;
  simulationResponse: PacketJourneyResponse | null;
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

function getActionIcon(action: string): string {
  switch (action) {
    case 'forward': return '→';
    case 'deliver': return '✓';
    case 'drop': return '✕';
    case 'loop': return '↻';
    case 'error': return '⚠';
    default: return '?';
  }
}

function getActionLabel(action: string): string {
  switch (action) {
    case 'forward': return 'Forward';
    case 'deliver': return 'Delivered';
    case 'drop': return 'Dropped';
    case 'loop': return 'Loop Detected';
    case 'error': return 'Error';
    default: return action;
  }
}

export default function PacketJourney({
  labState,
  labError,
  simulationResponse,
  onSimulate,
  disabled,
}: PacketJourneyProps) {
  const isActive = ACTIVE_STATES.includes(labState);
  const isTerminal = ['completed', 'error', 'timeout', 'unavailable'].includes(labState);
  const progress = getProgress(labState);

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
            Trace Packet Journey
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

      {/* Hop-by-Hop Journey Visualization */}
      {simulationResponse && simulationResponse.hops.length > 0 && (
        <div className="journey-hops">
          <h3 className="panel-title">Packet Journey</h3>
          <div className="hops-timeline">
            {simulationResponse.hops.map((hop, index) => (
              <div key={hop.hop_number} className={`hop-step ${hop.action}`}>
                <div className="hop-header">
                  <span className="hop-number">Hop {hop.hop_number}</span>
                  <span className={`hop-action ${hop.action}`}>
                    <span className="action-icon">{getActionIcon(hop.action)}</span>
                    <span className="action-label">{getActionLabel(hop.action)}</span>
                  </span>
                </div>
                <div className="hop-details">
                  <div className="hop-detail-row">
                    <span className="detail-label">From:</span>
                    <span className="detail-value">{hop.current_device}</span>
                  </div>
                  <div className="hop-detail-row">
                    <span className="detail-label">To:</span>
                    <span className="detail-value">{hop.destination_ip}</span>
                  </div>
                  {hop.matched_route && (
                    <div className="hop-details-group">
                      <div className="hop-detail-row">
                        <span className="detail-label">Route:</span>
                        <span className="detail-value">{hop.matched_route.destination}</span>
                      </div>
                      {hop.matched_route.next_hop && (
                        <div className="hop-detail-row">
                          <span className="detail-label">Next Hop:</span>
                          <span className="detail-value">{hop.matched_route.next_hop}</span>
                        </div>
                      )}
                      <div className="hop-detail-row">
                        <span className="detail-label">Interface:</span>
                        <span className="detail-value">{hop.matched_route.interface}</span>
                      </div>
                      <div className="hop-detail-row">
                        <span className="detail-label">Metric:</span>
                        <span className="detail-value">{hop.matched_route.metric}</span>
                      </div>
                    </div>
                  )}
                  {hop.next_hop_ip && (
                    <div className="hop-detail-row">
                      <span className="detail-label">Next Hop:</span>
                      <span className="detail-value">{hop.next_hop_ip}</span>
                    </div>
                  )}
                  {hop.egress_interface && (
                    <div className="hop-detail-row">
                      <span className="detail-label">Egress Interface:</span>
                      <span className="detail-value">{hop.egress_interface}</span>
                    </div>
                  )}
                  <div className="hop-detail-row">
                    <span className="detail-label">Action:</span>
                    <span className={`detail-value action-${hop.action}`}>{getActionLabel(hop.action)}</span>
                  </div>
                  <div className="hop-explanation">
                    {hop.explanation}
                  </div>
                </div>
                {index < simulationResponse.hops.length - 1 && (
                  <div className="hop-connector" aria-hidden="true">
                    <span className="connector-line" />
                    <span className="connector-arrow">↓</span>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Action Button */}
      <div className="journey-actions">
        {!simulationResponse && !isActive && !isTerminal && (
          <button
            type="button"
            className="btn btn-primary"
            onClick={onSimulate}
            disabled={disabled}
            aria-busy={false}
          >
            Trace Packet Journey
          </button>
        )}
        {simulationResponse && !simulationResponse.success && labState !== 'completed' && (
          <button
            type="button"
            className="btn btn-secondary"
            onClick={onSimulate}
            disabled={disabled}
          >
            Try Again
          </button>
        )}
        {simulationResponse && simulationResponse.success && (
          <button
            type="button"
            className="btn btn-secondary"
            onClick={onSimulate}
          >
            Trace Another Packet
          </button>
        )}
      </div>

      {/* Summary */}
      {simulationResponse && (
        <div className="journey-summary">
          <h3 className="panel-title">Journey Summary</h3>
          <div className="summary-grid">
            <div className="summary-item">
              <span className="summary-label">Total Hops</span>
              <span className="summary-value">{simulationResponse.hops.length}</span>
            </div>
            <div className="summary-item">
              <span className="summary-label">Status</span>
              <span className={`summary-value ${simulationResponse.success ? 'success' : 'error'}`}>
                {simulationResponse.success ? 'Delivered' : 'Failed'}
              </span>
            </div>
            <div className="summary-item">
              <span className="summary-label">Source</span>
              <span className="summary-value">{simulationResponse.source_ip}</span>
            </div>
            <div className="summary-item">
              <span className="summary-label">Destination</span>
              <span className="summary-value">{simulationResponse.destination_ip}</span>
            </div>
            {simulationResponse.error && (
              <div className="summary-item error">
                <span className="summary-label">Error</span>
                <span className="summary-value">{simulationResponse.error}</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}