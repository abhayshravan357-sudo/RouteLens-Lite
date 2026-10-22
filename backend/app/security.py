"""
RouteLens Lite - Security Helpers

Input validation and rate limiting for the diagnostic endpoints.

The diagnostics let the backend run commands such as ping and traceroute on
behalf of the browser. That makes them a command-injection surface if the
target is not validated, and a way to make the machine generate arbitrary
traffic if the rate is not bounded.

Rules enforced here:
- Targets must be a literal IP address, or a hostname that looks like one.
- A target may never start with "-", so it can never be read as an option.
- Requests are rate limited per client and per operation, so one client
  exhausting its allowance does not stop any other client.
"""

from __future__ import annotations

import ipaddress
import re
import time
from collections import OrderedDict, deque
from typing import Deque, Dict, Optional

from fastapi import HTTPException, Request


#: Hostname shape: labels of letters/digits/hyphens separated by dots.
HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9-]{1,63}$",
    re.IGNORECASE,
)

#: The most distinct client keys the limiter will remember at once.
#:
#: The key map is keyed by client address, so an unauthenticated caller
#: could otherwise grow it without limit simply by sending requests from
#: many addresses. When the cap is reached the least recently used key is
#: dropped to make room.
MAX_TRACKED_CLIENTS = 1024


class TargetValidationError(ValueError):
    """The supplied target is not an acceptable host or address."""


#: Characters that must never appear in a value that will be handed to a
#: command or a device. A leading dash is handled separately, because it
#: would let the value be read as an option rather than as an argument.
SHELL_METACHARACTERS = ";|&$`<>(){}[]!\"'*\\"


def reject_unsafe_target_chars(value: str) -> str:
    """
    Apply the shared safety filter to a value that will be used as a
    command argument or a device address.

    The value is checked **exactly as given**. It is not stripped, because
    a caller that strips has already decided that surrounding whitespace is
    acceptable, and a caller that does not strip must still have leading or
    trailing whitespace refused.

    The filter rejects a value that:
    - is empty, or is not a string
    - starts with "-", so it can never be read as a command line option
    - contains whitespace
    - contains a shell metacharacter

    The same filter is used for a host target and for a CIDR network, so
    that a network cannot carry a metacharacter into a command. It is
    applied *before* the value is parsed, rather than relying on the parser
    to notice a metacharacter later.

    Args:
        value: The value to check.

    Returns:
        The value, unchanged.

    Raises:
        TargetValidationError: if the value is not safe to use.
    """
    if not isinstance(value, str):
        raise TargetValidationError("A target is required")

    if not value:
        raise TargetValidationError("A target is required")

    # A leading dash would let the value be read as an option by the
    # underlying tool. Reject it outright.
    if value.startswith("-"):
        raise TargetValidationError("A target may not start with '-'")

    # Reject anything with shell or whitespace metacharacters.
    if any(ch.isspace() for ch in value):
        raise TargetValidationError("A target may not contain whitespace")
    if any(ch in value for ch in SHELL_METACHARACTERS):
        raise TargetValidationError("A target may not contain shell metacharacters")

    return value


def validate_target(target: str) -> str:
    """
    Validate a user supplied target for use as a command argument.

    Accepts a literal IPv4/IPv6 address, or a hostname made of
    letters, digits, hyphens and dots.

    Raises:
        TargetValidationError: if the target is empty, malformed, or
            could be mistaken for a command line option.
    """
    if not target or not isinstance(target, str):
        raise TargetValidationError("A target is required")

    candidate = target.strip()
    if not candidate:
        raise TargetValidationError("A target is required")

    # The shared filter does the character checks. It is given the
    # stripped form, because a target with surrounding whitespace is
    # accepted and trimmed, exactly as it was before the filter was
    # shared out.
    reject_unsafe_target_chars(candidate)

    # Literal addresses are always fine.
    try:
        ipaddress.ip_address(candidate)
        return candidate
    except ValueError:
        pass

    # Otherwise it must look like a hostname.
    if not HOSTNAME_RE.match(candidate):
        raise TargetValidationError(f"Not a valid IP address or hostname: {target!r}")

    return candidate


class RateLimiter:
    """
    A sliding-window rate limiter, keyed by client and operation.

    Every distinct key gets its own budget, so one client exhausting its
    allowance does not stop any other client from making requests. The key
    for a request is built by `client_key`, which pairs the operation with
    the peer's address. The operation is part of the key so that the limit
    is not weakened: a client still gets its full allowance for each
    operation rather than one shared allowance across all of them.

    The number of keys is bounded. A key is forgotten once its window
    empties, and if the map reaches its cap the least recently used key is
    dropped to make room. Both bounds matter, because an unauthenticated
    caller could otherwise grow the map without limit just by sending
    requests from many addresses.
    """

    def __init__(
        self,
        max_requests: int = 10,
        period_seconds: float = 60.0,
        max_keys: int = MAX_TRACKED_CLIENTS,
    ):
        self.max_requests = max_requests
        self.period_seconds = period_seconds
        self.max_keys = max_keys
        self._hits: "OrderedDict[str, Deque[float]]" = OrderedDict()

    def _expire(self, now: float) -> None:
        """Drop hits that have aged out, and any key left with no hits."""
        for key in list(self._hits.keys()):
            window = self._hits[key]
            while window and (now - window[0]) > self.period_seconds:
                window.popleft()
            if not window:
                del self._hits[key]

    def check(self, key: str) -> None:
        """
        Record a request for `key` and raise if the limit is exceeded.

        Raises:
            HTTPException: 429 when the client has made too many requests.
        """
        now = time.monotonic()
        self._expire(now)

        window = self._hits.get(key)
        if window is None:
            if len(self._hits) >= self.max_keys:
                # Make room by dropping the least recently used key. Its
                # owner gets a fresh allowance rather than being refused,
                # which is no worse than the alternative of turning new
                # clients away.
                self._hits.popitem(last=False)
            window = deque()
            self._hits[key] = window
        else:
            self._hits.move_to_end(key)

        if len(window) >= self.max_requests:
            retry_after = int(self.period_seconds - (now - window[0])) + 1
            raise HTTPException(
                status_code=429,
                detail=(
                    "Too many diagnostic requests. "
                    f"Try again in about {retry_after} second(s)."
                ),
                headers={"Retry-After": str(retry_after)},
            )

        window.append(now)

    @property
    def tracked_keys(self) -> int:
        """How many client keys are currently remembered."""
        return len(self._hits)

    def reset(self, key: Optional[str] = None) -> None:
        """Forget recorded requests, for a key or entirely."""
        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)


def client_key(request: Request, operation: str) -> str:
    """
    The rate limit key for a request: the operation and the peer's address.

    The peer's address is taken from the connection, not from a header.

    The X-Forwarded-For header is deliberately NOT trusted. Any client can
    set it, so believing it would let anyone bypass the limit by varying
    the header. The cost of that choice is that behind a reverse proxy
    every request appears to come from the proxy, and all clients share
    one budget again. A deployment behind a proxy would need an explicit
    list of trusted proxy addresses before the header could be believed.
    This tool has no such configuration, so it does not believe it.

    Args:
        request: The incoming request.
        operation: The operation being limited, such as "dns".

    Returns:
        A key of the form "operation:address".
    """
    client = request.client
    host = client.host if client is not None else "unknown"
    return f"{operation}:{host}"


#: Shared limiter for the diagnostic endpoints.
diagnostic_limiter = RateLimiter(max_requests=20, period_seconds=60.0)

#: Shared limiter for authorised discovery.
#:
#: Discovery is the most expensive thing this backend does: a single run
#: probes up to a few hundred addresses with real packets. It gets its own
#: limiter rather than sharing the diagnostic one, so that a burst of DNS
#: lookups cannot use up a student's discovery allowance and vice versa.
discovery_limiter = RateLimiter(max_requests=10, period_seconds=60.0)
