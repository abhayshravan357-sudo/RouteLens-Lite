/**
 * RoutingTable
 *
 * The live routing table: the one the Route Lookup actually works
 * against. The student can add, change and remove routes here and watch
 * the lookup answer change.
 *
 * This is not the Scenario Lab's table. The scenario tables are a model
 * of someone else's network, used for tracing; this one is the table the
 * lookup reads, and the interface keeps the two visibly apart.
 *
 * Edits are written to disk by the backend, so they survive a restart of
 * the backend. Reset puts the original table back.
 */

import { useMemo, useState } from 'react';
import {
  addRoute,
  deleteRoute,
  resetRoutes,
  updateRoute,
} from '../api/routing';
import type {
  LookupComparison,
  NextHopType,
  RouteLookupResult,
  RouteProvenance,
  RouteRequest,
  RoutingEntry,
} from '../types/routing';
import ProvenanceBadge from './ProvenanceBadge';
import { IconSearch, IconCopy, IconCheck } from './Icons';
import './RoutingTable.css';

// ---------------------------------------------------------------------------
// Reading a CIDR block
//
// The table has to say what each route covers, and whether a more
// specific route hides part of it. That needs the network address, the
// prefix length and the size of the block, for both IPv4 and IPv6, so
// the arithmetic is done with BigInt to keep IPv6 exact.
// ---------------------------------------------------------------------------

interface ParsedCidr {
  family: 4 | 6;
  base: bigint;
  bits: number;
  prefix: number;
  size: bigint;
}

function parseIpv4(text: string): bigint | null {
  const parts = text.split('.');
  if (parts.length !== 4) return null;
  let value = 0n;
  for (const part of parts) {
    if (part.length === 0 || part.length > 3 || !/^\d+$/.test(part)) return null;
    const octet = Number(part);
    if (octet > 255) return null;
    value = (value << 8n) | BigInt(octet);
  }
  return value;
}

function parseIpv6(text: string): bigint | null {
  if (!text.includes(':')) return null;

  const halves = text.split('::');
  if (halves.length > 2) return null;

  const readGroups = (part: string): number[] | null => {
    if (part === '') return [];
    const groups: number[] = [];
    for (const piece of part.split(':')) {
      if (piece === '' || piece.length > 4 || !/^[0-9a-fA-F]+$/.test(piece)) {
        return null;
      }
      groups.push(parseInt(piece, 16));
    }
    return groups;
  };

  const head = readGroups(halves[0]);
  if (head === null) return null;

  if (halves.length === 1) {
    if (head.length !== 8) return null;
    let value = 0n;
    for (const group of head) value = (value << 16n) | BigInt(group);
    return value;
  }

  const tail = readGroups(halves[1]);
  if (tail === null) return null;

  const fill = 8 - head.length - tail.length;
  if (fill < 0) return null;

  const groups = [...head, ...new Array<number>(fill).fill(0), ...tail];
  let value = 0n;
  for (const group of groups) value = (value << 16n) | BigInt(group);
  return value;
}

/** Read a "network/prefix" string. Returns null if it does not make sense. */
function parseCidr(cidr: string): ParsedCidr | null {
  const trimmed = cidr.trim();
  const slash = trimmed.lastIndexOf('/');
  if (slash <= 0 || slash === trimmed.length - 1) return null;

  const address = trimmed.slice(0, slash);
  const prefixText = trimmed.slice(slash + 1);
  if (!/^\d+$/.test(prefixText)) return null;
  const prefix = Number(prefixText);

  const v4 = parseIpv4(address);
  if (v4 !== null) {
    if (prefix > 32) return null;
    const hostBits = BigInt(32 - prefix);
    const size = 1n << hostBits;
    const base = (v4 >> hostBits) << hostBits;
    return { family: 4, base, bits: 32, prefix, size };
  }

  const v6 = parseIpv6(address);
  if (v6 !== null) {
    if (prefix > 128) return null;
    const hostBits = BigInt(128 - prefix);
    const size = 1n << hostBits;
    const base = (v6 >> hostBits) << hostBits;
    return { family: 6, base, bits: 128, prefix, size };
  }

  return null;
}

function formatIpv4(value: bigint): string {
  const octets: number[] = [];
  for (let shift = 24n; shift >= 0n; shift -= 8n) {
    octets.push(Number((value >> shift) & 0xffn));
  }
  return octets.join('.');
}

function formatIpv6(value: bigint): string {
  const groups: number[] = [];
  for (let shift = 112n; shift >= 0n; shift -= 16n) {
    groups.push(Number((value >> shift) & 0xffffn));
  }

  // Collapse the longest run of zero groups into "::".
  let bestStart = -1;
  let bestLength = 0;
  let runStart = -1;
  let runLength = 0;
  for (let i = 0; i < groups.length; i += 1) {
    if (groups[i] === 0) {
      if (runStart === -1) runStart = i;
      runLength += 1;
      if (runLength > bestLength) {
        bestLength = runLength;
        bestStart = runStart;
      }
    } else {
      runStart = -1;
      runLength = 0;
    }
  }

  if (bestLength < 2) {
    return groups.map((g) => g.toString(16)).join(':');
  }

  const head = groups.slice(0, bestStart).map((g) => g.toString(16)).join(':');
  const tail = groups.slice(bestStart + bestLength).map((g) => g.toString(16)).join(':');
  return `${head}::${tail}`;
}

function formatCount(value: bigint): string {
  return value.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

/** What a single route does, worked out from the rest of the table. */
interface RouteEffect {
  /** The addresses the route covers, in words. */
  coverage: string;
  /** Routes with a longer prefix that sit inside this one. */
  shadowedBy: string[];
  /** Routes with the same prefix that beat this one on metric. */
  beatenBy: string[];
  /** Routes with a shorter prefix that this one overrides. */
  overrides: string[];
  /** One line for the student to read. */
  verdict: string;
}

/**
 * Work out, for each route, what it covers and what happens to it.
 *
 * A route is hidden when a more specific route covers part of it,
 * because the lookup prefers the longer prefix. A route with the same
 * prefix loses to the one with the lower metric.
 */
function analyseRoutes(routes: RoutingEntry[]): Map<number, RouteEffect> {
  const parsed = routes.map((route) => parseCidr(route.destination));
  const effects = new Map<number, RouteEffect>();

  for (let i = 0; i < routes.length; i += 1) {
    const route = routes[i];
    const network = parsed[i];

    if (!network) {
      effects.set(i, {
        coverage: 'Not a readable network',
        shadowedBy: [],
        beatenBy: [],
        overrides: [],
        verdict: 'The backend has not accepted this network yet.',
      });
      continue;
    }

    const first = network.base;
    const last = network.base + network.size - 1n;
    const coverage =
      network.family === 4
        ? `${formatIpv4(first)} – ${formatIpv4(last)} · ${formatCount(network.size)} addresses`
        : `${formatIpv6(first)} – ${formatIpv6(last)} · ${formatCount(network.size)} addresses`;

    const shadowedBy: string[] = [];
    const beatenBy: string[] = [];
    const tiedWith: string[] = [];
    const overrides: string[] = [];

    for (let j = 0; j < routes.length; j += 1) {
      if (i === j) continue;
      const other = parsed[j];
      if (!other) continue;
      // Only routes of the same family can hide each other.
      if (other.family !== network.family) continue;

      const otherEnd = other.base + other.size - 1n;
      const thisEnd = network.base + network.size - 1n;
      const otherInside =
        other.base >= network.base && otherEnd <= thisEnd;

      if (other.prefix > network.prefix && otherInside) {
        shadowedBy.push(routes[j].destination);
      } else if (other.prefix === network.prefix) {
        if (routes[j].metric < route.metric) {
          beatenBy.push(
            `${routes[j].destination} via ${routes[j].next_hop ?? 'direct'} (metric ${routes[j].metric})`
          );
        } else if (routes[j].metric === route.metric) {
          // Same prefix and same metric: the backend settles it on the
          // interface name, so say that rather than claiming a winner.
          tiedWith.push(
            `${routes[j].destination} on ${routes[j].interface}`
          );
        }
      } else if (other.prefix < network.prefix && otherInside) {
        overrides.push(routes[j].destination);
      }
    }

    // Every applicable fact is shown, not just the first one. A route can
    // be hidden by a longer prefix and still lose to a rival on metric.
    const facts: string[] = [];
    if (shadowedBy.length > 0) {
      facts.push(
        `Partly hidden by ${shadowedBy.join(', ')} — a longer prefix wins there.`
      );
    }
    if (beatenBy.length > 0) {
      facts.push(`Loses to ${beatenBy.join(', ')} — same prefix, lower metric.`);
    }
    if (tiedWith.length > 0) {
      facts.push(
        `Tied with ${tiedWith.join(', ')} — the interface name breaks the tie.`
      );
    }
    if (overrides.length > 0) {
      facts.push(`Wins over ${overrides.join(', ')} — a longer prefix beats them.`);
    }
    const verdict =
      facts.length > 0
        ? facts.join(' ')
        : 'Nothing in the table competes with this route.';

    effects.set(i, {
      coverage,
      shadowedBy,
      beatenBy,
      overrides,
      verdict,
    });
  }

  return effects;
}

// ---------------------------------------------------------------------------
// The form
// ---------------------------------------------------------------------------

interface RouteDraft {
  destination: string;
  next_hop: string;
  interface: string;
  metric: string;
  next_hop_type: NextHopType;
}

const EMPTY_DRAFT: RouteDraft = {
  destination: '',
  next_hop: '',
  interface: '',
  metric: '10',
  next_hop_type: 'gateway',
};

function toDraft(route: RoutingEntry): RouteDraft {
  return {
    destination: route.destination,
    next_hop: route.next_hop ?? '',
    interface: route.interface,
    metric: String(route.metric),
    next_hop_type: route.next_hop_type,
  };
}

/**
 * Build the request body.
 *
 * The values go to the backend as the student typed them. The rules
 * about what a valid network or metric looks like live in the backend,
 * which writes the messages a student reads, so they are not repeated
 * here.
 */
function toRequest(draft: RouteDraft, provenance: RouteProvenance): RouteRequest {
  const metricText = draft.metric.trim();
  const metric: number | string = /^-?\d+$/.test(metricText)
    ? Number(metricText)
    : metricText;

  return {
    destination: draft.destination.trim(),
    next_hop: draft.next_hop_type === 'direct' ? null : draft.next_hop.trim(),
    interface: draft.interface.trim(),
    metric,
    next_hop_type: draft.next_hop_type,
    provenance,
  };
}

/** True when the student changed something the route means. */
function meaningChanged(draft: RouteDraft, original: RoutingEntry): boolean {
  return (
    draft.destination.trim() !== original.destination ||
    (draft.next_hop_type === 'direct' ? null : draft.next_hop.trim()) !==
      original.next_hop ||
    draft.interface.trim() !== original.interface ||
    String(original.metric) !== draft.metric.trim() ||
    draft.next_hop_type !== original.next_hop_type
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

type Family = 'all' | 'ipv4' | 'ipv6';

function familyOf(destination: string): Family {
  return destination.includes(':') ? 'ipv6' : 'ipv4';
}

/**
 * A value with a copy button beside it.
 *
 * The clipboard can be refused by the browser; the value stays on screen
 * either way, so a refusal is not worth an error message.
 */
function CopyValue({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      // Clipboard access can be refused; the value is still on screen.
    }
  };

  return (
    <span className="copyable">
      <span>{value}</span>
      <button
        type="button"
        className="copy-button"
        onClick={copy}
        aria-label={`Copy ${label} ${value}`}
        title={`Copy ${value}`}
      >
        {copied ? <IconCheck size={12} /> : <IconCopy size={12} />}
      </button>
    </span>
  );
}

interface RoutingTableProps {
  routes: RoutingEntry[];
  /**
   * Called after the table changed, so the lookup can be run again and
   * the student can see the new answer beside the old one.
   */
  onTableChanged?: () => void | Promise<void>;
  /** The lookup result before and after the last change. */
  comparison?: LookupComparison | null;
  /** The result of the current lookup, used to label the comparison. */
  lookupResult?: RouteLookupResult | null;
  /** Where the current lookup was aimed. */
  lookupDestination?: string;
  /**
   * Destination of the route that won the last real lookup, if any.
   * The row it names is marked, so the winning route is findable in a
   * long table.
   */
  bestMatch?: string | null;
}

export default function RoutingTable({
  routes,
  onTableChanged,
  comparison = null,
  lookupResult = null,
  lookupDestination = '',
  bestMatch = null,
}: RoutingTableProps) {
  const [draft, setDraft] = useState<RouteDraft>(EMPTY_DRAFT);
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [family, setFamily] = useState<Family>('all');

  const effects = useMemo(() => analyseRoutes(routes), [routes]);

  // The route that won the last lookup. The caller may name it directly,
  // or it may come from the lookup result it already holds.
  const winningDestination =
    bestMatch ?? lookupResult?.route?.destination ?? null;

  // The filter is over what the student reads, not over what the backend
  // holds, so a hidden row is still there to be edited.
  const counts = useMemo(() => {
    const v4 = routes.filter((r) => familyOf(r.destination) === 'ipv4').length;
    return { v4, v6: routes.length - v4 };
  }, [routes]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return routes
      .map((route, index) => ({ route, index }))
      .filter(({ route }) => {
        if (family !== 'all' && familyOf(route.destination) !== family) {
          return false;
        }
        if (!needle) return true;
        return (
          route.destination.toLowerCase().includes(needle) ||
          (route.next_hop ?? '').toLowerCase().includes(needle) ||
          route.interface.toLowerCase().includes(needle)
        );
      });
  }, [routes, query, family]);

  // Pulled out of the comparison so the rest of the markup does not have
  // to narrow them again.
  const before = comparison?.before ?? null;
  const after = comparison?.after ?? null;
  const comparisonDestination = comparison?.destination ?? lookupDestination;
  const answerChanged =
    before !== null && after !== null && describeLookup(before) !== describeLookup(after);

  const startAdding = () => {
    setEditingIndex(null);
    setDraft(EMPTY_DRAFT);
    setFormOpen(true);
    setError(null);
    setNotice(null);
  };

  const startEditing = (index: number) => {
    setEditingIndex(index);
    setDraft(toDraft(routes[index]));
    setFormOpen(true);
    setError(null);
    setNotice(null);
  };

  const cancelEditing = () => {
    setEditingIndex(null);
    setDraft(EMPTY_DRAFT);
    setFormOpen(false);
    setError(null);
  };

  const handleChange = (field: keyof RouteDraft, value: string) => {
    setDraft((prev) => ({ ...prev, [field]: value }));
    if (error) setError(null);
  };

  /** Run a change, then let the rest of the app catch up. */
  const applyChange = async (action: () => Promise<string>) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const message = await action();
      setNotice(message);
      setEditingIndex(null);
      setDraft(EMPTY_DRAFT);
      setFormOpen(false);
      await onTableChanged?.();
    } catch (err) {
      // The backend's own words, written for a student to read.
      setError(err instanceof Error ? err.message : 'The change did not go through.');
    } finally {
      setBusy(false);
    }
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();

    if (editingIndex === null) {
      // A route the student typed is modelled, not observed.
      const body = toRequest(draft, 'simulated');
      await applyChange(() =>
        addRoute(body).then(() => `Added ${body.destination}.`)
      );
      return;
    }

    const original = routes[editingIndex];
    if (!original) {
      setError('That route is no longer in the table.');
      setEditingIndex(null);
      return;
    }

    // Keep the provenance the route already had, unless the student
    // changed what the route means. A changed route is a modelled one.
    const provenance: RouteProvenance = meaningChanged(draft, original)
      ? 'simulated'
      : original.provenance ?? 'unknown';
    const body = toRequest(draft, provenance);

    await applyChange(() =>
      updateRoute(editingIndex, body).then(() => `Updated ${body.destination}.`)
    );
  };

  const handleDelete = async (index: number) => {
    const route = routes[index];
    if (!route) return;
    await applyChange(() =>
      deleteRoute(index).then(() => `Deleted ${route.destination}.`)
    );
  };

  const handleReset = async () => {
    await applyChange(() =>
      resetRoutes().then(() => 'Restored the original table.')
    );
  };

  return (
    <div className="routing-table-panel">
      <div className="routing-table-notices">
        <div className="routing-table-notice routing-table-notice-info">
          <span aria-hidden="true">ℹ</span>
          <div>
            <strong>This is the live table the Route Lookup works against.</strong>{' '}
            It is not the Scenario Lab&rsquo;s table, which is a model of
            someone else&rsquo;s network used for tracing. Changes here change
            the lookup answer directly.
          </div>
        </div>
        <div className="routing-table-notice routing-table-notice-warning">
          <span aria-hidden="true">⚠</span>
          <div>
            <strong>Edits are saved to disk.</strong> They survive a restart
            of the backend, so the table you leave behind is the table you
            come back to. Use <em>Reset to original</em> to put the
            original table back at any time.
          </div>
        </div>
      </div>

      {before !== null && after !== null && (
        <div className="routing-table-comparison" role="status">
          <h4 className="routing-table-comparison-title">
            What your change did to the lookup for{' '}
            <code>{comparisonDestination}</code>
          </h4>
          <div className="routing-table-comparison-columns">
            <div className="routing-table-comparison-column">
              <span className="routing-table-comparison-label">Before</span>
              <p className="routing-table-comparison-answer">
                {describeLookup(before)}
              </p>
            </div>
            <span className="routing-table-comparison-arrow" aria-hidden="true">
              →
            </span>
            <div className="routing-table-comparison-column">
              <span className="routing-table-comparison-label">After</span>
              <p
                className={`routing-table-comparison-answer ${
                  answerChanged ? 'changed' : 'unchanged'
                }`}
              >
                {describeLookup(after)}
              </p>
            </div>
          </div>
          {lookupResult && (
            <p className="routing-table-comparison-note">
              The Route Lookup section below now shows the new answer for{' '}
              <code>{lookupDestination}</code>.
            </p>
          )}
        </div>
      )}

      {error && (
        <div className="error-message" role="alert">
          <span aria-hidden="true">⚠</span>
          {error}
        </div>
      )}

      {notice && !error && (
        <div className="routing-table-notice routing-table-notice-success" role="status">
          <span aria-hidden="true">✓</span>
          <div>{notice}</div>
        </div>
      )}

      {routes.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon" aria-hidden="true">
            <IconSearch size={28} />
          </div>
          <p>The routing table is empty, so no destination can be reached.</p>
          <p className="empty-state-hint">
            Add a route, or restore the original table with Reset.
          </p>
        </div>
      ) : (
        <>
          <div className="routing-table-toolbar">
            <div className="routing-search">
              <span className="routing-search-icon" aria-hidden="true">
                <IconSearch size={15} />
              </span>
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Filter by prefix, next hop or interface"
                aria-label="Filter routing table"
                spellCheck={false}
              />
            </div>

            <div className="routing-families" role="group" aria-label="Address family">
              <button
                type="button"
                className={`family-chip ${family === 'all' ? 'active' : ''}`}
                onClick={() => setFamily('all')}
                aria-pressed={family === 'all'}
              >
                All <span className="family-count">{routes.length}</span>
              </button>
              <button
                type="button"
                className={`family-chip ${family === 'ipv4' ? 'active' : ''}`}
                onClick={() => setFamily('ipv4')}
                aria-pressed={family === 'ipv4'}
              >
                IPv4 <span className="family-count">{counts.v4}</span>
              </button>
              <button
                type="button"
                className={`family-chip ${family === 'ipv6' ? 'active' : ''}`}
                onClick={() => setFamily('ipv6')}
                aria-pressed={family === 'ipv6'}
              >
                IPv6 <span className="family-count">{counts.v6}</span>
              </button>
            </div>
          </div>

          {visible.length === 0 ? (
            <div className="empty-state">
              <p>Nothing matches that filter.</p>
              <p className="empty-state-hint">
                {query
                  ? `No prefix, next hop or interface contains “${query}”.`
                  : 'No routes in this address family.'}
              </p>
            </div>
          ) : (
            <div className="table-container" role="region" aria-label="Routing table" tabIndex={0}>
              <table className="routing-table routing-table-editable">
                <caption className="visually-hidden">
                  {visible.length} routing{' '}
                  {visible.length === 1 ? 'entry' : 'entries'}
                  {query ? ` matching “${query}”` : ''}
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Destination</th>
                    <th scope="col">Next Hop</th>
                    <th scope="col">Interface</th>
                    <th scope="col">Metric</th>
                    <th scope="col">Type</th>
                    <th scope="col">Source</th>
                    <th scope="col">What it does</th>
                    <th scope="col" aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {visible.map(({ route, index }) => {
                    const effect = effects.get(index);
                    const isEditing = editingIndex === index;
                    const isBest = winningDestination === route.destination;
                    return (
                      <tr
                        key={`${route.destination}-${route.interface}-${index}`}
                        className={[
                          'routing-table-row',
                          isEditing ? 'editing' : '',
                          isBest ? 'best-match' : '',
                        ]
                          .filter(Boolean)
                          .join(' ')}
                      >
                        <td className="cell-destination">
                          <CopyValue value={route.destination} label="prefix" />
                          {isBest && (
                            <span className="best-match-flag">best match</span>
                          )}
                        </td>
                        <td
                          className={`cell-next-hop ${
                            route.next_hop_type === 'direct' ? 'direct' : ''
                          }`}
                        >
                          {route.next_hop ? (
                            <CopyValue value={route.next_hop} label="next hop" />
                          ) : (
                            '—'
                          )}
                        </td>
                        <td className="cell-interface">{route.interface}</td>
                        <td className="cell-metric">{route.metric}</td>
                        <td className="cell-type">
                          <span className={`type-badge ${route.next_hop_type}`}>
                            {route.next_hop_type}
                          </span>
                        </td>
                        <td className="cell-provenance">
                          <ProvenanceBadge
                            provenance={route.provenance ?? 'unknown'}
                            size="small"
                          />
                        </td>
                        <td className="cell-effect">
                          {effect ? (
                            <>
                              <span className="routing-table-coverage">
                                {effect.coverage}
                              </span>
                              <span
                                className={`routing-table-verdict ${
                                  effect.shadowedBy.length > 0 ||
                                  effect.beatenBy.length > 0
                                    ? 'shadowed'
                                    : 'clear'
                                }`}
                              >
                                {effect.verdict}
                              </span>
                            </>
                          ) : (
                            '—'
                          )}
                        </td>
                        <td className="cell-actions">
                          <button
                            type="button"
                            className="btn btn-sm btn-secondary"
                            onClick={() => startEditing(index)}
                            disabled={busy}
                          >
                            Edit
                          </button>
                          <button
                            type="button"
                            className="btn btn-sm routing-table-delete"
                            onClick={() => handleDelete(index)}
                            disabled={busy}
                          >
                            Delete
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {visible.length > 0 && (
            <p className="routing-table-count">
              Showing {visible.length} of {routes.length}{' '}
              {routes.length === 1 ? 'entry' : 'entries'}
            </p>
          )}
        </>
      )}

      <div className="routing-table-actions">
        <button
          type="button"
          className="btn btn-secondary"
          onClick={startAdding}
          disabled={busy}
        >
          + Add route
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={handleReset}
          disabled={busy}
        >
          Reset to original
        </button>
      </div>

      {formOpen && (
        <form className="routing-table-form" onSubmit={handleSubmit} noValidate>
          <h4 className="routing-table-form-title">
            {editingIndex === null
              ? 'Add a route'
              : `Edit route ${editingIndex + 1} (${routes[editingIndex]?.destination ?? ''})`}
          </h4>
          <p className="routing-table-form-hint">
            Type what you want. The backend checks it and explains anything
            it will not accept.
          </p>

          <div className="routing-table-form-grid">
            <div className="input-group">
              <label htmlFor="route-destination">Destination network</label>
              <input
                id="route-destination"
                type="text"
                value={draft.destination}
                onChange={(e) => handleChange('destination', e.target.value)}
                placeholder="192.168.1.0/25"
                spellCheck={false}
                disabled={busy}
              />
            </div>

            <div className="input-group">
              <label htmlFor="route-next-hop">Next hop</label>
              <input
                id="route-next-hop"
                type="text"
                value={draft.next_hop}
                onChange={(e) => handleChange('next_hop', e.target.value)}
                placeholder="10.0.0.2"
                spellCheck={false}
                disabled={busy || draft.next_hop_type === 'direct'}
              />
            </div>

            <div className="input-group">
              <label htmlFor="route-interface">Interface</label>
              <input
                id="route-interface"
                type="text"
                value={draft.interface}
                onChange={(e) => handleChange('interface', e.target.value)}
                placeholder="eth1"
                spellCheck={false}
                disabled={busy}
              />
            </div>

            <div className="input-group">
              <label htmlFor="route-metric">Metric</label>
              <input
                id="route-metric"
                type="text"
                inputMode="numeric"
                value={draft.metric}
                onChange={(e) => handleChange('metric', e.target.value)}
                placeholder="10"
                disabled={busy}
              />
            </div>

            <div className="input-group">
              <label htmlFor="route-type">Next hop type</label>
              <select
                id="route-type"
                value={draft.next_hop_type}
                onChange={(e) =>
                  handleChange('next_hop_type', e.target.value as NextHopType)
                }
                disabled={busy}
              >
                <option value="gateway">gateway</option>
                <option value="direct">direct</option>
              </select>
            </div>
          </div>

          <div className="routing-table-form-actions">
            <button
              type="submit"
              className="btn btn-primary"
              disabled={busy}
            >
              {busy
                ? 'Working…'
                : editingIndex === null
                  ? 'Add route'
                  : 'Save route'}
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={cancelEditing}
              disabled={busy}
            >
              Cancel
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

/** One line saying what a lookup answered. */
function describeLookup(result: RouteLookupResult): string {
  if (result.error) return `Refused: ${result.error}`;
  if (!result.matched) {
    return 'No route matched, so the destination is unreachable.';
  }
  if (!result.route) return 'No route matched.';
  return `${result.route.destination} via ${result.route.next_hop ?? 'direct'} on ${result.route.interface} (metric ${result.route.metric})`;
}
