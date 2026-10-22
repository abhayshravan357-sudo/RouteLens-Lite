/**
 * DiscoveryPanel
 *
 * Finds hosts on a network you have explicitly authorised.
 *
 * Because this is the one feature that reaches out to other machines,
 * it is deliberately slower to use than the read-only diagnostics:
 *
 *   1. Enter the network.
 *   2. Preview the scope, so you can see exactly what would be probed.
 *   3. Type the target back to confirm you own it and meant it.
 *   4. Run the scan.
 *
 * Every request, including refused ones, is written to an audit trail
 * that is shown below the form.
 */

import { useEffect, useState } from 'react';
import {
  cancelDiscovery,
  fetchDiscoveryAudit,
  previewDiscoveryScope,
  runDiscovery,
} from '../api/routing';
import type {
  DiscoveryAuditEntry,
  DiscoveryResult,
  DiscoveryScopePreview,
} from '../types/routing';
import ProvenanceBadge from './ProvenanceBadge';
import './DiscoveryPanel.css';

interface DiscoveryPanelProps {
  /** The host's own IPv4 address, offered as a sensible starting point. */
  localAddress?: string | null;
}

export default function DiscoveryPanel({ localAddress }: DiscoveryPanelProps) {
  const [target, setTarget] = useState('');
  const [maxHosts, setMaxHosts] = useState(64);
  const [interval, setIntervalMs] = useState(0.2);
  const [timeout, setTimeout] = useState(1.0);

  const [preview, setPreview] = useState<DiscoveryScopePreview | null>(null);
  const [result, setResult] = useState<DiscoveryResult | null>(null);
  const [audit, setAudit] = useState<DiscoveryAuditEntry[]>([]);

  const [previewing, setPreviewing] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshAudit = () => {
    fetchDiscoveryAudit()
      .then(setAudit)
      .catch(() => setAudit([]));
  };

  useEffect(() => {
    refreshAudit();
  }, []);

  const handlePreview = async (e: React.FormEvent) => {
    e.preventDefault();
    setPreviewing(true);
    setError(null);
    setResult(null);
    setPreview(null);
    try {
      const scope = await previewDiscoveryScope(
        target.trim(),
        maxHosts,
        interval,
        timeout
      );
      setPreview(scope);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not read the scope');
    } finally {
      setPreviewing(false);
      refreshAudit();
    }
  };

  const handleRun = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!preview) return;
    setRunning(true);
    setError(null);
    try {
      const found = await runDiscovery(
        target.trim(),
        target.trim(),
        maxHosts,
        interval,
        timeout
      );
      setResult(found);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The scan could not be run');
    } finally {
      setRunning(false);
      refreshAudit();
    }
  };

  const handleCancel = async () => {
    if (!result?.scan_id) return;
    try {
      await cancelDiscovery(result.scan_id);
    } catch {
      /* The scan may already have finished. */
    }
  };

  return (
    <div className="discovery-panel">
      <div className="discovery-header">
        <div>
          <h3>Find hosts on a network</h3>
          <p className="discovery-intro">
            This sends real ping probes to other machines on your network.
            Only use it on a network you own or have permission to scan.
          </p>
        </div>
        <ProvenanceBadge
          provenance="observed"
          label="Real probes"
          showDescription
        />
      </div>

      <div className="discovery-authorisation">
        <strong>Before you run this:</strong> scanning a network you do not
        own or have permission to test may be illegal. Check with whoever
        runs the network first.
      </div>

      {error && (
        <div className="error-message" role="alert">
          <span aria-hidden="true">⚠</span>
          {error}
        </div>
      )}

      <form className="discovery-form" onSubmit={handlePreview}>
        <div className="discovery-form-fields">
          <div className="discovery-field discovery-field-wide">
            <label htmlFor="discovery-target">Network to scan</label>
            <input
              id="discovery-target"
              type="text"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              placeholder="e.g. 192.168.1.0/24"
              spellCheck={false}
              required
            />
            {localAddress && (
              <button
                type="button"
                className="discovery-suggest"
                onClick={() => {
                  const guess = localAddress.split('.').slice(0, 3).join('.');
                  setTarget(`${guess}.0/24`);
                }}
              >
                Use my network ({localAddress})
              </button>
            )}
          </div>

          <div className="discovery-field">
            <label htmlFor="discovery-max">Most addresses</label>
            <input
              id="discovery-max"
              type="number"
              value={maxHosts}
              onChange={(e) => setMaxHosts(parseInt(e.target.value, 10) || 64)}
              min="1"
              max="1024"
            />
          </div>

          <div className="discovery-field">
            <label htmlFor="discovery-interval">Gap between probes (s)</label>
            <input
              id="discovery-interval"
              type="number"
              value={interval}
              onChange={(e) => setIntervalMs(parseFloat(e.target.value) || 0.2)}
              min="0.05"
              max="10"
              step="0.05"
            />
          </div>

          <div className="discovery-field">
            <label htmlFor="discovery-timeout">Wait for a reply (s)</label>
            <input
              id="discovery-timeout"
              type="number"
              value={timeout}
              onChange={(e) => setTimeout(parseFloat(e.target.value) || 1)}
              min="0.1"
              max="10"
              step="0.1"
            />
          </div>
        </div>

        <button
          type="submit"
          className="btn btn-secondary"
          disabled={previewing || !target.trim()}
        >
          {previewing ? 'Checking scope…' : 'Check what would be scanned'}
        </button>
      </form>

      {preview && (
        <div className="discovery-preview">
          <h4>Here is exactly what would be probed</h4>
          <p className="discovery-preview-text">
            Network <code>{preview.scope.network}</code>, containing{' '}
            <strong>{preview.scope.host_count}</strong> address
            {preview.scope.host_count === 1 ? '' : 'es'}. At most{' '}
            <strong>{preview.scope.max_hosts}</strong> would be probed, one at
            a time, with a {preview.scope.interval}s gap between probes.
          </p>
          <details className="discovery-addresses">
            <summary>
              Show the {preview.addresses.length} address
              {preview.addresses.length === 1 ? '' : 'es'}
            </summary>
            <ul>
              {preview.addresses.map((address) => (
                <li key={address}>
                  <code>{address}</code>
                </li>
              ))}
            </ul>
          </details>

          <form className="discovery-confirm" onSubmit={handleRun}>
            <label htmlFor="discovery-confirmation">
              Type <code>{target.trim()}</code> to confirm you have permission
              to scan this network
            </label>
            <input
              id="discovery-confirmation"
              type="text"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              spellCheck={false}
              required
            />
            <button
              type="submit"
              className="btn btn-primary"
              disabled={running || target.trim() !== preview.scope.network}
            >
              {running ? 'Scanning…' : 'Start the scan'}
            </button>
          </form>
        </div>
      )}

      {result && (
        <div className="discovery-result">
          <div className="discovery-result-header">
            <span
              className={`discovery-status ${result.status}`}
            >
              {result.status === 'completed'
                ? 'Scan finished'
                : result.status === 'cancelled'
                ? 'Scan cancelled'
                : 'Scan failed'}
            </span>
            {result.message && (
              <span className="discovery-message">{result.message}</span>
            )}
            {result.scan_id && result.status === 'completed' && (
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                onClick={handleCancel}
              >
                Cancel
              </button>
            )}
          </div>

          <div className="discovery-result-meta">
            <span>
              {result.addresses_probed} of {result.addresses_total} address
              {result.addresses_total === 1 ? '' : 'es'} probed
            </span>
            <span>{result.duration_seconds.toFixed(1)}s elapsed</span>
          </div>

          {result.hosts.length > 0 ? (
            <table className="discovery-hosts">
              <thead>
                <tr>
                  <th scope="col">IP address</th>
                  <th scope="col">Method</th>
                  <th scope="col">Latency</th>
                  <th scope="col">Answered at</th>
                </tr>
              </thead>
              <tbody>
                {result.hosts.map((host) => (
                  <tr key={host.ip_address}>
                    <td className="mono">{host.ip_address}</td>
                    <td>{host.method}</td>
                    <td className="mono">
                      {host.latency_ms !== null
                        ? `${host.latency_ms.toFixed(2)}ms`
                        : '-'}
                    </td>
                    <td className="mono">
                      {host.responded_at
                        ? new Date(host.responded_at).toLocaleTimeString()
                        : '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="discovery-empty">
              No host answered. That is a real result: it means nothing replied
              to the probes, not that the scan was not run.
            </p>
          )}
        </div>
      )}

      {audit.length > 0 && (
        <details className="discovery-audit">
          <summary>Audit trail ({audit.length} request{audit.length === 1 ? '' : 's'})</summary>
          <table className="discovery-audit-table">
            <thead>
              <tr>
                <th scope="col">When</th>
                <th scope="col">Target</th>
                <th scope="col">Outcome</th>
                <th scope="col">Hosts</th>
                <th scope="col">Confirmed</th>
                <th scope="col">Reason</th>
              </tr>
            </thead>
            <tbody>
              {audit.map((entry, i) => (
                <tr key={i}>
                  <td className="mono">
                    {new Date(entry.timestamp).toLocaleTimeString()}
                  </td>
                  <td className="mono">{entry.target}</td>
                  <td>
                    <span className={`audit-outcome ${entry.outcome}`}>
                      {entry.outcome}
                    </span>
                  </td>
                  <td>{entry.hosts_found}</td>
                  <td>{entry.confirmed ? 'yes' : 'no'}</td>
                  <td className="audit-reason">{entry.reason ?? '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  );
}
