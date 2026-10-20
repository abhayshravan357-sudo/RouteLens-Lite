import type { NetworkInterface, InterfacesResult } from '../types/routing';

interface NetworkInterfacesProps {
  data: InterfacesResult | null;
  loading: boolean;
  error: string | null;
}

function formatFlags(flags: string[]): string {
  if (!flags || flags.length === 0) return '-';
  return flags.join(', ');
}

function getStateColor(state: string): string {
  switch (state.toUpperCase()) {
    case 'UP':
      return 'var(--color-success)';
    case 'DOWN':
      return 'var(--color-error)';
    default:
      return 'var(--color-text-muted)';
  }
}

export default function NetworkInterfaces({ data, loading, error }: NetworkInterfacesProps) {
  if (loading) {
    return (
      <div className="loading">
        <span className="spinner" aria-hidden="true"></span>
        Loading interfaces...
      </div>
    );
  }

  if (error) {
    return (
      <div className="error-message" role="alert">
        <span aria-hidden="true">⚠</span>
        Failed to load interfaces: {error}
      </div>
    );
  }

  if (!data?.success || !data.data) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon">🔌</div>
        <p>No interface data available</p>
      </div>
    );
  }

  const interfaces = data.data;

  return (
    <div className="network-interfaces">
      <div className="table-container">
        <table className="network-table" role="table">
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">State</th>
              <th scope="col">MTU</th>
              <th scope="col">MAC Address</th>
              <th scope="col">IPv4 Addresses</th>
              <th scope="col">IPv6 Addresses</th>
              <th scope="col">Flags</th>
            </tr>
          </thead>
          <tbody>
            {interfaces.map((iface: NetworkInterface) => (
              <tr key={iface.name}>
                <td className="cell-name">{iface.name}</td>
                <td>
                  <span
                    className="state-badge"
                    style={{ backgroundColor: `${getStateColor(iface.state)}20`, color: getStateColor(iface.state) }}
                  >
                    {iface.state}
                  </span>
                </td>
                <td className="cell-mtu">{iface.mtu ?? '-'}</td>
                <td className="cell-mac">{iface.mac_address ?? '-'}</td>
                <td>
                  {iface.ipv4_addresses.length > 0 ? (
                    <div className="ip-list">
                      {iface.ipv4_networks.map((net, i) => (
                        <span key={i} className="ip-network">{net}</span>
                      ))}
                    </div>
                  ) : (
                    '-'
                  )}
                </td>
                <td>
                  {iface.ipv6_addresses.length > 0 ? (
                    <div className="ip-list">
                      {iface.ipv6_networks.map((net, i) => (
                        <span key={i} className="ip-network">{net}</span>
                      ))}
                    </div>
                  ) : (
                    '-'
                  )}
                </td>
                <td className="cell-flags">{formatFlags(iface.flags)}</td>
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