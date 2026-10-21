/**
 * Type definitions matching the FastAPI backend models.
 *
 * Where the backend publishes a response model, the type comes from the
 * generated OpenAPI types in ./api.generated.ts, so the two cannot drift
 * apart. Run `npm run generate:api` after a backend change.
 */

import type { components } from './api.generated';

export type NextHopType = 'gateway' | 'direct';

/**
 * How a route came to be known.
 *
 * The backend uses the same four words as the rest of the project, so a
 * route the student typed can be told apart from one that was measured.
 */
export type RouteProvenance = 'observed' | 'inferred' | 'simulated' | 'unknown';

export interface RoutingEntry {
  destination: string;
  next_hop: string | null;
  interface: string;
  metric: number;
  next_hop_type: NextHopType;
  /**
   * Optional so code that builds a RoutingEntry without it still compiles.
   * The backend always sends it; routes the student typed are 'simulated'.
   */
  provenance?: RouteProvenance;
}

export interface RouteLookupResult {
  matched: boolean;
  route: RoutingEntry | null;
  explanation: string;
  error: string | null;
  transmitted: boolean;
}

/**
 * A route as sent to the backend.
 *
 * The metric may be the text the student typed. The rules about what is
 * acceptable live in the backend, which writes the message a student
 * reads, so the browser does not second-guess the value.
 */
export interface RouteRequest {
  destination: string;
  next_hop: string | null;
  interface: string;
  metric: number | string;
  next_hop_type: NextHopType;
  provenance?: RouteProvenance;
}

/**
 * Counts and statistics for the live routing table.
 * Backend contract: GET /routes/summary
 */
export interface RoutesSummary {
  total_routes: number;
  longest_prefix: string | null;
  lowest_metric: number | null;
  default_route_count: number;
  ipv4_count: number;
  ipv6_count: number;
}

/**
 * The result of a lookup before and after the routing table was changed,
 * so a student can see what their edit actually did.
 */
export interface LookupComparison {
  destination: string;
  before: RouteLookupResult | null;
  after: RouteLookupResult | null;
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

/**
 * What the lab router looks like.
 *
 * Taken from the generated schema, so the backend and the interface
 * cannot disagree about it. The backend used to declare this as a
 * free-form dictionary, which meant the schema said nothing about it.
 */
export type RouterInfo = components['schemas']['RouterInfoModel'];
export type RouterRouteEntry = components['schemas']['RouterRouteEntryModel'];

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

/**
 * Packet Lab response types.
 *
 * These are taken from the generated OpenAPI types rather than written by
 * hand, so the frontend and the backend cannot disagree about them. The
 * backend reports, for each verification, not just whether it passed but
 * where the answer came from.
 */

/** One verification result, with the evidence behind it. */
export type VerificationField = components['schemas']['VerificationFieldModel'];

/** The three checks the lab runs over a captured packet. */
export type VerificationDetails = components['schemas']['VerificationDetailsModel'];

export type ForwardingInfoResponse =
  components['schemas']['ForwardingInfoModel'];

export type PacketResponse = components['schemas']['PacketResponseModel'];

export type SimulateResponse = components['schemas']['SimulateResponseModel'];

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

export interface PacketJourneyRequest {
  source_ip: string;
  destination_ip: string;
}

/**
 * Packet Journey types.
 *
 * Taken from the generated OpenAPI types, so the frontend and the backend
 * cannot disagree about them. The backend's `provenance` is a plain string
 * because the vocabulary is the project's own — observed / inferred /
 * simulated / unknown — and the journey this endpoint returns is always
 * "simulated": the path is worked out from a routing table and no packet is
 * transmitted.
 */
export type PacketHopResponse = components['schemas']['PacketHopResponse'];

export type MatchedRoute = components['schemas']['MatchedRoute'];

export type PacketJourneyResponse = components['schemas']['PacketJourneyResponse'];

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
  /**
   * "dry_run" means the commands were reported but not run.
   * "ok" means they ran. "failed" means one of them failed — see `failed_at`.
   * "unavailable" means the lab could not be run at all — see `reason`.
   */
  status: 'dry_run' | 'ok' | 'failed' | 'unavailable' | (string & {});
  log?: { cmd: string; rc: number; stdout?: string; stderr?: string }[];
  /** The commands that would run, or that ran. */
  commands?: string[];
  /** Why the lab could not run. Present when status is "unavailable". */
  reason?: string;
  /** The index of the command that failed. */
  failed_at?: number | string[] | null;
  /** The failure message, when the backend included one. */
  error?: string | null;
}

/**
 * The terminal outcome of a packet journey.
 *
 * The backend reports this as a hop `action` plus an `explanation`. The
 * three ways a journey can fail are distinguished here so the interface can
 * say which one happened. The backend's own explanation is always shown
 * alongside, so the student reads the real reason rather than a paraphrase.
 */
export type JourneyOutcome =
  | 'delivered'
  | 'loop'
  | 'hop_limit_exceeded'
  | 'no_route'
  | 'unresolved_next_hop'
  | 'invalid_input'
  | 'in_progress';

/**
 * How a lab test result should be read.
 *
 * "captured" means packets were really observed. "calculated" means the
 * routing table was only reasoned about. They are never mixed.
 */
export type LabTestOutcome =
  | 'captured'
  | 'calculated'
  | 'failed'
  | 'timeout'
  | 'unavailable'
  | 'not_run';

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
 * An exercise that works against the routing table of the machine the
 * student is sitting at.
 *
 * Backend contract: GET /api/host-exercises
 */
export interface HostExerciseSummary {
  id: string;
  title: string;
  concept: string;
  kind: 'trace' | 'lookup' | 'edit';
  table_source: 'scenario' | 'host';
  source: string;
}

/**
 * The full explanation of a host exercise.
 *
 * Backend contract: GET /api/host-exercises/{exercise_id}
 */
export interface HostExerciseDetail extends HostExerciseSummary {
  what_it_is: string;
  why_it_matters: string;
  what_happens: string;
  analogy: string;
  instruction: string;
  prediction_prompt: string;
  result_hint: string;
  takeaway: string;
  /** What the student could look at instead when their machine lacks it. */
  unavailable_hint: string | null;
  editable_node: string | null;
  editable_routes: { prefix: string; dev: string; via: string | null; metric: number }[] | null;
}

/**
 * The result of checking a host exercise.
 *
 * The table is read from the kernel and is OBSERVED; the conclusion drawn
 * from it is INFERRED. The two are reported separately and never merged.
 *
 * Backend contract: POST /api/host-exercises/{exercise_id}/check
 */
export interface HostExerciseState {
  exercise_id: string;
  title: string;
  concept: string;
  complete: boolean;
  checks: ExerciseCheck[];
  explanation: string;
  /** False when the machine's table does not have what the exercise needs. */
  available: boolean;
  unavailable_reason: string | null;
  message: string;
  table_provenance: string;
  analysis_provenance: string;
  destination: string | null;
  selected_route: string | null;
  selected_prefix_length: number | null;
  selected_next_hop: string | null;
  selected_interface: string | null;
  candidates: Record<string, unknown>[];
  beaten: Record<string, unknown>[];
  shadow: Record<string, unknown> | null;
  default_routes: string[];
  table_routes: Record<string, unknown>[];
  limitations: string[];
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

/**
 * The outcome of tracing a packet through a set of routing tables.
 *
 * The backend already publishes this model, so it is taken from the
 * generated schema rather than written out again.
 */
export type TraceResult = components['schemas']['TraceResult'];

/**
 * Router discovery.
 *
 * This is a different thing from the ICMP host sweep in
 * `/api/discovery/`. That one finds hosts on a network by pinging them.
 * This one walks a network of *routers*: it asks each device for its
 * neighbours over LLDP or CDP where it can, reads the routing tables where
 * it can, and works out the links between devices where it cannot.
 *
 * The distinction matters because the two kinds of link are not equally
 * trustworthy. An LLDP or CDP neighbour was told to us by the device
 * itself — that is an observation. A next hop or a shared subnet was
 * deduced — that is an inference. The interface shows which is which.
 *
 * The backend has not published these models yet, so they are written out
 * here rather than aliased from the generated schema. When it does, these
 * should become aliases of `components['schemas'][...]` the way
 * `VerificationField` and `PacketJourneyResponse` already are, so there is
 * one declaration of each and the two cannot drift apart.
 */

/** How a link between two devices was established. */
export type RouterDiscoveryEdgeKind =
  | 'lldp'
  | 'cdp'
  | 'l3_next_hop'
  | 'shared_subnet';

/**
 * Where a piece of knowledge came from.
 *
 * The project's own vocabulary: observed, inferred, simulated, unknown.
 * An observed link was told to us by a device; an inferred one was
 * deduced by the backend.
 */
export type RouterDiscoveryProvenance =
  | 'observed'
  | 'inferred'
  | 'simulated'
  | 'unknown';

/** One route in a device's routing table. */
export interface RouteEntry {
  prefix: string;
  next_hop: string | null;
  interface: string | null;
  protocol: string | null;
  metric: number;
  admin_distance: number | null;
  /** True when the device itself marks this route as the selected one. */
  selected: boolean;
}

/** One interface on a device. */
export interface IfaceInfo {
  name: string;
  addresses: string[];
  up: boolean;
}

/** One neighbour a device knows about. */
export interface Neighbor {
  local_if: string;
  remote_name: string | null;
  remote_if: string | null;
  remote_ip: string | null;
  via: string | null;
}

/** Everything the backend managed to read from one device. */
export interface DeviceSnapshot {
  device_id: string;
  hostname: string | null;
  mgmt_target: string | null;
  method: string | null;
  collected_at: string | null;
  interfaces: IfaceInfo[];
  routes: RouteEntry[];
  neighbors: Neighbor[];
  /** Why parts of this device could not be read. */
  errors: string[];
  provenance: RouterDiscoveryProvenance;
}

/** A link between two devices. */
export interface RouterDiscoveryEdge {
  /** The device the link is from. */
  a: string;
  /** The device the link is to. */
  b: string;
  kind: RouterDiscoveryEdgeKind;
  provenance: RouterDiscoveryProvenance;
  /** What the backend used to decide this link exists. */
  evidence: string;
}

/** A device in the discovered graph. */
export interface RouterDiscoveryNode {
  device_id: string;
  /** What the reader sees on the map. */
  label: string;
  provenance: RouterDiscoveryProvenance;
  /** Set when the device could not be collected at all. */
  error: string | null;
  /** Partial failures while collecting this device. */
  errors: string[];
}

/** The graph the backend built from a run. */
export interface RouterDiscoveryGraph {
  nodes: RouterDiscoveryNode[];
  edges: RouterDiscoveryEdge[];
}

/** A device as the drawer shows it. */
export interface RouterDiscoveryDevice extends DeviceSnapshot {
  /** The links this device takes part in, as the backend reported them. */
  edges: RouterDiscoveryEdge[];
}

/** Something the backend noticed worth telling the student about. */
export interface RouterDiscoveryFinding {
  device_id: string;
  /** What sort of finding this is. */
  kind: string;
  /** How serious the backend judged it to be. */
  severity: string;
  /** The finding in one line. */
  title: string;
  /** What it means. */
  detail: string;
  /** What the backend used to reach the conclusion. */
  evidence: string;
}

/** The state of one discovery run. */
export interface RouterDiscoveryRun {
  /**
   * The run's identifier.
   *
   * The status response does not carry it — the caller already knows it,
   * because it asked for this run by name. It is here for convenience and
   * is absent when the backend does not echo it.
   */
  run_id?: string;
  status: string;
  /** What the backend has done so far, in order. */
  progress: string[];
  /**
   * What failed.
   *
   * The shape of each value is the backend's, so it is left open rather
   * than guessed at.
   */
  failures: Record<string, unknown>;
}

/** The result of starting a run. */
export interface RouterDiscoveryRunStart {
  run_id: string;
  status: string;
}

/** The routes of one device. */
export interface RouterDiscoveryDeviceRoutes {
  routes: RouteEntry[];
}

/** The findings of one run. */
export interface RouterDiscoveryFindings {
  findings: RouterDiscoveryFinding[];
}

/** How two runs differ. */
export interface RouterDiscoveryDiff {
  added: string[];
  removed: string[];
  changed: string[];
}

/** The request that starts a run. */
export interface RouterDiscoveryRunRequest {
  /** The devices to start from. */
  seeds: string[];
  /** The network to stay within. */
  scope: string;
  /** How to reach a device. */
  method: string;
  max_depth: number;
  max_devices: number;
}

/** The request that traces a path through the collected tables. */
export interface RouterDiscoveryTraceRequest {
  src_device: string;
  dst_ip: string;
}
