"""
Temporary Phase 1 mocked-browser verification test.

QA-ONLY: this file is newly created and does not modify any application
code. It uses Playwright's page.route() to intercept /api/lab/status (and
the build endpoint) at the browser boundary and return an unavailable /
refused response, so the unavailable-lab behaviour of VirtualLabPanel can
be exercised in an environment where the real lab reports available: true
and the port-8000 backend cannot be restarted.

It is a throwaway test file and is not part of the committed suite.

Run from /home/abhaysawant/Desktop/cn_project_2/backend with .venv active:

    python -m pytest tests/test_phase1_mocked_unavailable.py -v
"""

import json
import os
import re
import urllib.error
import urllib.request

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api",
    reason="Playwright is not installed; browser-level checks need it",
)
from playwright.sync_api import sync_playwright  # noqa: E402

BASE_URL = os.environ.get("ROUTELENS_URL", "http://127.0.0.1:5173")

UNAVAILABLE_STATUS = {
    "available": False,
    "state": "unavailable",
    "message": "The virtual lab is not running.",
    "error": "Network namespaces require root privileges.",
    "router_info": None,
    "condition": None,
    "next_steps": [],
    "optional_steps": [],
    "detail": None,
}

REFUSED_BUILD = {
    "status": "unavailable",
    "reason": "needs root: network namespaces require CAP_SYS_ADMIN. Run the backend with sudo only for lab use.",
    "error": "The lab cannot be built without root privileges.",
}


def _reachable(url, timeout=5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError):
        return False


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
        except Exception as exc:  # pragma: no cover - environment dependent
            pytest.skip(f"Could not launch a browser: {exc}")
        try:
            yield b
        finally:
            b.close()


@pytest.fixture
def page(browser):
    context = browser.new_context(viewport={"width": 1400, "height": 1000})
    page = context.new_page()
    yield page
    context.close()


def open_lab(page):
    page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(1000)
    page.locator(".sidebar-nav .nav-item", has_text="Virtual Lab").first.click()
    # Wait for the lab panel to settle into its (mocked) unavailable state.
    page.locator(".lab-unavailable").first.wait_for(timeout=10000)
    page.wait_for_timeout(500)


def _mock_unavailable(page):
    page.route(
        "**/api/lab/status",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(UNAVAILABLE_STATUS),
        ),
    )


class TestMockedUnavailableLab:
    """BUG-01: unavailable message and failure reason visible; .lab-ready absent."""

    def test_unavailable_message_and_reason_visible(self, page):
        if not _reachable(BASE_URL):
            pytest.skip("frontend not reachable")
        _mock_unavailable(page)
        open_lab(page)

        assert page.locator(".lab-unavailable").count() >= 1
        assert page.get_by_text("The lab is not running.").count() >= 1
        assert page.get_by_text("Network namespaces require root privileges.").count() >= 1
        assert page.locator(".lab-ready").count() == 0

    def test_ready_only_actions_absent(self, page):
        """BUG-03: .lab-ready absent, 'Send a test packet' absent, 'Tear the lab down' absent."""
        if not _reachable(BASE_URL):
            pytest.skip("frontend not reachable")
        _mock_unavailable(page)
        open_lab(page)

        assert page.locator(".lab-ready").count() == 0
        assert page.get_by_role("button", name="Send a test packet").count() == 0
        assert page.get_by_role("button", name="Tear the lab down").count() == 0

    def test_build_button_visible_and_enabled_when_scenario_selected(self, page):
        """BUG-04: build button visible when scenario selected, enabled when not busy."""
        if not _reachable(BASE_URL):
            pytest.skip("frontend not reachable")
        _mock_unavailable(page)
        open_lab(page)

        build = page.get_by_role("button", name="Build the lab")
        assert build.count() == 1, "expected a 'Build the lab' action"
        assert not build.first.is_disabled(), (
            "the build action should be enabled when a scenario is selected and not busy"
        )

    def test_refused_build_reported_and_lab_stays_unavailable(self, page):
        """Refused build is reported with its reason; .lab-ready and .lab-test-result absent."""
        if not _reachable(BASE_URL):
            pytest.skip("frontend not reachable")

        def handle_status(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(UNAVAILABLE_STATUS),
            )

        def handle_apply(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(REFUSED_BUILD),
            )

        page.route("**/api/lab/status", handle_status)
        page.route("**/api/scenarios/*/lab/apply", handle_apply)
        open_lab(page)

        build = page.get_by_role("button", name="Build the lab")
        assert build.count() == 1, "expected a 'Build the lab' action"
        build.first.click()
        page.wait_for_timeout(3000)

        body = page.inner_text("body")
        assert re.search(r"refused|root|CAP_SYS_ADMIN", body, re.I), (
            f"the refused build was not reported: {body[-500:]}"
        )
        assert page.locator(".lab-ready").count() == 0, (
            "the lab claims to be ready after a build that was refused"
        )
        assert page.locator(".lab-test-result").count() == 0, (
            "a test result is shown after a build that was refused"
        )
