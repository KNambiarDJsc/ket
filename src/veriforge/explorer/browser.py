"""Browser explorer: real Playwright automation driven off the ARIA
accessibility tree (`locator.aria_snapshot()`), not raw CSS selectors — this
is the "precision mode: DOM/ARIA" path from spec §13/§14, not computer-use
vision (that's reserved for canvases/drag-drop/unknown UIs later).

Bounded, conservative auto-exploration: re-observes the page's accessibility
tree after every click (not just once at the start), so an element that only
appears after an action — e.g. a "Delete" button that shows up once a
project has been created — is actually discovered, not missed. Up to
`max_clicks` distinct elements whose accessible name doesn't look
destructive get clicked; destructive-looking elements are recorded as
skipped, never auto-clicked. Deciding to deliberately test a delete flow
with intent is the Test Scientist's job (Phase 5), going through the
Executor/Oracle (Phase 6), not something a bounded explorer should stumble
into by accident.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

INTERACTIVE_ROLES = {
    "button", "link", "checkbox", "radio", "textbox", "combobox", "menuitem", "tab", "switch",
}
DESTRUCTIVE_NAME_HINTS = ("delete", "remove", "archive", "destroy", "deactivate", "cancel")

# `networkidle` only tracks in-flight network connections; it can resolve a
# beat before a fetch's `.then()`/`await` continuation has actually finished
# mutating the DOM. Rather than guess a fixed sleep (racy either way — too
# short and the mutation isn't done yet, too long and every exploration pays
# for it), poll the accessibility tree until it actually changes or a ceiling
# is hit — this works for any target app, not just ones we know the DOM of.
POST_CLICK_POLL_INTERVAL_MS = 100
POST_CLICK_POLL_CEILING_MS = 1500

_ARIA_LINE_RE = re.compile(r'-\s+(?P<role>[\w-]+)\s+"(?P<name>[^"]*)"')


@dataclass
class DiscoveredElement:
    role: str
    name: str
    looks_destructive: bool


@dataclass
class ConsoleMessage:
    level: str
    text: str


@dataclass
class NetworkEvent:
    method: str
    url: str
    status: int | None


@dataclass
class PageObservation:
    url: str
    title: str
    elements: list[DiscoveredElement]
    screenshot_path: str | None = None


@dataclass
class ExplorationResult:
    pages: list[PageObservation] = field(default_factory=list)
    workflow_steps: list[str] = field(default_factory=list)
    skipped_destructive: list[str] = field(default_factory=list)
    console_messages: list[ConsoleMessage] = field(default_factory=list)
    network_events: list[NetworkEvent] = field(default_factory=list)


def _parse_aria_snapshot(snapshot_text: str) -> list[DiscoveredElement]:
    elements = []
    for match in _ARIA_LINE_RE.finditer(snapshot_text):
        role = match.group("role")
        name = match.group("name")
        if role not in INTERACTIVE_ROLES or not name:
            continue
        looks_destructive = any(hint in name.lower() for hint in DESTRUCTIVE_NAME_HINTS)
        elements.append(DiscoveredElement(role=role, name=name, looks_destructive=looks_destructive))
    return elements


class BrowserExplorer:
    def __init__(self, headless: bool = True):
        self._headless = headless

    @staticmethod
    def _observe_elements(page) -> list[DiscoveredElement]:
        return _parse_aria_snapshot(page.locator("body").aria_snapshot())

    @staticmethod
    def _observe_elements_after_change(page, snapshot_before: str) -> list[DiscoveredElement]:
        """Polls the accessibility tree until it differs from `snapshot_before`
        or the ceiling is hit, then returns the (possibly unchanged) result."""
        waited_ms = 0
        while waited_ms < POST_CLICK_POLL_CEILING_MS:
            page.wait_for_timeout(POST_CLICK_POLL_INTERVAL_MS)
            waited_ms += POST_CLICK_POLL_INTERVAL_MS
            snapshot_now = page.locator("body").aria_snapshot()
            if snapshot_now != snapshot_before:
                return _parse_aria_snapshot(snapshot_now)
        return _parse_aria_snapshot(snapshot_before)

    @staticmethod
    def _screenshot(page, screenshot_dir: Path | None, index: int) -> str | None:
        if screenshot_dir is None:
            return None
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        path = str(screenshot_dir / f"page_{index}.png")
        page.screenshot(path=path)
        return path

    def explore(
        self,
        start_url: str,
        *,
        max_clicks: int = 3,
        screenshot_dir: str | Path | None = None,
        timeout_ms: float = 10_000,
    ) -> ExplorationResult:
        screenshot_dir_path = Path(screenshot_dir) if screenshot_dir else None
        console_messages: list[ConsoleMessage] = []
        network_events: list[NetworkEvent] = []
        workflow_steps: list[str] = [f"navigated to {start_url}"]
        seen_elements: dict[tuple[str, str], DiscoveredElement] = {}
        clicked_keys: set[tuple[str, str]] = set()

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=self._headless)
            try:
                page = browser.new_page()
                page.on("console", lambda msg: console_messages.append(ConsoleMessage(msg.type, msg.text)))
                page.on(
                    "response",
                    lambda resp: network_events.append(NetworkEvent(resp.request.method, resp.url, resp.status)),
                )

                page.goto(start_url, timeout=timeout_ms, wait_until="networkidle")
                current_elements = self._observe_elements(page)
                for el in current_elements:
                    seen_elements.setdefault((el.role, el.name), el)

                initial_obs = PageObservation(
                    url=page.url,
                    title=page.title(),
                    elements=current_elements,
                    screenshot_path=self._screenshot(page, screenshot_dir_path, 0),
                )

                clicks_done = 0
                while clicks_done < max_clicks:
                    candidate = next(
                        (
                            el
                            for el in current_elements
                            if (el.role, el.name) not in clicked_keys and not el.looks_destructive
                        ),
                        None,
                    )
                    if candidate is None:
                        break
                    clicked_keys.add((candidate.role, candidate.name))
                    snapshot_before = page.locator("body").aria_snapshot()
                    try:
                        page.get_by_role(candidate.role, name=candidate.name, exact=True).first.click(timeout=3000)
                        page.wait_for_load_state("networkidle", timeout=3000)
                    except PlaywrightError as exc:
                        workflow_steps.append(f"failed to click {candidate.role} \"{candidate.name}\": {exc}")
                        continue
                    clicks_done += 1
                    workflow_steps.append(f"clicked {candidate.role} \"{candidate.name}\"")

                    # Re-observe: an action may have revealed elements (e.g. a
                    # "Delete" button that only exists once something has been
                    # created) that weren't present in the very first snapshot.
                    # Poll rather than fixed-sleep since networkidle can resolve
                    # a beat before the DOM mutation actually lands.
                    current_elements = self._observe_elements_after_change(page, snapshot_before)
                    for el in current_elements:
                        seen_elements.setdefault((el.role, el.name), el)

                pages = [initial_obs]
                if clicks_done:
                    pages.append(
                        PageObservation(
                            url=page.url,
                            title=page.title(),
                            elements=current_elements,
                            screenshot_path=self._screenshot(page, screenshot_dir_path, 1),
                        )
                    )
            finally:
                browser.close()

        skipped_destructive = [
            f'{role} "{name}" (looks destructive — not auto-clicked)'
            for (role, name), el in seen_elements.items()
            if el.looks_destructive and (role, name) not in clicked_keys
        ]

        return ExplorationResult(
            pages=pages,
            workflow_steps=workflow_steps,
            skipped_destructive=skipped_destructive,
            console_messages=console_messages,
            network_events=network_events,
        )
