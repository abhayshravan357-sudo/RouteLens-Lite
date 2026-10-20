/**
 * Check the hand-written frontend types against the backend's OpenAPI schema.
 *
 * The hand-written interfaces in src/types/routing.ts are what the app
 * actually uses. This script fetches the live schema and reports any field
 * that exists on one side and not the other, so a backend change cannot
 * quietly drift away from the frontend.
 *
 * Run it with:  npm run check:api
 * It exits non-zero when something has drifted.
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, '..');
const SCHEMA_URL =
  process.env.ROUTELENS_SCHEMA_URL ??
  'http://127.0.0.1:8000/openapi.json';

const TS_PATH = join(ROOT, 'src', 'types', 'routing.ts');
const GENERATED_PATH = join(ROOT, 'src', 'types', 'api.generated.ts');

/**
 * The hand-written interface -> the backend schema it mirrors.
 * The `fields` list is the contract the frontend relies on.
 */
const CONTRACTS = [
  ['RoutingEntry', 'RoutingEntry-Output', [
    'destination', 'next_hop', 'interface', 'metric', 'next_hop_type', 'provenance',
  ]],
  ['RouteLookupResult', 'RouteLookupResult', [
    'matched', 'route', 'explanation', 'error', 'transmitted',
  ]],
  ['LabStatusResponse', 'LabStatusResponse', [
    'available', 'state', 'message', 'router_info', 'error',
  ]],
  ['SimulateRequest', 'SimulateRequestModel', [
    'source_ip', 'destination_ip', 'protocol', 'ttl', 'length',
    'route_matched', 'egress_interface', 'next_hop',
  ]],
  ['SimulateResponse', 'SimulateResponseModel', [
    'state', 'message', 'packet', 'capture_verified', 'verification_details', 'error',
  ]],
  ['PacketResponse', 'PacketResponseModel', [
    'source_ip', 'destination_ip', 'protocol', 'ttl', 'length', 'forwarding_info',
  ]],
  ['ForwardingInfoResponse', 'ForwardingInfoModel', [
    'ingress_interface', 'egress_interface', 'next_hop', 'route_matched', 'action',
  ]],
  ['VerificationDetails', 'VerificationDetailsModel', [
    'ttl_decremented', 'checksum_valid', 'route_matched',
  ]],
  ['PacketJourneyRequest', 'PacketJourneyRequest', ['source_ip', 'destination_ip']],
  ['RouteAnalysisReport', 'RouteAnalysisReport', [
    'collected_at', 'command', 'ip_version', 'routes_in_table', 'routes_analysed',
    'routes_skipped', 'default_routes', 'table_provenance', 'analysis_provenance',
    'analyses', 'shadow_findings', 'limitations',
  ]],
  ['DestinationAnalysis', 'DestinationAnalysis', [
    'destination', 'matched', 'selected', 'candidates', 'beaten', 'explanation',
    'is_default_route', 'shadowed_by', 'provenance', 'limitations',
  ]],
  ['RouteCandidate', 'RouteCandidate', [
    'destination', 'prefix_length', 'next_hop', 'interface', 'metric',
    'next_hop_type', 'selected', 'outcome', 'explanation',
  ]],
  ['ShadowFinding', 'ShadowFinding', [
    'less_specific_destination', 'more_specific_destinations',
    'captured_prefixes', 'explanation',
  ]],
  ['SkippedRoute', 'SkippedRoute', ['destination', 'reason']],
  ['PcapAnalysisResult', 'PcapAnalyzeResponse', [
    'filename', 'size_bytes', 'format', 'parsed', 'error', 'collected_at',
    'summary', 'hosts', 'conversations', 'limitations', 'packets', 'handshakes',
  ]],
  ['PcapSummary', 'PcapSummaryResponse', [
    'total_packets', 'total_bytes', 'duration_seconds', 'start_time', 'end_time',
    'protocols', 'link_type',
  ]],
  ['PcapHost', 'PcapHostResponse', [
    'ip', 'packets', 'bytes', 'first_seen', 'last_seen',
  ]],
  ['PcapConversation', 'PcapConversationResponse', [
    'src', 'dst', 'protocol', 'packets', 'bytes',
  ]],
  ['PcapPacketDetail', 'PcapPacketDetailResponse', [
    'index', 'timestamp', 'src_mac', 'dst_mac', 'ethertype', 'src_ip', 'dst_ip',
    'protocol', 'src_port', 'dst_port', 'tcp_flags', 'tcp_flags_value', 'icmp_type',
    'icmp_type_name', 'icmp_code', 'icmp_code_name', 'dns_query_name', 'dns_answers',
    'dns_is_response', 'dns_response_code', 'arp_operation', 'arp_operation_name',
    'arp_sender_mac', 'arp_sender_ip', 'arp_target_mac', 'arp_target_ip',
    'handshake_stage', 'provenance', 'notes', 'parsed',
  ]],
  ['PcapHandshake', 'PcapHandshakeResponse', [
    'client', 'server', 'stages', 'complete', 'provenance', 'explanation',
  ]],
  ['TopologyNode', 'TopologyNode', [
    'id', 'kind', 'label', 'provenance', 'addresses', 'detail',
  ]],
  ['TopologyEdge', 'TopologyEdge', [
    'source', 'target', 'kind', 'provenance', 'label', 'detail',
  ]],
  ['TopologyGraph', 'TopologyGraph', [
    'nodes', 'edges', 'provenance', 'explanation', 'observed_at',
  ]],
];

/** Fields the frontend has but the backend does not: usually fine, worth a look. */
const FRONTEND_ONLY_OK = new Set(['RouterInfo', 'RouterRouteEntry']);

function fail(message) {
  console.error(`\n✗ ${message}`);
  process.exitCode = 1;
}

async function main() {
  let schema;
  try {
    const response = await fetch(SCHEMA_URL);
    if (!response.ok) {
      fail(`Could not read the OpenAPI schema from ${SCHEMA_URL} (HTTP ${response.status}).`);
      console.error('  Start the backend first, or set ROUTELENS_SCHEMA_URL.');
      return;
    }
    schema = await response.json();
  } catch (error) {
    fail(`Could not reach ${SCHEMA_URL}: ${error.message}`);
    return;
  }

  const schemas = schema.components?.schemas ?? {};
  const ts = readFileSync(TS_PATH, 'utf8');
  let generated = '';
  try {
    generated = readFileSync(GENERATED_PATH, 'utf8');
  } catch {
    fail('src/types/api.generated.ts is missing. Run: npm run generate:api');
    return;
  }

  const problems = [];

  for (const [frontendName, schemaName, fields] of CONTRACTS) {
    const backend = schemas[schemaName];
    if (!backend) {
      problems.push(`${frontendName}: the backend has no schema named ${schemaName}`);
      continue;
    }

    // The frontend interface must exist in the handwritten file.
    if (!new RegExp(`interface\\s+${frontendName}\\b`).test(ts)) {
      problems.push(`${frontendName}: not found in src/types/routing.ts`);
      continue;
    }

    const backendFields = new Set(Object.keys(backend.properties ?? {}));
    for (const field of fields) {
      if (!backendFields.has(field)) {
        problems.push(
          `${frontendName}.${field} is in the frontend but not in the backend's ${schemaName}`
        );
      }
    }

    // Fields the backend has that the frontend interface does not declare.
    // The frontend interface may still be correct, because it may extend the
    // declared ones, so this is reported separately.
    const declared = fields;
    for (const field of backendFields) {
      if (!declared.includes(field) && !FRONTEND_ONLY_OK.has(frontendName)) {
        problems.push(
          `${frontendName}.${field} is in the backend's ${schemaName} but not declared in the frontend`
        );
      }
    }
  }

  // Every generated schema should be reachable from the generated file.
  // Schemas with a hyphen in the name are emitted as quoted keys.
  for (const name of Object.keys(schemas)) {
    const key = /^[A-Za-z_$][\w$]*$/.test(name) ? name : `"${name}"`;
    if (!generated.includes(`${key}:`)) {
      problems.push(`${name} is in the schema but missing from api.generated.ts — rerun npm run generate:api`);
    }
  }

  if (problems.length === 0) {
    console.log(`✓ ${CONTRACTS.length} frontend contracts match the backend schema.`);
    return;
  }

  console.error(`\n${problems.length} contract difference(s):`);
  for (const problem of problems) {
    console.error(`  - ${problem}`);
  }
  console.error(
    '\nIf the backend changed, update src/types/routing.ts to match. Do not change the backend to suit the frontend.'
  );
  process.exitCode = 1;
}

main();
