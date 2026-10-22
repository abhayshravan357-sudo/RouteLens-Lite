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


#: Commands that must match exactly, the whole string. A command that
#: merely starts with one of these is not that command, so "hostname -x"
#: is refused.
ALLOWED_EXACT = (
    "hostname",
    "lldpcli show neighbors -f json",
)

#: Prefixes a command may start with.
ALLOWED_PREFIX = (
    "show ",
    "ip -j ",
)

#: Every command the guard will run, for the record.
ALLOWED = ALLOWED_EXACT + ALLOWED_PREFIX

#: The characters that could chain, redirect or expand another command.
#: A command containing any of these is not a read, whatever it starts
#: with, so it is refused.
#:
#: This is the project's shared filter, extended by the four characters
#: that only matter in a command: a wildcard, and the whitespace that
#: could end a line. There is one list of dangerous characters, so a
#: host target, a CIDR network and a device command are all filtered the
#: same way.
try:
    from app.security import SHELL_METACHARACTERS as SHARED_SHELL_METACHARACTERS
except ImportError:  # pragma: no cover - the shared filter is not merged yet
    # The same set as app.security's, for branches that predate it. Once
    # the shared filter is merged the import above is used and this is
    # only a fallback.
    SHARED_SHELL_METACHARACTERS = ";|&$`<>(){}[]!\"'*\\"

SHELL_METACHARACTERS = frozenset(SHARED_SHELL_METACHARACTERS) | frozenset("?\n\r\t")

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
    # A secret given as a value: password=letmein, secret: letmein
    re.compile(r"(?i)\b(pass(?:word)?|secret|token|api[_-]?key)(\s*[=:]\s*)\S+"),
    # A secret given as userinfo with a host after it: admin:letmein@10.0.0.1.
    # The host is kept, because knowing which host was talked to is the
    # point of the trail.
    re.compile(r"(?i)(?<![\w.])([a-z0-9._%+-]+):([^\s/@]+)@"),
    # A secret given as userinfo with nothing after it: admin:letmein.
    #
    # The secret is anything up to the next space, so it may not start
    # with a "/" (which keeps the scheme of a URL from being mistaken
    # for a name) and it may not start with a "*" (which keeps a secret
    # that has already been replaced from being replaced again). An
    # ordinary message such as "connect: refused" keeps its colon and
    # its text, because there is a space after the colon.
    re.compile(r"(?i)(?<![\w.])([a-z0-9._%+-]+):([^\s/*][^\s]*)"),
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
    written down. Where a shape cannot be told apart from ordinary text
    with confidence, the text is replaced: a "***" is better than a
    leaked password, and the trail is read by a person.
    """
    if not text:
        return text
    # A secret given as a value: password=letmein -> password=***
    redacted = _CREDENTIAL_PATTERNS[0].sub(r"\1\2***", text)
    # A secret given as userinfo with a host: admin:letmein@host -> admin:***@host
    redacted = _CREDENTIAL_PATTERNS[1].sub(r"\1:***@", redacted)
    # A secret given as userinfo with nothing after it: admin:letmein -> admin:***
    redacted = _CREDENTIAL_PATTERNS[2].sub(r"\1:***", redacted)
    return redacted


def command_problem(command: str) -> Optional[str]:
    """
    Say why a command may not be run, or None if it may.

    A command is allowed when it matches an exact entry, or starts with
    an allowed prefix, and has no leading whitespace and contains
    nothing that could chain or expand another command.
    """
    if not isinstance(command, str) or not command.strip():
        return "the command is empty"
    if command != command.lstrip():
        return "the command starts with whitespace"
    found = sorted({ch for ch in command if ch in SHELL_METACHARACTERS})
    if found:
        shown = " ".join(repr(ch) for ch in found)
        return f"the command contains {shown}, which could chain or expand another command"
    if command in ALLOWED_EXACT:
        return None
    if any(command.startswith(prefix) for prefix in ALLOWED_PREFIX):
        return None
    allowed = ", ".join(
        [repr(entry) for entry in ALLOWED_EXACT]
        + [f"{prefix!r}..." for prefix in ALLOWED_PREFIX]
    )
    return f"the command is not read-only; only {allowed} may be run"


def check_command(command: str) -> None:
    """
    Raise PermissionError if a command may not be run.

    This is the read-only guard. It is deliberately separate from the
    runner so that it can be tested on its own and used by any collector.
    """
    problem = command_problem(command)
    if problem is not None:
        raise CommandNotAllowed(f"Refusing to run {command!r}: {problem}.")


def safe_exception_reason(exc: BaseException, limit: int = 160) -> str:
    """
    A short reason for a failure, with anything device-shaped removed.

    A router's stderr can carry a banner, a login prompt or a snippet of
    its configuration. None of that belongs in a log, so a reason that
    is long or spans lines is reduced to the exception's name.
    """
    name = type(exc).__name__
    text = str(exc)
    if not text:
        return name
    if len(text) > limit or "\n" in text or "\r" in text:
        return name
    collapsed = " ".join(text.split())
    return f"{name}: {collapsed}" if collapsed else name


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
            # The reason is built here and kept short. A device's own
            # output is never copied into the trail.
            self._record(target, command, "failed", safe_exception_reason(exc))
            raise

        self._record(target, command, "ok", None)
        return output
