"""Registers the real tools Phase 1's job runner needs, so it goes through
the harness instead of calling httpx/filesystem/LLM code directly.

More tools (browser, database, git, docker...) get registered here as later
phases add them — this module is the one place that maps "capability" to
"risk level", which is exactly the harness-not-the-LLM enforcement point.
"""
from __future__ import annotations

import httpx

from veriforge.cartography.cartographer import analyze as analyze_repository_facts
from veriforge.cartography.filesystem import scan_repository
from veriforge.domain.enums import RiskLevel
from veriforge.explorer.browser import BrowserExplorer
from veriforge.harness.tools import RetryPolicy, ToolRegistry, ToolSpec
from veriforge.llm.provider import LLMProvider


def register_builtin_tools(registry: ToolRegistry, llm: LLMProvider) -> None:
    registry.register(
        ToolSpec(
            name="filesystem.scan_repository",
            description="Walk a repository path and report file counts, language markers, extensions.",
            risk=RiskLevel.READ,
            timeout_seconds=30.0,
        ),
        handler=lambda repo_path: scan_repository(repo_path),
    )

    registry.register(
        ToolSpec(
            name="code.analyze_repository",
            description=(
                "AST-based static analysis: discovers HTTP routes/endpoints, "
                "persistence backends, and role/permission-check hints. No code execution."
            ),
            risk=RiskLevel.READ,
            timeout_seconds=30.0,
        ),
        handler=lambda repo_path: analyze_repository_facts(repo_path),
    )

    registry.register(
        ToolSpec(
            name="api.get",
            description="HTTP GET a URL (read-only reachability/status check).",
            risk=RiskLevel.READ,
            timeout_seconds=10.0,
            retry_policy=RetryPolicy(max_retries=1, backoff_seconds=0.5),
        ),
        handler=lambda url, headers=None: httpx.get(url, headers=headers, timeout=5.0, follow_redirects=True),
    )

    # POST/PUT/DELETE are MEDIUM_RISK, not HIGH/DESTRUCTIVE, on the basis that
    # Phase 6's Executor only ever calls them against (a) a target URL the
    # user explicitly provided as the job's --url, and (b) resources the
    # Executor itself just created for the experiment — never arbitrary,
    # pre-existing, unscoped data. A tool that could target *any* resource
    # (e.g. a raw database.DELETE) would warrant HIGH_RISK/DESTRUCTIVE.
    registry.register(
        ToolSpec(
            name="api.post",
            description="HTTP POST to a URL (creates a resource for an experiment to act on).",
            risk=RiskLevel.MEDIUM_RISK,
            timeout_seconds=10.0,
        ),
        handler=lambda url, json=None, headers=None: httpx.post(url, json=json, headers=headers, timeout=5.0),
    )

    registry.register(
        ToolSpec(
            name="api.put",
            description="HTTP PUT to a URL, scoped to a resource an experiment created.",
            risk=RiskLevel.MEDIUM_RISK,
            timeout_seconds=10.0,
        ),
        handler=lambda url, json=None, headers=None: httpx.put(url, json=json, headers=headers, timeout=5.0),
    )

    registry.register(
        ToolSpec(
            name="api.delete",
            description="HTTP DELETE a URL, scoped to a resource an experiment created for this test.",
            risk=RiskLevel.MEDIUM_RISK,
            timeout_seconds=10.0,
        ),
        handler=lambda url, headers=None: httpx.delete(url, headers=headers, timeout=5.0),
    )

    registry.register(
        ToolSpec(
            name="browser.explore",
            description=(
                "Navigate a URL in a real headless browser, read the ARIA accessibility "
                "tree, and bounded-auto-click up to N non-destructive-looking elements, "
                "capturing console/network/screenshots as it goes."
            ),
            risk=RiskLevel.LOW_RISK,
            timeout_seconds=60.0,
        ),
        handler=lambda url, screenshot_dir=None, max_clicks=3: BrowserExplorer().explore(
            url, max_clicks=max_clicks, screenshot_dir=screenshot_dir
        ),
    )

    registry.register(
        ToolSpec(
            name="llm.generate",
            description="Generate a completion from the configured local LLM provider.",
            risk=RiskLevel.LOW_RISK,
            timeout_seconds=120.0,
        ),
        handler=lambda prompt, system=None: llm.generate(prompt, system=system),
    )
