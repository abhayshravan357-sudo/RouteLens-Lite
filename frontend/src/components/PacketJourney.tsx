import { useEffect, useState } from 'react';
import type { LabState, PacketJourneyResponse } from '../types/routing';
import './PacketJourney.css';

interface PacketJourneyProps {
  labState: LabState;
  labError: string | null;
  simulationResponse: PacketJourneyResponse | null;
  onSimulate: () => void;
  disabled: boolean;
}

const STATE_LABELS: Record<LabState, string> = {
  idle: 'Ready to simulate',
  ready: 'Lab ready',
  simulating: 'Simulating decision',
  transmitting: 'Transmitting packet',
  capturing: 'Capturing response',
  verifying: 'Verifying capture',
  completed: 'Simulation complete',
  error: 'Simulation failed',
  timeout: 'Simulation timed out',
  unavailable: 'Lab unavailable',
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

const ACTION_LABELS: Record<string, string> = {
  forward: 'Forward',
  deliver: 'Delivered',
  drop: 'Dropped',
  loop: 'Loop',
  error: 'Error',
};

const ACTIVE_STATES: LabState[] = [
  'simulating',
  'transmitting',
  'capturing',
  'verifying',
];

function getActionIcon(action: string): string {
  switch (action) {
    case 'forward':
      return '→';
    case 'deliver':
      return '✓';
    case 'drop':
      return '✕';
    case 'loop':
      return '↻';
    case 'error':
      return '⚠';
    default:
      return '?';
  }
}

export default function PacketJourney({
  labState,
  labError,
  simulationResponse,
  onSimulate,
  disabled,
}: PacketJourneyProps) {
  const [activeIndex, setActiveIndex] = useState(0);

  const hops = simulationResponse?.hops ?? [];
  const isActive = ACTIVE_STATES.includes(labState);
  const isTerminal = ['completed', 'error', 'timeout', 'unavailable'].includes(
    labState
  );
  const hasResult = simulationResponse !== null;
  const safeIndex = hops.length > 0 ? Math.min(activeIndex, hops.length - 1) : 0;
  const activeHop = hops[safeIndex];

  // A new result starts at the first hop.
  useEffect(() => {
    setActiveIndex(0);
  }, [simulationResponse]);

  const canStep = hops.length > 0;

  return (
    <div className="packet-journey">
      {/* State strip */}
      <div className="journey-state" role="status" aria-live="polite">
        <span
          className={`status-badge ${STATE_TONE[labState] ?? 'neutral'}`}
        >
          <span className="dot" aria-hidden="true" />
          {STATE_LABELS[labState] ?? labState}
        </span>
        {labError && (
          <span className="journey-state-error">{labError}</span>
        )}
        {isActive && (
          <span className="journey-state-note">
            The engine is working through the route table.
          </span>
        )}
      </div>

      {/* Controls */}
      <div className="journey-actions">
        {!hasResult && !isActive && !isTerminal && (
          <button
            type="button"
            className="btn btn-primary"
            onClick={onSimulate}
            disabled={disabled}
          >
            Trace packet journey
          </button>
        )}

        {hasResult && canStep && (
          <div className="hop-controls">
            <button
              type="button"
              className="btn btn-sm btn-secondary"
              onClick={() => setActiveIndex(0)}
              disabled={safeIndex === 0}
            >
              ⏮ Start
            </button>
            <button
              type="button"
              className="btn btn-sm btn-secondary"
              onClick={() => setActiveIndex((i) => Math.max(0, i - 1))}
              disabled={safeIndex === 0}
            >
              ← Previous
            </button>
            <button
              type="button"
              className="btn btn-sm btn-secondary"
              onClick={() =>
                setActiveIndex((i) => Math.min(hops.length - 1, i + 1))
              }
              disabled={safeIndex >= hops.length - 1}
            >
              Next →
            </button>
            <button
              type="button"
              className="btn btn-sm btn-secondary"
              onClick={onSimulate}
            >
              ↻ Replay
            </button>
            <span className="hop-position">
              Hop {safeIndex + 1} of {hops.length}
            </span>
          </div>
        )}

        {hasResult && !canStep && (
          <p className="journey-no-hops">
            The trace returned no hops. The engine did not find a path.
          </p>
        )}
      </div>

      {/* Hop timeline */}
      {canStep && (
        <ol className="journey-timeline" aria-label="Packet journey hops">
          {hops.map((hop, index) => (
            <li
              key={hop.hop_number}
              className={`journey-timeline-entry ${hop.action} ${
                index === safeIndex ? 'active' : ''
              } ${index < safeIndex ? 'passed' : ''}`}
            >
              <button
                type="button"
                className="journey-timeline-button"
                onClick={() => setActiveIndex(index)}
                aria-current={index === safeIndex ? 'step' : undefined}
              >
                <span className="journey-timeline-number">{hop.hop_number}</span>
                <span className="journey-timeline-device">{hop.current_device}</span>
                <span className={`journey-timeline-action ${hop.action}`}>
                  <span aria-hidden="true">{getActionIcon(hop.action)}</span>
                  {ACTION_LABELS[hop.action] ?? hop.action}
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}

      {/* Active hop detail */}
      {activeHop && (
        <div className="journey-hop-detail">
          <div className="journey-hop-header">
            <h3>
              Hop {activeHop.hop_number} — {activeHop.current_device}
            </h3>
            <span className={`journey-hop-action ${activeHop.action}`}>
              <span aria-hidden="true">{getActionIcon(activeHop.action)}</span>
              {ACTION_LABELS[activeHop.action] ?? activeHop.action}
            </span>
          </div>

          <p className="journey-hop-explanation">{activeHop.explanation}</p>

          <div className="journey-hop-grid">
            <div className="detail-item">
              <span className="detail-label">From</span>
              <span className="detail-value">{activeHop.current_device}</span>
            </div>
            <div className="detail-item">
              <span className="detail-label">To</span>
              <span className="detail-value">{activeHop.destination_ip}</span>
            </div>
            {activeHop.matched_route && (
              <>
                <div className="detail-item">
                  <span className="detail-label">Matched route</span>
                  <span className="detail-value">
                    {activeHop.matched_route.destination}
                  </span>
                </div>
                <div className="detail-item">
                  <span className="detail-label">Next hop</span>
                  <span className="detail-value">
                    {activeHop.matched_route.next_hop ?? 'directly connected'}
                  </span>
                </div>
                <div className="detail-item">
                  <span className="detail-label">Outgoing interface</span>
                  <span className="detail-value">
                    {activeHop.matched_route.interface}
                  </span>
                </div>
                <div className="detail-item">
                  <span className="detail-label">Metric</span>
                  <span className="detail-value">
                    {activeHop.matched_route.metric}
                  </span>
                </div>
              </>
            )}
            {activeHop.next_hop_ip && (
              <div className="detail-item">
                <span className="detail-label">Next hop IP</span>
                <span className="detail-value">{activeHop.next_hop_ip}</span>
              </div>
            )}
            {activeHop.egress_interface && (
              <div className="detail-item">
                <span className="detail-label">Egress interface</span>
                <span className="detail-value">{activeHop.egress_interface}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Summary */}
      {simulationResponse && (
        <div className="journey-summary">
          <div className="summary-grid">
            <div className="summary-item">
              <span className="summary-label">Total hops</span>
              <span className="summary-value">{hops.length}</span>
            </div>
            <div className="summary-item">
              <span className="summary-label">Status</span>
              <span
                className={`summary-value ${
                  simulationResponse.success ? 'success' : 'error'
                }`}
              >
                {simulationResponse.success ? 'Delivered' : 'Failed'}
              </span>
            </div>
            <div className="summary-item">
              <span className="summary-label">Source</span>
              <span className="summary-value">{simulationResponse.source_ip}</span>
            </div>
            <div className="summary-item">
              <span className="summary-label">Destination</span>
              <span className="summary-value">
                {simulationResponse.destination_ip}
              </span>
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
