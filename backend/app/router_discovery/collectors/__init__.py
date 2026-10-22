"""
RouteLens Lite - Device collectors.

A collector reads one device and returns what it read. The read-only
guard and the audit trail live in base, so every collector inherits them
and no collector can run a command that writes.
"""

from app.router_discovery.collectors.base import (
    ALLOWED,
    AuditedRunner,
    AuditEntry,
    CommandNotAllowed,
    check_command,
    command_problem,
    redact,
)

__all__ = [
    "ALLOWED",
    "AuditedRunner",
    "AuditEntry",
    "CommandNotAllowed",
    "check_command",
    "command_problem",
    "redact",
]
