# RouteLens Lite — Frontend

React + TypeScript + Vite. The dev server proxies API calls to the backend
on `http://127.0.0.1:8000`.

## Commands

```bash
npm install

npm run dev            # development server on http://127.0.0.1:5173
npm run build          # tsc --noEmit + production build into dist/
npm run lint           # type check only
npm run preview        # serve the production build

npm run generate:api   # regenerate src/types/api.generated.ts from the backend
npm run check:api      # verify the hand-written types still match the backend
```

## The generated types

`src/types/api.generated.ts` is produced by
[openapi-typescript](https://github.com/openapi-ts/openapi-typescript) from
the running backend's OpenAPI schema. It is committed so that the frontend
can be type-checked without the backend running.

Regenerate it after the backend's response models change:

```bash
npm run generate:api
```

`npm run check:api` compares the schemas the app actually uses against the
live backend and fails if a field has drifted. It needs the backend running.
When it reports a difference, the **frontend** is what needs updating — the
backend is the contract, not the other way round.

Two endpoints are outside the OpenAPI schema and are typed by hand:
`POST /packet-journey` (it declares no `response_model`) and the
`router_info` object inside `LabStatusResponse`, which the schema leaves
free-form.

## Dependencies

| Package | Why | Licence |
|---------|-----|---------|
| `@xyflow/react` | The topology graph. Pan, zoom, minimap, and custom React nodes. | MIT |
| `dagre` | Layered graph layout, so a device sits to the left of what it points at. | MIT |
| `openapi-typescript` | Generates the TypeScript types from the backend's OpenAPI schema. | MIT |

The graph renderer is loaded on demand: the list view of the topology and
the first paint of the page do not pay for it.

## Provenance

Every network claim carries where it came from — `observed`, `inferred`,
`simulated` or `unknown`. A simulated node never looks observed, and the
topology draws a relationship only when the backend reported one. Nothing is
connected to fill a gap.

## Configuration

### VITE_API_URL

`src/api/routing.ts` centralises all API requests behind `API_BASE`, which is
read from `import.meta.env.VITE_API_URL`.

- **Local development:** Leave `VITE_API_URL` empty (or unset). The Vite dev
  server proxies API calls to `http://127.0.0.1:8000`, so relative URLs work.
- **Production (GitHub Pages + remote backend):** Set `VITE_API_URL` to the
  HTTPS URL of your separately hosted FastAPI backend, e.g.
  `https://api.example.com`. Do not include a trailing slash.

Copy `frontend/.env.example` to `frontend/.env.local` for local overrides.
Never commit real secrets or credentials.

### GitHub Pages base path

`frontend/vite.config.ts` sets `base: '/RouteLens-Lite/'` so built assets are
served from the `/RouteLens-Lite/` subdirectory on GitHub Pages.

## Deployment

The frontend is built and deployed to GitHub Pages by
`.github/workflows/deploy.yml`. Set `VITE_API_URL` as a GitHub repository
secret or variable so the production build points at your remote backend.

The backend runs separately on a reachable Linux machine and must remain
online for the GitHub Pages frontend to call it. Diagnostic endpoints
(ping, traceroute, DNS, etc.) execute system commands on the backend host,
so they should not be exposed publicly without an access gateway.
