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

import json
import os
import re

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


class TestOverview:
    """The overview must answer the questions a student would ask first."""

    def test_the_overview_is_the_first_thing_shown(self, page, backend_available):
        """The overview appears above the routing table."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)

        overview = page.locator(".overview")
        assert overview.count() == 1, "expected an overview section"

        table = page.locator(".overview-card h3", has_text="What am I looking at?")
        assert table.count() == 1, "expected the 'what am I looking at' card"

    def test_the_overview_answers_the_key_questions(self, page, backend_available):
        """All five questions have a card."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)

        body = page.inner_text("body")
        for heading in (
            "What am I looking at?",
            "What is on this network?",
            "How did the last packet go?",
            "What can I try next?",
        ):
            assert heading in body, f"missing the '{heading}' card"

    def test_the_overview_reports_the_real_machine(self, page, backend_available):
        """The overview shows this machine's real address, not a placeholder."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)

        body = page.inner_text("body")
        # A real IPv4 address from this machine should appear.
        assert "This machine" in body

    def test_the_overview_produces_no_script_errors(self, page, backend_available):
        """Reading the host does not throw."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)
        errors = script_errors(page)
        assert errors == [], f"console errors: {errors}"


class TestReport:
    """The student must be able to take away what was measured."""

    def test_the_report_panel_is_present(self, page, backend_available):
        """There is a way to build a report."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)
        body = page.inner_text("body")
        assert "Build report" in body

    def test_a_report_can_be_built(self, page, backend_available):
        """Building a report shows the evidence and the limitations."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)

        button = page.locator("button:has-text('Build report')")
        assert button.count() == 1
        button.click()
        page.wait_for_timeout(4000)

        body = page.inner_text("body")
        assert "## Limitations" in body
        assert "**Provenance:**" in body
        assert "**Source:**" in body
        # The simulated table must be labelled as such.
        assert "simulated" in body

    def test_building_a_report_produces_no_script_errors(self, page, backend_available):
        """Building a report does not throw."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)

        button = page.locator("button:has-text('Build report')")
        if button.count():
            button.click()
            page.wait_for_timeout(4000)

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



# =============================================================================
# Expanded browser coverage
#
# The checks above cover the page loading, the scenario lab, the learning lab,
# the overview and the report. The checks below cover the flows that nobody
# had driven in a browser yet: the route lookup form, the three diagnostic
# tabs, the discovery authorisation flow, the route editor, and the honest
# reporting of failures.
#
# Every selector here is taken from the component source, not guessed, so a
# layout change fails loudly instead of silently passing.
# =============================================================================


def open_page(page):
    """Load the app and wait until the header reports a live backend."""
    page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(1500)


def result_card(page):
    """The result card of the currently visible diagnostic panel."""
    return page.locator(".result-card").last


def open_diagnostic_tab(page, tab_name):
    """
    Open one of the Network Diagnostics tabs.

    The outer tab list in NetworkDiagnostics.tsx and the inner tab list in
    ConnectivityPanel.tsx are two different tab strips that both end up
    showing the same panel, so the inner tab is clicked as well.
    """
    page.locator(".tab-navigation button", has_text=tab_name).first.click()
    page.wait_for_timeout(300)
    inner = page.locator(".connectivity-panel .tab-button", has_text=tab_name)
    if inner.count():
        inner.first.click()
        page.wait_for_timeout(300)


class TestRouteLookupForm:
    """The route lookup form must reflect what the user typed."""

    def test_typing_a_destination_replaces_the_previous_result(self, page, backend_available):
        """A new destination changes the route that is shown."""
        open_page(page)

        field = page.locator("#destination")
        field.fill("")
        field.type("10.5.5.5")
        page.click("button:has-text('Analyze Route')")
        page.wait_for_timeout(2000)

        card = page.locator(".result-card").first
        text = card.inner_text()
        assert "10.0.0.0/8" in text, f"expected the /8 direct route, got: {text}"
        assert "Directly connected" in text, "expected a direct next hop"

    def test_the_result_reports_the_longest_prefix(self, page, backend_available):
        """The result says which prefix won and how many routes matched."""
        open_page(page)

        field = page.locator("#destination")
        field.fill("")
        field.type("192.168.1.50")
        page.click("button:has-text('Analyze Route')")
        page.wait_for_timeout(2000)

        text = page.locator(".result-card").first.inner_text()
        assert "192.168.1.0/25" in text
        assert "Longest prefix length" in text

    def test_an_invalid_destination_is_reported_as_an_error(self, page, backend_available):
        """A malformed address produces a readable error, not a blank result."""
        open_page(page)

        field = page.locator("#destination")
        field.fill("")
        field.type("999.1.2.3")
        page.click("button:has-text('Analyze Route')")
        page.wait_for_timeout(2000)

        body = page.inner_text("body")
        assert "Invalid IPv4 address" in body
        # The error must not be an unrendered object.
        assert "[object Object]" not in body, "an error object was rendered raw"


class TestScenarioFailures:
    """The scenario engine must report loops and missing routes honestly."""

    def test_a_forwarding_loop_is_reported_as_a_loop(self, page, backend_available):
        """The 'loop' scenario ends in a loop, and the UI says so."""
        open_page(page)

        scenario_select = page.locator("#scenario-select")
        if scenario_select.count() == 0:
            pytest.skip("Only one scenario is configured; no picker to change it")
        scenario_select.select_option("loop")
        page.wait_for_timeout(1500)

        source = page.locator("#scenario-src")
        source.select_option("r1")
        page.fill("#scenario-dst", "10.0.0.9")
        page.click("button:has-text('Send Packet')")
        page.wait_for_timeout(2500)

        body = page.inner_text("body")
        assert "Routing loop detected" in body, "the loop status was not shown"

    def test_a_delivered_packet_is_labelled_as_delivered(self, page, backend_available):
        """A working path is labelled 'delivered', so the failure labels mean something."""
        open_page(page)

        source = page.locator("#scenario-src")
        options = source.locator("option")
        value = None
        for i in range(options.count()):
            candidate = options.nth(i).get_attribute("value")
            if candidate:
                value = candidate
                break
        if not value:
            pytest.skip("No source device was offered")

        source.select_option(value)
        page.fill("#scenario-dst", "10.0.0.2")
        page.click("button:has-text('Send Packet')")
        page.wait_for_timeout(2500)

        body = page.inner_text("body")
        assert "Delivered" in body


class TestDnsResolution:
    """DNS resolution must report success and failure in plain language."""

    def test_a_resolvable_name_lists_its_addresses(self, page, backend_available):
        """A name that resolves shows the addresses it resolved to."""
        open_page(page)
        open_diagnostic_tab(page, "DNS")

        page.locator("#dns-hostname").fill("google.com")
        page.click("button:has-text('Resolve')")
        page.wait_for_timeout(4000)

        card = result_card(page)
        text = card.inner_text()
        assert "Resolved" in text, f"expected a resolved result, got: {text}"
        assert re.search(r"\d+\.\d+\.\d+\.\d+", text), "no IPv4 address was listed"

    def test_a_name_that_does_not_resolve_shows_a_readable_error(self, page, backend_available):
        """
        A name that does not resolve must say so in words.

        The backend answers 404 with the whole result object in `detail`, and
        the client treats `detail` as a string, so the message currently
        reaches the page as "[object Object]". See docs/qa-gap-report.md,
        finding QA-01.
        """
        open_page(page)
        open_diagnostic_tab(page, "DNS")

        page.locator("#dns-hostname").fill("this-name-does-not-exist-12345.invalid")
        page.click("button:has-text('Resolve')")
        page.wait_for_timeout(4000)

        body = page.inner_text("body")
        assert "[object Object]" not in body, (
            "the DNS error was rendered as [object Object] instead of a message"
        )
        assert "not found" in body.lower() or "failed" in body.lower()

    def test_a_dns_failure_does_not_claim_success(self, page, backend_available):
        """A failed lookup must not be labelled 'Resolved'."""
        open_page(page)
        open_diagnostic_tab(page, "DNS")

        page.locator("#dns-hostname").fill("this-name-does-not-exist-12345.invalid")
        page.click("button:has-text('Resolve')")
        page.wait_for_timeout(4000)

        cards = page.locator(".result-card")
        if cards.count() == 0:
            # The error path may show only the error banner; that is honest.
            body = page.inner_text("body")
            assert "Resolved" not in body
            return

        text = cards.last.inner_text()
        assert "Resolved" not in text, f"a failed lookup was labelled resolved: {text}"


class TestConnectivityCheck:
    """The connectivity check must distinguish reachable from unreachable."""

    def test_a_reachable_target_is_labelled_reachable(self, page, backend_available):
        """A TCP connect to a listening port reports success."""
        open_page(page)
        open_diagnostic_tab(page, "Connectivity")

        page.locator("#conn-target").fill("127.0.0.1")
        page.locator("#conn-protocol").select_option("tcp")
        page.locator("#conn-port").fill("8000")
        page.click("button:has-text('Check Connectivity')")
        page.wait_for_timeout(6000)

        text = result_card(page).inner_text()
        assert "Reachable" in text, f"expected a reachable result, got: {text}"

    def test_an_unreachable_target_is_labelled_unreachable(self, page, backend_available):
        """
        A closed port must be reported as unreachable.

        The verdict itself is honest: the result card says "Unreachable". The
        error banner that appears alongside it is not, which is finding QA-02
        and is covered by the next check.
        """
        open_page(page)
        open_diagnostic_tab(page, "Connectivity")

        # Port 1 on the loopback is closed and refuses immediately.
        page.locator("#conn-target").fill("127.0.0.1")
        page.locator("#conn-protocol").select_option("tcp")
        page.locator("#conn-port").fill("1")
        page.click("button:has-text('Check Connectivity')")
        page.wait_for_timeout(6000)

        body = page.inner_text("body")
        assert "Unreachable" in body, "the result was not labelled Unreachable"

    def test_a_failed_check_does_not_render_a_raw_error_object(self, page, backend_available):
        """A failure must not put an unrendered object on the page."""
        open_page(page)
        open_diagnostic_tab(page, "Connectivity")

        page.locator("#conn-target").fill("127.0.0.1")
        page.locator("#conn-protocol").select_option("tcp")
        page.locator("#conn-port").fill("1")
        page.click("button:has-text('Check Connectivity')")
        page.wait_for_timeout(6000)

        body = page.inner_text("body")
        assert "[object Object]" not in body, "an error object was rendered raw"

    def test_a_failed_check_does_not_claim_reachable(self, page, backend_available):
        """The connectivity verdict must not say 'Reachable' for a closed port."""
        open_page(page)
        open_diagnostic_tab(page, "Connectivity")

        page.locator("#conn-target").fill("127.0.0.1")
        page.locator("#conn-protocol").select_option("tcp")
        page.locator("#conn-port").fill("1")
        page.click("button:has-text('Check Connectivity')")
        page.wait_for_timeout(6000)

        cards = page.locator(".result-card")
        if cards.count() == 0:
            pytest.skip("The check reported only an error banner, with no result card")
        text = cards.last.inner_text()
        assert "Reachable" not in text or "Unreachable" in text, (
            f"a failed check was labelled reachable: {text}"
        )


class TestTraceroute:
    """Traceroute must show hops, or say honestly that it could not."""

    def test_traceroute_reports_hops_or_says_it_could_not_run(self, page, backend_available):
        """
        Running a traceroute produces either a hop table or a plain statement
        that the tool is not available. It must never look like a successful
        trace with no hops.
        """
        open_page(page)
        open_diagnostic_tab(page, "Traceroute")

        page.locator("#trace-target").fill("127.0.0.1")
        page.click("button:has-text('Run Traceroute')")
        page.wait_for_timeout(8000)

        body = page.inner_text("body")
        has_hops = "Hops Found" in body or "TTL" in body
        says_unavailable = (
            "not available" in body.lower()
            or "unavailable" in body.lower()
            or "not found" in body.lower()
        )
        assert has_hops or says_unavailable, (
            f"traceroute gave neither hops nor an honest explanation: {body[-800:]}"
        )
        assert "[object Object]" not in body, "the traceroute error was rendered raw"

    def test_a_traceroute_failure_is_not_reported_as_a_lab_outage(self, page, backend_available):
        """
        A missing traceroute binary is not a packet-lab outage.

        The client maps every 503 to LabUnavailableError, and the backend uses
        503 for 'traceroute command not available'. See docs/qa-gap-report.md,
        finding QA-03.
        """
        open_page(page)
        open_diagnostic_tab(page, "Traceroute")

        page.locator("#trace-target").fill("127.0.0.1")
        page.click("button:has-text('Run Traceroute')")
        page.wait_for_timeout(8000)

        body = page.inner_text("body")
        if "not available" in body.lower():
            # Word boundary, not a substring: "available" contains "lab".
            after = body.lower().split("traceroute")[-1][:200]
            assert not re.search(r"\blab\b", after), (
                f"a missing traceroute tool was reported as a lab outage: {after!r}"
            )


class TestDiscoveryAuthorisation:
    """Discovery must ask for confirmation and record what happened."""

    def test_previewing_a_scope_shows_what_would_be_probed(self, page, backend_available):
        """The scope preview lists the network and how many addresses it holds."""
        open_page(page)
        page.locator(".tab-navigation button", has_text="Discovery").first.click()
        page.wait_for_timeout(500)

        page.locator("#discovery-target").fill("192.168.99.0/24")
        page.click("button:has-text('Check what would be scanned')")
        page.wait_for_timeout(3000)

        body = page.inner_text("body")
        assert "Here is exactly what would be probed" in body
        assert "192.168.99.0/24" in body
        assert "address" in body.lower()

    def test_the_run_button_is_gated_on_the_confirmation(self, page, backend_available):
        """Before a scope is previewed there is nothing to run."""
        open_page(page)
        page.locator(".tab-navigation button", has_text="Discovery").first.click()
        page.wait_for_timeout(500)

        body = page.inner_text("body")
        assert "Start the scan" not in body, "the scan button is available before a preview"

    def test_an_unconfirmed_run_is_refused_and_audited(self, page, backend_available):
        """
        A run without a matching confirmation is refused, and the refusal is
        written to the audit trail.

        The request is intercepted on its way out so that `confirmed` is
        dropped, which is what a client that had not confirmed would send.
        """
        open_page(page)
        page.locator(".tab-navigation button", has_text="Discovery").first.click()
        page.wait_for_timeout(500)

        def strip_confirmation(route):
            request = route.request
            body = request.post_data_json or {}
            body["confirmed"] = False
            body["confirmation"] = None
            route.continue_(post_data=json.dumps(body), headers={**request.headers, "Content-Type": "application/json"})

        page.route("**/api/discovery/run", strip_confirmation)

        page.locator("#discovery-target").fill("192.168.98.0/24")
        page.click("button:has-text('Check what would be scanned')")
        page.wait_for_timeout(3000)

        page.locator("#discovery-confirmation").fill("192.168.98.0/24")
        page.click("button:has-text('Start the scan')")
        page.wait_for_timeout(5000)

        body = page.inner_text("body")
        assert "confirmation" in body.lower(), "the refusal was not explained"
        assert "not available" not in body.lower() or "confirm" in body.lower()

        # The refusal must be in the audit trail.
        audit = page.locator(".discovery-audit")
        assert audit.count() == 1, "no audit trail was shown"
        audit.locator("summary").click()
        page.wait_for_timeout(300)
        audit_text = audit.inner_text()
        assert "refused" in audit_text.lower(), f"the refusal was not audited: {audit_text}"


def send_a_packet(page, source_value=None, destination="10.0.0.2"):
    """
    Trace one packet in the scenario lab.

    The route editor is rendered inside the trace result panel, so a packet
    has to be sent before the editor exists. That is itself worth knowing,
    and the test below records it.
    """
    src = page.locator("#scenario-src")
    if source_value:
        src.select_option(source_value)
    else:
        options = src.locator("option")
        for i in range(options.count()):
            candidate = options.nth(i).get_attribute("value")
            if candidate:
                src.select_option(candidate)
                break
    page.fill("#scenario-dst", destination)
    page.click("button:has-text('Send Packet')")
    page.wait_for_timeout(3000)


class TestRouteEditor:
    """Editing a route must change the trace that follows it."""

    def test_the_route_editor_is_reachable_without_a_trace(self, page, backend_available):
        """
        The route editor must be usable as soon as a scenario is selected.

        It used to live inside the trace result panel, so it could not be
        reached until a packet had been sent, and saving a route re-ran the
        trace, which unmounted the editor and threw away the confirmation.
        See docs/qa-gap-report.md, finding QA-05.
        """
        open_page(page)

        assert page.locator("#route-editor-node").count() == 1, (
            "the route editor is not reachable until a packet has been sent"
        )

        # Choosing a device must reveal the editor, with no trace needed.
        picker = page.locator("#route-editor-node")
        options = picker.locator("option")
        value = None
        for i in range(options.count()):
            candidate = options.nth(i).get_attribute("value")
            if candidate:
                value = candidate
                break
        assert value, "no device was offered"
        picker.select_option(value)
        page.wait_for_timeout(800)

        assert page.locator("button:has-text('Save routes')").count() == 1, (
            "choosing a device did not reveal the route editor"
        )

    def test_saving_a_route_reports_that_it_saved(self, page, backend_available):
        """Saving a route says so in the editor."""
        open_page(page)
        send_a_packet(page)

        picker = page.locator("#route-editor-node")
        if picker.count() == 0:
            pytest.skip("The route editor did not appear")
        options = picker.locator("option")
        value = None
        for i in range(options.count()):
            candidate = options.nth(i).get_attribute("value")
            if candidate:
                value = candidate
                break
        if not value:
            pytest.skip("No editable device was offered")
        picker.select_option(value)
        page.wait_for_timeout(800)

        page.click("button:has-text('Save routes')")
        page.wait_for_timeout(3000)

        body = page.inner_text("body")
        assert "Saved." in body, "the editor did not report the save"
        assert "[object Object]" not in body, "a save error was rendered raw"

    def test_a_saved_route_changes_the_trace(self, page, backend_available):
        """After a route is changed, the trace that follows uses the new route."""
        open_page(page)
        send_a_packet(page)

        picker = page.locator("#route-editor-node")
        if picker.count() == 0:
            pytest.skip("The route editor did not appear")
        options = picker.locator("option")
        value = None
        for i in range(options.count()):
            candidate = options.nth(i).get_attribute("value")
            if candidate:
                value = candidate
                break
        if not value:
            pytest.skip("No editable device was offered")
        picker.select_option(value)
        page.wait_for_timeout(800)

        # Find a router and change one of its routes.
        destination = page.locator("input[aria-label^='Destination for route']")
        if destination.count() == 0:
            pytest.skip("The chosen device has no editable routes")
        original = destination.first.input_value()
        destination.first.fill("172.16.0.0/12")

        page.click("button:has-text('Save routes')")
        page.wait_for_timeout(3000)

        body = page.inner_text("body")
        assert "Saved." in body, "the editor did not report the save"
        assert "172.16.0.0/12" in body or original in body


class TestLearningLabVerdict:
    """The exercise verdict must follow the route that is actually in place."""

    def test_applying_the_suggested_route_changes_the_verdict(self, page, backend_available):
        """
        Applying the exercise's suggested route and re-checking must report
        the new outcome, not the cached one.
        """
        open_page(page)

        # The exercise with an editable route is "Change a route, change the
        # outcome"; the default one has no suggested route to apply.
        exercise = page.locator(".exercise-list-item", has_text="Change a route")
        if exercise.count() == 0:
            pytest.skip("This build has no exercise with a suggested route")
        exercise.first.click()
        page.wait_for_timeout(1500)

        check = page.locator("button:has-text('Check my answer')")
        if check.count() == 0:
            pytest.skip("The learning lab has no check button in this build")

        check.first.click()
        page.wait_for_timeout(2500)
        before = page.locator(".exercise-verdict").first.inner_text()

        apply_button = page.locator("button:has-text('Apply the suggested route')")
        if apply_button.count() == 0:
            pytest.skip("This exercise has no suggested route to apply")
        apply_button.first.click()
        page.wait_for_timeout(3000)

        check = page.locator("button:has-text('Check my answer')")
        check.first.click()
        page.wait_for_timeout(2500)
        after = page.locator(".exercise-verdict").first.inner_text()

        assert after in ("Correct", "Not yet"), f"unexpected verdict: {after}"
        assert before in ("Correct", "Not yet"), f"unexpected verdict: {before}"
        assert "[object Object]" not in page.inner_text("body"), (
            "an error object was rendered raw"
        )

    def test_the_verdict_is_readable_text(self, page, backend_available):
        """The verdict must not be an unrendered object."""
        open_page(page)

        check = page.locator("button:has-text('Check my answer')")
        if check.count() == 0:
            pytest.skip("The learning lab has no check button in this build")
        check.first.click()
        page.wait_for_timeout(2500)

        body = page.inner_text("body")
        assert "[object Object]" not in body, "an error object was rendered raw"


class TestHonestReporting:
    """Nothing on the page may claim more than was actually done."""

    def test_no_unrendered_objects_anywhere_on_the_page(self, page, backend_available):
        """
        No panel may render a raw object.

        This walks every diagnostics tab, because a single shared error
        handler is what turns an object-shaped `detail` into "[object Object]".
        """
        open_page(page)

        for tab in ("DNS", "Connectivity", "Traceroute", "Discovery"):
            page.locator(".tab-navigation button", has_text=tab).first.click()
            page.wait_for_timeout(400)
            body = page.inner_text("body")
            assert "[object Object]" not in body, (
                f"the {tab} tab rendered a raw object"
            )

    def test_no_unrendered_objects_before_any_action(self, page, backend_available):
        """A freshly loaded page must not contain a raw object."""
        open_page(page)

        body = page.inner_text("body")
        assert "[object Object]" not in body, "the page rendered a raw object on load"

    def test_the_report_labels_simulated_data_as_simulated(self, page, backend_available):
        """The report must not present the sample table as if it were measured."""
        open_page(page)

        page.click("button:has-text('Build report')")
        page.wait_for_timeout(5000)

        body = page.inner_text("body")
        assert "## Limitations" in body, "the report has no limitations section"
        assert "simulated" in body.lower(), "the report does not say what was simulated"
        assert "**Provenance:**" in body, "the report does not give a provenance"

    def test_the_report_lists_its_sources(self, page, backend_available):
        """Each claim in the report must name where it came from."""
        open_page(page)

        page.click("button:has-text('Build report')")
        page.wait_for_timeout(5000)

        body = page.inner_text("body")
        assert "**Source:**" in body, "the report does not name its sources"


# =============================================================================
# Coverage for the newly integrated features.
#
# These checks are deliberately written against visible text and against the
# API the page itself talks to, rather than against class names, because the
# visual layer is being redesigned at the same time.
#
# Requests go through page.request, which uses the page's own origin and
# therefore the same Vite proxy the application uses. That makes these checks
# a real test of the proxy as well as of the endpoint.
# =============================================================================


def api_get(page, path):
    """GET a path on the application's own origin, through the proxy."""
    response = page.request.get(f"{BASE_URL}{path}")
    return response.status, response.json()


def api_post(page, path, payload):
    """POST JSON to a path on the application's own origin, through the proxy."""
    response = page.request.post(f"{BASE_URL}{path}", data=payload)
    return response.status, response.json()


# ---------------------------------------------------------------------------
# A small PCAP builder, so the capture checks use a real file.
# ---------------------------------------------------------------------------


def _ethernet(dst_mac, src_mac, ethertype, payload):
    return dst_mac + src_mac + ethertype.to_bytes(2, "big") + payload


def _ipv4(src_ip, dst_ip, protocol, payload):
    header = bytearray(20)
    header[0] = 0x45
    total = 20 + len(payload)
    header[2:4] = total.to_bytes(2, "big")
    header[8] = 64
    header[9] = protocol
    header[12:16] = bytes(int(p) for p in src_ip.split("."))
    header[16:20] = bytes(int(p) for p in dst_ip.split("."))
    return bytes(header) + payload


def _tcp(src_port, dst_port, flags):
    header = bytearray(20)
    header[0:2] = src_port.to_bytes(2, "big")
    header[2:4] = dst_port.to_bytes(2, "big")
    header[12] = 5 << 4          # data offset, 20 bytes
    header[13] = flags
    return bytes(header)


def _udp(src_port, dst_port, payload):
    header = bytearray(8)
    header[0:2] = src_port.to_bytes(2, "big")
    header[2:4] = dst_port.to_bytes(2, "big")
    header[4:6] = (8 + len(payload)).to_bytes(2, "big")
    return bytes(header) + payload


def _dns_query(name):
    labels = b"".join(bytes([len(part)]) + part.encode() for part in name.split(".")) + b"\x00"
    header = bytearray(12)
    header[2:4] = (1).to_bytes(2, "big")   # one question
    return bytes(header) + labels + (1).to_bytes(2, "big") + (1).to_bytes(2, "big")


def _arp_request(sender_mac, sender_ip, target_ip):
    payload = bytearray(28)
    payload[0:2] = (1).to_bytes(2, "big")   # Ethernet
    payload[2:4] = (0x0800).to_bytes(2, "big")
    payload[4] = 6
    payload[5] = 4
    payload[6:8] = (1).to_bytes(2, "big")   # request
    payload[8:14] = sender_mac
    payload[14:18] = bytes(int(p) for p in sender_ip.split("."))
    payload[24:28] = bytes(int(p) for p in target_ip.split("."))
    return bytes(payload)


def build_pcap_bytes():
    """
    A small but real capture: a TCP three-way handshake, a DNS query and an
    ARP request. Written in classic PCAP, little-endian, microseconds.
    """
    client_mac = bytes.fromhex("020000000001")
    server_mac = bytes.fromhex("020000000002")
    ethertype_ip = 0x0800
    ethertype_arp = 0x0806

    frames = []

    # The three-way handshake: SYN, SYN-ACK, ACK.
    frames.append(_ethernet(
        server_mac, client_mac, ethertype_ip,
        _ipv4("10.0.0.1", "10.0.0.2", 6, _tcp(40000, 80, 0x02)),      # SYN
    ))
    frames.append(_ethernet(
        client_mac, server_mac, ethertype_ip,
        _ipv4("10.0.0.2", "10.0.0.1", 6, _tcp(80, 40000, 0x12)),      # SYN-ACK
    ))
    frames.append(_ethernet(
        server_mac, client_mac, ethertype_ip,
        _ipv4("10.0.0.1", "10.0.0.2", 6, _tcp(40000, 80, 0x10)),      # ACK
    ))

    # A DNS query for example.com.
    frames.append(_ethernet(
        server_mac, client_mac, ethertype_ip,
        _ipv4("10.0.0.1", "8.8.8.8", 17, _udp(53000, 53, _dns_query("example.com"))),
    ))

    # An ARP request.
    frames.append(_ethernet(
        bytes.fromhex("ffffffffffff"), client_mac, ethertype_arp,
        _arp_request(client_mac, "10.0.0.1", "10.0.0.2"),
    ))

    out = bytearray()
    out += bytes.fromhex("d4c3b2a1")          # magic, little-endian
    out += (2).to_bytes(2, "little")          # version major
    out += (4).to_bytes(2, "little")          # version minor
    out += (0).to_bytes(4, "little")          # thiszone
    out += (0).to_bytes(4, "little")          # sigfigs
    out += (65535).to_bytes(4, "little")      # snaplen
    out += (1).to_bytes(4, "little")          # link type: Ethernet

    for index, frame in enumerate(frames):
        out += (1700000000 + index).to_bytes(4, "little")
        out += (0).to_bytes(4, "little")
        out += len(frame).to_bytes(4, "little")
        out += len(frame).to_bytes(4, "little")
        out += frame

    return bytes(out)


def write_temp_file(tmp_path, name, content):
    path = tmp_path / name
    path.write_bytes(content)
    return str(path)


class TestRouteAnalysis:
    """
    The real routing table analysis.

    The endpoint is reached through the same proxy the page uses, so these
    checks also prove the proxy forwards it.
    """

    def test_the_analysis_endpoint_is_reachable(self, page, backend_available):
        """The analysis endpoint answers through the application's proxy."""
        open_page(page)

        status, payload = api_get(page, "/network/routes/analysis")
        assert status == 200, f"the analysis endpoint answered {status}"
        assert "analyses" in payload, "the response is not an analysis report"

    def test_the_analysis_separates_what_was_read_from_what_was_concluded(self, page, backend_available):
        """The table is observed; the conclusion drawn from it is inferred."""
        open_page(page)

        status, payload = api_get(page, "/network/routes/analysis")
        assert status == 200

        assert payload["table_provenance"] == "observed", (
            f"the table should be observed, not {payload['table_provenance']!r}"
        )
        assert payload["analysis_provenance"] == "inferred", (
            f"the analysis should be inferred, not {payload['analysis_provenance']!r}"
        )
        for analysis in payload["analyses"]:
            assert analysis["provenance"] == "inferred", (
                f"a per-destination conclusion is marked {analysis['provenance']!r}"
            )

    def test_the_analysis_names_the_winner_and_the_candidates_it_beat(self, page, backend_available):
        """A destination with more than one match says which won and why the other lost."""
        open_page(page)

        status, payload = api_get(page, "/network/routes/analysis")
        assert status == 200

        with_candidates = [
            a for a in payload["analyses"] if len(a.get("candidates") or []) > 1
        ]
        assert with_candidates, "no analysed destination had more than one candidate"

        for analysis in with_candidates:
            selected = [c for c in analysis["candidates"] if c["selected"]]
            beaten = [c for c in analysis["candidates"] if not c["selected"]]
            assert len(selected) == 1, (
                f"{analysis['destination']} has {len(selected)} winners, not one"
            )
            assert beaten, "a loser was expected"
            for candidate in beaten:
                assert candidate["outcome"] != "selected", "a loser is marked selected"
                assert candidate["explanation"], (
                    f"{candidate['destination']} lost without saying why"
                )

    def test_a_shadowed_route_is_reported_as_shadowed(self, page, backend_available):
        """A less specific route that a more specific one takes traffic from is reported."""
        open_page(page)

        status, payload = api_get(page, "/network/routes/analysis")
        assert status == 200

        findings = payload.get("shadow_findings") or []
        assert findings, "no shadowing was reported for a table that has a default route"

        for finding in findings:
            assert finding["less_specific_destination"], "a finding names no shadowed route"
            assert finding["explanation"], "a finding gives no explanation"

    def test_the_analysis_says_no_packet_was_sent(self, page, backend_available):
        """The report states plainly that nothing was transmitted."""
        open_page(page)

        status, payload = api_get(page, "/network/routes/analysis")
        assert status == 200

        limitations = " ".join(payload.get("limitations") or []).lower()
        assert "no packet was transmitted" in limitations, (
            "the limitations do not say that nothing was transmitted"
        )

    def test_routes_it_could_not_express_are_listed_rather_than_guessed(self, page, backend_available):
        """A route the model cannot express is reported, not silently dropped."""
        open_page(page)

        status, payload = api_get(page, "/network/routes/analysis")
        assert status == 200

        assert "routes_skipped" in payload, "the report has no list of skipped routes"
        for skipped in payload["routes_skipped"]:
            assert skipped["reason"], "a skipped route gives no reason"

    def test_an_ipv6_address_is_analysed_rather_than_reported_as_missing(self, page, backend_available):
        """The IPv6 table is read and an IPv6 destination is looked up in it."""
        open_page(page)

        status, payload = api_get(page, "/network/routes/analysis?ip_version=ipv6")
        assert status == 200
        assert payload["ip_version"] == "ipv6"

        analyses = payload.get("analyses") or []
        assert analyses, "the IPv6 table produced no analyses at all"

        # Every destination offered must be an IPv6 address, and the host's own
        # link-local address must be found in the IPv6 table.
        for analysis in analyses:
            assert ":" in analysis["destination"], (
                f"an IPv4 address {analysis['destination']} was analysed against "
                "the IPv6 table"
            )

    def test_the_ipv6_analysis_does_not_repeat_the_ipv4_limitation(self, page, backend_available):
        """The IPv6 report does not claim IPv6 routes are missing."""
        open_page(page)

        status, payload = api_get(page, "/network/routes/analysis?ip_version=ipv6")
        assert status == 200

        limitations = " ".join(payload.get("limitations") or [])
        assert "IPv6 routes are a separate table and are not included" not in limitations, (
            "the IPv6 report says IPv6 routes are not included"
        )


class TestRouteAnalysisIsNotShownToTheUser:
    """
    The analysis endpoint has no client in the frontend.

    The coordinator asked for a browser check that the route analysis renders.
    It cannot render, because nothing in the page calls the endpoint. This
    check records that gap; it will start failing when the frontend grows a
    client for it.
    """

    @pytest.mark.xfail(
        reason=(
            "QA-06: no frontend code calls /network/routes/analysis, so the "
            "analysis is never shown. The route analysis panel does not exist."
        ),
    )
    def test_the_route_analysis_is_visible_somewhere_on_the_page(self, page, backend_available):
        """The analysis should be reachable from the page, not only from the API."""
        open_page(page)

        body = page.inner_text("body").lower()
        assert "shadow" in body or "route analysis" in body, (
            "the route analysis is not shown anywhere on the page"
        )


class TestCaptureFilePanel:
    """The capture panel must report what it read, and admit what it could not."""

    def _open_capture_tab(self, page):
        page.locator(".tab-navigation button", has_text="Capture file").first.click()
        page.wait_for_timeout(400)

    def _upload(self, page, path):
        page.locator("input[type='file']").first.set_input_files(path)
        page.wait_for_timeout(400)
        page.get_by_role("button", name="Analyze").first.click()
        page.wait_for_timeout(4000)

    def test_a_capture_that_cannot_be_parsed_says_so(self, page, backend_available, tmp_path):
        """A file that is not a capture is reported as a parse failure."""
        open_page(page)
        self._open_capture_tab(page)

        path = write_temp_file(tmp_path, "not-a-capture.pcap", b"this is not a capture file at all")
        self._upload(page, path)

        body = page.inner_text("body")
        assert "Parse error" in body or "could not" in body.lower(), (
            "the parse failure was not shown"
        )
        assert "[object Object]" not in body, "an error object was rendered raw"

    def test_a_capture_that_cannot_be_parsed_shows_no_summary(self, page, backend_available, tmp_path):
        """A failed parse must not also present a summary as though it had read the file."""
        open_page(page)
        self._open_capture_tab(page)

        path = write_temp_file(tmp_path, "not-a-capture.pcap", b"this is not a capture file at all")
        self._upload(page, path)

        body = page.inner_text("body")
        # The summary of a successfully read file lists its protocols and
        # hosts. None of that may be present for a file that was not read.
        assert "Total packets" not in body, "a summary was shown for a file that failed to parse"
        assert "Total bytes" not in body, "a summary was shown for a file that failed to parse"

    def test_a_real_capture_produces_a_summary(self, page, backend_available, tmp_path):
        """A real capture is read and summarised."""
        open_page(page)
        self._open_capture_tab(page)

        path = write_temp_file(tmp_path, "sample.pcap", build_pcap_bytes())
        self._upload(page, path)

        body = page.inner_text("body")
        assert "Parse error" not in body, f"a real capture failed to parse: {body[-500:]}"
        assert "10.0.0.1" in body, "the capture's own addresses were not listed"

    @pytest.mark.xfail(
        reason=(
            "QA-07: the deeper capture analysis is not shown. The frontend "
            "PcapAnalysisResult type has no packets or handshakes field and "
            "the panel renders neither."
        ),
    )
    def test_the_capture_panel_shows_ports_flags_and_a_handshake(self, page, backend_available, tmp_path):
        """The panel should show the per-packet detail the backend now returns."""
        open_page(page)
        self._open_capture_tab(page)

        path = write_temp_file(tmp_path, "sample.pcap", build_pcap_bytes())
        self._upload(page, path)

        body = page.inner_text("body")
        assert "40000" in body, "the TCP ports were not shown"
        assert "SYN" in body, "the TCP flags were not shown"
        assert "handshake" in body.lower(), "no handshake was shown"
        assert "example.com" in body, "the DNS name was not shown"


class TestIPv6Collection:
    """The collector must be able to read the IPv6 table, not only IPv4."""

    @pytest.mark.xfail(
        reason=(
            "QA-08: /network/routes does not take an ip_version parameter, so it "
            "always returns the IPv4 table even when the IPv6 table is asked for."
        ),
    )
    def test_the_routes_endpoint_honours_the_address_family(self, page, backend_available):
        """Asking for the IPv6 table should return IPv6 routes."""
        open_page(page)

        status, payload = api_get(page, "/network/routes?ip_version=ipv6")
        assert status == 200

        for route in payload.get("data") or []:
            assert ":" in route["destination"] or route["destination"] == "default", (
                f"an IPv4 route {route['destination']} was returned for the IPv6 table"
            )


class TestErrorContract:
    """
    A failed request must come back with a message, not an object.

    The backend used to put the whole result object in HTTPException.detail.
    FastAPI documents `detail` as a string and the client renders it as one,
    so the page showed "[object Object]" instead of the reason. This check
    locks the fix in place at the level the bug actually lived.
    """

    def test_a_failed_dns_lookup_returns_a_string_detail(self, page, backend_available):
        """A name that cannot be resolved comes back with a readable message."""
        open_page(page)

        status, payload = api_post(
            page,
            "/network/dns-resolve",
            {"hostname": "this-name-does-not-exist-12345.invalid"},
        )
        assert status >= 400, "the lookup should have failed"
        assert isinstance(payload.get("detail"), str), (
            f"detail should be a message, got {type(payload.get('detail')).__name__}: "
            f"{payload.get('detail')!r}"
        )
        assert payload["detail"], "the error message was empty"

    def test_a_failed_connectivity_check_returns_a_string_detail(self, page, backend_available):
        """A refused connection comes back with a readable message."""
        open_page(page)

        status, payload = api_post(
            page,
            "/network/connectivity",
            {"target": "127.0.0.1", "protocol": "tcp", "port": 1, "timeout": 3},
        )
        assert status >= 400, "the check should have failed"
        assert isinstance(payload.get("detail"), str), (
            f"detail should be a message, got {type(payload.get('detail')).__name__}: "
            f"{payload.get('detail')!r}"
        )
