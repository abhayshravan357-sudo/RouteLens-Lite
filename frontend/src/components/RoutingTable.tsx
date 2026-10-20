import type { RoutingEntry } from '../types/routing';

interface RoutingTableProps {
  routes: RoutingEntry[];
}

export default function RoutingTable({ routes }: RoutingTableProps) {
  if (routes.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon" aria-hidden="true">📭</div>
        <p>No routing entries available.</p>
        <p className="empty-state-hint">Check if the backend is running and has sample routes configured.</p>
      </div>
    );
  }

  return (
    <div className="table-container" role="region" aria-label="Routing table" tabIndex={0}>
      <table className="routing-table">
        <thead>
          <tr>
            <th scope="col">Destination</th>
            <th scope="col">Next Hop</th>
            <th scope="col">Interface</th>
            <th scope="col">Metric</th>
            <th scope="col">Type</th>
          </tr>
        </thead>
        <tbody>
          {routes.map((route, index) => (
            <tr key={`${route.destination}-${route.interface}-${index}`}>
              <td className="cell-destination">{route.destination}</td>
              <td className={`cell-next-hop ${route.next_hop_type === 'direct' ? 'direct' : ''}`}>
                {route.next_hop || '—'}
              </td>
              <td className="cell-interface">{route.interface}</td>
              <td className="cell-metric">{route.metric}</td>
              <td className="cell-type">
                <span className={`type-badge ${route.next_hop_type}`}>
                  {route.next_hop_type}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}