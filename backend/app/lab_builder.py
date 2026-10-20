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

import os
import shutil
import subprocess
from typing import List, Optional

from app.scenario import Scenario

#: Prefix for every namespace this module creates, so cleanup is unambiguous.
PFX = "rl_"


def ns(node_id: str) -> str:
    """The namespace name for a node id."""
    return PFX + node_id


def build_commands(sc: Scenario) -> List[List[str]]:
    """
    Produce the command sequence that realises a scenario.

    Covers namespace creation, veth pairs, address assignment, link state,
    IP forwarding on routers, and static routes.
    """
    cmds: List[List[str]] = []

    # Namespaces, with loopback up.
    for node in sc.nodes:
        cmds.append(["ip", "netns", "add", ns(node.id)])
        cmds.append(["ip", "-n", ns(node.id), "link", "set", "lo", "up"])

    # One veth pair per link, moved into the namespaces and renamed.
    for idx, link in enumerate(sc.links):
        a_nid, a_ifname = link.a.split(":")
        b_nid, b_ifname = link.b.split(":")
        tmp_a, tmp_b = f"rlv{idx}a", f"rlv{idx}b"

        cmds.append(["ip", "link", "add", tmp_a, "type", "veth", "peer", "name", tmp_b])
        cmds.append(["ip", "link", "set", tmp_a, "netns", ns(a_nid)])
        cmds.append(["ip", "link", "set", tmp_b, "netns", ns(b_nid)])
        cmds.append(["ip", "-n", ns(a_nid), "link", "set", tmp_a, "name", a_ifname])
        cmds.append(["ip", "-n", ns(b_nid), "link", "set", tmp_b, "name", b_ifname])

    # Addresses and link state.
    for node in sc.nodes:
        for iface in node.ifaces:
            cmds.append(
                ["ip", "-n", ns(node.id), "addr", "add", iface.cidr, "dev", iface.name]
            )
            cmds.append(["ip", "-n", ns(node.id), "link", "set", iface.name, "up"])

    # Forwarding on routers only.
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

    # Static routes.
    for node in sc.nodes:
        for route in node.routes:
            cmd = ["ip", "-n", ns(node.id), "route", "add", route.prefix]
            if route.via:
                cmd += ["via", route.via]
            cmd += ["dev", route.dev, "metric", str(route.metric)]
            cmds.append(cmd)

    return cmds


def teardown_commands(scenario: Scenario) -> List[List[str]]:
    """Commands that remove every namespace belonging to a scenario."""
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


def run_all(
    commands: List[List[str]],
    dry_run: bool = True,
    stop_on_error: bool = True,
) -> dict:
    """
    Execute a list of commands.

    In dry-run mode the commands are reported and nothing is executed.
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
    for cmd in commands:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except subprocess.TimeoutExpired:
            log.append({"cmd": " ".join(cmd), "rc": -1, "stderr": "timed out"})
            return {"status": "failed", "log": log, "failed_at": cmd}
        except OSError as exc:
            log.append({"cmd": " ".join(cmd), "rc": -1, "stderr": str(exc)})
            return {"status": "failed", "log": log, "failed_at": cmd}

        entry = {
            "cmd": " ".join(cmd),
            "rc": result.returncode,
            "stdout": result.stdout[-500:] if result.stdout else "",
            "stderr": result.stderr[-500:] if result.stderr else "",
        }
        log.append(entry)

        if result.returncode != 0 and stop_on_error:
            return {"status": "failed", "log": log, "failed_at": cmd}

    return {"status": "ok", "log": log}


def probe(src: str, dst_ip: str) -> dict:
    """
    Ping a destination from inside a namespace.

    Returns a dict whose status is one of delivered, failed, timeout,
    unavailable, or error. Never fabricates a success.
    """
    reason = _guard()
    if reason:
        return {"status": "unavailable", "reason": reason}

    try:
        result = subprocess.run(
            ["ip", "netns", "exec", ns(src), "ping", "-c", "1", "-W", "1", "--", dst_ip],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "provenance": "lab"}
    except OSError as exc:
        return {"status": "error", "reason": str(exc), "provenance": "lab"}

    return {
        "status": "delivered" if result.returncode == 0 else "failed",
        "rc": result.returncode,
        "output": result.stdout[-500:] if result.stdout else "",
        "provenance": "lab",
    }
