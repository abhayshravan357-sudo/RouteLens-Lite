import type { NetworkRoute, RoutesResult } from '../types/routing';

interface NetworkRoutesProps {
  data: RoutesResult | null;
  loading: boolean;
  error: string | null;
}

function getProtoColor(proto: string): string {
  switch (proto) {
    case 'kernel':
      return 'var(--color-primary)';
    case 'dhcp':
      return 'var(--color-info)';
    case 'static':
      return 'var(--color-success)';
    default:
      return 'var(--color-text-muted)';
  }
}

export default function NetworkRoutes({ data, loading, error }: NetworkRoutesProps) {
  if (loading) {
    return (
      <div className="loading">
        <span className="spinner" aria-hidden="true"></span>
        Loading routes...
      </div>
    );
  }

  if (error) {
    return (
      <div className="error-message" role="alert">
        <span aria-hidden="true">⚠</span>
        Failed to load routes: {error}
      </div>
    );
  }

  if (!data?.success || !data.data) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon">🛣️</div>
        <p>No route data available</p>
      </div>
    );
  }

  const routes = data.data;

  return (
    <div className="network-routes">
      <div className="table-container">
        <table className="network-table" role="table">
          <thead>
            <tr>
              <th scope="col">Destination</th>
              <th scope="col">Gateway</th>
              <th scope="col">Interface</th>
              <th scope="col">Protocol</th>
              <th scope="col">Scope</th>
              <th scope="col">Metric</th>
              <th scope="col">Preferred Source</th>
            </tr>
          </thead>
          <tbody>
            {routes.map((route: NetworkRoute, index: number) => (
              <tr key={index}>
                <td className="cell-destination">{route.destination}</td>
                <td className="cell-gateway">{route.gateway ?? '-'}</td>
                <td className="cell-interface">{route.interface ?? '-'}</td>
                <td>
                  <span
                    className="type-badge"
                    style={{ backgroundColor: `${getProtoColor(route.proto)}20`, color: getProtoColor(route.proto) }}
                  >
                    {route.proto}
                  </span>
                </td>
                <td>{route.scope}</td>
                <td className="cell-metric">{route.metric ?? '-'}</td>
                <td className="cell-prefsrc">{route.pref_src ?? '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="collection-meta">
        <span>Collected: {new Date(data.timestamp).toLocaleTimeString()}</span>
        <span>Command: <code>{data.command}</code></span>
        <span>Duration: {data.duration_ms.toFixed(1)}ms</span>
      </div>
    </div>
  );
}