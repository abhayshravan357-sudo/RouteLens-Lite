/**
 * ComparePanel
 *
 * Shows a simulation next to a real probe from the virtual lab.
 *
 * The point of this panel is honesty. When the lab is unavailable the
 * panel says so plainly and shows no agreement verdict, because there is
 * nothing to compare. When the lab did run, it shows whether the
 * prediction and the reality agreed.
 */

import { useState } from 'react';
import { compareScenarioWithLab } from '../api/routing';
import type { ScenarioCompare } from '../types/routing';
import ProvenanceBadge from './ProvenanceBadge';
import './ComparePanel.css';

interface ComparePanelProps {
  scenarioId: string | null;
  src: string;
  dst: string;
}

export default function ComparePanel({ scenarioId, src, dst }: ComparePanelProps) {
  const [result, setResult] = useState<ScenarioCompare | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runComparison = async () => {
    if (!scenarioId || !src || !dst) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const comparison = await compareScenarioWithLab(scenarioId, { src, dst });
      setResult(comparison);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Comparison failed');
    } finally {
      setLoading(false);
    }
  };

  if (!scenarioId) {
    return null;
  }

  const labUnavailable = result?.lab.status === 'unavailable';

  return (
    <div className="compare-panel">
      <div className="compare-header">
        <div>
          <h3>Compare with the real lab</h3>
          <p className="compare-subtitle">
            Run the same packet in the isolated namespaces and see whether reality
            matches the prediction.
          </p>
        </div>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={runComparison}
          disabled={loading || !src || !dst}
        >
          {loading ? 'Comparing…' : 'Compare with lab'}
        </button>
      </div>

      {!src || !dst ? (
        <p className="compare-hint">
          Trace a packet first, then compare it against the lab.
        </p>
      ) : null}

      {error && (
        <div className="error-message" role="alert">
          <span aria-hidden="true">⚠</span>
          {error}
        </div>
      )}

      {result && (
        <div className="compare-results">
          <div className="compare-side">
            <div className="compare-side-header">
              <h4>Predicted</h4>
              <ProvenanceBadge provenance="simulated" size="small" />
            </div>
            <div className={`compare-verdict ${result.simulated.status === 'delivered' ? 'good' : 'bad'}`}>
              {result.simulated.status === 'delivered' ? 'Would be delivered' : 'Would fail'}
            </div>
            <p className="compare-status">{result.simulated.status}</p>
            <ol className="compare-hops">
              {result.simulated.hops.map((hop, i) => (
                <li key={i}>
                  <span className="mono">{hop.node}</span>
                  <span className="compare-hop-action">{hop.action}</span>
                </li>
              ))}
            </ol>
          </div>

          <div className="compare-divider" aria-hidden="true">
            vs
          </div>

          <div className="compare-side">
            <div className="compare-side-header">
              <h4>Actual</h4>
              <ProvenanceBadge
                provenance={labUnavailable ? 'unknown' : 'observed'}
                size="small"
              />
            </div>

            {labUnavailable ? (
              <>
                <div className="compare-verdict unknown">Lab unavailable</div>
                <p className="compare-status">{result.lab.reason}</p>
                <p className="compare-note">
                  Building the lab needs root and network namespace support, so
                  there is nothing to compare against right now. The prediction
                  above is a simulation, not a measurement.
                </p>
              </>
            ) : (
              <>
                <div className={`compare-verdict ${result.lab.status === 'delivered' ? 'good' : 'bad'}`}>
                  {result.lab.status === 'delivered' ? 'Was delivered' : 'Was not delivered'}
                </div>
                <p className="compare-status">{result.lab.status}</p>
              </>
            )}
          </div>
        </div>
      )}

      {result && (
        <div className={`compare-agreement ${result.agree === null ? 'unknown' : result.agree ? 'agree' : 'disagree'}`}>
          {result.agree === null ? (
            <>
              <strong>No verdict.</strong> {result.note}
            </>
          ) : result.agree ? (
            <>
              <strong>They agree.</strong> The simulation predicted the same
              outcome the lab produced.
            </>
          ) : (
            <>
              <strong>They disagree.</strong> The simulation predicted a
              different outcome from the one the lab produced. This is worth
              investigating: the routing table the simulation used and the one
              installed in the lab are not the same.
            </>
          )}
        </div>
      )}
    </div>
  );
}
