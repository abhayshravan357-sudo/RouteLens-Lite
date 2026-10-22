"""
State storage for router discovery.

Centralizes mutable in-memory state (runs, audit logs, active counts)
to avoid circular imports between routes and engine/analysis.
"""

from typing import Any, Dict, List

RUNS: Dict[str, Dict[str, Any]] = {}
AUDIT: List[Dict[str, Any]] = []
CLIENT_RUN_COUNTS: Dict[str, int] = {}
CREDENTIALS: Dict[str, Any] = {}
run_methods: List[Any] = []
