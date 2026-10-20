import { useMemo } from 'react';
import type { RoutingEntry } from '../types/routing';
import './Visualization.css';

interface VisualizationProps {
  routes: RoutingEntry[];
  selectedRoute: RoutingEntry;
  destination: string;
}

// Helper class to parse and match CIDR networks
class IPNetwork {
  private ip: number[];
  private prefixLength: number;

  constructor(cidr: string) {
    const [ipStr, prefixStr] = cidr.split('/');
    this.prefixLength = parseInt(prefixStr, 10);
    this.ip = ipStr.split('.').map(Number);
  }

  get prefixLen(): number {
    return this.prefixLength;
  }

  contains(ipStr: string): boolean {
    const ip = ipStr.split('.').map(Number);
    const mask = this.prefixLength === 0 ? 0 : (~0 << (32 - this.prefixLength)) >>> 0;
    const networkInt = this.ipToInt(this.ip);
    const ipInt = this.ipToInt(ip);
    return (networkInt & mask) === (ipInt & mask);
  }

  private ipToInt(ip: number[]): number {
    return ((ip[0] << 24) | (ip[1] << 16) | (ip[2] << 8) | ip[3]) >>> 0;
  }
}

export default function Visualization({ routes, selectedRoute, destination }: VisualizationProps) {
  // Find all routes that match the destination
  const matchingRoutes = useMemo(() => {
    return routes
      .filter(route => {
        try {
          const network = new IPNetwork(route.destination);
          return network.contains(destination);
        } catch {
          return false;
        }
      })
      .sort((a, b) => {
        const networkA = new IPNetwork(a.destination);
        const networkB = new IPNetwork(b.destination);
        const prefixA = networkA.prefixLen;
        const prefixB = networkB.prefixLen;
        if (prefixB !== prefixA) return prefixB - prefixA;
        return a.metric - b.metric;
      });
  }, [routes, destination]);

  if (matchingRoutes.length === 0) {
    return (
      <div className="visualization">
        <p className="explanation">No routes match the destination {destination}.</p>
      </div>
    );
  }

  return (
    <div className="visualization">
      <h3 className="visualization-title">
        Decision Flow for <code>{destination}</code>
      </h3>
      <div className="route-flow" role="list" aria-label="Route selection steps">
        {matchingRoutes.map((route, index) => {
          const isSelected = route.destination === selectedRoute.destination &&
                            route.interface === selectedRoute.interface &&
                            route.metric === selectedRoute.metric;
          return (
            <div
              key={`${route.destination}-${route.interface}-${index}`}
              className={`flow-step ${isSelected ? 'selected' : ''}`}
              role="listitem"
              aria-selected={isSelected}
            >
              <div className="flow-step-number" aria-hidden="true">
                {index + 1}
              </div>
              <div className="flow-step-content">
                <span className="flow-step-network">{route.destination}</span>
                <div className="flow-step-meta">
                  <span className="flow-step-meta-item">
                    <span className="flow-step-meta-label">Next hop</span>
                    <span className="mono">{route.next_hop || 'direct'}</span>
                  </span>
                  <span className="flow-step-meta-item">
                    <span className="flow-step-meta-label">Interface</span>
                    <span className="mono">{route.interface}</span>
                  </span>
                  <span className="flow-step-meta-item">
                    <span className="flow-step-meta-label">Metric</span>
                    <span className="mono flow-step-metric">{route.metric}</span>
                  </span>
                  <span className="flow-step-meta-item">
                    <span className="flow-step-meta-label">Type</span>
                    <span className="flow-step-type">{route.next_hop_type}</span>
                  </span>
                </div>
              </div>
              {isSelected && (
                <span className="flow-step-selected-badge" aria-label="Selected route">Selected</span>
              )}
            </div>
          );
        })}
      </div>
      <div className="explanation">
        <strong>Algorithm:</strong> Routes are evaluated in order:
        <ol>
          <li>Filter routes that contain the destination IP</li>
          <li>Select the route with the longest prefix (most specific)</li>
          <li>If tied, choose the lowest metric</li>
          <li>If still tied, use deterministic ordering (interface name, then next hop)</li>
        </ol>
        The highlighted route above is the winner.
      </div>
    </div>
  );
}