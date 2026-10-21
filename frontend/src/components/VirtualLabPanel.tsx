/**
 * VirtualLabPanel
 *
 * The isolated Linux lab, and the whole lifecycle around it: check whether
 * it is there, build it, send a packet through it, and take it down again.
 *
 * The five states are the five states a lab is actually in:
 *
 *   1. Unavailable   — the namespaces are not there. Say why.
 *   2. Preparing     — the commands are running.
 *   3. Ready         — confirmed by the backend, so testing may begin.
 *   4. Result        — what the test actually showed.
 *   5. Cleanup       — tearing the lab down again.
 *
 * Two rules hold throughout:
 *
 *   - A calculated route is never shown as a captured packet. The wording
 *     for each state says which one happened.
 *   - The lab is not called inactive unless a response says it is.
 *
 * The topology is drawn from the scenario the backend holds, so it is the
 * network that will actually be built rather than a picture of one.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  applyScenarioLab,
  teardownScenarioLab,
  simulatePacket,
  checkLabStatus,
  fetchScenarios,
  fetchScenario,
} from '../api/routing';
import type {
  LabStatusResponse,
  LabState,
  LabRunResult,
  LabTestOutcome,
  Scenario,
  ScenarioSummary,
  SimulateResponse,
} from '../types/routing';
import './VirtualLabPanel.css';

interface VirtualLabPanelProps {
  status: LabStatusResponse | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  /**
   * The scenario to build by default. When this is absent the panel offers
   * the list of scenarios and lets the reader choose, so it works on its own.
   */
  scenarioId?: string;
}

type LabPhase =
  | 'unavailable'
  | 'preparing'
  | 'ready'
  | 'testing'
  | 'cleanup'
  | 'torn-down';

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

const PHASE_LABELS: Record<LabPhase, string> = {
  unavailable: 'Not available',
  preparing: 'Preparing',
  ready: 'Ready to test',
  testing: 'Testing',
  cleanup: 'Tearing down',
  'torn-down': 'Torn down',
};

const PHASE_TONE: Record<LabPhase, string> = {
  unavailable: 'error',
  preparing: 'info',
  ready: 'success',
  testing: 'info',
  cleanup: 'info',
  'torn-down': 'neutral',
};

interface TestOutcome {
  outcome: LabTestOutcome;
  label: string;
  detail: string;
  tone: 'success' | 'error' | 'warning' | 'neutral';
}

/**
 * Read a simulation result without over-claiming it.
 *
 * `capture_verified` is the only thing that makes a result a capture. When
 * it is not true the result is reported as what it actually is.
 */
function readTestResult(response: SimulateResponse): TestOutcome {
  if (response.state === 'timeout') {
    return {
      outcome: 'timeout',
      label: 'Timed out',
      detail:
        response.error ??
        'The packet was sent but no capture was confirmed before the timeout.',
      tone: 'warning',
    };
  }

  if (response.state === 'unavailable') {
    return {
      outcome: 'unavailable',
      label: 'Lab unavailable',
      detail: response.error ?? response.message,
      tone: 'error',
    };
  }

  if (response.state === 'error') {
    return {
      outcome: 'failed',
      label: 'Failed',
      detail: response.error ?? response.message,
      tone: 'error',
    };
  }

  if (response.capture_verified) {
    return {
      outcome: 'captured',
      label: 'Captured',
      detail:
        'The capture was verified. Each check below says whether it was read from the capture or only deduced.',
      tone: 'success',
    };
  }

  return {
    outcome: 'failed',
    label: 'Not verified',
    detail:
      response.error ??
      'The backend did not confirm a capture, so no packet is reported as having been observed.',
    tone: 'warning',
  };
}

/**
 * The three checks the lab runs, with the label the student reads.
 */
const VERIFICATION_CHECKS: {
  key: 'ttl_decremented' | 'checksum_valid' | 'route_matched';
  label: string;
}[] = [
  { key: 'ttl_decremented', label: 'TTL was decremented' },
  { key: 'checksum_valid', label: 'Checksum is valid' },
  { key: 'route_matched', label: 'Route matched' },
];

/**
 * The addresses the virtual router lab actually accepts.
 *
 * The lab validates the request against its own topology and refuses
 * anything else, so the test has to use the lab's addresses rather than a
 * scenario's. They are read from the status endpoint when it answers, and
 * fall back to the lab's documented topology when it does not.
 */
const LAB_CLIENT_IP = '192.168.10.2';
const LAB_SERVER_IP = '192.168.20.2';

function labTestAddresses(status: LabStatusResponse | null) {
  return {
    source: status?.router_info?.client_ip ?? LAB_CLIENT_IP,
    destination: status?.router_info?.server_ip ?? LAB_SERVER_IP,
  };
}

export default function VirtualLabPanel({
  status,
  loading,
  error,
  onRetry,
  scenarioId,
}: VirtualLabPanelProps) {
  const [phase, setPhase] = useState<LabPhase>('unavailable');
  const [applyResult, setApplyResult] = useState<LabRunResult | null>(null);
  const [teardownResult, setTeardownResult] = useState<LabRunResult | null>(null);
  const [preview, setPreview] = useState<LabRunResult | null>(null);
  const [testResult, setTestResult] = useState<SimulateResponse | null>(null);
  const [testOutcome, setTestOutcome] = useState<TestOutcome | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Which network to build. The panel works on its own, so it finds the
  // scenarios itself unless one is named for it.
  const [scenarios, setScenarios] = useState<ScenarioSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(scenarioId ?? null);
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [scenarioError, setScenarioError] = useState<string | null>(null);

  /**
   * The panel's own reading of the lab.
   *
   * The parent passes a status in, but the parent does not know when the
   * panel has just built or torn the lab down. The panel owns the lab's
   * lifecycle, so it owns the status too, and re-reads it whenever the
   * lab may have changed.
   */
  const [labStatus, setLabStatus] = useState<LabStatusResponse | null>(status);

  const available = labStatus?.available === true;

  const refreshStatus = useCallback(async () => {
    try {
      const fresh = await checkLabStatus();
      setLabStatus(fresh);
      return fresh;
    } catch (err) {
      // A 503 here is the backend saying the lab is not there, which is
      // information rather than a failure.
      setLabStatus({
        available: false,
        state: 'unavailable',
        message:
          err instanceof Error ? err.message : 'The lab is not available',
        router_info: null,
        error: err instanceof Error ? err.message : null,
      });
      return null;
    }
  }, []);

  // Take the parent's reading when it changes, unless the panel is in the
  // middle of doing something to the lab itself.
  useEffect(() => {
    if (busy) return;
    if (phase === 'preparing' || phase === 'cleanup') return;
    setLabStatus(status);
  }, [status, busy, phase]);

  // The backend is the only authority on whether the lab is there.
  useEffect(() => {
    if (available) {
      setPhase((current) => (current === 'preparing' ? current : 'ready'));
    } else if (phase !== 'preparing' && phase !== 'cleanup') {
      setPhase('unavailable');
    }
  }, [available, phase]);

  // Load the scenario list, and the chosen scenario's definition.
  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const list = await fetchScenarios();
        if (cancelled) return;
        setScenarios(list);

        const chosen =
          selectedId && list.some((s) => s.id === selectedId)
            ? selectedId
            : list[0]?.id ?? null;
        if (!chosen) return;
        setSelectedId(chosen);

        const definition = await fetchScenario(chosen);
        if (!cancelled) {
          setScenario(definition);
          setScenarioError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setScenarioError(
            err instanceof Error
              ? err.message
              : 'Could not load the scenarios'
          );
        }
      }
    };

    load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSelectScenario = useCallback(async (id: string) => {
    setSelectedId(id);
    setScenario(null);
    setPreview(null);
    setApplyResult(null);
    setTeardownResult(null);
    setTestResult(null);
    setTestOutcome(null);
    setActionError(null);
    try {
      const definition = await fetchScenario(id);
      setScenario(definition);
      setScenarioError(null);
    } catch (err) {
      setScenarioError(
        err instanceof Error ? err.message : 'Could not load the scenario'
      );
    }
  }, []);

  const canBuild = Boolean(scenario) && !busy;

  const handlePreview = useCallback(async () => {
    if (!scenario) return;
    setBusy(true);
    setActionError(null);
    try {
      const result = await applyScenarioLab(scenario.id, true);
      setPreview(result);
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : 'Could not read the lab commands'
      );
    } finally {
      setBusy(false);
    }
  }, [scenario]);

  const handleBuild = useCallback(async () => {
    if (!scenario) return;
    setBusy(true);
    setActionError(null);
    setApplyResult(null);
    setPhase('preparing');
    try {
      const result = await applyScenarioLab(scenario.id, false);
      setApplyResult(result);

      if (result.status === 'unavailable') {
        // The lab cannot be built here. The backend said why.
        setPhase('unavailable');
        await refreshStatus();
      } else if (result.status === 'failed') {
        setPhase('unavailable');
        await refreshStatus();
      } else {
        // Re-check: only the backend can confirm the namespaces are up.
        const after = await refreshStatus();
        setPhase(after?.available ? 'ready' : 'unavailable');
      }
    } catch (err) {
      setPhase('unavailable');
      setActionError(
        err instanceof Error ? err.message : 'Could not build the lab'
      );
    } finally {
      setBusy(false);
    }
  }, [scenario, refreshStatus]);

  const handleTest = useCallback(async () => {
    const addresses = labTestAddresses(labStatus);
    setBusy(true);
    setActionError(null);
    setTestResult(null);
    setTestOutcome(null);
    setPhase('testing');
    try {
      const result = await simulatePacket({
        source_ip: addresses.source,
        destination_ip: addresses.destination,
        protocol: 'icmp',
        ttl: 64,
        length: 84,
        route_matched: null,
        egress_interface: null,
        next_hop: null,
      });
      setTestResult(result);
      setTestOutcome(readTestResult(result));
      setPhase('ready');
    } catch (err) {
      setPhase('ready');
      setActionError(
        err instanceof Error ? err.message : 'The test could not be run'
      );
    } finally {
      setBusy(false);
    }
  }, [labStatus]);

  const handleTeardown = useCallback(async () => {
    if (!scenario) return;
    setBusy(true);
    setActionError(null);
    setTeardownResult(null);
    setPhase('cleanup');
    try {
      const result = await teardownScenarioLab(scenario.id, false);
      setTeardownResult(result);

      if (result.status === 'ok') {
        // The teardown commands ran. Re-read the status so the panel
        // reports what the backend now says, not what we assume.
        const after = await refreshStatus();
        setPhase(after?.available ? 'ready' : 'torn-down');
      } else {
        // A failed or refused teardown is not a confirmed inactive lab.
        setPhase(available ? 'ready' : 'unavailable');
      }
    } catch (err) {
      setPhase(available ? 'ready' : 'unavailable');
      setActionError(
        err instanceof Error ? err.message : 'Could not tear the lab down'
      );
    } finally {
      setBusy(false);
    }
  }, [scenario, available, refreshStatus]);

  const devices = useMemo(() => scenario?.nodes ?? [], [scenario]);
  const links = useMemo(() => scenario?.links ?? [], [scenario]);
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

  const info = labStatus?.router_info ?? null;

  return (
    <div className="virtual-lab">
      {scenarioError && (
        <div className="error-message" role="alert">
          <span aria-hidden="true">⚠</span>
          <span>{scenarioError}</span>
        </div>
      )}

      {/* --- Which network to build --- */}
      {scenarios.length > 0 && (
        <div className="lab-scenario-picker">
          <label htmlFor="lab-scenario">Network to build</label>
          <select
            id="lab-scenario"
            value={selectedId ?? ''}
            onChange={(e) => handleSelectScenario(e.target.value)}
            disabled={busy}
          >
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* --- The lifecycle, in one place --- */}
      <div className="lab-lifecycle">
        <ol className="lab-lifecycle-steps" aria-label="Lab lifecycle">
          {(
            [
              ['unavailable', 'Check'],
              ['preparing', 'Build'],
              ['ready', 'Test'],
              ['cleanup', 'Tear down'],
            ] as [LabPhase, string][]
          ).map(([step, label], index) => {
            const reached = phase === step;
            const done =
              (step === 'unavailable' && phase !== 'unavailable') ||
              (step === 'preparing' &&
                (phase === 'ready' || phase === 'testing' || phase === 'cleanup')) ||
              (step === 'ready' &&
                (phase === 'testing' || phase === 'cleanup' || phase === 'torn-down'));
            return (
              <li
                key={step}
                className={`lab-lifecycle-step ${reached ? 'reached' : ''} ${
                  done ? 'done' : ''
                }`}
              >
                <span className="lab-step-number" aria-hidden="true">
                  {index + 1}
                </span>
                <span className="lab-step-label">{label}</span>
              </li>
            );
          })}
        </ol>

        <span className={`status-badge ${PHASE_TONE[phase]}`} role="status">
          <span className="dot" aria-hidden="true" />
          {PHASE_LABELS[phase]}
        </span>
      </div>

      {labStatus && (
        <div className="lab-state-row">
          <span className={`status-badge ${STATE_TONE[labStatus.state] ?? 'neutral'}`}>
            <span className="dot" aria-hidden="true" />
            {STATE_LABELS[labStatus.state] ?? labStatus.state}
          </span>
          <p className="lab-state-message">{labStatus.message}</p>
        </div>
      )}

      {actionError && (
        <div className="error-message" role="alert">
          <span aria-hidden="true">⚠</span>
          <span>{actionError}</span>
        </div>
      )}

      {/* --- State 1: unavailable --- */}
      {phase === 'unavailable' && !available && (
        <div className="lab-unavailable" role="status">
          <div className="lab-unavailable-head">
            <span aria-hidden="true">⚠</span>
            <div>
              <strong>The lab is not running.</strong>
              <p>
                The lab is a set of isolated Linux network namespaces. It has
                to be built before a packet can be sent through it.
              </p>
            </div>
          </div>

          {labStatus?.error && (
            <p className="lab-unavailable-reason">
              The backend reported: {labStatus.error}
            </p>
          )}

          {applyResult?.status === 'unavailable' && applyResult.reason && (
            <p className="lab-unavailable-reason">
              Building it was refused: {applyResult.reason}
            </p>
          )}

          {applyResult?.status === 'failed' && (
            <p className="lab-unavailable-reason">
              Building it failed
              {applyResult.failed_at !== null &&
                applyResult.failed_at !== undefined &&
                ` at command ${applyResult.failed_at}`}
              . {applyResult.error ?? 'See the commands below.'}
            </p>
          )}

          <div className="lab-actions">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={handlePreview}
              disabled={!canBuild || busy}
            >
              {busy ? 'Working…' : 'Show the commands'}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleBuild}
              disabled={!canBuild || busy}
              aria-busy={busy}
            >
              {busy ? 'Building…' : 'Build the lab'}
            </button>
          </div>

          {!scenario && (
            <p className="lab-muted">
              No scenario is selected, so there is no network to build. Open a
              scenario from the Packet Journey view first.
            </p>
          )}
        </div>
      )}

      {/* --- State 2: preparing --- */}
      {phase === 'preparing' && (
        <div className="loading" role="status" aria-live="polite">
          <span className="spinner" aria-hidden="true" />
          Building the namespaces and bringing the interfaces up…
        </div>
      )}

      {/* --- State 3: ready --- */}
      {phase === 'ready' && available && (
        <div className="lab-ready">
          <div className="lab-ready-head">
            <span aria-hidden="true">✓</span>
            <div>
              <strong>The lab is up.</strong>
              <p>
                The namespaces are running and the router answers. A packet
                sent now is really sent, and a capture is really taken.
              </p>
            </div>
          </div>
          <div className="lab-actions">
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleTest}
              disabled={busy}
            >
              {busy ? 'Sending…' : 'Send a test packet'}
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={handleTeardown}
              disabled={busy}
            >
              Tear the lab down
            </button>
          </div>
          <p className="lab-test-target">
            The test packet goes from{' '}
            <code>{labTestAddresses(labStatus).source}</code> to{' '}
            <code>{labTestAddresses(labStatus).destination}</code> — the
            virtual router lab's own addresses.
          </p>
        </div>
      )}

      {/* --- State 4: the test result --- */}
      {phase === 'testing' && (
        <div className="loading" role="status" aria-live="polite">
          <span className="spinner" aria-hidden="true" />
          Sending the packet and waiting for the capture…
        </div>
      )}

      {testOutcome && (
        <div className={`lab-test-result ${testOutcome.tone}`} role="status">
          <div className="lab-test-head">
            <span className="lab-test-label">{testOutcome.label}</span>
            <span className="lab-test-provenance">
              {testOutcome.outcome === 'captured'
                ? 'observed on the wire'
                : testOutcome.outcome === 'calculated'
                ? 'calculated from the routing table'
                : 'no packet was observed'}
            </span>
          </div>
          <p className="lab-test-detail">{testOutcome.detail}</p>

          {testResult?.packet && (
            <div className="lab-test-packet">
              <div className="detail-item">
                <span className="detail-label">Source</span>
                <span className="detail-value">{testResult.packet.source_ip}</span>
              </div>
              <div className="detail-item">
                <span className="detail-label">Destination</span>
                <span className="detail-value">
                  {testResult.packet.destination_ip}
                </span>
              </div>
              <div className="detail-item">
                <span className="detail-label">Protocol</span>
                <span className="detail-value">
                  {testResult.packet.protocol.toUpperCase()}
                </span>
              </div>
              <div className="detail-item">
                <span className="detail-label">TTL</span>
                <span className="detail-value">{testResult.packet.ttl}</span>
              </div>
            </div>
          )}

          {/* Each check, with the evidence behind it.
              The backend reports whether a check was observed from the
              capture or only inferred, and the student sees which. */}
          {testResult?.verification_details && (
            <div className="lab-verification">
              <h4 className="lab-verification-title">The checks</h4>
              <ul className="lab-verification-list">
                {VERIFICATION_CHECKS.map((check) => {
                  const field = testResult.verification_details?.[check.key];
                  if (!field) return null;
                  const provenance = field.provenance ?? 'unknown';
                  return (
                    <li
                      key={check.key}
                      className={`lab-verification-item ${field.value ? 'passed' : 'failed'} prov-${provenance}`}
                    >
                      <span className="lab-verification-mark" aria-hidden="true">
                        {field.value ? '✓' : '✕'}
                      </span>
                      <span className="lab-verification-label">
                        {check.label}
                      </span>
                      <span
                        className={`lab-verification-provenance prov-${provenance}`}
                        title={field.details || undefined}
                      >
                        {provenance}
                      </span>
                      {field.details && (
                        <span className="lab-verification-details">
                          {field.details}
                        </span>
                      )}
                    </li>
                  );
                })}
              </ul>
              <p className="lab-verification-legend">
                <strong>observed</strong> was read from the capture.{' '}
                <strong>inferred</strong> was only deduced from the ping
                succeeding. A check can pass and still be only inferred.
              </p>
            </div>
          )}
        </div>
      )}

      {/* --- State 5: cleanup --- */}
      {phase === 'cleanup' && (
        <div className="loading" role="status" aria-live="polite">
          <span className="spinner" aria-hidden="true" />
          Removing the namespaces…
        </div>
      )}

      {phase === 'torn-down' && (
        <div className="lab-ready torn-down" role="status">
          <div className="lab-ready-head">
            <span aria-hidden="true">✓</span>
            <div>
              <strong>The lab was taken down.</strong>
              <p>
                The backend reported that the teardown commands completed. Build
                it again to send another packet.
              </p>
            </div>
          </div>
          <div className="lab-actions">
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleBuild}
              disabled={busy}
            >
              Build the lab again
            </button>
          </div>
        </div>
      )}

      {teardownResult && phase !== 'torn-down' && teardownResult.status !== 'ok' && (
        <div className="error-message" role="alert">
          <span aria-hidden="true">⚠</span>
          <span>
            The teardown did not complete
            {teardownResult.reason ? `: ${teardownResult.reason}` : '.'} The
            lab may still be partly in place.
          </span>
        </div>
      )}

      {/* --- The commands, when they were shown or run --- */}
      {(preview || applyResult?.status === 'failed') && (
        <details className="lab-commands">
          <summary>
            {preview ? 'The commands that would run' : 'The commands that ran'}
            {' '}
            ({(preview?.commands ?? applyResult?.commands ?? []).length})
          </summary>
          <ol className="lab-command-list">
            {(preview?.commands ?? applyResult?.commands ?? []).map(
              (command, index) => (
                <li key={index} className="mono">
                  {command}
                </li>
              )
            )}
          </ol>
        </details>
      )}

      {/* --- The topology, from the scenario the backend holds --- */}
      {devices.length > 0 ? (
        <div className="lab-topology-section">
          <h3 className="panel-title">
            The network this lab builds
            {scenario ? (
              <span className="lab-topology-source">
                {scenario.title}
              </span>
            ) : null}
          </h3>
          <div className="lab-devices">
            {devices.map((device) => (
              <div className="lab-device" key={device.id}>
                <span className="lab-device-kind">{device.kind}</span>
                <span className="lab-device-name">{device.id}</span>
                <ul className="lab-device-ifaces">
                  {device.ifaces.map((iface) => (
                    <li key={iface.name}>
                      <span className="mono">{iface.name}</span>
                      <span className="mono lab-device-cidr">{iface.cidr}</span>
                    </li>
                  ))}
                </ul>
                {device.routes.length > 0 && (
                  <ul className="lab-device-routes">
                    {device.routes.map((route) => (
                      <li key={`${route.prefix}-${route.dev}`} className="mono">
                        {route.prefix} via {route.via ?? 'direct'} dev {route.dev}
                        {route.metric !== undefined && ` metric ${route.metric}`}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
          {links.length > 0 && (
            <p className="lab-links">
              {links
                .map((link) => `${link.a} ↔ ${link.b}`)
                .join(' · ')}
            </p>
          )}
          <p className="lab-muted">
            These are the addresses and routes the backend will create. They
            are read from the scenario, not from a picture.
          </p>
        </div>
      ) : (
        <div className="lab-topology-section">
          <h3 className="panel-title">The network this lab builds</h3>
          <p className="lab-muted">
            No scenario is selected, so the lab's network is not known here.
            The panel still reports whether the lab is running.
          </p>
        </div>
      )}

      {/* --- What the router actually holds, when it could be read --- */}
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
        routing table in the analyser is a teaching sample. The lab is a real,
        isolated set of Linux network namespaces built from a scenario. A
        packet traced in one does not travel in the other.
      </div>
    </div>
  );
}
