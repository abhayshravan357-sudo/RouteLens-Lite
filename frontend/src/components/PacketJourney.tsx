/**
 * PacketJourney
 *
 * Shows the path a packet took, hop by hop, and why each hop happened.
 *
 * The most important thing this component does is tell the truth about what
 * kind of answer it is holding:
 *
 *   - A *calculated* journey is the routing table being reasoned about. No
 *     packet was sent. It is the right answer to "what would a router do",
 *     and the wrong answer to "was a packet seen".
 *   - A *captured* journey is what was really observed on the wire.
 *
 * The two are never presented the same way, and the wording of every state
 * follows the kind of answer.
 */

import { useEffect, useMemo, useState } from 'react';
import type {
  LabState,
  PacketHopResponse,
  PacketJourneyResponse,
  JourneyOutcome,
} from '../types/routing';
import './PacketJourney.css';

interface PacketJourneyProps {
  labState: LabState;
  labError: string | null;
  simulationResponse: PacketJourneyResponse | null;
  onSimulate: () => void;
  disabled: boolean;
  /**
   * What kind of answer this journey is.
   *
   * The default is "calculated", because that is what a routing-table
   * trace is. It is only "captured" when the response says a capture was
   * verified.
   */
  provenance?: 'calculated' | 'captured';
}

const CALCULATED_LABELS: Record<LabState, string> = {
  idle: 'Ready to calculate',
  ready: 'Routing table loaded',
  simulating: 'Calculating the decision',
  transmitting: 'Calculating the next hop',
  capturing: 'Calculating the delivery',
  verifying: 'Checking the result',
  completed: 'Calculation complete',
  error: 'Calculation failed',
  timeout: 'Calculation timed out',
  unavailable: 'Lab unavailable',
};

const CAPTURED_LABELS: Record<LabState, string> = {
  idle: 'Ready to send',
  ready: 'Lab ready',
  simulating: 'Preparing the packet',
  transmitting: 'Transmitting packet',
  capturing: 'Capturing response',
  verifying: 'Verifying capture',
  completed: 'Capture complete',
  error: 'Transmission failed',
  timeout: 'Transmission timed out',
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
  unresolved_next_hop: 'Handed over',
};

const OUTCOME_PRESENTATION: Record<
  JourneyOutcome,
  { label: string; tone: string; detail: string }
> = {
  delivered: {
    label: 'Delivered',
    tone: 'success',
    detail: 'The packet reached the destination.',
  },
  loop: {
    label: 'Routing loop',
    tone: 'error',
    detail:
      'The packet came back to a device it had already been at. Forwarding will continue until the hop limit stops it.',
  },
  hop_limit_exceeded: {
    label: 'Hop limit reached',
    tone: 'error',
    detail:
      'The packet was forwarded more times than the hop limit allows, so it was discarded before arriving.',
  },
  no_route: {
    label: 'No route',
    tone: 'error',
    detail:
      'No route in the table covers the destination, so the packet could not be forwarded.',
  },
  unresolved_next_hop: {
    // Not an error. The hand-off worked; only the next step is unknown.
    label: 'Handed to the next router',
    tone: 'info',
    detail:
      "The packet was handed over successfully, but that router's own routing table is not known here, so the next forwarding decision cannot be worked out. The teaching table is one router's table; a full multi-router journey is what the scenario lab is for.",
  },
  invalid_input: {
    label: 'Invalid address',
    tone: 'error',
    detail: 'The address could not be read, so no path was calculated.',
  },
  in_progress: {
    label: 'In progress',
    tone: 'info',
    detail: 'The path is still being calculated.',
  },
};

/**
 * Work out how the journey ended.
 *
 * The backend reports a hop `action` and an `explanation`. The ways a
 * journey can fail are mostly reported as "drop" apart from the loop, so the
 * explanation is consulted to tell them apart. The explanation itself is
 * always shown as well, so the student reads the backend's own words rather
 * than this summary.
 *
 * "unresolved_next_hop" is not a failure: the hand-over to the next router
 * worked, and only that router's own table is missing.
 */
function classifyOutcome(hops: PacketHopResponse[]): JourneyOutcome {
  if (hops.length === 0) return 'in_progress';

  const last = hops[hops.length - 1];
  const explanation = (last.explanation ?? '').toLowerCase();

  if (last.action === 'deliver') return 'delivered';
  if (last.action === 'loop') return 'loop';
  if (last.action === 'unresolved_next_hop') return 'unresolved_next_hop';
  if (last.action === 'error') return 'invalid_input';
  if (hops.some((hop) => hop.action === 'loop')) return 'loop';
  if (hops.some((hop) => hop.action === 'unresolved_next_hop')) {
    return 'unresolved_next_hop';
  }

  if (last.action === 'drop') {
    if (
      explanation.includes('hop count') ||
      explanation.includes('maximum hop') ||
      explanation.includes('hop limit') ||
      explanation.includes('ttl')
    ) {
      return 'hop_limit_exceeded';
    }
    return 'no_route';
  }

  return 'in_progress';
}

/** Whether a value looks like an address rather than a device name. */
function looksLikeAddress(value: string): boolean {
  return /^[0-9a-f:.]+$/i.test(value.trim()) && /[.:]/.test(value);
}

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
    case 'unresolved_next_hop':
      // The hand-over worked; only the next step is unknown.
      return '⇥';
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
  provenance,
}: PacketJourneyProps) {
  const [activeIndex, setActiveIndex] = useState(0);

  const hops = simulationResponse?.hops ?? [];
  const hasResult = simulationResponse !== null;
  const safeIndex = hops.length > 0 ? Math.min(activeIndex, hops.length - 1) : 0;
  const activeHop = hops[safeIndex];

  /**
   * What kind of answer this is.
   *
   * The backend will say so in the response's `provenance` field. Until it
   * does, a journey from the routing table is calculated — which is what it
   * is — and the fallback says so rather than guessing at a capture.
   */
  const kind: 'calculated' | 'captured' =
    provenance ??
    (simulationResponse?.provenance === 'captured' ? 'captured' : 'calculated');

  const outcome = useMemo(() => classifyOutcome(hops), [hops]);
  const presentation = OUTCOME_PRESENTATION[outcome];
  const stateLabels = kind === 'captured' ? CAPTURED_LABELS : CALCULATED_LABELS;

  // A new result starts at the first hop.
  useEffect(() => {
    setActiveIndex(0);
  }, [simulationResponse]);

  const canStep = hops.length > 0;
  const isBusy = ['simulating', 'transmitting', 'capturing', 'verifying'].includes(
    labState
  );
  const isTerminal = ['completed', 'error', 'timeout', 'unavailable'].includes(
    labState
  );

  return (
    <div className="packet-journey">
      {/* What kind of answer this is. This is the first thing shown, because
          it changes how every other word on the panel should be read. */}
      <div
        className={`journey-provenance ${kind}`}
        role="status"
        aria-live="polite"
      >
        <span className="journey-provenance-tag">
          {kind === 'captured' ? 'Captured' : 'Calculated'}
        </span>
        <span className="journey-provenance-text">
          {kind === 'captured'
            ? 'Every hop below was observed on the wire. A packet really was sent.'
            : 'Every hop below was worked out from the routing table. No packet was sent, and nothing was observed on the wire.'}
        </span>
      </div>

      {/* State strip */}
      <div className="journey-state">
        <span className={`status-badge ${STATE_TONE[labState] ?? 'neutral'}`}>
          <span className="dot" aria-hidden="true" />
          {stateLabels[labState] ?? labState}
        </span>
        {labError && <span className="journey-state-error">{labError}</span>}
        {isBusy && (
          <span className="journey-state-note">
            {kind === 'captured'
              ? 'The packet is on its way.'
              : 'The routing table is being worked through.'}
          </span>
        )}
      </div>

      {/* Controls */}
      <div className="journey-actions">
        {!hasResult && !isBusy && !isTerminal && (
          <button
            type="button"
            className="btn btn-primary"
            onClick={onSimulate}
            disabled={disabled}
          >
            {kind === 'captured'
              ? 'Send a packet and capture it'
              : 'Trace the packet journey'}
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

      {/* The outcome, in words, before the hops. */}
      {hasResult && (
        <div className={`journey-outcome ${presentation.tone}`} role="status">
          <span className="journey-outcome-label">{presentation.label}</span>
          <span className="journey-outcome-detail">{presentation.detail}</span>
          {simulationResponse?.error && (
            <span className="journey-outcome-reason">
              {simulationResponse.error}
            </span>
          )}
        </div>
      )}

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
              <span className="detail-label">Forwarding device</span>
              <span className="detail-value">{activeHop.current_device}</span>
            </div>
            <div className="detail-item">
              <span className="detail-label">Destination address</span>
              <span className="detail-value">{activeHop.destination_ip}</span>
            </div>
            {activeHop.matched_route && (
              <>
                <div className="detail-item">
                  <span className="detail-label">Route selected</span>
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
                <span className="detail-label">Next hop address</span>
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
              <span className="summary-label">Outcome</span>
              <span className={`summary-value ${presentation.tone}`}>
                {presentation.label}
              </span>
            </div>
            <div className="summary-item">
              <span className="summary-label">
                {looksLikeAddress(simulationResponse.source_ip)
                  ? 'Source address'
                  : 'Started at'}
              </span>
              <span className="summary-value">
                {simulationResponse.source_ip || '—'}
              </span>
            </div>
            <div className="summary-item">
              <span className="summary-label">Destination address</span>
              <span className="summary-value">
                {simulationResponse.destination_ip}
              </span>
            </div>
            <div className="summary-item">
              <span className="summary-label">Evidence</span>
              <span className="summary-value muted">
                {kind === 'captured'
                  ? 'observed on the wire'
                  : 'calculated from the routing table'}
              </span>
            </div>
          </div>

          {/* The backend puts a device label in the source field. It is
              shown as a device, and never as an address. */}
          {simulationResponse.source_ip &&
            !looksLikeAddress(simulationResponse.source_ip) && (
              <p className="journey-source-note">
                The backend names the starting point by device, not by
                address: <code>{simulationResponse.source_ip}</code>
              </p>
            )}
        </div>
      )}
    </div>
  );
}
