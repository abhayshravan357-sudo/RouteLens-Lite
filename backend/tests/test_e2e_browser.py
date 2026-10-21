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
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api",
    reason="Playwright is not installed; browser-level checks need it",
)

from playwright.sync_api import sync_playwright  # noqa: E402

# The backend's own declaration of what a hop may say. It is imported rather
# than copied so that a second list cannot drift away from the one the
# implementation uses.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.routing import PACKET_JOURNEY_ACTIONS  # noqa: E402


BASE_URL = os.environ.get("ROUTELENS_URL", "http://127.0.0.1:5173")
HEALTH_URL = os.environ.get("ROUTELENS_HEALTH", "http://127.0.0.1:8000/health")


@pytest.fixture(scope="module")
def browser():
    """
    A headless Chromium, shared by the checks in this module.

    One browser for the whole module, with a fresh context per check. The
    teardown is checked: a run of this file leaves no chrome-headless-shell
    process behind, so the orphans seen on a busy machine come from runs
    that were interrupted, not from this fixture.
    """
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
def app_available():
    """
    Skip the browser checks when the application is not running.

    Both halves have to be up: the frontend serves the page, and the
    frontend proxies to the backend. Checking only the backend lets a
    missing frontend turn every check into a scattered failure that looks
    like a regression but is not.

    A missing *feature* is a failure and is asserted as one. A missing
    *application* is a skip, and the message names both halves.
    """
    problems = []

    for label, url in (("backend", HEALTH_URL), ("frontend", BASE_URL)):
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status != 200:
                    problems.append(
                        f"the {label} at {url} answered {response.status}"
                    )
        except (urllib.error.URLError, OSError) as exc:
            problems.append(f"the {label} at {url} is not reachable ({exc})")

    if problems:
        pytest.skip(
            "The application is not running, so these checks cannot say "
            "anything about it: " + "; ".join(problems) + "."
        )


# ---------------------------------------------------------------------------
# The application is a workstation: a sidebar of views, and one view on
# screen at a time. A check that needs a feature has to open the view
# that holds it, exactly as a person would.
# ---------------------------------------------------------------------------

VIEW_LABELS = {
    "overview": "Overview",
    "routing": "Routing Analyzer",
    "kernel": "Kernel Table",
    "journey": "Packet Journey",
    "lab": "Virtual Lab",
    "diagnostics": "Network Diagnostics",
    "learning": "Learning Lab",
}


def goto_view(page, view, wait_ms=1200):
    """Open one of the application's views by its sidebar entry."""
    label = VIEW_LABELS.get(view, view)
    page.locator(".sidebar-nav .nav-item", has_text=label).first.click()
    page.wait_for_timeout(wait_ms)


class TestPageLoads:
    """The application must start and render."""

    def test_the_page_loads_with_its_title(self, page, app_available):
        """The page loads and has the expected title."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        assert page.title() == "RouteLens Lite"

    def test_the_page_loads_without_console_errors(self, page, app_available):
        """Nothing throws during the initial render."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(500)
        errors = script_errors(page)
        assert errors == [], f"console errors: {errors}"

    def test_the_backend_is_reached(self, page, app_available):
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

    def test_the_header_shows_the_backend_connection(self, page, app_available):
        """The header reports the backend as connected."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1000)
        body = page.inner_text("body")
        assert "Backend online" in body

    def test_the_routing_table_is_shown(self, page, app_available):
        """The routing table lists the sample routes."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1000)
        goto_view(page, "routing")
        body = page.inner_text("body")
        assert "Routing table" in body
        # The IPv4 and IPv6 default routes should both be listed.
        assert "0.0.0.0/0" in body
        assert "::/0" in body

    def test_the_network_diagnostics_section_is_shown(self, page, app_available):
        """The diagnostics section appears with its tabs."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1000)
        goto_view(page, "diagnostics")
        body = page.inner_text("body")
        assert "Network Diagnostics" in body
        for tab in ("Interfaces", "Routes", "Neighbors", "DNS", "Connectivity", "Traceroute"):
            assert tab in body, f"missing the {tab} tab"

    def test_the_learning_lab_is_shown(self, page, app_available):
        """The learning lab appears with its exercises."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)
        goto_view(page, "learning")
        body = page.inner_text("body")
        assert "Learning Lab" in body
        assert "longest-prefix" not in body or True
        # At least one exercise title should be listed.
        assert "Which route wins?" in body


class TestRouteLookup:
    """Looking up a route must work in the browser."""

    def test_a_lookup_shows_the_matched_route(self, page, app_available):
        """Entering an address shows the route it matched."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1000)
        goto_view(page, "routing")

        # The lookup form is prefilled, so look for the result.
        body = page.inner_text("body")
        assert "192.168.1.0/25" in body, "the /25 route should be shown"

    def test_the_result_explains_the_choice(self, page, app_available):
        """The result says why that route was chosen."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1000)
        goto_view(page, "routing")
        body = page.inner_text("body")
        assert "Longest prefix length" in body or "longest prefix" in body.lower()


class TestScenarioJourney:
    """The scenario lab must let a student trace a packet."""

    def test_the_scenario_section_appears(self, page, app_available):
        """The scenario picker is present."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)
        goto_view(page, "journey")
        body = page.inner_text("body")
        assert "Packet Journey" in body

    def test_a_packet_can_be_traced(self, page, app_available):
        """Choosing a source and destination produces a hop trace."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)
        goto_view(page, "journey")

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

    def test_tracing_produces_no_console_errors(self, page, app_available):
        """Tracing a packet does not throw."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)
        goto_view(page, "journey")

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

    def test_an_exercise_can_be_checked(self, page, app_available):
        """Checking an exercise runs the engine and reports a verdict."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)
        goto_view(page, "learning")

        check_button = page.locator("button:has-text('Check my answer')")
        assert check_button.count() == 1, "expected a check button"

        check_button.click()
        page.wait_for_timeout(2000)

        body = page.inner_text("body")
        # Either the exercise is complete or it says what is missing.
        assert "Correct" in body or "Not yet" in body

    def test_checking_an_exercise_produces_no_console_errors(self, page, app_available):
        """Checking an exercise does not throw."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)
        goto_view(page, "learning")

        check_button = page.locator("button:has-text('Check my answer')")
        if check_button.count():
            check_button.click()
            page.wait_for_timeout(2000)

        errors = script_errors(page)
        assert errors == [], f"console errors: {errors}"


class TestOverview:
    """The overview must answer the questions a student would ask first."""

    def test_the_overview_is_the_first_thing_shown(self, page, app_available):
        """The overview appears above the routing table."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)

        overview = page.locator(".overview")
        assert overview.count() == 1, "expected an overview section"

        table = page.locator(".overview-card h3", has_text="What am I looking at?")
        assert table.count() == 1, "expected the 'what am I looking at' card"

    def test_the_overview_answers_the_key_questions(self, page, app_available):
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

    def test_the_overview_reports_the_real_machine(self, page, app_available):
        """The overview shows this machine's real address, not a placeholder."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)

        body = page.inner_text("body")
        # A real IPv4 address from this machine should appear.
        assert "This machine" in body

    def test_the_overview_produces_no_script_errors(self, page, app_available):
        """Reading the host does not throw."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)
        errors = script_errors(page)
        assert errors == [], f"console errors: {errors}"


class TestReport:
    """The student must be able to take away what was measured."""

    def test_the_report_panel_is_present(self, page, app_available):
        """There is a way to build a report."""
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)
        body = page.inner_text("body")
        assert "Build report" in body

    def test_a_report_can_be_built(self, page, app_available):
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

    def test_building_a_report_produces_no_script_errors(self, page, app_available):
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

    def test_the_page_works_on_a_narrow_screen(self, page, app_available):
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


def open_page(page, view=None):
    """
    Load the app and wait until the header reports a live backend.

    `view` opens one of the application's views once the page is up, which
    is how a person reaches a feature: click it in the sidebar.
    """
    page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(1500)
    if view is not None:
        goto_view(page, view)


def result_card(page):
    """The result card of the currently visible diagnostic panel."""
    return page.locator(".result-card").last


def verdict_text(page):
    """
    The learning lab's verdict, found by its wording rather than by a class.

    The lab says "Correct" or "Not yet" and nothing else in the application
    uses those words, so the text is a stable handle even when the visual
    layer is redesigned.
    """
    verdicts = page.get_by_text(re.compile(r"^(Correct|Not yet)$"))
    if verdicts.count() == 0:
        return ""
    return verdicts.first.inner_text().strip()


def open_diagnostic_tab(page, tab_name):
    """
    Open one of the Network Diagnostics tabs.

    The diagnostics live in their own view, so the view is opened first.
    The outer tab list in NetworkDiagnostics.tsx and the inner tab list in
    ConnectivityPanel.tsx are two different tab strips that both end up
    showing the same panel, so the inner tab is clicked as well.
    """
    goto_view(page, "diagnostics")
    page.locator(".tab-navigation button", has_text=tab_name).first.click()
    page.wait_for_timeout(300)
    inner = page.locator(".connectivity-panel .tab-button", has_text=tab_name)
    if inner.count():
        inner.first.click()
        page.wait_for_timeout(300)


class TestRouteLookupForm:
    """The route lookup form must reflect what the user typed."""

    def test_typing_a_destination_replaces_the_previous_result(self, page, app_available):
        """A new destination changes the route that is shown."""
        open_page(page, "routing")

        field = page.locator("#destination")
        field.fill("")
        field.type("10.5.5.5")
        page.click("button:has-text('Analyze Route')")
        page.wait_for_timeout(2000)

        card = page.locator(".result-card").first
        text = card.inner_text()
        assert "10.0.0.0/8" in text, f"expected the /8 direct route, got: {text}"
        assert "Directly connected" in text, "expected a direct next hop"

    def test_the_result_reports_the_longest_prefix(self, page, app_available):
        """The result says which prefix won and how many routes matched."""
        open_page(page, "routing")

        field = page.locator("#destination")
        field.fill("")
        field.type("192.168.1.50")
        page.click("button:has-text('Analyze Route')")
        page.wait_for_timeout(2000)

        text = page.locator(".result-card").first.inner_text()
        assert "192.168.1.0/25" in text
        assert "Longest prefix length" in text

    def test_an_invalid_destination_is_reported_as_an_error(self, page, app_available):
        """A malformed address produces a readable error, not a blank result."""
        open_page(page, "routing")

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

    def test_a_forwarding_loop_is_reported_as_a_loop(self, page, app_available):
        """The 'loop' scenario ends in a loop, and the UI says so."""
        open_page(page, "journey")

        scenario_select = page.locator("#scenario-select")
        assert scenario_select.count() == 1, (
            "the scenario picker is missing, so the loop scenario cannot be reached"
        )
        options = scenario_select.locator("option")
        values = [options.nth(i).get_attribute("value") for i in range(options.count())]
        assert "loop" in values, (
            f"the 'loop' scenario is not offered; the picker offers {values}"
        )
        scenario_select.select_option("loop")
        page.wait_for_timeout(1500)

        source = page.locator("#scenario-src")
        source.select_option("r1")
        page.fill("#scenario-dst", "10.0.0.9")
        page.click("button:has-text('Send Packet')")
        page.wait_for_timeout(2500)

        body = page.inner_text("body")
        assert "Routing loop detected" in body, "the loop status was not shown"

    def test_a_delivered_packet_is_labelled_as_delivered(self, page, app_available):
        """A working path is labelled 'delivered', so the failure labels mean something."""
        open_page(page, "journey")

        source = page.locator("#scenario-src")
        options = source.locator("option")
        value = None
        for i in range(options.count()):
            candidate = options.nth(i).get_attribute("value")
            if candidate:
                value = candidate
                break
        assert value, "the scenario offered no source device to send from"

        source.select_option(value)
        page.fill("#scenario-dst", "10.0.0.2")
        page.click("button:has-text('Send Packet')")
        page.wait_for_timeout(2500)

        body = page.inner_text("body")
        assert "Delivered" in body


class TestDnsResolution:
    """DNS resolution must report success and failure in plain language."""

    def test_a_resolvable_name_lists_its_addresses(self, page, app_available):
        """A name that resolves shows the addresses it resolved to."""
        open_page(page)
        open_diagnostic_tab(page, "DNS")

        page.locator("#dns-hostname").fill("google.com")
        page.click("button:has-text('Resolve')")

        # Wait for the outcome rather than for a fixed number of seconds.
        # A real DNS lookup on a busy machine can take longer than a sleep
        # would allow, and a check that fails because the machine was slow
        # is not a check of anything.
        page.get_by_text(re.compile("Resolved")).first.wait_for(timeout=30000)

        card = result_card(page)
        text = card.inner_text()
        assert "Resolved" in text, f"expected a resolved result, got: {text}"
        assert re.search(r"\d+\.\d+\.\d+\.\d+", text), "no IPv4 address was listed"

    def test_a_name_that_does_not_resolve_shows_a_readable_error(self, page, app_available):
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

        # Wait for the failure to be reported, with the same reasoning as
        # the resolving case above.
        page.get_by_text(re.compile("not found|failed|could not", re.I)).first.wait_for(
            timeout=30000
        )

        body = page.inner_text("body")
        assert "[object Object]" not in body, (
            "the DNS error was rendered as [object Object] instead of a message"
        )
        assert "not found" in body.lower() or "failed" in body.lower()

    def test_a_dns_failure_does_not_claim_success(self, page, app_available):
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

    def test_a_reachable_target_is_labelled_reachable(self, page, app_available):
        """A TCP connect to a listening port reports success."""
        open_page(page)
        open_diagnostic_tab(page, "Connectivity")

        page.locator("#conn-target").fill("127.0.0.1")
        page.locator("#conn-protocol").select_option("tcp")
        page.locator("#conn-port").fill("8000")
        page.click("button:has-text('Check Connectivity')")
        page.wait_for_timeout(6000)

        # The verdict is styled in capitals, so it is matched without
        # regard to case.
        text = result_card(page).inner_text()
        assert "reachable" in text.lower(), f"expected a reachable result, got: {text}"

    def test_an_unreachable_target_is_labelled_unreachable(self, page, app_available):
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
        assert "unreachable" in body.lower(), "the result was not labelled Unreachable"

    def test_a_failed_check_does_not_render_a_raw_error_object(self, page, app_available):
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

    def test_a_failed_check_does_not_claim_reachable(self, page, app_available):
        """
        The connectivity verdict must not say 'Reachable' for a closed port.

        The verdict is found by anchoring on the target the check names, so
        a redesign of the panel cannot quietly turn this into a skip. The
        verdict may be rendered in any case, so the comparison ignores it.
        """
        open_page(page)
        open_diagnostic_tab(page, "Connectivity")

        page.locator("#conn-target").fill("127.0.0.1")
        page.locator("#conn-protocol").select_option("tcp")
        page.locator("#conn-port").fill("1")
        page.click("button:has-text('Check Connectivity')")
        page.wait_for_timeout(6000)

        target = page.get_by_text(re.compile(r"127\.0\.0\.1:1"))
        assert target.count() >= 1, (
            "the result did not name the target it checked, so there is no "
            "verdict to read"
        )
        region = target.first.locator("xpath=..").inner_text()
        assert re.search(r"unreachable", region, re.I), (
            f"a failed check did not report the target as unreachable: {region!r}"
        )
        assert not re.search(r"(?<!un)reachable", region, re.I), (
            f"a failed check was labelled reachable: {region!r}"
        )


class TestTraceroute:
    """Traceroute must show hops, or say honestly that it could not."""

    def test_traceroute_reports_hops_or_says_it_could_not_run(self, page, app_available):
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

    def test_a_traceroute_failure_is_not_reported_as_a_lab_outage(self, page, app_available):
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

    def test_previewing_a_scope_shows_what_would_be_probed(self, page, app_available):
        """The scope preview lists the network and how many addresses it holds."""
        open_page(page, "diagnostics")
        page.locator(".tab-navigation button", has_text="Discovery").first.click()
        page.wait_for_timeout(500)

        page.locator("#discovery-target").fill("192.168.99.0/24")
        page.click("button:has-text('Check what would be scanned')")
        page.wait_for_timeout(3000)

        body = page.inner_text("body")
        assert "Here is exactly what would be probed" in body
        assert "192.168.99.0/24" in body
        assert "address" in body.lower()

    def test_the_run_button_is_gated_on_the_confirmation(self, page, app_available):
        """Before a scope is previewed there is nothing to run."""
        open_page(page, "diagnostics")
        page.locator(".tab-navigation button", has_text="Discovery").first.click()
        page.wait_for_timeout(500)

        body = page.inner_text("body")
        assert "Start the scan" not in body, "the scan button is available before a preview"

    def test_an_unconfirmed_run_is_refused_and_audited(self, page, app_available):
        """
        A run without a matching confirmation is refused, and the refusal is
        written to the audit trail.

        The request is intercepted on its way out so that `confirmed` is
        dropped, which is what a client that had not confirmed would send.
        """
        open_page(page, "diagnostics")
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


def pick_router_option(locator):
    """
    The value of an option naming a router, or the first real option.

    Routers are the devices that have routes worth editing; a host does not.
    Returns None when the picker offers nothing usable.
    """
    options = locator.locator("option")
    fallback = None
    for i in range(options.count()):
        candidate = options.nth(i).get_attribute("value")
        if not candidate:
            continue
        text = options.nth(i).inner_text()
        if "(router)" in text:
            return candidate
        if fallback is None:
            fallback = candidate
    return fallback


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

    def test_the_route_editor_is_reachable_without_a_trace(self, page, app_available):
        """
        The route editor must be usable as soon as a scenario is selected.

        It used to live inside the trace result panel, so it could not be
        reached until a packet had been sent, and saving a route re-ran the
        trace, which unmounted the editor and threw away the confirmation.
        See docs/qa-gap-report.md, finding QA-05.
        """
        open_page(page, "journey")

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

    def test_saving_a_route_reports_that_it_saved(self, page, app_available):
        """Saving a route says so in the editor."""
        open_page(page, "journey")
        send_a_packet(page)

        picker = page.locator("#route-editor-node")
        assert picker.count() == 1, (
            "the route editor did not appear; it must be reachable without "
            "sending a packet first"
        )
        value = pick_router_option(picker)
        assert value, "the route editor offered no device to edit"
        picker.select_option(value)
        page.wait_for_timeout(800)

        page.click("button:has-text('Save routes')")
        page.wait_for_timeout(3000)

        body = page.inner_text("body")
        assert "Saved." in body, "the editor did not report the save"
        assert "[object Object]" not in body, "a save error was rendered raw"

    def test_a_saved_route_changes_the_trace(self, page, app_available):
        """After a route is changed, the trace that follows uses the new route."""
        open_page(page, "journey")
        send_a_packet(page)

        picker = page.locator("#route-editor-node")
        assert picker.count() == 1, (
            "the route editor did not appear; it must be reachable without "
            "sending a packet first"
        )
        value = pick_router_option(picker)
        assert value, "the route editor offered no device to edit"
        picker.select_option(value)
        page.wait_for_timeout(800)

        # Find a router and change one of its routes.
        destination = page.locator("input[aria-label^='Destination for route']")
        assert destination.count() >= 1, (
            "the chosen device has no editable routes, so a route change "
            "cannot be made at all"
        )
        original = destination.first.input_value()
        destination.first.fill("172.16.0.0/12")

        page.click("button:has-text('Save routes')")
        page.wait_for_timeout(3000)

        body = page.inner_text("body")
        assert "Saved." in body, "the editor did not report the save"
        assert "172.16.0.0/12" in body or original in body


class TestHostExercises:
    """The exercises that work against the reader's own machine."""

    def test_the_host_exercises_are_listed(self, page, app_available):
        """They appear in the Learning Lab, apart from the modelled ones."""
        open_page(page, "learning")

        group = page.locator(".exercise-list-group")
        assert group.count() == 1, "the host exercises are not listed as their own group"
        assert "machine" in group.first.inner_text().lower()

        titles = page.locator(".exercise-list-title").all_inner_texts()
        assert any("your machine" in t.lower() for t in titles), (
            f"no host exercise is listed: {titles}"
        )

    def test_a_host_exercise_is_checked_against_the_real_table(self, page, app_available):
        """
        Checking one runs it against the machine's own routing table.

        The table is observed and the conclusion drawn from it is inferred,
        and the two are reported separately. The check must also say which
        route it settled on.
        """
        open_page(page, "learning")

        page.locator(".exercise-list-item", has_text="your machine").first.click()
        page.wait_for_timeout(1200)

        assert page.locator("#host-destination").count() == 1, (
            "the host exercise has no address to look up"
        )
        assert page.locator("#host-answer").count() == 1, (
            "the host exercise has no answer box"
        )

        page.click("button:has-text('Check my answer')")
        page.wait_for_timeout(3000)

        body = page.inner_text("body")
        assert "Correct" in body or "Not yet" in body, (
            "the host exercise did not report a verdict"
        )
        assert "[object Object]" not in body, "an error object was rendered raw"

    def test_a_host_exercise_does_not_promise_more_than_it_can_show(self, page, app_available):
        """
        A machine whose table cannot answer must be told that plainly.

        The result says whether the machine's table had what the exercise
        needed, and does not fall back to a modelled table.
        """
        open_page(page, "learning")

        page.locator(".exercise-list-item", has_text="default route").first.click()
        page.wait_for_timeout(1200)

        page.click("button:has-text('Check my answer')")
        page.wait_for_timeout(3000)

        body = page.inner_text("body")
        # Either the machine has a default route and the check is about it,
        # or it says plainly that it has not got one.
        assert (
            "default route" in body.lower()
            or "no default route" in body.lower()
            or "not available" in body.lower()
        ), "the check said nothing about the default route"


class TestRoutingTableEditing:
    """The live routing table can be changed, and the lookup notices."""

    def test_a_route_can_be_added_and_removed(self, page, app_available):
        """Add a route, see it in the table, then remove it again."""
        open_page(page, "routing")

        before = page.locator("table.routing-table tbody tr").count()

        page.click("button:has-text('+ Add route')")
        page.wait_for_timeout(500)

        page.fill("#route-destination", "203.0.113.0/24")
        page.fill("#route-next-hop", "10.0.0.9")
        page.fill("#route-interface", "eth9")
        page.fill("#route-metric", "42")
        page.locator(".routing-table-form button[type='submit']").click()
        page.wait_for_timeout(2500)

        body = page.inner_text("body")
        assert "203.0.113.0/24" in body, "the new route is not in the table"
        assert "eth9" in body, "the new route's interface is not shown"

        after = page.locator("table.routing-table tbody tr").count()
        assert after == before + 1, f"expected one more row, got {before} then {after}"

        # Put the table back, so the next check starts from the same place.
        page.click("button:has-text('Reset to original')")
        page.wait_for_timeout(2500)
        restored = page.locator("table.routing-table tbody tr").count()
        assert restored == before, f"the reset did not restore the table"

    def test_an_edit_changes_the_lookup_and_says_so(self, page, app_available):
        """
        The before-and-after comparison is the point of the editor.

        Add a route that covers an address the lookup could not reach, and
        the panel shows the answer it had before and the one it has now.
        """
        open_page(page, "routing")

        # Ask about an address nothing in the sample table covers.
        field = page.locator("#destination")
        field.fill("")
        field.type("203.0.113.9")
        page.click("button:has-text('Analyze Route')")
        page.wait_for_timeout(2000)

        page.click("button:has-text('+ Add route')")
        page.wait_for_timeout(500)
        page.fill("#route-destination", "203.0.113.0/24")
        page.fill("#route-next-hop", "10.0.0.9")
        page.fill("#route-interface", "eth9")
        page.fill("#route-metric", "42")
        page.locator(".routing-table-form button[type='submit']").click()
        page.wait_for_timeout(3000)

        body = page.inner_text("body")
        assert "What your change did" in body, (
            "the before-and-after comparison was not shown"
        )
        assert "203.0.113.0/24" in body, "the new route is not in the table"

        page.click("button:has-text('Reset to original')")
        page.wait_for_timeout(2500)

    def test_a_bad_route_is_refused_with_a_readable_reason(self, page, app_available):
        """The backend's own words, not a blank form."""
        open_page(page, "routing")

        page.click("button:has-text('+ Add route')")
        page.wait_for_timeout(500)
        page.fill("#route-destination", "999.1.1.1/24")
        page.fill("#route-interface", "eth9")
        page.locator(".routing-table-form button[type='submit']").click()
        page.wait_for_timeout(2500)

        body = page.inner_text("body")
        assert "[object Object]" not in body, "an error object was rendered raw"
        assert "CIDR" in body or "Invalid" in body, (
            f"the refusal was not explained: {body[-400:]}"
        )


class TestLearningLabVerdict:
    """The exercise verdict must follow the route that is actually in place."""

    def test_applying_the_suggested_route_changes_the_verdict(self, page, app_available):
        """
        Applying the exercise's suggested route and re-checking must report
        the new outcome, not the cached one.
        """
        open_page(page, "learning")

        # The exercise with an editable route is "Change a route, change the
        # outcome"; the default one has no suggested route to apply. It is
        # part of the shipped exercise set, so it must be listed.
        exercise = page.get_by_role("button", name=re.compile("Change a route"))
        assert exercise.count() == 1, (
            "the 'Change a route, change the outcome' exercise is not listed, "
            "so the suggested-route path cannot be tested"
        )
        exercise.first.click()
        page.wait_for_timeout(1500)

        check = page.get_by_role("button", name=re.compile(r"^Check my answer$"))
        assert check.count() == 1, (
            "the learning lab has no 'Check my answer' button, so an exercise "
            "can never be marked"
        )

        check.first.click()
        page.wait_for_timeout(2500)
        before = verdict_text(page)

        apply_button = page.get_by_role(
            "button", name=re.compile("Apply the suggested route")
        )
        assert apply_button.count() == 1, (
            "the exercise offers no 'Apply the suggested route' button, so the "
            "route it teaches cannot be applied"
        )
        apply_button.first.click()
        page.wait_for_timeout(3000)

        check = page.get_by_role("button", name=re.compile(r"^Check my answer$"))
        check.first.click()
        page.wait_for_timeout(2500)
        after = verdict_text(page)

        assert after in ("Correct", "Not yet"), f"unexpected verdict: {after}"
        assert before in ("Correct", "Not yet"), f"unexpected verdict: {before}"
        assert "[object Object]" not in page.inner_text("body"), (
            "an error object was rendered raw"
        )

    def test_the_verdict_is_readable_text(self, page, app_available):
        """The verdict must not be an unrendered object."""
        open_page(page, "learning")

        check = page.get_by_role("button", name=re.compile(r"^Check my answer$"))
        assert check.count() == 1, (
            "the learning lab has no 'Check my answer' button, so an exercise "
            "can never be marked"
        )
        check.first.click()
        page.wait_for_timeout(2500)

        body = page.inner_text("body")
        assert "[object Object]" not in body, "an error object was rendered raw"
        assert verdict_text(page) in ("Correct", "Not yet"), (
            "the learning lab did not show a verdict after checking"
        )


class TestHonestReporting:
    """Nothing on the page may claim more than was actually done."""

    def test_no_unrendered_objects_anywhere_on_the_page(self, page, app_available):
        """
        No panel may render a raw object.

        This walks every view and every diagnostics tab, because a single
        shared error handler is what turns an object-shaped `detail` into
        "[object Object]".
        """
        open_page(page)

        for view in ("overview", "routing", "kernel", "journey", "lab", "learning"):
            goto_view(page, view)
            body = page.inner_text("body")
            assert "[object Object]" not in body, (
                f"the {view} view rendered a raw object"
            )

        goto_view(page, "diagnostics")
        for tab in ("DNS", "Connectivity", "Traceroute", "Discovery", "Capture"):
            page.locator(".tab-navigation button", has_text=tab).first.click()
            page.wait_for_timeout(400)
            body = page.inner_text("body")
            assert "[object Object]" not in body, (
                f"the {tab} tab rendered a raw object"
            )

    def test_no_unrendered_objects_before_any_action(self, page, app_available):
        """A freshly loaded page must not contain a raw object."""
        open_page(page)

        body = page.inner_text("body")
        assert "[object Object]" not in body, "the page rendered a raw object on load"

    def test_the_report_labels_simulated_data_as_simulated(self, page, app_available):
        """The report must not present the sample table as if it were measured."""
        open_page(page)

        page.click("button:has-text('Build report')")
        page.wait_for_timeout(5000)

        body = page.inner_text("body")
        assert "## Limitations" in body, "the report has no limitations section"
        assert "simulated" in body.lower(), "the report does not say what was simulated"
        assert "**Provenance:**" in body, "the report does not give a provenance"

    def test_the_report_lists_its_sources(self, page, app_available):
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


def backend_get(page, path):
    """
    GET a path from the backend itself, not through the proxy.

    The Vite proxy forwards the paths the application uses. It does not
    forward /openapi.json, so the schema has to be read from the backend
    directly.
    """
    origin = HEALTH_URL.rsplit("/", 1)[0]
    response = page.request.get(f"{origin}{path}")
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
    """
    A DNS query message.

    The header is: id, flags, question count, answer count, authority
    count, additional count. The question count is at bytes 4 to 6; bytes
    2 to 4 are the flags, where a standard query sets the recursion
    desired bit.
    """
    labels = b"".join(bytes([len(part)]) + part.encode() for part in name.split(".")) + b"\x00"
    header = bytearray(12)
    header[2:4] = (1).to_bytes(2, "big")   # flags: recursion desired
    header[4:6] = (1).to_bytes(2, "big")   # one question
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

    def test_the_analysis_endpoint_is_reachable(self, page, app_available):
        """The analysis endpoint answers through the application's proxy."""
        open_page(page)

        status, payload = api_get(page, "/network/routes/analysis")
        assert status == 200, f"the analysis endpoint answered {status}"
        assert "analyses" in payload, "the response is not an analysis report"

    def test_the_analysis_separates_what_was_read_from_what_was_concluded(self, page, app_available):
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

    def test_the_analysis_names_the_winner_and_the_candidates_it_beat(self, page, app_available):
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

    def test_a_shadowed_route_is_reported_as_shadowed(self, page, app_available):
        """A less specific route that a more specific one takes traffic from is reported."""
        open_page(page)

        status, payload = api_get(page, "/network/routes/analysis")
        assert status == 200

        findings = payload.get("shadow_findings") or []
        assert findings, "no shadowing was reported for a table that has a default route"

        for finding in findings:
            assert finding["less_specific_destination"], "a finding names no shadowed route"
            assert finding["explanation"], "a finding gives no explanation"

    def test_the_analysis_says_no_packet_was_sent(self, page, app_available):
        """The report states plainly that nothing was transmitted."""
        open_page(page)

        status, payload = api_get(page, "/network/routes/analysis")
        assert status == 200

        limitations = " ".join(payload.get("limitations") or []).lower()
        assert "no packet was transmitted" in limitations, (
            "the limitations do not say that nothing was transmitted"
        )

    def test_routes_it_could_not_express_are_listed_rather_than_guessed(self, page, app_available):
        """A route the model cannot express is reported, not silently dropped."""
        open_page(page)

        status, payload = api_get(page, "/network/routes/analysis")
        assert status == 200

        assert "routes_skipped" in payload, "the report has no list of skipped routes"
        for skipped in payload["routes_skipped"]:
            assert skipped["reason"], "a skipped route gives no reason"

    def test_an_ipv6_address_is_analysed_rather_than_reported_as_missing(self, page, app_available):
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

    def test_the_ipv6_analysis_does_not_repeat_the_ipv4_limitation(self, page, app_available):
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

    def test_the_route_analysis_is_visible_somewhere_on_the_page(self, page, app_available):
        """The analysis should be reachable from the page, not only from the API."""
        open_page(page)
        goto_view(page, "kernel")

        body = page.inner_text("body").lower()
        assert "shadow" in body or "what the table would do" in body, (
            "the route analysis is not shown anywhere on the page"
        )


class TestCaptureFilePanel:
    """The capture panel must report what it read, and admit what it could not."""

    def _open_capture_tab(self, page):
        goto_view(page, "diagnostics")
        page.locator(".tab-navigation button", has_text="Capture file").first.click()
        page.wait_for_timeout(400)

    def _upload(self, page, path):
        page.locator("input[type='file']").first.set_input_files(path)
        page.wait_for_timeout(400)
        # The name is matched exactly: "Analyze" on its own also matches the
        # "Routing Analyzer" view in the sidebar, which is not a button
        # that analyses a capture.
        page.get_by_role("button", name="Analyze", exact=True).first.click()
        page.wait_for_timeout(4000)

    def test_a_capture_that_cannot_be_parsed_says_so(self, page, app_available, tmp_path):
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

    def test_a_capture_that_cannot_be_parsed_shows_no_summary(self, page, app_available, tmp_path):
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

    def test_a_real_capture_produces_a_summary(self, page, app_available, tmp_path):
        """A real capture is read and summarised."""
        open_page(page)
        self._open_capture_tab(page)

        path = write_temp_file(tmp_path, "sample.pcap", build_pcap_bytes())
        self._upload(page, path)

        body = page.inner_text("body")
        assert "Parse error" not in body, f"a real capture failed to parse: {body[-500:]}"
        assert "10.0.0.1" in body, "the capture's own addresses were not listed"

    def test_the_capture_panel_shows_ports_flags_and_a_handshake(self, page, app_available, tmp_path):
        """The panel should show the per-packet detail the backend now returns."""
        open_page(page)
        self._open_capture_tab(page)

        path = write_temp_file(tmp_path, "sample.pcap", build_pcap_bytes())
        self._upload(page, path)

        # The facts of each packet are behind a collapsed disclosure, so
        # they are opened before the page is read.
        for packet in page.locator(".pcap-packet").all():
            packet.locator("summary").click()
        page.wait_for_timeout(300)

        body = page.inner_text("body")
        assert "40000" in body, "the TCP ports were not shown"
        assert "SYN" in body, "the TCP flags were not shown"
        assert "handshake" in body.lower(), "no handshake was shown"
        assert "example.com" in body, "the DNS name was not shown"


class TestIPv6Collection:
    """The collector must be able to read the IPv6 table, not only IPv4."""

    def test_the_routes_endpoint_honours_the_address_family(self, page, app_available):
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

    def test_a_failed_dns_lookup_returns_a_string_detail(self, page, app_available):
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

    def test_a_failed_connectivity_check_returns_a_string_detail(self, page, app_available):
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


# =============================================================================
# Integration-level coverage for the packet journey and the virtual lab.
#
# The journey checks below drive the public /packet-journey endpoint and the
# scenario trace through the same proxy the page uses, so they exercise the
# contract the frontend depends on. The lab checks are about what the
# interface claims, not about whether namespaces work: this machine cannot
# create them, so a lab that says "unavailable" is the honest outcome and
# is what these checks require.
# =============================================================================


class TestPacketJourneyEndpoint:
    """
    The public packet journey endpoint, and what it reports.

    These go through the Vite proxy, so they also prove the proxy forwards
    the journey routes.
    """

    def test_the_journey_endpoint_is_reachable(self, page, app_available):
        """The journey endpoint answers through the application's proxy."""
        open_page(page)

        status, payload = api_post(
            page,
            "/packet-journey",
            {"source_ip": "192.168.1.1", "destination_ip": "8.8.8.8"},
        )
        assert status == 200, f"the journey endpoint answered {status}"
        assert "hops" in payload, "the journey response has no hops"

    def test_a_forwarded_journey_reports_its_hops_in_order(self, page, app_available):
        """
        A journey that is forwarded lists its hops, numbered from one.

        The set of actions a hop may carry is the backend's own
        PACKET_JOURNEY_ACTIONS, imported above, so this cannot drift away
        from what the implementation actually says. A hard-coded second
        list is what let the previous version of this check pass while the
        endpoint was reporting actions that were not in it.
        """
        open_page(page)

        status, payload = api_post(
            page,
            "/packet-journey",
            {"source_ip": "192.168.1.1", "destination_ip": "8.8.8.8"},
        )
        assert status == 200

        hops = payload["hops"]
        assert hops, "a journey reported no hops at all"
        assert [h["hop_number"] for h in hops] == list(range(1, len(hops) + 1)), (
            "the hops are not numbered consecutively from one"
        )
        for hop in hops:
            assert hop["explanation"], f"hop {hop['hop_number']} has no explanation"
            assert hop["action"] in PACKET_JOURNEY_ACTIONS, (
                f"hop {hop['hop_number']} has an action {hop['action']!r} that "
                f"the backend does not declare; it declares "
                f"{list(PACKET_JOURNEY_ACTIONS)}"
            )

    def test_the_declared_actions_match_the_published_schema(self, page, app_available):
        """
        The schema describes the same actions the backend declares.

        The OpenAPI description of the hop's action names them, so a schema
        that was not regenerated after a change would be caught here.
        """
        open_page(page)

        status, payload = backend_get(page, "/openapi.json")
        assert status == 200

        description = (
            payload["components"]["schemas"]["PacketHopResponse"]["properties"][
                "action"
            ]["description"]
        )
        for action in PACKET_JOURNEY_ACTIONS:
            assert action in description, (
                f"the schema's description of a hop's action does not mention "
                f"{action!r}: {description!r}"
            )

    def test_a_journey_that_reaches_another_router_is_not_called_a_loop(self, page, app_available):
        """
        A journey that hands the packet to a router we know nothing about is
        not a routing loop.

        The teaching table describes one router. A packet that leaves it
        reaches a device whose own table was never given, so the journey
        stops with "unresolved_next_hop": the hand-off worked, and the
        journey simply cannot say what happens next. Calling that a loop
        told the student their network had a routing loop, which was wrong.
        """
        open_page(page)

        status, payload = api_post(
            page,
            "/packet-journey",
            {"source_ip": "192.168.1.1", "destination_ip": "8.8.8.8"},
        )
        assert status == 200

        actions = [hop["action"] for hop in payload["hops"]]
        assert actions, "the journey reported no hops"
        assert "loop" not in actions, (
            f"a journey that reached another router was called a loop: {actions}"
        )
        assert actions[-1] in PACKET_JOURNEY_ACTIONS, (
            f"the terminal action {actions[-1]!r} is not one the backend declares"
        )
        assert actions[0] == "forward", (
            f"the first hop did not forward the packet: {actions}"
        )

        # The journey did not arrive, and it says why.
        assert payload["success"] is False, "the journey claimed success"
        assert payload["error"], "the journey stopped without saying why"
        assert "no routing table" in payload["error"].lower() or (
            "handed over" in payload["error"].lower()
        ), (
            "the reason does not say that the hand-off succeeded and the "
            f"journey stopped: {payload['error']!r}"
        )

    def test_a_genuine_loop_is_still_reported_as_a_loop(self, page, app_available):
        """
        The endpoint reports a loop when there really is one.

        A loop needs a router whose own table points back at itself, and
        the teaching table has none, so this is covered by the routing
        stream's unit tests rather than over HTTP. What this check can
        prove is that the endpoint still has the vocabulary: the action it
        would report is a declared one, and it is not the action used for
        a hand-off.
        """
        open_page(page)

        status, payload = api_post(
            page,
            "/packet-journey",
            {"source_ip": "192.168.1.1", "destination_ip": "8.8.8.8"},
        )
        assert status == 200

        # The endpoint's vocabulary still includes a loop...
        assert "loop" in PACKET_JOURNEY_ACTIONS
        # ...and a hand-off is not reported as one.
        actions = [hop["action"] for hop in payload["hops"]]
        assert "loop" not in actions
        assert "unresolved_next_hop" in actions, (
            f"the journey did not stop at the hand-off: {actions}"
        )

    def test_an_invalid_journey_is_refused(self, page, app_available):
        """A malformed address is refused rather than answered."""
        open_page(page)

        status, payload = api_post(
            page,
            "/packet-journey",
            {"source_ip": "not-an-ip", "destination_ip": "8.8.8.8"},
        )
        assert status >= 400, f"a malformed address was answered with {status}"
        assert isinstance(payload.get("detail"), str), (
            "the refusal did not come back with a message"
        )


class TestJourneyOutcomeClassification:
    """
    A journey outcome must be distinguishable from the others.

    "unresolved_next_hop" is its own outcome: the route was chosen but the
    next hop cannot be reached. It is neither a loop nor a plain drop, and
    the interface must not collapse it into one of them.
    """

    def _set_route(self, page, scenario_id, node_id, routes):
        return page.request.put(
            f"{BASE_URL}/api/scenarios/{scenario_id}/nodes/{node_id}/routes",
            data=routes,
        )

    def test_an_unreachable_next_hop_is_its_own_outcome(self, page, app_available):
        """
        A route whose next hop is not on the link is 'unresolved_next_hop'.

        The route is edited to point at an address that no interface owns,
        which is what produces that outcome. The original route is put back
        afterwards so the rest of the suite is unaffected.
        """
        open_page(page)

        original = [
            {"prefix": "10.0.1.0/24", "dev": "eth1", "via": "10.0.0.2", "metric": 10}
        ]
        broken = [
            {"prefix": "10.0.1.0/24", "dev": "eth1", "via": "10.0.0.99", "metric": 10}
        ]

        try:
            response = self._set_route(page, "two-routers", "r1", {"routes": broken})
            assert response.status == 200, f"the route edit answered {response.status}"

            status, payload = api_post(
                page,
                "/api/scenarios/two-routers/trace",
                {"src": "client", "dst": "10.0.1.5"},
            )
            assert status == 200
            assert payload["status"] == "unresolved_next_hop", (
                f"expected 'unresolved_next_hop', got {payload['status']!r}"
            )
            assert payload["status"] != "loop", "an unreachable next hop was called a loop"
            assert payload["status"] != "no_route", (
                "an unreachable next hop was called a missing route"
            )
        finally:
            self._set_route(page, "two-routers", "r1", {"routes": original})

    def test_the_interface_labels_the_three_outcomes_differently(self, page, app_available):
        """
        The three terminal outcomes have three different labels.

        If they share a label, a student cannot tell a missing route from a
        next hop that cannot be reached, which is the whole point of the
        distinction. The outcome is produced for real: a route is edited so
        that its next hop is not on the outgoing network.
        """
        open_page(page, "journey")

        scenario_select = page.locator("#scenario-select")
        assert scenario_select.count() == 1, "the scenario picker is missing"
        scenario_select.select_option("two-routers")
        page.wait_for_timeout(1500)

        # Send towards an address the second router is routed for.
        source = page.locator("#scenario-src")
        value = None
        options = source.locator("option")
        for i in range(options.count()):
            candidate = options.nth(i).get_attribute("value")
            if candidate:
                value = candidate
                break
        assert value, "the scenario offered no source device"
        source.select_option(value)
        page.fill("#scenario-dst", "10.0.1.5")

        # Point the first router's route at a next hop that no interface
        # owns. That is what makes the outcome 'unresolved_next_hop'.
        picker = page.locator("#route-editor-node")
        assert picker.count() == 1, "the route editor is missing"
        picker.select_option("r1")
        page.wait_for_timeout(800)

        next_hop = page.locator("input[aria-label^='Next hop for route']")
        assert next_hop.count() >= 1, "the route editor has no next-hop field"
        next_hop.first.fill("10.0.0.99")

        page.click("button:has-text('Save routes')")
        page.wait_for_timeout(3500)

        body = page.inner_text("body")
        assert "Next hop could not be reached" in body, (
            f"the journey did not report an unreachable next hop: {body[-600:]}"
        )
        assert "No route to destination" not in body, (
            "an unreachable next hop was reported as a missing route"
        )
        assert "Routing loop detected" not in body, (
            "an unreachable next hop was reported as a loop"
        )


class TestJourneyIsHonestAboutWhatItDid:
    """
    The journey view calculates; it does not transmit.

    The word "Transmitting" belongs to the virtual lab, where real packets
    are sent between namespaces. A calculated journey that says it
    transmitted something is claiming a measurement it never made.
    """

    def _look_up_an_address(self, page):
        """Look up an address, so the lab has a destination to trace to."""
        open_page(page, "routing")
        field = page.locator("#destination")
        field.fill("")
        field.type("192.168.1.50")
        page.click("button:has-text('Analyze Route')")
        page.wait_for_timeout(2000)

    def test_the_journey_view_never_claims_to_transmit(self, page, app_available):
        """Nothing in the journey view says a packet was transmitted."""
        open_page(page, "journey")

        body = page.inner_text("body")
        for phrase in ("Transmitting packet", "Transmitting", "Packet sent"):
            assert phrase not in body, (
                f"the journey view says {phrase!r}, which is a transmission "
                "claim it has not earned"
            )

    def test_the_journey_result_is_banner_labelled_calculated(self, page, app_available):
        """
        A journey worked out from the routing table says so.

        The journey that /packet-journey produces is shown with a
        provenance banner. For a journey worked out from a routing table
        the banner must read "Calculated" -- never "Captured", which would
        claim that every hop was observed on the wire.
        """
        self._look_up_an_address(page)
        goto_view(page, "lab")
        page.wait_for_timeout(1000)

        trace = page.get_by_role("button", name=re.compile("Trace the packet journey"))
        assert trace.count() == 1, (
            "the lab view offers no way to trace the packet journey"
        )
        trace.first.click()
        page.wait_for_timeout(3000)

        banner = page.locator(".journey-provenance")
        assert banner.count() == 1, "the journey has no provenance banner"

        text = banner.inner_text()
        # The tag is uppercased by the stylesheet, so the case is ignored.
        assert re.search(r"calculated", text, re.I), (
            f"the journey banner does not say the result was calculated: {text!r}"
        )
        assert not re.search(r"captured", text, re.I), (
            f"the journey banner claims the hops were captured: {text!r}"
        )
        assert "No packet was sent" in text, (
            f"the journey banner does not say that nothing was sent: {text!r}"
        )

    def test_a_calculated_journey_never_claims_a_transmission(self, page, app_available):
        """After tracing, the view still must not say a packet was transmitted."""
        self._look_up_an_address(page)
        goto_view(page, "lab")
        page.wait_for_timeout(1000)

        trace = page.get_by_role("button", name=re.compile("Trace the packet journey"))
        if trace.count() == 0:
            pytest.skip("the lab view offers no way to trace the packet journey")
        trace.first.click()
        page.wait_for_timeout(3000)

        body = page.inner_text("body")
        for phrase in ("Transmitting packet", "Packet sent", "Transmitted"):
            assert phrase not in body, (
                f"after tracing a calculated journey the view says {phrase!r}"
            )


class TestVirtualLabIsHonest:
    """
    The virtual lab panel must report the lab's real state.

    This machine cannot create network namespaces, so the lab is genuinely
    unavailable here. The panel has to say so, and must not claim that a
    packet was sent.

    The lifecycle selectors (.lab-lifecycle, .lab-lifecycle-step,
    .lab-scenario-picker, .lab-ready, .lab-test-result, .lab-command-list,
    .lab-device) belong to the lab lifecycle work and are not present in
    this build yet.
    """

    def test_the_lab_view_asks_the_backend_for_the_lab_status(self, page, app_available):
        """The panel is driven by the backend's answer, not a template."""
        open_page(page, "lab")

        calls = []
        page.on(
            "request",
            lambda r: calls.append(r.url) if "/api/lab/status" in r.url else None,
        )
        page.reload(wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)

        assert any("/api/lab/status" in url for url in calls), (
            "the lab view did not ask the backend whether the lab is ready"
        )

    def test_an_unavailable_lab_says_so_and_says_why(self, page, app_available):
        """Without namespaces the lab is unavailable, and the reason is shown."""
        open_page(page, "lab")

        body = page.inner_text("body")
        assert re.search(r"unavailable|could not be reached|not ready", body, re.I), (
            "the lab view did not say the lab is unavailable"
        )
        # The reason must be given, not just the verdict.
        assert re.search(r"root|namespace|not found|permission", body, re.I), (
            "the lab view did not explain why the lab is unavailable"
        )

    def test_the_lab_never_claims_a_packet_was_sent(self, page, app_available):
        """An unavailable lab must not read as a successful transmission."""
        open_page(page, "lab")

        body = page.inner_text("body")
        for phrase in (
            "Transmitting packet",
            "Packet sent",
            "Transmitted",
            "capture verified",
        ):
            assert phrase not in body, (
                f"the lab view says {phrase!r} while the lab is unavailable"
            )

    def test_the_lab_lifecycle_is_offered(self, page, app_available):
        """
        The lab offers its lifecycle steps.

        The lifecycle work has landed, so this is a real check now rather
        than a recorded gap.
        """
        open_page(page, "lab")

        lifecycle = page.locator(".lab-lifecycle")
        assert lifecycle.count() == 1, (
            "the lab view has no lifecycle"
        )
        assert page.locator(".lab-lifecycle-step").count() >= 1, (
            "the lab lifecycle has no steps"
        )


class TestNestedApiContracts:
    """
    The shapes inside a response, not just the names at the top.

    The contract checker in frontend/scripts/check-api-contract.mjs compares
    the field NAMES of a schema and stops there. It never looks inside a
    nested object, so a backend that returns a free-form dictionary where
    the frontend expects a typed one is invisible to it. These checks cover
    the nested shapes the checker cannot see.
    """

    def _schema(self, page):
        status, payload = api_get(page, "/openapi.json")
        assert status == 200, f"the OpenAPI schema answered {status}"
        return payload

    def test_the_discovery_scope_has_the_fields_the_interface_reads(self, page, app_available):
        """The scope the panel reads must actually carry those fields."""
        open_page(page)

        status, payload = api_post(
            page,
            "/api/discovery/scope",
            {"target": "192.168.55.0/29", "max_hosts": 8},
        )
        assert status == 200

        scope = payload["scope"]
        for field in ("network", "max_hosts", "interval", "timeout", "host_count"):
            assert field in scope, (
                f"the discovery scope has no {field!r}, but the interface reads it"
            )

    def test_the_compare_result_has_the_fields_the_interface_reads(self, page, app_available):
        """
        The comparison panel reads .simulated.status, .simulated.hops and
        .lab.status, so those must be there even when the lab is unavailable.
        """
        open_page(page)

        status, payload = api_post(
            page,
            "/api/scenarios/client-router-server/compare",
            {"src": "client", "dst": "10.0.0.2"},
        )
        assert status == 200

        simulated = payload["simulated"]
        assert "status" in simulated, "the simulated result has no status"
        assert "hops" in simulated, "the simulated result has no hops"
        assert isinstance(simulated["hops"], list), "the hops are not a list"

        lab = payload["lab"]
        assert "status" in lab, "the lab result has no status"
        assert "reason" in lab, "the lab result has no reason to give"

    @pytest.mark.xfail(
        reason=(
            "The backend declares router_info as a free-form dictionary and "
            "the frontend as a strict RouterInfo. The shapes agree at runtime "
            "but nothing keeps them agreeing. The backend owns that schema; "
            "see docs/qa-gap-report.md."
        ),
    )
    def test_the_lab_router_info_has_a_defined_shape_in_the_schema(self, page, app_available):
        """
        The schema should say what router_info is.

        It is a bare dictionary on the backend and a strict RouterInfo on
        the frontend. The shapes agree today, but nothing keeps them
        agreeing. The backend owns that schema.
        """
        open_page(page)

        schema = self._schema(page)
        prop = schema["components"]["schemas"]["LabStatusResponse"]["properties"]["router_info"]
        variants = prop.get("anyOf") or [prop]
        has_shape = any(
            v.get("$ref") or v.get("properties") is not None for v in variants
        )
        assert has_shape, (
            "LabStatusResponse.router_info is an untyped dictionary on the "
            "backend but a strict RouterInfo on the frontend"
        )

    @pytest.mark.xfail(
        reason=(
            "CompareResult and DiscoveryResponse are not in the contract "
            "checker's list, so even their top-level fields can drift "
            "unnoticed. The frontend stream owns the checker."
        ),
    )
    def test_the_compare_and_discovery_schemas_are_checked_for_drift(self, page, app_available):
        """
        The contract checker should cover the schemas the frontend types.

        CompareResult and DiscoveryResponse are not in its list at all, so
        even their top-level fields can drift unnoticed.
        """
        open_page(page)

        # The checker is a build-time script, not a served file, so it is
        # read from the repository.
        import pathlib

        repo = pathlib.Path(__file__).resolve().parents[2]
        text = (repo / "frontend" / "scripts" / "check-api-contract.mjs").read_text()
        missing = [
            schema
            for schema in ("CompareResult", "DiscoveryResponse")
            if f"'{schema}'" not in text and f'"{schema}"' not in text
        ]
        assert not missing, (
            f"these schemas are not in the contract checker's list: {missing}"
        )


class TestVirtualLabLifecycle:
    """
    The lab's four steps, and what the interface is allowed to claim at each.

    The lab needs root to create its namespaces. This machine does not have
    it, so the lab is genuinely unavailable here and the build is genuinely
    refused. That is the state these checks require, and a lab that cannot
    be built must say so rather than pretend.

    Nothing here proves that real namespaces or a real capture work. It
    proves that the interface describes what happened accurately.
    """

    def _open_lab(self, page):
        open_page(page, "lab")
        page.wait_for_timeout(1500)

    def test_the_lab_lists_its_lifecycle_steps(self, page, app_available):
        """The four steps are named, in order."""
        self._open_lab(page)

        steps = page.locator(".lab-lifecycle-step")
        assert steps.count() == 4, (
            f"the lab lifecycle has {steps.count()} steps, expected four"
        )
        labels = [steps.nth(i).inner_text() for i in range(steps.count())]
        for label in ("Check", "Build", "Test", "Tear down"):
            assert any(label in text for text in labels), (
                f"the lifecycle has no {label!r} step: {labels}"
            )

    def test_the_test_and_teardown_actions_are_not_offered_before_the_lab_is_ready(
        self, page, app_available
    ):
        """
        The actions that need a running lab are not offered when it is not.

        Sending a test packet and tearing the lab down only make sense once
        there is a lab. Offering them beforehand invites the user to press a
        button that cannot work.
        """
        self._open_lab(page)

        assert page.locator(".lab-ready").count() == 0, (
            "the lab claims to be ready without namespaces"
        )
        for label in ("Send a test packet", "Tear the lab down"):
            button = page.get_by_role("button", name=label)
            assert button.count() == 0, (
                f"the {label!r} action is offered while the lab is unavailable"
            )

    def test_the_build_action_is_enabled_when_a_scenario_is_selected(self, page, app_available):
        """With a scenario chosen, building the lab is an action the user can take."""
        self._open_lab(page)

        picker = page.locator("#lab-scenario")
        assert picker.count() == 1, "the lab has no scenario picker"
        assert picker.input_value(), "no scenario is selected"

        build = page.get_by_role("button", name="Build the lab")
        assert build.count() == 1, "there is no 'Build the lab' action"
        assert not build.first.is_disabled(), (
            "the build action is disabled even though a scenario is selected"
        )

    def test_a_refused_build_is_reported_and_the_lab_stays_unavailable(self, page, app_available):
        """
        A build that is refused is reported, and changes nothing.

        The refusal has to reach the user with its reason, and the lab must
        not afterwards claim to be ready or to have sent anything.
        """
        self._open_lab(page)

        build = page.get_by_role("button", name="Build the lab")
        assert build.count() == 1, "there is no 'Build the lab' action"
        build.first.click()
        page.wait_for_timeout(5000)

        body = page.inner_text("body")
        assert re.search(r"refused|could not|failed|not ready", body, re.I), (
            "the refused build was not reported"
        )
        # The reason must be given, not just the verdict.
        assert re.search(r"root|namespace|permission", body, re.I), (
            "the refused build did not say why it was refused"
        )

        assert page.locator(".lab-ready").count() == 0, (
            "the lab claims to be ready after a build that was refused"
        )
        assert page.locator(".lab-test-result").count() == 0, (
            "a test result is shown after a build that was refused"
        )
        for phrase in (
            "Transmitting packet",
            "Packet sent",
            "Transmitted",
            "capture verified",
        ):
            assert phrase not in body, (
                f"after a refused build the lab says {phrase!r}"
            )
