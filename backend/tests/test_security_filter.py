"""
Tests for the shared safety filter.

`reject_unsafe_target_chars` was extracted from `validate_target` so that a
host target and a CIDR network are filtered the same way. The extraction
must not change what any caller accepts or refuses.

These tests pin that down two ways: a differential comparison against the
original implementation, and a table of the cases that matter.
"""

import ipaddress

import pytest

from app.discovery import DiscoveryScopeError, validate_scope
from app.security import (
    SHELL_METACHARACTERS,
    TargetValidationError,
    reject_unsafe_target_chars,
    validate_target,
)


# --------------------------------------------------------------------------
# The implementation as it was before the filter was shared out
# --------------------------------------------------------------------------


def _original_validate_target(target):
    """validate_target exactly as it was before the extraction."""
    if not target or not isinstance(target, str):
        raise TargetValidationError("A target is required")

    candidate = target.strip()
    if not candidate:
        raise TargetValidationError("A target is required")

    if candidate.startswith("-"):
        raise TargetValidationError("A target may not start with '-'")

    if any(ch.isspace() for ch in candidate):
        raise TargetValidationError("A target may not contain whitespace")
    if any(ch in candidate for ch in ";|&$`<>(){}[]!\"'*\\"):
        raise TargetValidationError("A target may not contain shell metacharacters")

    try:
        ipaddress.ip_address(candidate)
        return candidate
    except ValueError:
        pass

    import re

    hostname_re = re.compile(
        r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9-]{1,63}$",
        re.IGNORECASE,
    )
    if not hostname_re.match(candidate):
        raise TargetValidationError(
            f"Not a valid IP address or hostname: {target!r}"
        )
    return candidate


def _original_cidr_branch(target):
    """The CIDR branch of validate_scope as it was before the extraction."""
    try:
        validated = _original_validate_target(target)
    except TargetValidationError as exc:
        if (
            "/"
            in target
            and not any(ch.isspace() for ch in target)
            and not target.startswith("-")
        ):
            return target
        raise DiscoveryScopeError(str(exc)) from exc
    return validated


def _original_validate_scope(target, max_hosts=256, interval=0.2, timeout=1.0):
    """validate_scope exactly as it was before the extraction."""
    from app.discovery import DiscoveryScope, MAX_SCOPE_HOSTS

    validated = _original_cidr_branch(target)

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


#: A wide corpus of inputs, including every metacharacter in several
#: positions, every whitespace form, and the odd corners of ip_network.
def _corpus():
    cases = [
        "10.0.0.1", "0.0.0.0", "255.255.255.255", "192.168.0.107", "127.0.0.1",
        "2001:db8::1", "::1", "fe80::1", "fe80::%eth0", "fe80::%eth0/64",
        "localhost", "router1.lab.example.com", "clab-rl-r1", "r1",
        "clab-rl-r1.example.net", "a.b", "xn--bcher-kva.example",
        "10.0.0.0/24", "10.0.0.0/8", "192.168.0.0/16", "10.0.0.0/024",
        "10.0.0.0/24 ", " 10.0.0.0/24", "10.0.0.0/24\n", "10.0.0.0/24\t",
        "\t10.0.0.1", "  8.8.8.8  ", "8.8.8.8  ",
        "-c", "--help", "-", "-10.0.0.1", "-10.0.0.0/24",
        "a b", "show ip route", "10.0.0.0/24 10.0.0.1",
        "", "   ", "\t", "\n", "a" * 300,
        "10.0.0.0/33", "10.0.0.0/-1", "10.0.0.0/", "999.1.1.1", "10.0.0.0.1",
        "10.0.0.1/24", "röuter", "router.example", "a\x00b", "a\x7fb",
        "10.0.0.0/24%eth0", "10.0.0.0/24 ",
    ]
    for meta in SHELL_METACHARACTERS:
        cases += [
            f"10.0.0.0/24{meta}",
            f"10.0.0.0{meta}/24",
            f"{meta}10.0.0.0/24",
            f"10.0.0.0/24{meta}1",
            f"a{meta}b",
            f"{meta}",
        ]
    for ws in (" ", "\t", "\n", "\r", "\v", "\f"):
        cases += [
            f"10.0.0.0/24{ws}",
            f"{ws}10.0.0.0/24",
            f"10.0.0.1{ws}",
            f"{ws}10.0.0.1",
        ]
    return cases


def _outcome(fn, value):
    """Whether the call accepted or refused, and what it said."""
    try:
        return ("ACCEPT", fn(value))
    except (TargetValidationError, DiscoveryScopeError) as exc:
        return ("REFUSE", str(exc))
    except Exception as exc:  # noqa: BLE001
        return ("ERROR", f"{type(exc).__name__}: {exc}")


class TestValidateTargetIsUnchanged:
    """validate_target must decide exactly as it did before."""

    @pytest.mark.parametrize("value", _corpus())
    def test_same_decision_and_same_value(self, value):
        before_kind, before_detail = _outcome(_original_validate_target, value)
        after_kind, after_detail = _outcome(validate_target, value)

        assert after_kind == before_kind, (
            f"{value!r}: was {before_kind}, now {after_kind} ({after_detail!r})"
        )
        if before_kind == "ACCEPT":
            assert after_detail == before_detail

    @pytest.mark.parametrize("value", _corpus())
    def test_same_refusal_message(self, value):
        before_kind, before_detail = _outcome(_original_validate_target, value)
        after_kind, after_detail = _outcome(validate_target, value)

        if before_kind == "REFUSE":
            assert after_detail == before_detail, (
                f"{value!r}: refusal wording changed from {before_detail!r} "
                f"to {after_detail!r}"
            )

    def test_the_corpus_is_wide_enough_to_be_meaningful(self):
        assert len(_corpus()) > 150


class TestCidrBranchIsUnchanged:
    """The CIDR branch of validate_scope must decide exactly as it did."""

    @pytest.mark.parametrize("value", _corpus())
    def test_the_whole_scope_function_keeps_its_decision(self, value):
        """Accept or refuse, and the resulting network, must not change."""
        before_kind, before_detail = _outcome(
            lambda v: _original_validate_scope(v), value
        )
        after_kind, after_detail = _outcome(validate_scope, value)

        assert after_kind == before_kind, (
            f"{value!r}: was {before_kind} ({before_detail!r}), "
            f"now {after_kind} ({after_detail!r})"
        )
        if before_kind == "ACCEPT":
            assert str(before_detail.network) == str(after_detail.network)

    def test_the_filter_now_refuses_a_network_before_it_is_parsed(self):
        """The branch used to pass a metacharacter network on to ip_network.

        The scope still refused it, because ip_network refused it, so no
        input changed its decision. But the refusal now happens at the
        filter, which is where it belongs.
        """
        # The old branch handed this string on.
        assert _original_cidr_branch("10.0.0.0/24;id") == "10.0.0.0/24;id"

        # The new branch does not: the shared filter refuses it.
        with pytest.raises(TargetValidationError):
            reject_unsafe_target_chars("10.0.0.0/24;id")

    def test_a_network_with_a_metacharacter_is_still_refused(self):
        with pytest.raises(DiscoveryScopeError):
            validate_scope("10.0.0.0/24;id")

    def test_a_clean_network_is_still_accepted(self):
        scope = validate_scope("10.0.0.0/24")
        assert str(scope.network) == "10.0.0.0/24"


class TestTheFilterItself:
    """The shared filter does what it says."""

    def test_it_returns_the_value_unchanged(self):
        assert reject_unsafe_target_chars("10.0.0.1") == "10.0.0.1"
        assert reject_unsafe_target_chars("10.0.0.0/24") == "10.0.0.0/24"

    def test_it_does_not_strip(self):
        """A caller that does not strip must still have whitespace refused."""
        with pytest.raises(TargetValidationError):
            reject_unsafe_target_chars(" 10.0.0.1")
        with pytest.raises(TargetValidationError):
            reject_unsafe_target_chars("10.0.0.1 ")

    def test_it_refuses_an_empty_value(self):
        with pytest.raises(TargetValidationError):
            reject_unsafe_target_chars("")

    def test_it_refuses_a_non_string(self):
        with pytest.raises(TargetValidationError):
            reject_unsafe_target_chars(None)

    def test_it_refuses_a_leading_dash(self):
        with pytest.raises(TargetValidationError):
            reject_unsafe_target_chars("-c")

    def test_it_refuses_whitespace(self):
        with pytest.raises(TargetValidationError):
            reject_unsafe_target_chars("a b")

    @pytest.mark.parametrize("meta", list(SHELL_METACHARACTERS))
    def test_it_refuses_every_shell_metacharacter(self, meta):
        with pytest.raises(TargetValidationError):
            reject_unsafe_target_chars(f"a{meta}b")

    def test_a_network_is_filtered_the_same_way_as_a_host(self):
        """The point of sharing it: a network cannot smuggle a character."""
        with pytest.raises(TargetValidationError):
            reject_unsafe_target_chars("10.0.0.0/24;id")

    def test_the_metacharacter_set_is_the_one_the_code_always_used(self):
        assert set(SHELL_METACHARACTERS) == set(";|&$`<>(){}[]!\"'*\\")
