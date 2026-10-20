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
  transmitted: boolean;
}

/**
 * Packet Lab types - matching the FastAPI backend Pydantic models exactly.
 * Backend source: backend/app/packet_lab_routes.py
 */

export interface LabStatusResponse {
  available: boolean;
  state: LabState;
  message: string;
  router_info: RouterInfo | null;
  error: string | null;
}

export interface RouterInfo {
  interfaces: string[];
  routing_table: RouterRouteEntry[];
  client_ip: string | null;
  server_ip: string | null;
}

export interface RouterRouteEntry {
  destination: string;
  next_hop: string | null;
  interface: string;
}

export interface SimulateRequest {
  source_ip: string;
  destination_ip: string;
  protocol: 'icmp';
  ttl: number;
  length: number;
  route_matched: string | null;
  egress_interface: string | null;
  next_hop: string | null;
}

export interface ForwardingInfoResponse {
  ingress_interface: string;
  egress_interface: string;
  next_hop: string;
  route_matched: string;
  action: string;
}

export interface PacketResponse {
  source_ip: string;
  destination_ip: string;
  protocol: string;
  ttl: number;
  length: number;
  forwarding_info: ForwardingInfoResponse;
}

export interface VerificationDetails {
  ttl_decremented: boolean;
  checksum_valid: boolean;
  route_matched: boolean;
}

export interface SimulateResponse {
  state: LabState;
  message: string;
  packet: PacketResponse | null;
  capture_verified: boolean;
  verification_details: VerificationDetails | null;
  error: string | null;
}

/**
 * Network Collector types - matching the FastAPI backend Pydantic models exactly.
 * Backend source: backend/app/network_collector.py
 */

export interface NetworkInterface {
  name: string;
  index: number;
  state: string;
  mtu: number | null;
  mac_address: string | null;
  ipv4_addresses: string[];
  ipv4_networks: string[];
  ipv6_addresses: string[];
  ipv6_networks: string[];
  flags: string[];
}

export interface NetworkRoute {
  destination: string;
  gateway: string | null;
  interface: string | null;
  metric: number | null;
  proto: string;
  scope: string;
  pref_src: string | null;
}

export interface NetworkNeighbor {
  ip_address: string;
  interface: string;
  mac_address: string | null;
  state: string;
  is_router: boolean;
}

export interface CollectionResult<T> {
  timestamp: string;
  success: boolean;
  data: T | null;
  error: string | null;
  command: string;
  duration_ms: number;
}

export type InterfacesResult = CollectionResult<NetworkInterface[]>;
export type RoutesResult = CollectionResult<NetworkRoute[]>;
export type NeighborsResult = CollectionResult<NetworkNeighbor[]>;
export type AllNetworkResult = {
  interfaces: InterfacesResult;
  routes: RoutesResult;
  neighbors: NeighborsResult;
};

/**
 * Network Diagnostics types - matching the FastAPI backend Pydantic models exactly.
 * Backend source: backend/app/main.py (DNS, connectivity, traceroute endpoints)
 */

export interface DnsResolveRequest {
  hostname: string;
  timeout: number;
  ipv6?: boolean;
}

export interface DnsRecord {
  address: string;
  type: string; // 'A' or 'AAAA'
  ttl?: number;
}

export interface DnsResolveResponse {
  hostname: string;
  addresses: DnsRecord[];
  latency_ms: number;
  error: string | null;
}

export interface ConnectivityCheckRequest {
  target: string;
  port?: number;
  protocol: 'icmp' | 'tcp';
  timeout: number;
  count?: number;
  interval?: number;
}

export interface ConnectivityCheckResponse {
  target: string;
  port: number | null;
  protocol: string;
  reachable: boolean;
  latency_ms: number;
  packets_sent?: number;
  packets_received?: number;
  packet_loss_percent?: number;
  rtt_min_ms?: number;
  rtt_avg_ms?: number;
  rtt_max_ms?: number;
  rtt_mdev_ms?: number;
  error: string | null;
}

export interface TracerouteHopResponse {
  ttl: number;
  address: string | null;
  hostname: string | null;
  rtt_ms: number | null;
  error: string | null;
}

export interface TracerouteRequest {
  target: string;
  max_hops: number;
  timeout_per_hop: number;
  probes_per_hop: number;
  overall_timeout: number;
}

export interface TracerouteResponse {
  target: string;
  hops: TracerouteHopResponse[];
  max_hops: number;
  timeout_per_hop: number;
  probes_per_hop: number;
  completed: boolean;
  total_time_ms: number;
  error: string | null;
}

export interface TracerouteHopResponse {
  ttl: number;
  address: string | null;
  hostname: string | null;
  rtt_ms: number | null;
  error: string | null;
}

export interface TracerouteRequest {
  target: string;
  max_hops: number;
  timeout_per_hop: number;
  probes_per_hop: number;
  overall_timeout: number;
}

export interface TracerouteResponse {
  target: string;
  hops: TracerouteHopResponse[];
  max_hops: number;
  timeout_per_hop: number;
  probes_per_hop: number;
  completed: boolean;
  total_time_ms: number;
  error: string | null;
}

export interface TracerouteResponse {
  target: string;
  hops: TracerouteHopResponse[];
  max_hops: number;
  timeout_per_hop: number;
  probes_per_hop: number;
  completed: boolean;
  total_time_ms: number;
  error: string | null;
}

export interface PacketJourneyRequest {
  source_ip: string;
  destination_ip: string;
}

export interface PacketHopResponse {
  hop_number: number;
  current_device: string;
  destination_ip: string;
  action: string;
  explanation: string;
  matched_route?: {
    destination: string;
    next_hop: string | null;
    interface: string;
    metric: number;
  };
  next_hop_ip?: string;
  egress_interface?: string;
}

export interface PacketJourneyResponse {
  source_ip: string;
  destination_ip: string;
  hops: PacketHopResponse[];
  success: boolean;
  error: string | null;
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
/**
 * Scenario engine types - matching backend/app/scenario.py exactly.
 */

export type ScenarioNodeKind = 'host' | 'router';

export type TraceStatus =
  | 'delivered'
  | 'no_route'
  | 'unresolved_next_hop'
  | 'not_forwarding'
  | 'loop'
  | 'max_hops';

export type HopAction = 'forward' | 'delivered' | 'dropped';

export interface ScenarioIface {
  name: string;
  cidr: string;
}

export interface ScenarioRoute {
  prefix: string;
  dev: string;
  via: string | null;
  metric: number;
  source: 'connected' | 'static';
}

export interface ScenarioNode {
  id: string;
  kind: ScenarioNodeKind;
  ifaces: ScenarioIface[];
  routes: ScenarioRoute[];
}

export interface ScenarioLink {
  a: string;
  b: string;
}

export interface ScenarioSummary {
  id: string;
  title: string;
}

export interface Scenario {
  id: string;
  title: string;
  nodes: ScenarioNode[];
  links: ScenarioLink[];
}

export interface TraceHop {
  node: string;
  action: HopAction;
  matched: ScenarioRoute | null;
  candidates: ScenarioRoute[];
  explanation: string;
  next_node: string | null;
  hop_number: number;
}

export interface ScenarioTrace {
  status: TraceStatus;
  hops: TraceHop[];
  provenance: 'simulated';
}

export interface ScenarioTraceRequest {
  src: string;
  dst: string;
  /** Workspace id returned by a route edit, so the edit is traced. */
  workspace?: string | null;
}

export interface LabRunResult {
  status: 'dry_run' | 'ok' | 'failed' | 'unavailable';
  log?: { cmd: string; rc: number; stdout?: string; stderr?: string }[];
  commands?: string[];
  reason?: string;
  failed_at?: string[];
}

export interface LabProbeResult {
  status: 'delivered' | 'failed' | 'timeout' | 'unavailable' | 'error';
  rc?: number;
  output?: string;
  reason?: string;
  provenance?: 'lab';
}

export interface ScenarioCompare {
  simulated: ScenarioTrace;
  lab: LabProbeResult;
  agree: boolean | null;
  note: string;
}

/**
 * Evidence-based topology types - matching backend/app/topology.py.
 */

export type TopologyProvenance = 'observed' | 'inferred' | 'simulated' | 'unknown';

export interface TopologyNode {
  id: string;
  kind: 'host' | 'router' | 'interface' | 'gateway' | 'neighbor' | 'unknown';
  label: string;
  provenance: TopologyProvenance;
  addresses: string[];
  detail: string | null;
}

export interface TopologyEdge {
  source: string;
  target: string;
  kind: string;
  provenance: TopologyProvenance;
  label: string;
  detail: string | null;
}

export interface TopologyGraph {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
  provenance: TopologyProvenance;
  explanation: string;
  observed_at: string;
}
