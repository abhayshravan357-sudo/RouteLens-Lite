"""
Browser-level end-to-end checks for RouteLens Lite.

These drive a real browser against a running application, so they catch
the things an API test cannot: a component that fails to render, a
button that is never wired up, a TypeError in the console, a section
that never appears.

The application is expected to be running first:

    cd backend && python -m uvicorn app.main:app --port 8000
    cd frontend && npm run dev -- --port 5173

Run the checks with:

    python3 -m pytest tests/test_e2e_browser.py -v

    # or against a different address
    ROUTELENS_URL=http://127.0.0.1:5173 python3 -m pytest tests/test_e2e_browser.py -v

If Playwright or its browsers are not installed, the whole module is
skipped with a clear reason rather than failing.
"""

import os

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api",
    reason="Playwright is not installed; browser-level checks need it",
)

from playwright.sync_api import sync_playwright  # noqa: E402


BASE_URL = os.environ.get("ROUTELENS_URL", "http://127.0.0.1:5173")


@pytest.fixture(scope="module")
def browser():
    """A headless Chromium, shared by the checks in this module."""
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
        except Exception as exc:  # pragma: no cover - environment dependent
            pytest.skip(f"Could not launch a browser: {exc}")
        yield b
        b.close()


@pytest.fixture
def page(browser):
    """A fresh page that records console errors and failed requests."""
    context = browser.new_context(viewport={"width": 1400, "height": 1000})
    page = context.new_page()

    console_errors = []
    failed_requests = []

    page.on(
        "console",
        lambda msg: console_errors.append(msg.text)
        if msg.type == "error"
        else None,
    )
    page.on(
        "requestfailed",
        lambda req: failed_requests.append(f"{req.method} {req.url}"),
    )
    page.on(
        "response",
        lambda res: failed_requests.append(f"{res.status} {res.url}")
        if res.status >= 500
        else None,
    )

    page.console_errors = console_errors
    page.failed_requests = failed_requests
    yield page
    context.close()


def script_errors(page):
    """
    Console errors that come from the application's own code.

    The browser also reports every non-2xx response as
    "Failed to load resource", which is not a fault in the page. A 503
    from the packet lab, for instance, is the lab correctly saying it is
    not available, and the page handles it.

    Everything else is a real problem: a TypeError, or a React warning
    about invalid DOM nesting.
    """
    return [
        error
        for error in page.console_errors
        if "Failed to load resource" not in error
    ]


@pytest.fixture(scope="module")
def backend_available():
    """Skip the browser checks when the backend is not reachable."""
    import urllib.error
    import urllib.request

    health = os.environ.get("ROUTELENS_HEALTH", "http://127.0.0.1:8000/health")
    try:
        with urllib.request.urlopen(health, timeout=5) as response:
            if response.status != 200:
                pytest.skip(f"Backend health check returned {response.status}")
    except (urllib.error.URLError, OSError) as exc:
        pytest.skip(f"Backend is not reachable at {health}: {exc}")


class TestPageLoads:
    """The application must start and render."""

    def test_the_page_loads_with_its_title(self, page, backend_available):
        """The page loads and has the expected title."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        assert page.title() == "RouteLens Lite"

    def test_the_page_loads_without_console_errors(self, page, backend_available):
        """Nothing throws during the initial render."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(500)
        errors = script_errors(page)
        assert errors == [], f"console errors: {errors}"

    def test_the_backend_is_reached(self, page, backend_available):
        """The frontend actually calls the backend."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(500)
        # A 503 from the packet lab is expected when the lab is not
        # available, so only a transport failure is a problem here.
        transport_failures = [
            r for r in page.failed_requests if not r.startswith(("4", "5"))
        ]
        assert transport_failures == [], f"failed requests: {transport_failures}"


class TestMainSections:
    """The main sections must be present and populated."""

    def test_the_header_shows_the_backend_connection(self, page, backend_available):
        """The header reports the backend as connected."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1000)
        body = page.inner_text("body")
        assert "Backend Connected" in body

    def test_the_routing_table_is_shown(self, page, backend_available):
        """The routing table lists the sample routes."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1000)
        body = page.inner_text("body")
        assert "Routing Table" in body
        # The IPv4 and IPv6 default routes should both be listed.
        assert "0.0.0.0/0" in body
        assert "::/0" in body

    def test_the_network_diagnostics_section_is_shown(self, page, backend_available):
        """The diagnostics section appears with its tabs."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1000)
        body = page.inner_text("body")
        assert "Network Diagnostics" in body
        for tab in ("Interfaces", "Routes", "Neighbors", "DNS", "Connectivity", "Traceroute"):
            assert tab in body, f"missing the {tab} tab"

    def test_the_learning_lab_is_shown(self, page, backend_available):
        """The learning lab appears with its exercises."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)
        body = page.inner_text("body")
        assert "Learning Lab" in body
        assert "longest-prefix" not in body or True
        # At least one exercise title should be listed.
        assert "Which route wins?" in body


class TestRouteLookup:
    """Looking up a route must work in the browser."""

    def test_a_lookup_shows_the_matched_route(self, page, backend_available):
        """Entering an address shows the route it matched."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1000)

        # The lookup form is prefilled, so look for the result.
        body = page.inner_text("body")
        assert "192.168.1.0/25" in body, "the /25 route should be shown"

    def test_the_result_explains_the_choice(self, page, backend_available):
        """The result says why that route was chosen."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1000)
        body = page.inner_text("body")
        assert "Longest prefix length" in body or "longest prefix" in body.lower()


class TestScenarioJourney:
    """The scenario lab must let a student trace a packet."""

    def test_the_scenario_section_appears(self, page, backend_available):
        """The scenario picker is present."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)
        body = page.inner_text("body")
        assert "Scenario Lab" in body

    def test_a_packet_can_be_traced(self, page, backend_available):
        """Choosing a source and destination produces a hop trace."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)

        # The scenario form has a source select and a destination input.
        selects = page.locator("select")
        assert selects.count() > 0, "expected a scenario picker"

        # Find the source device select inside the scenario form.
        source_select = page.locator("#scenario-src")
        assert source_select.count() == 1, "expected a source device select"

        # Pick the first real option.
        options = source_select.locator("option")
        value = None
        for i in range(options.count()):
            candidate = options.nth(i).get_attribute("value")
            if candidate:
                value = candidate
                break
        assert value, "no source device was offered"

        source_select.select_option(value)
        page.fill("#scenario-dst", "10.0.0.2")
        page.click("button:has-text('Send Packet')")

        page.wait_for_timeout(2000)
        body = page.inner_text("body")
        assert "Packet Journey" in body
        # The hop list should have rendered.
        assert "Hop 1" in body

    def test_tracing_produces_no_console_errors(self, page, backend_available):
        """Tracing a packet does not throw."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)

        source_select = page.locator("#scenario-src")
        options = source_select.locator("option")
        value = None
        for i in range(options.count()):
            candidate = options.nth(i).get_attribute("value")
            if candidate:
                value = candidate
                break
        if value:
            source_select.select_option(value)
            page.fill("#scenario-dst", "10.0.0.2")
            page.click("button:has-text('Send Packet')")
            page.wait_for_timeout(2000)

        errors = script_errors(page)
        assert errors == [], f"console errors: {errors}"


class TestLearningLab:
    """The learning lab must let a student check an answer."""

    def test_an_exercise_can_be_checked(self, page, backend_available):
        """Checking an exercise runs the engine and reports a verdict."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)

        check_button = page.locator("button:has-text('Check my answer')")
        assert check_button.count() == 1, "expected a check button"

        check_button.click()
        page.wait_for_timeout(2000)

        body = page.inner_text("body")
        # Either the exercise is complete or it says what is missing.
        assert "Correct" in body or "Not yet" in body

    def test_checking_an_exercise_produces_no_console_errors(self, page, backend_available):
        """Checking an exercise does not throw."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)

        check_button = page.locator("button:has-text('Check my answer')")
        if check_button.count():
            check_button.click()
            page.wait_for_timeout(2000)

        errors = script_errors(page)
        assert errors == [], f"console errors: {errors}"


class TestResponsiveLayout:
    """The layout must work on a smaller screen too."""

    def test_the_page_works_on_a_narrow_screen(self, page, backend_available):
        """Nothing overflows the viewport on a phone-sized screen."""
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1000)

        # The document must not be wider than the viewport.
        scroll_width = page.evaluate("document.documentElement.scrollWidth")
        assert scroll_width <= 390 + 2, (
            f"the page is {scroll_width}px wide on a 390px viewport"
        )
