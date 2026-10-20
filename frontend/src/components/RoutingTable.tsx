import { useMemo, useState } from 'react';
import type { RoutingEntry } from '../types/routing';
import { IconSearch, IconCopy, IconCheck } from './Icons';
import './RoutingTable.css';

interface RoutingTableProps {
  routes: RoutingEntry[];
  /** Destination of the route that won the last real lookup, if any. */
  bestMatch?: string | null;
}

type Family = 'all' | 'ipv4' | 'ipv6';

function familyOf(destination: string): Family {
  return destination.includes(':') ? 'ipv6' : 'ipv4';
}

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

export default function RoutingTable({ routes, bestMatch = null }: RoutingTableProps) {
  const [query, setQuery] = useState('');
  const [family, setFamily] = useState<Family>('all');

  const counts = useMemo(() => {
    const v4 = routes.filter((r) => familyOf(r.destination) === 'ipv4').length;
    const v6 = routes.length - v4;
    return { v4, v6 };
  }, [routes]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return routes.filter((route) => {
      if (family !== 'all' && familyOf(route.destination) !== family) return false;
      if (!needle) return true;
      return (
        route.destination.toLowerCase().includes(needle) ||
        (route.next_hop ?? '').toLowerCase().includes(needle) ||
        route.interface.toLowerCase().includes(needle)
      );
    });
  }, [routes, query, family]);

  if (routes.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon" aria-hidden="true">
          <IconSearch size={28} />
        </div>
        <p>No routing entries are available.</p>
        <p className="empty-state-hint">
          The backend returned an empty routing table. That is a real result,
          not a failure to load.
        </p>
      </div>
    );
  }

  return (
    <div className="routing-table-wrapper">
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

      {filtered.length === 0 ? (
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
          <table className="routing-table">
            <caption className="visually-hidden">
              {filtered.length} routing{' '}
              {filtered.length === 1 ? 'entry' : 'entries'}
              {query ? ` matching “${query}”` : ''}
            </caption>
            <thead>
              <tr>
                <th scope="col">Destination</th>
                <th scope="col">Next hop</th>
                <th scope="col">Interface</th>
                <th scope="col">Metric</th>
                <th scope="col">Type</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((route, index) => {
                const isBest = bestMatch === route.destination;
                return (
                  <tr
                    key={`${route.destination}-${route.interface}-${index}`}
                    className={isBest ? 'best-match' : undefined}
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
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {filtered.length > 0 && (
        <p className="routing-table-count">
          Showing {filtered.length} of {routes.length}{' '}
          {routes.length === 1 ? 'entry' : 'entries'}
        </p>
      )}
    </div>
  );
}
