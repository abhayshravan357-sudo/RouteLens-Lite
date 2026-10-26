"""
RouteLens Lite - Lab Next Steps

The wording a student reads when the lab cannot be used, and the one place
that wording is written down.

Three things have to agree about what to tell somebody who opens the Virtual
Lab and finds it unusable: the API response the interface renders, the README
in `lab/`, and the `--help` output of `scripts/lab-up.sh`. If any of them
says something different, that is a defect, not a style difference. So the
text lives here, once, and the other two are generated from it and checked
against it by a test.

Nothing in this module runs a command, touches the network, or needs
privilege. It is a piece of writing with a shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Sequence


class LabCondition(str, Enum):
    """The distinct states a student can meet, in the order they meet them.

    The order matters: the first match is the condition reported, and the
    steps are for that condition alone. A student who is missing a tool
    should not be told to build the lab, because building will fail for a
    reason that has nothing to do with the missing tool.
    """

    TOOLS_MISSING = "tools_missing"
    PRIVILEGES_MISSING = "privileges_missing"
    NAMESPACES_MISSING = "namespaces_missing"
    TOPOLOGY_MISMATCH = "topology_mismatch"
    READY = "ready"


@dataclass(frozen=True)
class NextStep:
    """One thing the reader can do, in the order they should do it."""

    order: int
    title: str
    detail: str
    command: Optional[str] = None
    optional: bool = False

    def as_dict(self) -> dict:
        """The shape the API returns, so the interface need not guess."""
        return {
            "order": self.order,
            "title": self.title,
            "detail": self.detail,
            "command": self.command,
            "optional": self.optional,
        }


@dataclass
class LabGuidance:
    """What to tell the reader, and what to do about it."""

    condition: LabCondition
    summary: str
    steps: list[NextStep] = field(default_factory=list)
    optional_steps: list[NextStep] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "condition": self.condition.value,
            "summary": self.summary,
            "next_steps": [s.as_dict() for s in self.steps],
            "optional_steps": [s.as_dict() for s in self.optional_steps],
        }


#: Which package provides each tool the lab needs, and what it is for.
#: The package name is what the reader types; the purpose is what they
#: need to know to trust that installing it is the right thing to do.
TOOL_PACKAGES: dict[str, tuple[str, str]] = {
    "ip": (
        "iproute2",
        "The `ip` command creates the network namespaces and gives them their "
        "addresses and routes. It is the tool the lab is built out of.",
    ),
    "ping": (
        "iputils-ping",
        "The `ping` command sends the test packet through the lab router and "
        "reports whether it came back.",
    ),
    "tcpdump": (
        "tcpdump",
        "The `tcpdump` command captures the packet on the far side of the "
        "router, which is how the TTL and the checksum are checked against "
        "something that actually happened.",
    ),
    "timeout": (
        "coreutils",
        "The `timeout` command bounds how long a lab command may run, so a "
        "stuck command cannot hang the backend.",
    ),
}

#: The privileges a lab command needs, and why.
LAB_CAPABILITY = "CAP_SYS_ADMIN"

#: The container runtime and the tool that builds a topology with it. The
#: four-router topology is a separate thing from the lab in the application
#: and is never required by it.
CONTAINERLAB_TOOLS: dict[str, tuple[str, str]] = {
    "docker": (
        "docker.io",
        "The `docker` command runs the router containers.",
    ),
    "containerlab": (
        "containerlab",
        "The `containerlab` command builds the four-router topology from a "
        "topology file.",
    ),
}


def _ordered(steps: Sequence[NextStep]) -> list[NextStep]:
    """Number the steps in the order they were given."""
    return [
        NextStep(
            order=index,
            title=s.title,
            detail=s.detail,
            command=s.command,
            optional=s.optional,
        )
        for index, s in enumerate(steps, start=1)
    ]


def tools_missing_steps(missing_tools: Sequence[str]) -> list[NextStep]:
    """Steps for the case where a tool the lab needs is not installed.

    One step per tool, because "install iproute2" and "install tcpdump" are
    different errands and a reader who is told both at once does neither.
    """
    steps: list[NextStep] = []
    for tool in missing_tools:
        package, purpose = TOOL_PACKAGES.get(
            tool, (tool, f"The lab needs the `{tool}` command.")
        )
        steps.append(
            NextStep(
                order=0,
                title=f"Install the `{tool}` command.",
                detail=(
                    f"The lab needs the `{tool}` command, which comes from the "
                    f"`{package}` package. {purpose} Without it the lab cannot "
                    f"be built or read."
                ),
                command=f"sudo apt install {package}",
            )
        )
    steps.append(
        NextStep(
            order=0,
            title="Check what the backend says now.",
            detail=(
                "Ask the backend again. It answers with the lab's condition and "
                "the steps that are left, so you do not have to guess whether "
                "the install worked."
            ),
            command="curl -s http://127.0.0.1:8000/api/lab/status",
        )
    )
    return _ordered(steps)


def privileges_missing_steps(
    detail: str = "",
) -> list[NextStep]:
    """Steps for the case where the lab's privilege is not available.

    The privilege is for the lab and only the lab. Saying that is the
    difference between a student who reads the message and a student who
    thinks the whole application needs root.
    """
    steps = [
        NextStep(
            order=0,
            title=f"The lab needs one extra privilege: {LAB_CAPABILITY}.",
            detail=(
                f"Creating a network namespace needs {LAB_CAPABILITY}, which an "
                f"ordinary user does not have. {detail} Only the virtual lab "
                f"needs this privilege. Every other part of RouteLens - the "
                f"routing table, the lookup, the diagnostics, the report - "
                f"works as an ordinary user, and you do not have to run the "
                f"whole application as root to use them."
            ),
        ),
        NextStep(
            order=0,
            title="Start the backend with that privilege.",
            detail=(
                "Run the backend as root, or give the Python binary the "
                "capability. With the privilege the backend stops reporting a "
                "privilege problem: it will report either that the lab is "
                "ready, or that the namespaces still have to be built. It will "
                "not ask for the privilege again."
            ),
            command="sudo python -m uvicorn app.main:app --host 127.0.0.1 --port 8000",
        ),
        NextStep(
            order=0,
            title="Check what the backend says now.",
            detail=(
                "Ask the backend again. It answers with the lab's condition and "
                "the steps that are left."
            ),
            command="curl -s http://127.0.0.1:8000/api/lab/status",
        ),
    ]
    return _ordered(steps)


def namespaces_missing_steps(missing_namespaces: Sequence[str]) -> list[NextStep]:
    """Steps for the case where the lab has not been built yet."""
    names = ", ".join(missing_namespaces) if missing_namespaces else "the lab namespaces"
    steps = [
        NextStep(
            order=0,
            title="The lab has not been built yet.",
            detail=(
                f"The lab is a set of isolated Linux network namespaces, and "
                f"none of them exist yet ({names} are missing). Building the "
                f"lab creates them, and until you ask for it, nothing is "
                f"created. Everything the lab touches stays on this machine: "
                f"the namespaces are separate from your own network, and "
                f"nothing outside this machine is reached or changed."
            ),
        ),
        NextStep(
            order=0,
            title="Build the lab.",
            detail=(
                "This runs the same commands the API would run, and takes a "
                "few seconds. Building needs the network-namespace privilege. "
                "If the backend cannot get it, it will refuse the build and "
                "give you the steps for that instead, rather than failing "
                "half way."
            ),
            command="./scripts/lab-up.sh",
        ),
        NextStep(
            order=0,
            title="Check that the namespaces are there.",
            detail=(
                "The lab's namespaces are the ones whose names start with "
                "`rl_`. The lab uses three: the client, the router and the "
                "server."
            ),
            command="ip netns list | grep '^rl'",
        ),
    ]
    return _ordered(steps)


def topology_mismatch_steps(issues: Sequence[str]) -> list[NextStep]:
    """Steps for the case where the namespaces exist but hold the wrong lab."""
    detail = "; ".join(issues) if issues else "the expected addresses and routes were not found"
    steps = [
        NextStep(
            order=0,
            title="The namespaces exist, but the lab inside them is not what this application expects.",
            detail=(
                f"What the backend found: {detail}. This usually means the lab "
                f"was built by something else, or was changed after it was "
                f"built. The lab's own namespaces are the ones whose names "
                f"start with `rl_`."
            ),
        ),
        NextStep(
            order=0,
            title="Build the lab again.",
            detail=(
                "Taking the lab down and building it again puts the expected "
                "addresses, routes and forwarding back in place. This only "
                "affects the lab's own namespaces."
            ),
            command="./scripts/lab-down.sh && ./scripts/lab-up.sh",
        ),
        NextStep(
            order=0,
            title="Check what the backend says now.",
            detail=(
                "Ask the backend again. It answers with the lab's condition and "
                "the steps that are left."
            ),
            command="curl -s http://127.0.0.1:8000/api/lab/status",
        ),
    ]
    return _ordered(steps)


def ready_steps() -> list[NextStep]:
    """Steps for the case where the lab is up and working."""
    steps = [
        NextStep(
            order=0,
            title="The lab is up.",
            detail=(
                "You can send a packet through the lab router and watch it be "
                "forwarded. The simulation can be compared with the lab's own "
                "routing table, and the packet's TTL decrement and checksum "
                "can be checked against a capture of the real packet."
            ),
        ),
        NextStep(
            order=0,
            title="Take the lab down when you are finished.",
            detail=(
                "This removes the lab's namespaces again. It does not touch "
                "anything outside this machine, and it is safe to run when the "
                "lab is not there."
            ),
            command="./scripts/lab-down.sh",
        ),
    ]
    return _ordered(steps)


def containerlab_steps(missing_tools: Sequence[str]) -> list[NextStep]:
    """Steps for the separate, optional four-router topology.

    This is never a blocker for the lab in the application, and the first
    step says so, because the two are easy to confuse and the confusion
    costs a student an afternoon.
    """
    steps = [
        NextStep(
            order=0,
            title="This is not needed for the lab in the application.",
            detail=(
                "The lab in the application is built by the application "
                "itself, from the scenario you choose. It needs no container "
                "runtime, no Docker and no containerlab. If the lab in the "
                "application is what you wanted, ignore these steps."
            ),
            optional=True,
        ),
        NextStep(
            order=0,
            title="The four-router topology is a separate, optional thing.",
            detail=(
                "Router discovery can be exercised against four FRR routers - "
                "r1 to r4 - joined by point-to-point links and running OSPF. "
                "That topology is a hand-built network, not something the "
                "application creates, and it is optional."
            ),
            optional=True,
        ),
    ]
    for tool in missing_tools:
        package, purpose = CONTAINERLAB_TOOLS.get(
            tool, (tool, f"The four-router topology needs the `{tool}` command.")
        )
        steps.append(
            NextStep(
                order=0,
                title=f"Install the `{tool}` command.",
                detail=(
                    f"The four-router topology needs the `{tool}` command, "
                    f"which comes from the `{package}` package. {purpose} This "
                    f"is only for the optional topology, not for the lab in "
                    f"the application."
                ),
                command=f"sudo apt install {package}",
                optional=True,
            )
        )
    return _ordered(steps)


def diagnose(
    *,
    missing_tools: Sequence[str] = (),
    privilege_available: bool = True,
    privilege_detail: str = "",
    permission_issues: Sequence[str] = (),
    missing_namespaces: Sequence[str] = (),
    topology_issues: Sequence[str] = (),
    containerlab_missing: Sequence[str] = (),
) -> LabGuidance:
    """Work out the condition and the steps for it.

    The order of the checks is the order a student meets the problems, and
    it matters: the first problem found is the one reported, and the steps
    are for that one alone. A student missing a tool is told to install the
    tool, not to build a lab that could not work anyway.
    """
    optional_steps = containerlab_steps(containerlab_missing) if containerlab_missing else []

    if missing_tools:
        return LabGuidance(
            condition=LabCondition.TOOLS_MISSING,
            summary=(
                f"The lab cannot run because {len(missing_tools)} of the tools "
                f"it needs are not installed."
            ),
            steps=tools_missing_steps(missing_tools),
            optional_steps=optional_steps,
        )

    if not privilege_available:
        return LabGuidance(
            condition=LabCondition.PRIVILEGES_MISSING,
            summary=(
                f"The lab cannot run because this backend does not have the "
                f"{LAB_CAPABILITY} privilege it needs (permission denied)."
            ),
            steps=privileges_missing_steps(privilege_detail),
            optional_steps=optional_steps,
        )

    if permission_issues:
        # A namespace exists but cannot be read due to a namespace-specific
        # permission error. The general privilege may be available, but this
        # backend cannot access this namespace. Report it as a privileges
        # problem so the reader is not told the lab is ready.
        return LabGuidance(
            condition=LabCondition.PRIVILEGES_MISSING,
            summary=(
                f"The lab cannot run because this backend does not have "
                f"permission to read the following namespaces: "
                f"{', '.join(permission_issues)}."
            ),
            steps=privileges_missing_steps(
                "; ".join(permission_issues)
            ),
            optional_steps=optional_steps,
        )

    if missing_namespaces:
        return LabGuidance(
            condition=LabCondition.NAMESPACES_MISSING,
            summary="The lab has not been built yet.",
            steps=namespaces_missing_steps(missing_namespaces),
            optional_steps=optional_steps,
        )

    if topology_issues:
        return LabGuidance(
            condition=LabCondition.TOPOLOGY_MISMATCH,
            summary="The lab exists, but the lab inside it is not what this application expects.",
            steps=topology_mismatch_steps(topology_issues),
            optional_steps=optional_steps,
        )

    return LabGuidance(
        condition=LabCondition.READY,
        summary="The lab is up and ready for packets.",
        steps=ready_steps(),
        optional_steps=optional_steps,
    )


# ---------------------------------------------------------------------------
# The same text, rendered for a README and for a terminal
# ---------------------------------------------------------------------------

#: The conditions in the order a student meets them, with a heading for
#: each. Used to render the README section and the script's --help.
CONDITION_ORDER: list[LabCondition] = [
    LabCondition.TOOLS_MISSING,
    LabCondition.PRIVILEGES_MISSING,
    LabCondition.NAMESPACES_MISSING,
    LabCondition.TOPOLOGY_MISMATCH,
    LabCondition.READY,
]

CONDITION_HEADINGS: dict[LabCondition, str] = {
    LabCondition.TOOLS_MISSING: "The tools are missing",
    LabCondition.PRIVILEGES_MISSING: "The privileges are missing",
    LabCondition.NAMESPACES_MISSING: "The namespaces do not exist yet",
    LabCondition.TOPOLOGY_MISMATCH: "The namespaces hold the wrong lab",
    LabCondition.READY: "The lab is built and up",
}

#: The example each condition is written out for in the README and in
#: `--help`. The wording of a condition does not vary with which tool or
#: which namespace is missing, apart from the name, so one example each is
#: enough to pin the wording down.
_EXAMPLES: dict[LabCondition, dict] = {
    LabCondition.TOOLS_MISSING: {"missing_tools": ["ip"]},
    LabCondition.PRIVILEGES_MISSING: {
        "privilege_available": False,
        "privilege_detail": (
            "The backend is running as an ordinary user, and it cannot ask "
            "for the privilege without a password."
        ),
    },
    LabCondition.NAMESPACES_MISSING: {"missing_namespaces": ["rl260-client", "rl260-router", "rl260-server"]},
    LabCondition.TOPOLOGY_MISMATCH: {
        "topology_issues": ["Router client-side interface rlr0c missing or wrong IP"]
    },
    LabCondition.READY: {},
}


def example_guidance(condition: LabCondition) -> LabGuidance:
    """The guidance for a condition, written out for the README and --help."""
    return diagnose(**_EXAMPLES[condition])


def _render_step_markdown(step: NextStep, indent: str = "") -> str:
    """One step, as markdown."""
    lines = [f"{indent}{step.order}. **{step.title}**", f"{indent}   {step.detail}"]
    if step.command:
        lines.append(f"{indent}   ```bash")
        lines.append(f"{indent}   {step.command}")
        lines.append(f"{indent}   ```")
    return "\n".join(lines)


def render_conditions_markdown() -> str:
    """Every condition, as a markdown section.

    This is the block the README carries, so the README and the API say the
    same thing. A test compares them.
    """
    parts: list[str] = []
    for condition in CONDITION_ORDER:
        guidance = example_guidance(condition)
        parts.append(f"### {CONDITION_HEADINGS[condition]}")
        parts.append("")
        parts.append(f"Condition name: `{condition.value}`")
        parts.append("")
        parts.append(f"{guidance.summary}")
        parts.append("")
        for step in guidance.steps:
            parts.append(_render_step_markdown(step))
            parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def render_conditions_text() -> str:
    """Every condition, as plain text for a terminal."""
    parts: list[str] = []
    for condition in CONDITION_ORDER:
        guidance = example_guidance(condition)
        parts.append(CONDITION_HEADINGS[condition].upper())
        parts.append(f"condition: {condition.value}")
        parts.append(guidance.summary)
        parts.append("")
        for step in guidance.steps:
            parts.append(f"  {step.order}. {step.title}")
            parts.append(f"     {step.detail}")
            if step.command:
                parts.append(f"     $ {step.command}")
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def render_guidance_text(guidance: LabGuidance) -> str:
    """One guidance, as plain text."""
    lines = [guidance.summary, ""]
    for step in guidance.steps:
        lines.append(f"  {step.order}. {step.title}")
        lines.append(f"     {step.detail}")
        if step.command:
            lines.append(f"     $ {step.command}")
    if guidance.optional_steps:
        lines.append("")
        lines.append("  Separate and optional - the four-router topology:")
        for step in guidance.optional_steps:
            lines.append(f"  {step.order}. {step.title}")
            lines.append(f"     {step.detail}")
            if step.command:
                lines.append(f"     $ {step.command}")
    return "\n".join(lines) + "\n"


#: The markers the README's generated block sits between. The README is
#: hand-written apart from this block, which is written by this module, so
#: the hand-written part stays readable and the repeated part cannot drift.
README_BEGIN = "<!-- BEGIN GENERATED: lab-next-steps -->"
README_END = "<!-- END GENERATED: lab-next-steps -->"


def README_GENERATED_BLOCK() -> str:  # noqa: N802 - a constant, named like one
    """The block the README carries, markers included."""
    return f"{README_BEGIN}\n\n{render_conditions_markdown()}\n{README_END}"


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Print the text. Used by `scripts/lab-up.sh --help`."""
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--write-readme":
        target = args[1] if len(args) > 1 else "lab/README.md"
        path = _write_readme_block(target)
        print(f"wrote the generated block into {path}")
        return 0
    sys.stdout.write(render_conditions_text())
    return 0


def _write_readme_block(target: str) -> str:
    """Replace the generated block in a README with the current text."""
    from pathlib import Path

    path = Path(target)
    if not path.exists():
        raise SystemExit(f"no such file: {target}")
    text = path.read_text()
    begin = text.find(README_BEGIN)
    end = text.find(README_END)
    if begin == -1 or end == -1:
        raise SystemExit(
            f"{target} does not have the generated block between "
            f"{README_BEGIN} and {README_END}"
        )
    new = text[:begin] + README_GENERATED_BLOCK() + text[end + len(README_END):]
    path.write_text(new)
    return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
