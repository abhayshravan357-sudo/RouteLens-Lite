# RouteLens Lite — Developer Runbook

Exact commands to install, start, configure, inspect, maintain, and
demonstrate RouteLens Lite. Intended for a new developer cloning this
repository for the first time.

## 1. Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.11+ (CI uses 3.12) | Backend runtime |
| Node.js | 18+ (CI uses 22) | Frontend runtime |
| npm | bundled with Node | Frontend package manager |
| `ip` (iproute2) | any | Real network diagnostics (read-only) |
| `ping` | any | ICMP connectivity checks |
| `traceroute` | any | Optional; degrades gracefully if missing |

Only the **virtual packet lab** needs root (`CAP_SYS_ADMIN`) plus `ip` and
`ping`. Everything else runs unprivileged.

## 2. Backend — install and start

Terminal 1:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
python -m uvicorn app.main:app --port 8000
```

The backend listens on `http://127.0.0.1:8000`. Interactive API docs are at
`http://localhost:8000/docs`.

### Verify the backend

```bash
curl http://127.0.0.1:8000/health
# Expected: {"status":"ok","service":"RouteLens Lite API"}

curl http://127.0.0.1:8000/lookup?destination=192.168.1.50
# Expected: route lookup result with longest-prefix match
```

To run the backend on a different port:

```bash
python -m uvicorn app.main:app --port 8010
```

## 3. Frontend — install and start

Terminal 2:

```bash
cd frontend
cp .env.example .env.local   # optional; see section 4
npm ci                       # or `npm install` if changing dependencies
npm run dev                  # Vite dev server on http://127.0.0.1:5173
```

Open **http://localhost:5173**. If 5173 is taken, Vite prints the next free
port — open the URL it shows.

### Verify the frontend

- The page loads and shows the sidebar views (Overview, Routing Analyzer,
  Kernel Table, Packet Journey, Learning Lab, Network Diagnostics, Report).
- `http://localhost:5173/health` proxies to the backend `/health`.

To point the frontend at a backend on a different port:

```bash
cd frontend
ROUTELENS_BACKEND_URL=http://127.0.0.1:8010 npm run dev
```

## 4. Environment variables

Copy `frontend/.env.example` to `frontend/.env.local` and edit as needed:

| Variable | Where used | Default | Purpose |
|----------|-----------|---------|---------|
| `ROUTELENS_BACKEND_URL` | Frontend (Vite proxy) | `http://127.0.0.1:8000` | Backend origin proxied by the Vite dev server |
| `ROUTELENS_URL` | Browser tests (`test_e2e_browser.py`) | `http://127.0.0.1:5173` | Frontend URL the browser tests drive |
| `ROUTELENS_HEALTH` | Browser tests (`test_e2e_browser.py`) | `http://127.0.0.1:8000/health` | Backend health URL the browser tests poll |

`frontend/.env.example` documents `ROUTELENS_BACKEND_URL`. `ROUTELENS_URL`
and `ROUTELENS_HEALTH` are backend-test variables, passed on the `pytest`
command line rather than loaded from a dotenv file.

## 5. Browser (E2E) checks

These drive a real Chromium against a running backend + frontend. They skip
cleanly if Playwright or either half of the app is not running.

```bash
cd backend
source .venv/bin/activate
pip install playwright
python -m playwright install chromium

# With backend on 8000 and frontend on 5173:
ROUTELENS_URL=http://127.0.0.1:5173 \
ROUTELENS_HEALTH=http://127.0.0.1:8000/health \
python -m pytest tests/test_e2e_browser.py -q -p no:cacheprovider
```

## 6. Testing

### Backend (full suite)

```bash
cd backend
source .venv/bin/activate
python -m pytest -q
```

To exclude browser checks (they need a running app):

```bash
python -m pytest -q --ignore=tests/test_e2e_browser.py
```

### Frontend (type check + production build)

```bash
cd frontend
npx tsc --noEmit
npm run build
```

### Everything at once

```bash
bash scripts/routelens-check.sh
```

Runs the git whitespace check, backend suite, TypeScript check, and frontend
build; writes a report under `.routelens/reports/`.

## 7. Inspection and maintenance

### Health check

```bash
curl http://127.0.0.1:8000/health
```

### OpenAPI schema

```bash
curl http://127.0.0.1:8000/openapi.json
```

### Regenerate frontend API types

After backend response models change:

```bash
cd frontend
npm run generate:api     # openapi-typescript from live backend
npm run check:api        # verify hand-written types match live backend
```

### Logs

The backend logs to stdout via uvicorn. No log file is configured. To capture
output:

```bash
python -m uvicorn app.main:app --port 8000 > backend.log 2>&1 &
```

### Clean restart

```bash
# Backend
pkill -f uvicorn
cd backend && source .venv/bin/activate && python -m uvicorn app.main:app --port 8000

# Frontend
pkill -f "vite"
cd frontend && npm run dev
```

## 8. Demonstration checklist

Before demoing, confirm:

- [ ] Backend answers `GET /health` → 200 `{"status":"ok",...}`
- [ ] Frontend loads at http://localhost:5173
- [ ] Route lookup works: `GET /lookup?destination=192.168.1.50`
- [ ] Kernel Table view shows real host routes
- [ ] Network Diagnostics tabs (Interfaces / Routes / Neighbors) populate
- [ ] Virtual lab unavailable message appears (expected without root) —
      demo the lab only if running as root with `ip` and `ping` available

## 9. What does not need root

Routing analysis, scenario lab, diagnostics, capture importer, exercises,
and report all work without root. Only run the backend under `sudo` when you
actually want the virtual packet lab.

## 10. CI configuration

`.github/workflows/ci.yml` runs three jobs on push/PR:

- **backend** — Python 3.12, `pytest`
- **frontend** — Node 22, `npm ci` + `npm run build`
- **browser** — Playwright Chromium, starts both dev servers, runs E2E checks
  (`continue-on-error: true`)
- **whitespace** — `git diff --check` on changed commits

`.github/workflows/deploy.yml` deploys the frontend build to GitHub Pages on
push to `main`.
