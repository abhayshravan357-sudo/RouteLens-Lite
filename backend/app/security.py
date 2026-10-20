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
- Requests are rate limited per client.
"""

from __future__ import annotations

import ipaddress
import re
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional

from fastapi import HTTPException


#: Hostname shape: labels of letters/digits/hyphens separated by dots.
HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9-]{1,63}$",
    re.IGNORECASE,
)


class TargetValidationError(ValueError):
    """The supplied target is not an acceptable host or address."""


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

    # A leading dash would let the target be read as an option by the
    # underlying tool. Reject it outright.
    if candidate.startswith("-"):
        raise TargetValidationError("A target may not start with '-'")

    # Reject anything with shell or whitespace metacharacters.
    if any(ch.isspace() for ch in candidate):
        raise TargetValidationError("A target may not contain whitespace")
    if any(ch in candidate for ch in ";|&$`<>(){}[]!\"'*\\"):
        raise TargetValidationError("A target may not contain shell metacharacters")

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
    A simple sliding-window rate limiter.

    Used to bound how many diagnostic requests a single client may make
    in a given period.
    """

    def __init__(self, max_requests: int = 10, period_seconds: float = 60.0):
        self.max_requests = max_requests
        self.period_seconds = period_seconds
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        """
        Record a request for `key` and raise if the limit is exceeded.

        Raises:
            HTTPException: 429 when the client has made too many requests.
        """
        now = time.monotonic()
        window = self._hits[key]
        while window and (now - window[0]) > self.period_seconds:
            window.popleft()

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

    def reset(self, key: Optional[str] = None) -> None:
        """Forget recorded requests, for a key or entirely."""
        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)


#: Shared limiter for the diagnostic endpoints.
diagnostic_limiter = RateLimiter(max_requests=20, period_seconds=60.0)
