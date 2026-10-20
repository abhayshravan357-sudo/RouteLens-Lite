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
  /**
   * A reverse DNS name for the address, when one could be looked up.
   *
   * The address itself is OBSERVED — the kernel reported it. The name is
   * INFERRED — it came from a reverse DNS query, not from the kernel. The
   * two are kept apart, which is what `name_provenance` records.
   */
  hostname?: string | null;
  /** "inferred" when a name was found, "not_looked_up" or "unknown" otherwise. */
  name_provenance?: string;
  name_error?: string | null;
}

/**
 * How the reverse name lookup went.
 * Backend: NameLookupSummary
 */
export interface NameLookupSummary {
  attempted: number;
  found: number;
  no_name: number;
  skipped: number;
  cap: number;
  timeout_seconds: number;
  max_concurrency: number;
  cap_reached: boolean;
}

export interface CollectionResult<T> {
  timestamp: string;
  success: boolean;
  data: T | null;
  error: string | null;
  command: string;
  duration_ms: number;
  /**
   * Which address family this was read from: "ipv4", "ipv6", or "both".
   * The kernel keeps the IPv4 and IPv6 routing tables and neighbour caches
   * apart, so this says which one was read.
   */
  ip_version?: string;
  /** Present when the result came from a collection that looked up names. */
  name_lookup?: NameLookupSummary | null;
}

export type InterfacesResult = CollectionResult<NetworkInterface[]>;
export type RoutesResult = CollectionResult<NetworkRoute[]>;
export type NeighborsResult = CollectionResult<NetworkNeighbor[]>;
export type AllNetworkResult = {
  interfaces: InterfacesResult;
  routes: RoutesResult;
  neighbors: NeighborsResult;
  /** The IPv6 routing table. The kernel keeps it apart from the IPv4 one. */
  routes_ipv6?: RoutesResult;
  /** The IPv6 neighbour cache. */
  neighbors_ipv6?: NeighborsResult;
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

/**
 * Learning Lab exercise types - matching backend/app/exercises.py.
 */

export interface ExerciseSummary {
  id: string;
  title: string;
  concept: string;
  kind: 'trace' | 'lookup' | 'edit';
  scenario_id: string;
  source: string;
  destination: string;
}

export interface ExerciseDetail {
  id: string;
  title: string;
  concept: string;
  kind: 'trace' | 'lookup' | 'edit';
  what_it_is: string;
  why_it_matters: string;
  what_happens: string;
  analogy: string;
  instruction: string;
  scenario_id: string;
  source: string;
  destination: string;
  prediction_prompt: string;
  result_hint: string;
  takeaway: string;
  editable_node: string | null;
  editable_routes: { prefix: string; dev: string; via: string | null; metric: number }[] | null;
}

export interface ExerciseCheck {
  description: string;
  satisfied: boolean;
  detail: string;
}

export interface ExerciseState {
  exercise_id: string;
  title: string;
  concept: string;
  complete: boolean;
  checks: ExerciseCheck[];
  explanation: string;
  trace_status: string | null;
  selected_route: string | null;
  selected_prefix_length: number | null;
  matched_route: string | null;
  hops: {
    hop_number: number;
    node: string;
    action: string;
    explanation: string;
    matched_prefix: string | null;
  }[];
}

/**
 * Authorised discovery types - matching backend/app/discovery.py.
 */

export interface DiscoveryScope {
  network: string;
  max_hosts: number;
  interval: number;
  timeout: number;
  host_count: number;
}

export interface DiscoveredHost {
  ip_address: string;
  method: string;
  latency_ms: number | null;
  mac_address: string | null;
  responded_at: string;
}

export interface DiscoveryResult {
  status: string;
  hosts: DiscoveredHost[];
  addresses_probed: number;
  addresses_total: number;
  scope: DiscoveryScope;
  duration_seconds: number;
  cancelled: boolean;
  scan_id: string | null;
  message: string | null;
}

export interface DiscoveryScopePreview {
  scope: DiscoveryScope;
  addresses: string[];
  requires_confirmation: boolean;
}

export interface DiscoveryAuditEntry {
  timestamp: string;
  target: string;
  outcome: 'completed' | 'refused' | 'cancelled' | 'failed';
  hosts_found: number;
  addresses_probed: number;
  duration_seconds: number;
  reason: string | null;
  confirmed: boolean;
}

/**
 * PCAP Analysis types - matching the FastAPI backend Pydantic models exactly.
 * Backend contract: POST /api/pcap/analyze
 */

/**
 * Real routing table analysis - matching the FastAPI backend Pydantic models
 * exactly.
 * Backend source: backend/app/route_analysis.py
 *
 * This analyses the routing table the running kernel actually holds, rather
 * than the teaching sample the RouteCore engine works on. The table itself
 * is OBSERVED; the conclusion drawn from it is INFERRED.
 */

export interface RouteCandidate {
  destination: string;
  prefix_length: number;
  next_hop: string | null;
  interface: string;
  metric: number;
  next_hop_type: string;
  selected: boolean;
  outcome: string;
  explanation: string;
}

export interface ShadowFinding {
  less_specific_destination: string;
  more_specific_destinations: string[];
  captured_prefixes: string[];
  explanation: string;
}

export interface SkippedRoute {
  destination: string;
  reason: string;
}

export interface DestinationAnalysis {
  destination: string;
  matched: boolean;
  selected: RoutingEntry | null;
  candidates: RouteCandidate[];
  beaten: RouteCandidate[];
  explanation: string;
  is_default_route: boolean;
  shadowed_by: ShadowFinding | null;
  provenance: string;
  limitations: string[];
}

export interface RouteAnalysisReport {
  collected_at: string;
  command: string;
  /** Present only when the backend supports per-family analysis. */
  ip_version?: string;
  routes_in_table: number;
  routes_analysed: number;
  routes_skipped: SkippedRoute[];
  default_routes: string[];
  table_provenance: string;
  analysis_provenance: string;
  analyses: DestinationAnalysis[];
  shadow_findings: ShadowFinding[];
  limitations: string[];
}

export interface PcapAnalyzeRequest {
  filename: string;
  data_base64: string;
}

export interface PcapSummary {
  total_packets: number;
  total_bytes: number;
  duration_seconds: number;
  start_time: string;
  end_time: string;
  protocols: Record<string, number>;
  link_type: number;
}

export interface PcapHost {
  ip: string;
  packets: number;
  bytes: number;
  first_seen: string;
  last_seen: string;
}

export interface PcapConversation {
  src: string;
  dst: string;
  protocol: string;
  packets: number;
  bytes: number;
}

/**
 * Per-packet detail as the backend parses it.
 * Backend schema: PcapPacketDetailResponse
 */
export interface PcapPacketDetail {
  index: number;
  timestamp: string;
  src_mac: string | null;
  dst_mac: string | null;
  ethertype: string | null;
  src_ip: string | null;
  dst_ip: string | null;
  protocol: string | null;
  src_port: number | null;
  dst_port: number | null;
  tcp_flags: string[];
  tcp_flags_value: number | null;
  icmp_type: number | null;
  icmp_type_name: string | null;
  icmp_code: number | null;
  icmp_code_name: string | null;
  dns_query_name: string | null;
  dns_answers: string[];
  dns_is_response: boolean | null;
  dns_response_code: string | null;
  arp_operation: number | null;
  arp_operation_name: string | null;
  arp_sender_mac: string | null;
  arp_sender_ip: string | null;
  arp_target_mac: string | null;
  arp_target_ip: string | null;
  handshake_stage: string | null;
  provenance: Record<string, unknown>;
  notes: string[];
  parsed: boolean;
}

/**
 * A reconstructed handshake, as the backend sees it in the capture.
 * Backend schema: PcapHandshakeResponse
 */
export interface PcapHandshake {
  client: string;
  server: string;
  stages: string[];
  complete: boolean;
  provenance: string;
  explanation: string;
}

export interface PcapAnalysisResult {
  filename: string;
  size_bytes: number;
  format: 'pcap' | 'pcapng' | 'unknown';
  parsed: boolean;
  error: string | null;
  collected_at: string;
  summary: PcapSummary | null;
  hosts: PcapHost[];
  conversations: PcapConversation[];
  limitations: string[];
  /** Per-packet detail. Present on backends that parse beyond the summary. */
  packets?: PcapPacketDetail[];
  /** Reconstructed handshakes. Present on backends that parse beyond the summary. */
  handshakes?: PcapHandshake[];
}
