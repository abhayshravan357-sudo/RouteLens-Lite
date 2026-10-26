import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import PacketJourney from './PacketJourney';
import type { PacketJourneyResponse, PacketHopResponse } from '../types/routing';

const baseHops: PacketHopResponse[] = [
  {
    hop_number: 1,
    current_device: 'Router A',
    destination_ip: '10.0.0.2',
    action: 'deliver',
    explanation: 'Packet delivered to destination',
    failure_reason: null,
    matched_route: { destination: '10.0.0.0/8', interface: 'eth0', metric: 1 },
    next_hop_ip: '10.0.0.2',
    egress_interface: 'eth0',
  },
];

const baseResponse: PacketJourneyResponse = {
  source_ip: '10.0.0.1',
  destination_ip: '10.0.0.50',
  hops: baseHops,
  success: true,
  error: null,
  failure_code: null,
  provenance: 'simulated',
};

describe('PacketJourney', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders delivered journey', () => {
    render(
      <PacketJourney
        labState="completed"
        labError={null}
        simulationResponse={baseResponse}
        onSimulate={vi.fn()}
        disabled={false}
      />
    );

    expect(screen.getByText('10.0.0.1')).toBeInTheDocument();
    expect(screen.getByText('10.0.0.50')).toBeInTheDocument();
  });

  it('renders failure state with failure_code', () => {
    const failureHops: PacketHopResponse[] = [
      {
        ...baseHops[0],
        destination_ip: '10.0.0.99',
        action: 'drop',
        explanation: 'No route to destination',
        failure_reason: 'no_route',
        matched_route: null,
        next_hop_ip: null,
        egress_interface: null,
      },
    ];

    const failureResponse: PacketJourneyResponse = {
      ...baseResponse,
      source_ip: '10.0.0.1',
      destination_ip: '10.0.0.99',
      hops: failureHops,
      success: false,
      error: 'No route to destination 10.0.0.99',
      failure_code: 'no_route',
    };

    render(
      <PacketJourney
        labState="completed"
        labError={null}
        simulationResponse={failureResponse}
        onSimulate={vi.fn()}
        disabled={false}
      />
    );

    expect(screen.getByText('No route to destination 10.0.0.99')).toBeInTheDocument();
  });

  it('shows IPv6 source and destination IPs', () => {
    const ipv6Hops: PacketHopResponse[] = [
      {
        ...baseHops[0],
        current_device: 'Router A',
        destination_ip: '2001:db8::99',
        action: 'drop',
        explanation: 'No route to destination',
        failure_reason: 'no_route',
        matched_route: null,
        next_hop_ip: null,
        egress_interface: null,
      },
    ];

    const ipv6Response: PacketJourneyResponse = {
      ...baseResponse,
      source_ip: '2001:db8::1',
      destination_ip: '2001:db8::99',
      hops: ipv6Hops,
      success: false,
      error: 'No route to destination 2001:db8::99',
      failure_code: 'no_route',
    };

    render(
      <PacketJourney
        labState="completed"
        labError={null}
        simulationResponse={ipv6Response}
        onSimulate={vi.fn()}
        disabled={false}
      />
    );

    expect(screen.getByText('2001:db8::1')).toBeInTheDocument();
    expect(screen.getAllByText('2001:db8::99').length).toBeGreaterThanOrEqual(1);
  });
});
