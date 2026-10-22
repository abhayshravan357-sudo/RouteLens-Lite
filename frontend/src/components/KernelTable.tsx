/**
 * KernelTable
 *
 * Reads the routing table the running kernel actually holds and explains
 * what it would do with a destination.
 *
 * This is a different claim from the teaching table in the Routing Analyzer.
 * Here the table is OBSERVED — it was read from the kernel — and the
 * conclusion drawn from it is INFERRED. No packet was sent.
 *
 * The two things it shows that the sample table cannot:
 *
 *   - Shadowing. A default route matches everything, so on its own it says
 *     nothing. The more specific routes are the parts of the address space
 *     it really covers.
 *   - Skipped routes. Routes the table holds that the teaching model cannot
 *     express are reported, not quietly dropped.
 */

import { useEffect, useMemo, useState } from 'react';
import { fetchRouteAnalysis } from '../api/routing';
import type {
  RouteAnalysisReport,
  DestinationAnalysis,
  RouteCandidate,
  ShadowFinding,
} from '../types/routing';
import ProvenanceBadge from './ProvenanceBadge';
import CountUp from './CountUp';
import './KernelTable.css';

type Family = 'ipv4' | 'ipv6';

const OUTCOME_LABELS: Record<string, string> = {
  selected: 'Selected',
  'less specific': 'Less specific',
  'higher metric': 'Higher metric',
  tied: 'Tied',
  'not selected': 'Not selected',
};

function candidateTone(outcome: string): string {
  switch (outcome) {
    case 'selected':
      return 'win';
    case 'tied':
      return 'tie';
    case 'higher metric':
      return 'metric';
    default:
      return 'lose';
  }
}

function CandidateRow({ candidate }: { candidate: RouteCandidate }) {
  return (
    <div className={`candidate-row ${candidateTone(candidate.outcome)}`}>
      <div className="candidate-head">
        <span className="candidate-prefix mono">{candidate.destination}</span>
        <span className="candidate-prefix-length">/{candidate.prefix_length}</span>
        <span className={`outcome-chip ${candidateTone(candidate.outcome)}`}>
          {OUTCOME_LABELS[candidate.outcome] ?? candidate.outcome}
        </span>
      </div>
      <div className="candidate-facts">
        <span>
          <span className="fact-label">Next hop</span>
          <span className="fact-value mono">
            {candidate.next_hop ?? 'directly connected'}
          </span>
        </span>
        <span>
          <span className="fact-label">Interface</span>
          <span className="fact-value mono">{candidate.interface}</span>
        </span>
        <span>
          <span className="fact-label">Metric</span>
          <span className="fact-value mono">{candidate.metric}</span>
        </span>
      </div>
      <p className="candidate-explanation">{candidate.explanation}</p>
    </div>
  );
}

function ShadowCard({ finding }: { finding: ShadowFinding }) {
  return (
    <div className="shadow-card">
      <div className="shadow-head">
        <span className="shadow-title">Shadowing</span>
        <ProvenanceBadge provenance="inferred" size="small" />
      </div>
      <p className="shadow-explanation">{finding.explanation}</p>
      {finding.more_specific_destinations.length > 0 && (
        <div className="shadow-facts">
          <span className="fact-label">Routes that take the traffic</span>
          <span className="shadow-destinations mono">
            {finding.more_specific_destinations.join(', ')}
          </span>
        </div>
      )}
      {finding.captured_prefixes.length > 0 && (
        <div className="shadow-facts">
          <span className="fact-label">Address space actually covered</span>
          <span className="shadow-destinations mono">
            {finding.captured_prefixes.join(', ')}
          </span>
        </div>
      )}
    </div>
  );
}

function AnalysisCard({ analysis }: { analysis: DestinationAnalysis }) {
  return (
    <article className={`analysis-card ${analysis.matched ? 'matched' : 'unmatched'}`}>
      <header className="analysis-head">
        <h3 className="analysis-destination mono">{analysis.destination}</h3>
        <span className={`status-badge ${analysis.matched ? 'connected' : 'disconnected'}`}>
          {analysis.matched ? 'Matched' : 'No route'}
        </span>
        {analysis.is_default_route && (
          <span className="default-flag">default route</span>
        )}
      </header>

      {analysis.matched && analysis.selected && (
        <div className="analysis-selected">
          <span className="fact-label">Route selected</span>
          <span className="analysis-selected-value mono">
            {analysis.selected.destination} via{' '}
            {analysis.selected.next_hop ?? 'the attached network'} on{' '}
            {analysis.selected.interface} (metric {analysis.selected.metric})
          </span>
        </div>
      )}

      <p className="analysis-explanation">{analysis.explanation}</p>

      {analysis.candidates.length > 1 && (
        <div className="analysis-candidates">
          <h4>Every route that matched, and why this one won</h4>
          {analysis.candidates.map((candidate) => (
            <CandidateRow
              key={`${candidate.destination}-${candidate.interface}-${candidate.metric}`}
              candidate={candidate}
            />
          ))}
        </div>
      )}

      {analysis.shadowed_by && (
        <div className="analysis-shadow">
          <ShadowCard finding={analysis.shadowed_by} />
        </div>
      )}
    </article>
  );
}

export default function KernelTable() {
  const [family, setFamily] = useState<Family>('ipv4');
  const [destination, setDestination] = useState('');
  const [report, setReport] = useState<RouteAnalysisReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async (nextFamily: Family, dest?: string) => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchRouteAnalysis(dest ?? null, nextFamily);
      setReport(result);
    } catch (err) {
      setReport(null);
      setError(
        err instanceof Error
          ? err.message
          : 'Could not read the routing table'
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load('ipv4');
  }, []);

  /**
   * A backend that predates per-family analysis ignores `ip_version` and
   * returns the IPv4 table regardless. Say so plainly rather than letting
   * an IPv4 table appear under an IPv6 heading.
   */
  const familyMismatch = useMemo(() => {
    if (!report) return null;
    if (report.ip_version) {
      return report.ip_version === family ? null : report.ip_version;
    }
    // No family field. Fall back to the command that was actually run.
    const command = (report.command || '').toLowerCase();
    const commandIsV6 = command.includes('-6') || command.includes('v6');
    if (family === 'ipv6' && !commandIsV6) return 'ipv4';
    if (family === 'ipv4' && commandIsV6) return 'ipv6';
    return null;
  }, [report, family]);

  /**
   * The backend reports a shadow finding once per destination that triggers
   * it, plus one summary for the default route. The same finding therefore
   * arrives several times. It is shown once at the top, and once inside the
   * destination that triggered it, where it is in context.
   */
  const uniqueShadowFindings = useMemo(() => {
    const seen = new Set<string>();
    const unique: ShadowFinding[] = [];
    for (const finding of report?.shadow_findings ?? []) {
      const key = `${finding.less_specific_destination}|${[
        ...finding.more_specific_destinations,
      ].sort().join(',')}|${finding.explanation}`;
      if (seen.has(key)) continue;
      seen.add(key);
      unique.push(finding);
    }
    return unique;
  }, [report]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    load(family, destination.trim() || undefined);
  };

  return (
    <div className="kernel-table">
      <div className="eyebrow eyebrow-lit kernel-eyebrow">
        Observed from the kernel
      </div>

      <form className="kernel-form" onSubmit={handleSubmit}>
        <div className="kernel-family" role="group" aria-label="Address family">
          <button
            type="button"
            className={`family-chip ${family === 'ipv4' ? 'active' : ''}`}
            onClick={() => {
              setFamily('ipv4');
              load('ipv4', destination.trim() || undefined);
            }}
            aria-pressed={family === 'ipv4'}
          >
            IPv4
          </button>
          <button
            type="button"
            className={`family-chip ${family === 'ipv6' ? 'active' : ''}`}
            onClick={() => {
              setFamily('ipv6');
              load('ipv6', destination.trim() || undefined);
            }}
            aria-pressed={family === 'ipv6'}
          >
            IPv6
          </button>
        </div>

        <div className="kernel-destination">
          <label htmlFor="kernel-destination">Destination (optional)</label>
          <input
            id="kernel-destination"
            type="text"
            value={destination}
            onChange={(e) => setDestination(e.target.value)}
            placeholder="Leave empty to analyse the addresses this host cares about"
            spellCheck={false}
          />
        </div>

        <button type="submit" className="btn btn-primary" disabled={loading}>
          {loading ? 'Reading…' : 'Analyse table'}
        </button>
      </form>

      {error && (
        <div className="error-message" role="alert">
          <span aria-hidden="true">⚠</span>
          {error}
        </div>
      )}

      {familyMismatch && (
        <div className="kernel-mismatch" role="status">
          <span aria-hidden="true">⚠</span>
          <span>
            This backend read the <strong>{familyMismatch.toUpperCase()}</strong>{' '}
            table and cannot yet read them separately, so the {familyMismatch.toUpperCase()}{' '}
            request was answered with {familyMismatch.toUpperCase()} data.
          </span>
        </div>
      )}

      {loading && !report && (
        <div className="loading">
          <span className="spinner" aria-hidden="true" />
          Reading the kernel's routing table…
        </div>
      )}

      {report && (
        <>
          <div className="kernel-stats">
            <div className="kernel-stat">
              <span className="stat-label">Routes in table</span>
              <span className="stat-value">
                <CountUp value={report.routes_in_table} />
              </span>
            </div>
            <div className="kernel-stat">
              <span className="stat-label">Analysable</span>
              <span className="stat-value">
                <CountUp value={report.routes_analysed} />
              </span>
            </div>
            <div className="kernel-stat">
              <span className="stat-label">Skipped</span>
              <span
                className={`stat-value ${report.routes_skipped.length > 0 ? 'warning' : 'muted'}`}
              >
                <CountUp value={report.routes_skipped.length} />
              </span>
            </div>
            <div className="kernel-stat">
              <span className="stat-label">Default route</span>
              <span className="stat-value mono">
                {report.default_routes[0] ?? 'none'}
              </span>
            </div>
          </div>

          <div className="kernel-provenance">
            <span>
              Table read by <code className="mono">{report.command}</code> at{' '}
              {new Date(report.collected_at).toLocaleString()}
            </span>
            <span className="kernel-provenance-badges">
              <ProvenanceBadge provenance="observed" size="small" /> the table
              <ProvenanceBadge provenance="inferred" size="small" /> the conclusion
            </span>
          </div>

          {uniqueShadowFindings.length > 0 && (
            <section className="kernel-section">
              <h3 className="panel-title">What the default route really covers</h3>
              <div className="shadow-list">
                {uniqueShadowFindings.map((finding, i) => (
                  <ShadowCard key={i} finding={finding} />
                ))}
              </div>
            </section>
          )}

          {report.analyses.length > 0 && (
            <section className="kernel-section">
              <h3 className="panel-title">
                What the table would do ({report.analyses.length}{' '}
                destination{report.analyses.length === 1 ? '' : 's'})
              </h3>
              <div className="analysis-list">
                {report.analyses.map((analysis) => (
                  <AnalysisCard key={analysis.destination} analysis={analysis} />
                ))}
              </div>
            </section>
          )}

          {report.routes_skipped.length > 0 && (
            <section className="kernel-section">
              <h3 className="panel-title">
                Routes the table holds that this model cannot express (
                {report.routes_skipped.length})
              </h3>
              <div className="skipped-list">
                {report.routes_skipped.map((skipped, i) => (
                  <div key={i} className="skipped-row">
                    <span className="skipped-destination mono">
                      {skipped.destination}
                    </span>
                    <span className="skipped-reason">{skipped.reason}</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          {report.limitations.length > 0 && (
            <section className="kernel-section">
              <h3 className="panel-title">What this analysis cannot tell you</h3>
              <ul className="kernel-limitations">
                {report.limitations.map((limitation, i) => (
                  <li key={i}>{limitation}</li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  );
}
