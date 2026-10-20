import type { NetworkNeighbor, NeighborsResult } from '../types/routing';

interface NetworkNeighborsProps {
  data: NeighborsResult | null;
  loading: boolean;
  error: string | null;
}

function getStateColor(state: string): string {
  switch (state.toUpperCase()) {
    case 'REACHABLE':
      return 'var(--color-success)';
    case 'STALE':
      return 'var(--color-warning)';
    case 'DELAY':
    case 'PROBE':
      return 'var(--color-info)';
    case 'FAILED':
      return 'var(--color-error)';
    default:
      return 'var(--color-text-muted)';
  }
}

export default function NetworkNeighbors({ data, loading, error }: NetworkNeighborsProps) {
  if (loading) {
    return (
      <div className="loading">
        <span className="spinner" aria-hidden="true"></span>
        Loading neighbors...
      </div>
    );
  }

  if (error) {
    return (
      <div className="error-message" role="alert">
        <span aria-hidden="true">⚠</span>
        Failed to load neighbors: {error}
      </div>
    );
  }

  if (!data?.success || !data.data) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon">🔗</div>
        <p>No neighbor data available</p>
      </div>
    );
  }

  const neighbors = data.data;
  const lookup = data.name_lookup;

  return (
    <div className="network-neighbors">
      <div className="table-container">
        <table className="network-table" role="table">
          <thead>
            <tr>
              <th scope="col">IP Address</th>
              <th scope="col">Name</th>
              <th scope="col">Interface</th>
              <th scope="col">MAC Address</th>
              <th scope="col">State</th>
              <th scope="col">Router</th>
            </tr>
          </thead>
          <tbody>
            {neighbors.map((neigh: NetworkNeighbor, index: number) => (
              <tr key={index}>
                <td className="cell-ip">{neigh.ip_address}</td>
                <td className="cell-name">
                  {neigh.hostname ? (
                    <>
                      <span className="cell-hostname">{neigh.hostname}</span>
                      <span
                        className={`name-provenance ${neigh.name_provenance ?? 'unknown'}`}
                        title={
                          neigh.name_provenance === 'inferred'
                            ? 'This name came from a reverse DNS lookup, not from the kernel.'
                            : 'No reverse DNS name was found for this address.'
                        }
                      >
                        {neigh.name_provenance === 'inferred' ? 'inferred' : 'no name'}
                      </span>
                      {neigh.name_error && (
                        <span className="name-error" title={neigh.name_error}>
                          {neigh.name_error}
                        </span>
                      )}
                    </>
                  ) : (
                    <span className="cell-no-name" title={neigh.name_error ?? undefined}>
                      {neigh.name_provenance === 'not_looked_up'
                        ? 'not looked up'
                        : 'no name found'}
                    </span>
                  )}
                </td>
                <td className="cell-interface">{neigh.interface}</td>
                <td className="cell-mac">{neigh.mac_address ?? '-'}</td>
                <td>
                  <span
                    className="state-badge"
                    style={{ backgroundColor: `${getStateColor(neigh.state)}20`, color: getStateColor(neigh.state) }}
                  >
                    {neigh.state}
                  </span>
                </td>
                <td>
                  {neigh.is_router ? (
                    <span className="router-badge" aria-label="Router">
                      ✓
                    </span>
                  ) : (
                    '-'
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {lookup && (
        <div className="name-lookup-summary">
          <span className="lookup-label">Reverse name lookup</span>
          <span>
            {lookup.found} of {lookup.attempted} name{lookup.attempted === 1 ? '' : 's'} found
          </span>
          {lookup.no_name > 0 && <span>{lookup.no_name} had no name</span>}
          {lookup.skipped > 0 && <span>{lookup.skipped} skipped</span>}
          {lookup.cap_reached && (
            <span className="lookup-cap" title={`Only ${lookup.cap} names are looked up at once.`}>
              cap reached
            </span>
          )}
          <span className="lookup-note">
            The address is observed; the name is inferred.
          </span>
        </div>
      )}

      <div className="collection-meta">
        <span>Collected: {new Date(data.timestamp).toLocaleTimeString()}</span>
        <span>Command: <code>{data.command}</code></span>
        <span>Duration: {data.duration_ms.toFixed(1)}ms</span>
        {data.ip_version && <span>Family: {data.ip_version}</span>}
      </div>
    </div>
  );
}