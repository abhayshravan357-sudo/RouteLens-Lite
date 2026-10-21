/**
 * Check the frontend against the backend's OpenAPI schema.
 *
 * Two things are checked:
 *
 *   1. That the generated types (src/types/api.generated.ts) still describe
 *      the backend's live schema. A snapshot of the schema is committed
 *      alongside the generated types, and the live schema is compared with
 *      it — field by field, all the way down. A field that changed shape,
 *      or a field that appeared or disappeared, is reported.
 *
 *      Comparing names alone is not enough. A field that changed from
 *      `boolean` to an object with three fields inside keeps its name, so a
 *      name-only check would pass while the frontend was silently wrong.
 *
 *   2. That the hand-written interfaces the app relies on still line up
 *      with the schemas they mirror.
 *
 * Run it with:  npm run check:api
 * It needs the backend running. It exits non-zero when something has
 * drifted.
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, '..');
const SCHEMA_URL =
  process.env.ROUTELENS_SCHEMA_URL ??
  'http://127.0.0.1:8000/openapi.json';

const SNAPSHOT_PATH = join(ROOT, 'src', 'types', 'openapi.snapshot.json');
const TS_PATH = join(ROOT, 'src', 'types', 'routing.ts');
const GENERATED_PATH = join(ROOT, 'src', 'types', 'api.generated.ts');

/**
 * The hand-written interface -> the backend schema it mirrors, and the
 * fields the frontend depends on.
 */
const CONTRACTS = [
  ['RoutingEntry', 'RoutingEntry-Output', [
    'destination', 'next_hop', 'interface', 'metric', 'next_hop_type', 'provenance',
  ]],
  ['RouteLookupResult', 'RouteLookupResult', [
    'matched', 'route', 'explanation', 'error', 'transmitted',
  ]],
  ['RouterInfo', 'RouterInfoModel', [
    'interfaces', 'routing_table', 'client_ip', 'server_ip',
  ]],
  ['RouterRouteEntry', 'RouterRouteEntryModel', [
    'destination', 'next_hop', 'interface',
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
  ['VerificationField', 'VerificationFieldModel', [
    'value', 'provenance', 'details',
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

/**
 * Fields the frontend has that the backend does not: usually fine.
 *
 * RouterInfo and RouterRouteEntry used to be here, because the backend
 * declared router_info as a free-form dictionary. It is a model now, so
 * the pair is checked like every other contract.
 */
const FRONTEND_ONLY_OK = new Set();

function fail(message) {
  console.error(`\n✗ ${message}`);
  process.exitCode = 1;
}

/**
 * A stable description of a schema's shape.
 *
 * Names, types and nesting are all included, so a field that changed from a
 * boolean into an object is a difference.
 */
function describe(schema) {
  if (!schema || typeof schema !== 'object') return 'unknown';

  if (schema.$ref) return schema.$ref;

  if (Array.isArray(schema.items)) {
    return `array<${schema.items.map(describe).join('|')}>`;
  }
  if (schema.items) return `array<${describe(schema.items)}>`;

  if (schema.anyOf) {
    return schema.anyOf.map(describe).join('|');
  }
  if (schema.oneOf) {
    return schema.oneOf.map(describe).join('|');
  }
  if (schema.allOf) {
    return schema.allOf.map(describe).join('&');
  }

  if (schema.type === 'object' || schema.properties) {
    const parts = Object.entries(schema.properties ?? {})
      .map(([name, prop]) => `${name}:${describe(prop)}`)
      .sort();
    const required = (schema.required ?? []).slice().sort().join(',');
    return `object{${parts.join(';')}} required[${required}]`;
  }

  if (schema.enum) return `enum(${schema.enum.join('|')})`;

  if (schema.type) {
    return `${schema.type}${schema.default !== undefined ? `=${schema.default}` : ''}`;
  }

  return 'unknown';
}

/** Compare two schemas' component sections, all the way down. */
function compareSchemas(live, snapshot) {
  const differences = [];

  const liveSchemas = live.components?.schemas ?? {};
  const snapSchemas = snapshot.components?.schemas ?? {};

  const names = new Set([
    ...Object.keys(liveSchemas),
    ...Object.keys(snapSchemas),
  ]);

  for (const name of names) {
    if (!(name in snapSchemas)) {
      differences.push(`${name}: new in the backend, not in the snapshot`);
      continue;
    }
    if (!(name in liveSchemas)) {
      differences.push(`${name}: in the snapshot but not in the backend`);
      continue;
    }
    const liveShape = describe(liveSchemas[name]);
    const snapShape = describe(snapSchemas[name]);
    if (liveShape !== snapShape) {
      differences.push(
        `${name}: shape changed\n      snapshot: ${snapShape}\n      live:     ${liveShape}`
      );
    }
  }

  return differences;
}

async function main() {
  let live;
  try {
    const response = await fetch(SCHEMA_URL);
    if (!response.ok) {
      fail(
        `Could not read the OpenAPI schema from ${SCHEMA_URL} (HTTP ${response.status}).`
      );
      console.error('  Start the backend first, or set ROUTELENS_SCHEMA_URL.');
      return;
    }
    live = await response.json();
  } catch (error) {
    fail(`Could not reach ${SCHEMA_URL}: ${error.message}`);
    return;
  }

  const problems = [];

  // 1. The generated types must still describe the live schema.
  let snapshot;
  try {
    snapshot = JSON.parse(readFileSync(SNAPSHOT_PATH, 'utf8'));
  } catch {
    fail(
      'src/types/openapi.snapshot.json is missing. Run: npm run generate:api'
    );
    return;
  }

  const shapeChanges = compareSchemas(live, snapshot);
  if (shapeChanges.length) {
    problems.push(
      'The backend schema has changed since the types were generated:\n    - ' +
        shapeChanges.join('\n    - ')
    );
  }

  // The generated file must exist and mention every schema.
  let generated = '';
  try {
    generated = readFileSync(GENERATED_PATH, 'utf8');
  } catch {
    fail('src/types/api.generated.ts is missing. Run: npm run generate:api');
    return;
  }
  for (const name of Object.keys(live.components?.schemas ?? {})) {
    const key = /^[A-Za-z_$][\w$]*$/.test(name) ? name : `"${name}"`;
    if (!generated.includes(`${key}:`)) {
      problems.push(
        `${name} is in the schema but missing from api.generated.ts — rerun npm run generate:api`
      );
    }
  }

  // 2. The hand-written interfaces must still line up.
  const ts = readFileSync(TS_PATH, 'utf8');
  const schemas = live.components?.schemas ?? {};

  for (const [frontendName, schemaName, fields] of CONTRACTS) {
    const backend = schemas[schemaName];
    if (!backend) {
      problems.push(
        `${frontendName}: the backend has no schema named ${schemaName}`
      );
      continue;
    }

    if (!new RegExp(`\\b${frontendName}\\b`).test(ts)) {
      problems.push(`${frontendName}: not found in src/types/routing.ts`);
      continue;
    }

    const backendFields = Object.keys(backend.properties ?? {});
    for (const field of fields) {
      if (!backendFields.includes(field)) {
        problems.push(
          `${frontendName}.${field} is in the frontend but not in the backend's ${schemaName}`
        );
      }
    }
    for (const field of backendFields) {
      if (!fields.includes(field) && !FRONTEND_ONLY_OK.has(frontendName)) {
        problems.push(
          `${frontendName}.${field} is in the backend's ${schemaName} but not declared in the frontend`
        );
      }
    }
  }

  if (problems.length === 0) {
    console.log(
      `✓ ${CONTRACTS.length} frontend contracts match, and the generated types still describe the backend schema.`
    );
    return;
  }

  console.error(`\n${problems.length} contract difference(s):`);
  for (const problem of problems) {
    console.error(`  - ${problem}`);
  }
  console.error(
    '\nIf the backend changed, run: npm run generate:api   and update src/types/routing.ts to match.\nDo not change the backend to suit the frontend.'
  );
  process.exitCode = 1;
}

main();
