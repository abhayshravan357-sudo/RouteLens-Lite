/**
 * Type definitions matching the FastAPI backend models.
 */

export type NextHopType = 'gateway' | 'direct';

export interface RoutingEntry {
  destination: string;
  next_hop: string | null;
  interface: string;
  metric: number;
  next_hop_type: NextHopType;
}

export interface RouteLookupResult {
  matched: boolean;
  route: RoutingEntry | null;
  explanation: string;
  error: string | null;
}

/**
 * Packet Lab types - placeholder for future packet-lab API integration.
 * These types will be updated when Agent B provides the packet-lab contract.
 * Do not invent endpoint paths or response fields.
 */

export type PacketProtocol = 'tcp' | 'udp' | 'icmp' | 'other';

export interface PacketDetails {
  source_ip: string;
  destination_ip: string;
  protocol: PacketProtocol;
  ttl: number;
  length: number;
  forwarding_info?: ForwardingInfo;
}

export interface ForwardingInfo {
  ingress_interface: string;
  egress_interface: string | null;
  next_hop: string | null;
  route_matched: string;
  action: 'forward' | 'drop' | 'local';
}

export type LabState =
  | 'idle'
  | 'ready'
  | 'simulating'
  | 'transmitting'
  | 'capturing'
  | 'verifying'
  | 'completed'
  | 'error'
  | 'timeout'
  | 'unavailable';

export interface PacketLabStatus {
  state: LabState;
  message: string;
  packet?: PacketDetails;
  capture_verified?: boolean;
  error?: string;
}