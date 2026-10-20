# RouteLens Lite

A simple IPv4 routing table analyzer for a college project.

## Features
- Add and view routing table entries
- Find the best route using longest-prefix matching
- Display next hop and explain route selection
- Visualize the selected network route
- Handle invalid destinations and unreachable routes

## Technology
- Backend: Python and FastAPI
- Frontend: React, TypeScript, and Vite
- Testing: pytest and frontend build checks

## Backend Setup

### Prerequisites
- Python 3.11+
- pip (Python package manager)

### Installation
```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Running the Backend
```bash
# From the backend directory with virtual environment activated
uvicorn app.main:app --reload --port 8000
```
The API will be available at http://localhost:8000
Health check: http://localhost:8000/health
Interactive API docs: http://localhost:8000/docs

### Running Tests
```bash
# From the backend directory with virtual environment activated
pytest
```
Or for more verbose output:
```bash
pytest -v
```
