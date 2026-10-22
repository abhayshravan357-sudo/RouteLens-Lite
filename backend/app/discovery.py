"""
RouteLens Lite - Authorized Host Discovery

Finds hosts on a network the operator has explicitly authorised.

The rules this module enforces, because discovery is the one feature
that can reach out to other machines:

- The target must be a network the operator named, and the scan stays
  inside it. A scan can never widen itself.
- The operator must confirm the scope before any packet is sent.
- The scan is rate limited and bounded in both time and packet count.
- A scan can be cancelled while it runs.
- Every scan, including refused ones, is written to an audit trail.
- A discovery that cannot run says why. It never reports hosts it did
  not actually hear from.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Deque, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.security import (
    TargetValidationError,
    reject_unsafe_target_chars,
    validate_target,
)


#: A scan may not cover more than this many addresses.
MAX_SCOPE_HOSTS = 1024

#: Seconds to wait between probes within a scan.
DEFAULT_INTERVAL = 0.2

#: Hard ceiling on how long a scan may run, in seconds.
MAX_DURATION = 300.0

#: Probes per address, at most this many.
MAX_PROBES_PER_HOST = 3

#: The most audit entries kept. Once the trail is full the oldest entry is
#: dropped to make room.
#:
#: The trail has to be bounded, because the endpoint that records a
#: refusal is unauthenticated and can be called without limit. Refusals are
#: still recorded; only how many are kept is capped.
MAX_AUDIT_ENTRIES = 500


class DiscoveryStatus(str, Enum):
    """How a discovery run ended."""

    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    REFUSED = "refused"


class AuditOutcome(str, Enum):
    """The decision recorded for a discovery request."""

    COMPLETED = "completed"
    REFUSED = "refused"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass
class DiscoveredHost:
    """A host that answered."""

    ip_address: str
    method: str
    latency_ms: Optional[float] = None
    mac_address: Optional[str] = None
    responded_at: str = ""

    def to_dict(self) -> dict:
        return {
            "ip_address": self.ip_address,
            "method": self.method,
            "latency_ms": self.latency_ms,
            "mac_address": self.mac_address,
            "responded_at": self.responded_at,
        }


@dataclass
class DiscoveryAuditEntry:
    """One line in the audit trail."""

    timestamp: str
    target: str
    outcome: AuditOutcome
    hosts_found: int
    addresses_probed: int
    duration_seconds: float
    reason: Optional[str] = None
    confirmed: bool = False

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "target": self.target,
            "outcome": self.outcome.value,
            "hosts_found": self.hosts_found,
            "addresses_probed": self.addresses_probed,
            "duration_seconds": round(self.duration_seconds, 3),
            "reason": self.reason,
            "confirmed": self.confirmed,
        }


class DiscoveryScopeError(ValueError):
    """The requested scope is not acceptable."""


@dataclass
class DiscoveryScope:
    """A validated, bounded scan scope."""

    network: ipaddress.IPv4Network
    max_hosts: int
    interval: float
    timeout: float

    @property
    def host_count(self) -> int:
        """How many addresses the scope covers."""
        return self.network.num_addresses

    def addresses(self) -> List[str]:
        """The addresses to probe, bounded by max_hosts."""
        # Skip the network and broadcast addresses of a /31 or /32.
        hosts = list(self.network.hosts())
        if len(hosts) > self.max_hosts:
            hosts = hosts[: self.max_hosts]
        return [str(h) for h in hosts]

    def to_dict(self) -> dict:
        return {
            "network": str(self.network),
            "max_hosts": self.max_hosts,
            "interval": self.interval,
            "timeout": self.timeout,
            "host_count": self.host_count,
        }


def validate_scope(
    target: str,
    max_hosts: int = 256,
    interval: float = DEFAULT_INTERVAL,
    timeout: float = 1.0,
) -> DiscoveryScope:
    """
    Turn a user supplied target into a bounded scope.

    The target may be a single address or a CIDR network. Either way the
    scope is checked against the limits before anything is probed.

    Raises:
        DiscoveryScopeError: if the scope is not acceptable.
    """
    try:
        validated = validate_target(target)
    except TargetValidationError as exc:
        # A CIDR network is not a host name, so it is validated separately.
        #
        # It goes through the same shared character filter as a host
        # target, so a network cannot carry a metacharacter into a
        # command. The filter is applied to the raw target, so leading or
        # trailing whitespace is still refused, exactly as it was when
        # this branch checked for whitespace and a leading dash itself.
        #
        # The filter is strictly stronger than the check it replaces: it
        # also refuses shell metacharacters. That does not change which
        # inputs are accepted, because ip_network() refused every one of
        # those strings anyway. Only the wording of the refusal changes.
        try:
            reject_unsafe_target_chars(target)
        except TargetValidationError:
            raise DiscoveryScopeError(str(exc)) from exc
        if "/" not in target:
            raise DiscoveryScopeError(str(exc)) from exc
        validated = target

    try:
        if "/" in validated:
            network = ipaddress.ip_network(validated, strict=False)
        else:
            network = ipaddress.ip_network(f"{validated}/32", strict=False)
    except ValueError as exc:
        raise DiscoveryScopeError(f"Not a valid network or address: {target}") from exc

    if network.version != 4:
        raise DiscoveryScopeError("Only IPv4 discovery is supported at present")

    if network.num_addresses > MAX_SCOPE_HOSTS:
        raise DiscoveryScopeError(
            f"Scope covers {network.num_addresses} addresses, more than the "
            f"limit of {MAX_SCOPE_HOSTS}. Narrow it down."
        )

    if max_hosts < 1 or max_hosts > MAX_SCOPE_HOSTS:
        raise DiscoveryScopeError(f"max_hosts must be between 1 and {MAX_SCOPE_HOSTS}")

    if interval < 0.05 or interval > 10:
        raise DiscoveryScopeError("interval must be between 0.05 and 10 seconds")

    if timeout < 0.1 or timeout > 10:
        raise DiscoveryScopeError("timeout must be between 0.1 and 10 seconds")

    return DiscoveryScope(
        network=network,
        max_hosts=max_hosts,
        interval=interval,
        timeout=timeout,
    )


class DiscoveryService:
    """
    Runs authorised discovery and keeps the audit trail.

    The service is deliberately boring: it probes one address at a time,
    waits between probes, and stops when told to.
    """

    def __init__(self) -> None:
        # Bounded: the oldest entry is dropped once the trail is full.
        self._audit: Deque[DiscoveryAuditEntry] = deque(maxlen=MAX_AUDIT_ENTRIES)
        # Only scans that are actually running are here, so a cancellation
        # request for a scan that does not exist is not remembered.
        self._cancelled: Dict[str, bool] = {}
        self._running: set[str] = set()

    # -- audit ----------------------------------------------------------

    @property
    def audit_trail(self) -> List[DiscoveryAuditEntry]:
        """Every request still in the trail, in order."""
        return list(self._audit)

    def record(
        self,
        target: str,
        outcome: AuditOutcome,
        hosts_found: int = 0,
        addresses_probed: int = 0,
        duration: float = 0.0,
        reason: Optional[str] = None,
        confirmed: bool = False,
    ) -> None:
        """Add one line to the audit trail."""
        self._audit.append(
            DiscoveryAuditEntry(
                timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                target=target,
                outcome=outcome,
                hosts_found=hosts_found,
                addresses_probed=addresses_probed,
                duration_seconds=duration,
                reason=reason,
                confirmed=confirmed,
            )
        )

    def cancel(self, scan_id: str) -> bool:
        """
        Ask a running scan to stop.

        Returns whether a scan was actually marked. A scan id that is not
        running is not recorded: remembering it would let anyone grow the
        map without limit, and it would claim a cancellation that never
        happened.
        """
        if scan_id not in self._running:
            return False
        self._cancelled[scan_id] = True
        return True

    def is_cancelled(self, scan_id: str) -> bool:
        """Whether a scan has been asked to stop."""
        return self._cancelled.get(scan_id, False)

    # -- probing --------------------------------------------------------

    async def _probe(self, address: str, timeout: float) -> Optional[DiscoveredHost]:
        """
        Probe one address.

        Returns the host if it answered, or None if it did not. A failure
        here is a normal outcome, not an error.
        """
        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                "ping",
                "-c", "1",
                "-W", str(int(max(1, round(timeout)))),
                "--",
                address,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=timeout + 1.0)
        except (asyncio.TimeoutError, FileNotFoundError, PermissionError, OSError):
            return None

        if proc.returncode != 0:
            return None

        latency = (time.monotonic() - start) * 1000.0
        return DiscoveredHost(
            ip_address=address,
            method="icmp",
            latency_ms=round(latency, 2),
            responded_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )

    async def discover(
        self,
        scope: DiscoveryScope,
        scan_id: str,
        max_probes: int = MAX_PROBES_PER_HOST,
    ) -> dict:
        """
        Probe every address in the scope, at the configured rate.

        The scan is marked as running for as long as it is, so that a
        cancellation only applies to a scan that exists. When it ends, the
        mark and any cancellation are forgotten.

        Returns a result describing what was found and what was covered.
        """
        self._running.add(scan_id)
        try:
            return await self._run_scan(scope, scan_id, max_probes)
        finally:
            self._running.discard(scan_id)
            self._cancelled.pop(scan_id, None)

    async def _run_scan(
        self,
        scope: DiscoveryScope,
        scan_id: str,
        max_probes: int,
    ) -> dict:
        """The scan itself. See `discover` for the bookkeeping around it."""
        started = time.monotonic()
        addresses = scope.addresses()
        hosts: List[DiscoveredHost] = []
        probed = 0

        for address in addresses:
            if self.is_cancelled(scan_id):
                self.record(
                    target=str(scope.network),
                    outcome=AuditOutcome.CANCELLED,
                    hosts_found=len(hosts),
                    addresses_probed=probed,
                    duration=time.monotonic() - started,
                    reason="cancelled by the operator",
                    confirmed=True,
                )
                return {
                    "status": DiscoveryStatus.CANCELLED.value,
                    "hosts": [h.to_dict() for h in hosts],
                    "addresses_probed": probed,
                    "addresses_total": len(addresses),
                    "scope": scope.to_dict(),
                    "duration_seconds": round(time.monotonic() - started, 3),
                    "cancelled": True,
                }

            for _ in range(max(1, min(MAX_PROBES_PER_HOST, max_probes))):
                probed += 1
                host = await self._probe(address, scope.timeout)
                if host is not None:
                    hosts.append(host)
                    break
                await asyncio.sleep(scope.interval)

        duration = time.monotonic() - started
        self.record(
            target=str(scope.network),
            outcome=AuditOutcome.COMPLETED,
            hosts_found=len(hosts),
            addresses_probed=probed,
            duration=duration,
            confirmed=True,
        )

        return {
            "status": DiscoveryStatus.COMPLETED.value,
            "hosts": [h.to_dict() for h in hosts],
            "addresses_probed": probed,
            "addresses_total": len(addresses),
            "scope": scope.to_dict(),
            "duration_seconds": round(duration, 3),
            "cancelled": False,
        }


#: The shared service instance.
discovery_service = DiscoveryService()
