"""
RouteLens Lite - Read-only command guard and audit trail.

This module is the gate between the collectors and whatever actually
runs a command on a router. Two things matter here.

First, a collector may only ask a router to read. The allowlist below
is short on purpose: `show`, `ip -j` and `hostname`. A command that
merely starts with an allowed prefix but carries a shell metacharacter
is refused too, because a command that can chain another command is not
a read.

Second, every command that is run is written down: who it was run
against, what it was, when, and how it went. Credentials are never
written down, and the trail is bounded so that a long run cannot fill
memory.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Deque, List, Optional


#: The only command prefixes a collector may run. Read-only, all of them.
ALLOWED = ("show ", "ip -j ", "hostname")

#: Characters that could chain, redirect or expand another command.
#: A command containing any of these is not a read, whatever it starts
#: with, so it is refused.
SHELL_METACHARACTERS = frozenset(";|&`$()<>\\\"'*?!\n\r\t[]{}")

#: The most audit entries kept. Once the trail is full the oldest entry
#: is dropped to make room, so a long run cannot grow it without bound.
MAX_AUDIT_ENTRIES = 500

#: How much of an error message is kept. Enough to diagnose, not enough
#: to fill the trail.
MAX_ERROR_CHARS = 300

#: Patterns that look like a credential, and what is written in their
#: place. A target may carry userinfo, and a command may carry a
#: password, and neither belongs in a log.
_CREDENTIAL_PATTERNS = (
    # key=value or key: value, where the key names a secret
    re.compile(r"(?i)\b(pass(?:word)?|secret|token|api[_-]?key)\b\s*[=:]\s*\S+"),
    # userinfo in a URL, or in a target such as admin:secret@10.0.0.1
    re.compile(r"(?i)([a-z0-9._%+-]+):([^/\s@]+)@"),
)


class CommandNotAllowed(PermissionError):
    """
    Raised when a collector asks for a command that is not read-only.

    This is a PermissionError so that a caller which forgets to check
    still stops, rather than running the command.
    """


def redact(text: str) -> str:
    """
    Remove anything that looks like a credential from a string.

    The audit trail records what was run and where. It must not record a
    password, so anything shaped like one is replaced before it is
    written down.
    """
    if not text:
        return text
    # A secret given as a value: password=letmein -> password=***
    redacted = _CREDENTIAL_PATTERNS[0].sub(r"\1=***", text)
    # A secret given as userinfo: admin:letmein@host -> admin:***@host
    redacted = _CREDENTIAL_PATTERNS[1].sub(r"\1:***@", redacted)
    return redacted


def command_problem(command: str) -> Optional[str]:
    """
    Say why a command may not be run, or None if it may.

    A command is allowed when it starts with an allowed prefix, has no
    leading whitespace, and contains nothing that could chain or expand
    another command.
    """
    if not isinstance(command, str) or not command.strip():
        return "the command is empty"
    if command != command.lstrip():
        return "the command starts with whitespace"
    found = sorted({ch for ch in command if ch in SHELL_METACHARACTERS})
    if found:
        shown = " ".join(repr(ch) for ch in found)
        return f"the command contains {shown}, which could chain or expand another command"
    if not any(command.startswith(prefix) for prefix in ALLOWED):
        allowed = ", ".join(repr(prefix) for prefix in ALLOWED)
        return f"the command is not read-only; only {allowed} may be run"
    return None


def check_command(command: str) -> None:
    """
    Raise PermissionError if a command may not be run.

    This is the read-only guard. It is deliberately separate from the
    runner so that it can be tested on its own and used by any collector.
    """
    problem = command_problem(command)
    if problem is not None:
        raise CommandNotAllowed(f"Refusing to run {command!r}: {problem}.")


@dataclass
class AuditEntry:
    """One line in the audit trail."""

    timestamp: str
    target: str
    command: str
    outcome: str
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "target": self.target,
            "command": self.command,
            "outcome": self.outcome,
            "error": self.error,
        }


@dataclass
class AuditedRunner:
    """
    Runs read-only commands, and writes down what it ran.

    The runner that actually executes a command is injected, so this
    module never shells out itself and a collector can be pointed at
    anything: a real router over SSH, a container, or a fake in a test.

    The guard is applied here, so every caller of an AuditedRunner gets
    it, and the trail records both the commands that ran and the ones
    that were refused.
    """

    run: Callable[[str, str], str]
    max_audit: int = MAX_AUDIT_ENTRIES
    _audit: Deque[AuditEntry] = field(default_factory=deque, init=False)

    def __post_init__(self) -> None:
        self._audit = deque(maxlen=self.max_audit)

    @property
    def audit(self) -> List[AuditEntry]:
        """The audit trail, oldest first."""
        return list(self._audit)

    def _record(
        self, target: str, command: str, outcome: str, error: Optional[str]
    ) -> None:
        self._audit.append(
            AuditEntry(
                timestamp=datetime.now(timezone.utc).isoformat(),
                target=redact(str(target)),
                command=redact(str(command)),
                outcome=outcome,
                error=redact(error)[:MAX_ERROR_CHARS] if error else None,
            )
        )

    def __call__(self, target: str, command: str) -> str:
        """
        Run a read-only command against a target.

        Raises:
            CommandNotAllowed: if the command is not read-only
            Exception: whatever the injected runner raised, after the
                failure has been written to the trail
        """
        problem = command_problem(command)
        if problem is not None:
            self._record(target, command, "refused", problem)
            raise CommandNotAllowed(f"Refusing to run {command!r}: {problem}.")

        try:
            output = self.run(target, command)
        except Exception as exc:
            self._record(target, command, "failed", f"{type(exc).__name__}: {exc}")
            raise

        self._record(target, command, "ok", None)
        return output
