# RouteLens Lite — Deployment Guide

RouteLens Lite is a college Computer Networks Lab project with two parts:

- **Frontend** — React/TypeScript/Vite, hosted on GitHub Pages.
- **Backend** — FastAPI, runs separately on a reachable Linux machine.

The frontend calls the backend through a configurable HTTPS API URL. The
backend executes real networking commands (`ip`, `ping`, `traceroute`) on the
host machine, so it must remain online and must not be exposed publicly
without an access gateway.

---

## 1. Architecture overview

```
GitHub Pages (frontend)  -->  HTTPS API URL  -->  FastAPI backend (Linux host)
                                (VITE_API_URL)
```

- GitHub Pages serves only static frontend assets.
- The backend runs on a separate Linux machine you control.
- The frontend browser makes cross-origin requests to the backend.
- CORS on the backend controls which origins may call it.

---

## 2. Prerequisites

### Frontend (GitHub Pages build machine / local dev)

- Node.js 22+
- npm

### Backend (Linux host)

- Python 3.12+
- `ip` command (from `iproute2`)
- `ping` command (for ICMP connectivity)
- `traceroute` command (optional, for traceroute diagnostics)
- FRR (optional, for FRR integration)

The backend does **not** need Node.js.

---

## 3. Step 1 — Configure the backend CORS origins

The backend's CORS policy controls which frontend origins may call it. Edit
the allowed origins on the backend host.

### Default allowed origins

These are always allowed:

- `http://localhost:5173`
- `http://127.0.0.1:5173`
- `http://localhost:5174`
- `http://127.0.0.1:5174`
- `https://abhayshravan357-sudo.github.io` (GitHub Pages)

### Adding additional origins

Set the `ROUTELENS_CORS_ORIGINS` environment variable on the backend host
to a comma-separated list of extra origins:

```bash
export ROUTELENS_CORS_ORIGINS="https://my-custom-domain.example.com"
```

Then restart the backend.

A wildcard (`*`) is never accepted — it is silently ignored to prevent
any site from using the backend as a network proxy.

---

## 4. Step 2 — Configure the frontend API URL

The frontend reads `VITE_API_URL` to know where the backend lives.

### Local development

Leave `VITE_API_URL` empty (or unset). The Vite dev server proxies API calls
to `http://127.0.0.1:8000`:

```bash
cd frontend
cp .env.example .env.local
# Edit .env.local: leave VITE_API_URL empty
npm run dev
```

### Production (GitHub Pages)

Set `VITE_API_URL` to the HTTPS URL of your backend:

```bash
# In .env.local (never commit real values):
VITE_API_URL=https://api.example.com
```

Do **not** include a trailing slash.

### GitHub Actions configuration

Set `VITE_API_URL` as a GitHub repository secret or variable (not committed):

1. Go to your repository on GitHub → Settings → Secrets and variables → Actions.
2. Add a repository variable named `VITE_API_URL` with your backend URL.
3. The deploy workflow (`.github/workflows/deploy.yml`) will inject it into
   the build via `npm run build`.

Never put backend secrets, API keys, or credentials in `VITE_API_URL` — it
is embedded in the JavaScript bundle and visible to anyone.

---

## 5. Step 3 — Build the frontend for GitHub Pages

```bash
cd frontend
npm ci
npm run build
```

This produces `frontend/dist/` with asset paths prefixed by
`/RouteLens-Lite/` (configured in `frontend/vite.config.ts`).

The deploy workflow runs these same commands and uploads `frontend/dist/` to
GitHub Pages.

---

## 6. Step 4 — Run the backend locally

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The backend listens on `127.0.0.1:8000` by default — **not** publicly.

To make it reachable from the GitHub Pages frontend, bind it to a public
interface or place it behind a reverse proxy:

```bash
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**Warning:** Binding to `0.0.0.0` exposes the backend to the network. Only
do this behind a firewall or access gateway. See section 8.

---

## 7. Step 5 — Why the backend computer must remain online

The GitHub Pages frontend is static — it cannot run networking commands
itself. Every diagnostic (ping, traceroute, DNS, interface inspection)
executes on the backend host. If the backend machine is offline, the
frontend cannot reach it and those features will fail.

---

## 8. Security — why you need an access gateway

### What the backend exposes

The backend has **no authentication**. Its diagnostic endpoints execute
real system commands:

| Endpoint | Command | Risk |
|---|---|---|
| `GET /network/interfaces` | `ip -j addr show` | Read-only, low risk |
| `GET /network/routes` | `ip -j route show` | Read-only, low risk |
| `GET /network/neighbors` | `ip -j neigh show` | Read-only, low risk |
| `POST /network/dns-resolve` | `getaddrinfo()` | Read-only, rate-limited |
| `POST /network/connectivity` | `ping` / TCP connect | Generates network traffic, rate-limited |
| `POST /network/traceroute` | `traceroute` | Generates network traffic, rate-limited |

### Protections already in place

- **Input validation** (`validate_target`): rejects shell metacharacters,
  leading dashes, whitespace, and malformed targets. Prevents command
  injection.
- **Rate limiting** (`diagnostic_limiter`): 20 requests per minute per
  client per operation. Prevents abuse.
- **CORS**: only listed origins may call the API from a browser.
- **No wildcard CORS**: `*` is rejected.

### What is NOT in place

- **No authentication**: anyone who can reach the backend can call its
  endpoints.
- **No TLS termination**: the FastAPI app serves HTTP directly.

### Required for remote access

Do **not** expose the backend directly to the internet. Instead:

1. Place it behind a reverse proxy (nginx, Caddy, Cloudflare Tunnel, etc.)
   that terminates TLS.
2. Add authentication at the proxy layer (e.g., OAuth2, basic auth, or
   IP allowlisting).
3. Keep CORS origins limited to your GitHub Pages domain.

Document your specific proxy setup — this project does not prescribe one.

---

## 9. Linux capabilities and privileges

The backend uses `ip`, `ping`, and `traceroute`. On some Linux systems:

- `ping` may require `CAP_NET_RAW` or setuid root.
- `traceroute` may require similar capabilities.
- `ip` commands for reading (`ip -j addr show`, etc.) generally do not
  require privileges, but writing/modifying network configuration does.

The RouteLens Lite backend only **reads** network state — it does not modify
kernel routing tables or create network namespaces through these endpoints.
If you need write operations, you will need appropriate Linux capabilities
(`CAP_NET_ADMIN`) and must design that access control yourself.

---

## 10. Optional tools

| Tool | Used by | Required? |
|---|---|---|
| `ip` (iproute2) | Network interfaces, routes, neighbors | Yes |
| `ping` | ICMP connectivity checks | Yes |
| `traceroute` | Traceroute diagnostics | No (degrades gracefully) |
| FRR | Optional FRR integration | No |

Install missing tools on the backend host:

```bash
# Debian/Ubuntu/Pop!_OS
sudo apt install iproute2 iputils-ping traceroute
```

---

## 11. Summary of commands

### Backend (on Linux host)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export ROUTELENS_CORS_ORIGINS="https://abhayshravan357-sudo.github.io"
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Frontend (local dev)

```bash
cd frontend
cp .env.example .env.local
# Edit .env.local as needed
npm install
npm run dev
```

### Frontend (production build)

```bash
cd frontend
npm ci
npm run build
# Output: frontend/dist/ (served from /RouteLens-Lite/ on GitHub Pages)
```

### GitHub Actions deploy

Push to `main` — the `.github/workflows/deploy.yml` workflow builds and
deploys automatically. Set `VITE_API_URL` as a repository variable first.

---

## 12. Features that require a live backend connection

The following features **will not work** if the backend is unreachable:

- Route lookup (`/lookup`)
- Packet journey tracing (`/packet-journey`)
- Network interface inspection (`/network/interfaces`)
- Route table inspection (`/network/routes`)
- Neighbor cache inspection (`/network/neighbors`)
- DNS resolution (`/network/dns-resolve`)
- Connectivity checks (`/network/connectivity`)
- Traceroute (`/network/traceroute`)
- Route editing (`POST /routes`, `PUT /routes/{index}`, `DELETE /routes/{index}`)
- Scenario lab traces (`/api/scenarios/{id}/trace`)

All of these execute on the backend host and return results to the frontend
over HTTP.
