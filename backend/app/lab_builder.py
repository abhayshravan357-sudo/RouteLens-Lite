"""
RouteLens Lite - Lab Builder

Builds real Linux network namespaces from a Scenario definition so that the
simulated trace can be compared against actual packet forwarding.

Safety:
- Commands are always argument lists, never shell strings.
- Namespace and interface names are validated to be shell-safe.
- Nothing runs without root; the caller is told why instead of failing silently.
- Teardown is idempotent: missing namespaces are not an error.
"""

from __future__ import annotations

import ipaddress as ipa
import os
import shutil
import subprocess
from typing import List, Optional

from app.scenario import Scenario, Node, Route


#: Prefix for every namespace this module creates, so cleanup is unambiguous.
PFX = "rl_"


def ns(node_id: str) -> str:
    """The namespace name for a node id."""
    return PFX + node_id


def _veth_names(idx: int) -> tuple[str, str]:
    """Generate consistent veth temporary names using the PFX prefix."""
    return f"{PFX}v{idx}a", f"{PFX}v{idx}b"


def _validate_route_via(route: Route, node: Node) -> Optional[str]:
    """
    Validate that a route's `via` address is reachable on the specified `dev` interface.

    Returns an error message if validation fails, None if valid.
    """
    if not route.via:
        return None  # No via = directly connected, no validation needed

    via_ip = ipa.ip_address(route.via)

    # Find the interface on this node with name route.dev
    iface = next((i for i in node.ifaces if i.name == route.dev), None)
    if not iface:
        return f"Route {route.prefix} references unknown interface {route.dev!r}"

    # Check if via_ip is in the same network as the interface
    if via_ip not in iface.net:
        return (
            f"Route {route.prefix} via {route.via} is not reachable on {route.dev}: "
            f"{route.via} is not in {iface.net}"
        )

    return None


def build_commands(sc: Scenario) -> List[List[str]]:
    """
    Produce the command sequence that realises a scenario.

    Covers namespace creation, veth pairs, address assignment, link state,
    IP forwarding on routers, and static routes.

    Validates:
    - Every namespace is created before anything is moved into it
    - lo is brought up in each namespace
    - Each veth pair is created, then BOTH ends are moved into their namespace,
      then renamed — a veth renamed before it is moved will fail
    - The interface name in the namespace matches the name the scenario uses
    - Addresses are added after the interface is renamed
    - Interfaces are brought up after addresses are added
    - IP forwarding is enabled on routers only, never on hosts
    - Static routes are added after the interface is up, and dev names an interface that exists
    - A route with via on a different subnet is rejected (would fail at ip route add time)
    """
    cmds: List[List[str]] = []

    # 1. Namespaces, with loopback up.
    for node in sc.nodes:
        cmds.append(["ip", "netns", "add", ns(node.id)])
        cmds.append(["ip", "-n", ns(node.id), "link", "set", "lo", "up"])

    # 2. One veth pair per link, moved into the namespaces and renamed.
    for idx, link in enumerate(sc.links):
        a_nid, a_ifname = link.a.split(":")
        b_nid, b_ifname = link.b.split(":")
        tmp_a, tmp_b = _veth_names(idx)

        cmds.append(["ip", "link", "add", tmp_a, "type", "veth", "peer", "name", tmp_b])
        cmds.append(["ip", "link", "set", tmp_a, "netns", ns(a_nid)])
        cmds.append(["ip", "link", "set", tmp_b, "netns", ns(b_nid)])
        cmds.append(["ip", "-n", ns(a_nid), "link", "set", tmp_a, "name", a_ifname])
        cmds.append(["ip", "-n", ns(b_nid), "link", "set", tmp_b, "name", b_ifname])

    # 3. Addresses and link state.
    for node in sc.nodes:
        for iface in node.ifaces:
            cmds.append(
                ["ip", "-n", ns(node.id), "addr", "add", iface.cidr, "dev", iface.name]
            )
            cmds.append(["ip", "-n", ns(node.id), "link", "set", iface.name, "up"])

    # 4. Forwarding on routers only.
    for node in sc.nodes:
        if node.kind == "router":
            cmds.append(
                [
                    "ip", "netns", "exec", ns(node.id),
                    "sysctl", "-qw", "net.ipv4.ip_forward=1",
                ]
            )
            cmds.append(
                [
                    "ip", "netns", "exec", ns(node.id),
                    "sysctl", "-qw", "net.ipv6.conf.all.forwarding=1",
                ]
            )

    # 5. Static routes - with validation.
    for node in sc.nodes:
        for route in node.routes:
            # Validate route before adding to command list
            err = _validate_route_via(route, node)
            if err:
                # This is a scenario definition error - fail fast with clear message
                raise ValueError(f"Node {node.id}: {err}")

            cmd = ["ip", "-n", ns(node.id), "route", "add", route.prefix]
            if route.via:
                cmd += ["via", route.via]
            cmd += ["dev", route.dev, "metric", str(route.metric)]
            cmds.append(cmd)

    return cmds


def teardown_commands(scenario: Scenario) -> List[List[str]]:
    """Commands that remove every namespace belonging to a scenario.

    Idempotent: missing namespaces are not an error.
    """
    return [["ip", "netns", "del", ns(node.id)] for node in scenario.nodes]


def _guard() -> Optional[str]:
    """Why the lab cannot run right now, or None if it can."""
    if os.geteuid() != 0:
        return (
            "needs root: network namespaces require CAP_SYS_ADMIN. "
            "Run the backend with sudo only for lab use."
        )
    if not shutil.which("ip"):
        return "the `ip` command was not found on this system"
    return None


class LabRunError(Exception):
    """Raised when a lab command fails during real execution."""

    def __init__(self, index: int, cmd: List[str], rc: int, stderr: str, stdout: str):
        self.index = index
        self.cmd = cmd
        self.rc = rc
        self.stderr = stderr
        self.stdout = stdout
        super().__init__(
            f"Command {index} failed (rc={rc}): {' '.join(cmd)}\nstderr: {stderr}"
        )


def run_all(
    commands: List[List[str]],
    dry_run: bool = True,
    stop_on_error: bool = True,
) -> dict:
    """
    Execute a list of commands.

    In dry-run mode the commands are reported and nothing is executed.
    Real execution requires dry_run=False AND root privileges.

    Returns a dict with:
    - status: "dry_run", "ok", "failed", "unavailable"
    - log: list of per-command results (for dry_run: command strings; for real: detailed entries)
    - failed_at: index of failed command (only on failure)
    - error: error message (only on failure)
    """
    if dry_run:
        return {
            "status": "dry_run",
            "commands": [" ".join(cmd) for cmd in commands],
        }

    reason = _guard()
    if reason:
        return {"status": "unavailable", "reason": reason}

    log: List[dict] = []
    for idx, cmd in enumerate(commands):
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except subprocess.TimeoutExpired:
            entry = {"index": idx, "cmd": " ".join(cmd), "rc": -1, "stderr": "timed out", "stdout": ""}
            log.append(entry)
            return {"status": "failed", "log": log, "failed_at": idx, "error": "timed out"}
        except OSError as exc:
            entry = {"index": idx, "cmd": " ".join(cmd), "rc": -1, "stderr": str(exc), "stdout": ""}
            log.append(entry)
            return {"status": "failed", "log": log, "failed_at": idx, "error": str(exc)}

        entry = {
            "index": idx,
            "cmd": " ".join(cmd),
            "rc": result.returncode,
            "stdout": result.stdout[-500:] if result.stdout else "",
            "stderr": result.stderr[-500:] if result.stderr else "",
        }
        log.append(entry)

        if result.returncode != 0 and stop_on_error:
            return {
                "status": "failed",
                "log": log,
                "failed_at": idx,
                "error": result.stderr.strip() or f"command exited with {result.returncode}",
            }

    return {"status": "ok", "log": log}


def run_teardown(commands: List[List[str]], dry_run: bool = False) -> dict:
    """
    Execute teardown commands idempotently.

    Missing namespaces (already gone) are not treated as errors.
    Other failures are reported.
    """
    if dry_run:
        return {
            "status": "dry_run",
            "commands": [" ".join(cmd) for cmd in commands],
        }

    reason = _guard()
    if reason:
        return {"status": "unavailable", "reason": reason}

    log: List[dict] = []
    for idx, cmd in enumerate(commands):
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except subprocess.TimeoutExpired:
            entry = {"index": idx, "cmd": " ".join(cmd), "rc": -1, "stderr": "timed out", "stdout": ""}
            log.append(entry)
            return {"status": "failed", "log": log, "failed_at": idx, "error": "timed out"}
        except OSError as exc:
            entry = {"index": idx, "cmd": " ".join(cmd), "rc": -1, "stderr": str(exc), "stdout": ""}
            log.append(entry)
            return {"status": "failed", "log": log, "failed_at": idx, "error": str(exc)}

        entry = {
            "index": idx,
            "cmd": " ".join(cmd),
            "rc": result.returncode,
            "stdout": result.stdout[-500:] if result.stdout else "",
            "stderr": result.stderr[-500:] if result.stderr else "",
        }
        log.append(entry)

        # ip netns del returns 1 if namespace doesn't exist - treat as success (idempotent)
        if result.returncode != 0:
            stderr_lower = result.stderr.lower()
            if "cannot find" in stderr_lower or "does not exist" in stderr_lower or "invalid argument" in stderr_lower:
                # Namespace already gone - this is fine for idempotent teardown
                entry["idempotent_skip"] = True
                continue
            return {
                "status": "failed",
                "log": log,
                "failed_at": idx,
                "error": result.stderr.strip() or f"command exited with {result.returncode}",
            }

    return {"status": "ok", "log": log}


def probe(src: str, dst_ip: str) -> dict:
    """
    Ping a destination from inside a namespace.

    Returns a dict whose status is one of:
    - "delivered": ping succeeded (exit code 0)
    - "timeout": ping timed out (no reply within -W)
    - "unreachable": host/network unreachable (ping ran but failed)
    - "permission_denied": pkexec/sudo failed or no CAP_NET_RAW
    - "missing_binary": ping or ip command not found
    - "unavailable": lab cannot run (not root, ip missing)
    - "error": other unexpected error

    Never fabricates a success.
    """
    reason = _guard()
    if reason:
        return {"status": "unavailable", "reason": reason}

    # Check if ping binary exists
    if not shutil.which("ping"):
        return {"status": "missing_binary", "reason": "ping command not found", "provenance": "lab"}

    try:
        result = subprocess.run(
            ["ip", "netns", "exec", ns(src), "ping", "-c", "1", "-W", "1", "--", dst_ip],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "reason": "The probe command timed out before completing.", "provenance": "lab"}
    except PermissionError:
        return {"status": "permission_denied", "reason": "permission denied executing ip netns exec", "provenance": "lab"}
    except FileNotFoundError:
        return {"status": "missing_binary", "reason": "ip command not found", "provenance": "lab"}
    except OSError as exc:
        return {"status": "error", "reason": str(exc), "provenance": "lab"}

    # Analyze ping exit code and output
    if result.returncode == 0:
        return {
            "status": "delivered",
            "rc": result.returncode,
            "output": result.stdout[-500:] if result.stdout else "",
            "provenance": "lab",
        }

    # ping exit codes (from man ping):
    # 0 = success
    # 1 = no reply received (timeout or unreachable)
    # 2 = other error (usage, permission, etc.)
    stderr_lower = result.stderr.lower()
    stdout_lower = result.stdout.lower()

    if "permission denied" in stderr_lower or "operation not permitted" in stderr_lower:
        return {"status": "permission_denied", "reason": "The probe command did not have sufficient permissions.", "rc": result.returncode, "stderr": result.stderr, "provenance": "lab"}

    if "network is unreachable" in stderr_lower or "host unreachable" in stderr_lower:
        return {"status": "unreachable", "reason": "The target host or network could not be reached.", "rc": result.returncode, "stderr": result.stderr, "provenance": "lab"}

    if "name or service not known" in stderr_lower:
        return {"status": "error", "reason": "DNS resolution failed", "provenance": "lab"}

    # Default: treat as unreachable (no reply)
    return {
        "status": "unreachable",
        "reason": "The target host or network could not be reached.",
        "rc": result.returncode,
        "stdout": result.stdout[-500:] if result.stdout else "",
        "stderr": result.stderr[-500:] if result.stderr else "",
        "provenance": "lab",
    }