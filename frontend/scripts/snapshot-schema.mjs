/**
 * Write a snapshot of the backend's OpenAPI schema.
 *
 * The generated types describe the schema at the moment they were made.
 * This snapshot records the schema itself, so `npm run check:api` can
 * compare the two and notice a change in a field's shape — not just in its
 * name — even before anyone regenerates the types.
 *
 * Run it as part of:  npm run generate:api
 */

import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, '..');
const SNAPSHOT_PATH = join(ROOT, 'src', 'types', 'openapi.snapshot.json');
const SCHEMA_URL =
  process.env.ROUTELENS_SCHEMA_URL ??
  'http://127.0.0.1:8000/openapi.json';

const response = await fetch(SCHEMA_URL);
if (!response.ok) {
  console.error(
    `Could not read the OpenAPI schema from ${SCHEMA_URL} (HTTP ${response.status}).`
  );
  process.exit(1);
}

const schema = await response.json();
writeFileSync(SNAPSHOT_PATH, `${JSON.stringify(schema, null, 2)}\n`);
console.log(
  `✓ schema snapshot written (${Object.keys(schema.components?.schemas ?? {}).length} schemas)`
);
