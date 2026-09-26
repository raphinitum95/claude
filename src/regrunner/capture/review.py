"""Review-only capture: console errors, page exceptions, failed requests and 4xx/5xx responses.

Everything captured here is tagged with the test and step it happened on and shown in a separate
"things to review" section.  It NEVER affects a step's or a test's pass/fail result.
"""
from __future__ import annotations

import re
from typing import Any, Callable


class ReviewCollector:
    def __init__(self, test_id: str, emit: Callable[..., Any], *, ignore_urls: list[str] | None = None,
                 ignore_messages: list[str] | None = None, max_items: int = 500):
        self.test_id = test_id
        self._emit = emit
        self.step = 0                       # updated by the runner before each step
        self.step_name = ""
        self.items: list[dict[str, Any]] = []
        self._seen: dict[tuple, dict[str, Any]] = {}
        self._ignore_urls = [re.compile(p) for p in (ignore_urls or [])]
        self._ignore_msgs = [re.compile(p) for p in (ignore_messages or [])]
        self._max = max_items
        self.dropped = 0

    # -- attachment ---------------------------------------------------------------------------
    def attach(self, page) -> None:
        page.on("console", self._on_console)
        page.on("pageerror", self._on_pageerror)
        page.on("requestfailed", self._on_requestfailed)
        page.on("response", self._on_response)

    # -- handlers (synchronous; Playwright calls them from its event loop) -----------------------
    def _on_console(self, msg) -> None:
        if msg.type != "error":
            return
        loc = msg.location or {}
        url = loc.get("url", "") if isinstance(loc, dict) else ""
        self._add("console_error", kind="console", message=msg.text, url=url)

    def _on_pageerror(self, err) -> None:
        self._add("console_error", kind="pageerror", message=str(err), url="")

    def _on_requestfailed(self, request) -> None:
        failure = request.failure or ""
        if "ERR_ABORTED" in failure or "cancel" in failure.lower():
            return                                  # navigations/XHR cancelled by the page itself: noise
        self._add("network_error", kind="requestfailed", url=request.url, method=request.method,
                  status=None, message=failure or "request failed", resource=request.resource_type)

    def _on_response(self, response) -> None:
        if response.status < 400:
            return
        req = response.request
        self._add("network_error", kind="http_error", url=response.url, method=req.method,
                  status=response.status, message=f"HTTP {response.status} {response.status_text}".strip(),
                  resource=req.resource_type)

    # -- core ------------------------------------------------------------------------------------
    def _add(self, event_type: str, **fields: Any) -> None:
        url, message = fields.get("url", ""), fields.get("message", "")
        if any(p.search(url) for p in self._ignore_urls) or any(p.search(message) for p in self._ignore_msgs):
            return
        key = (event_type, fields.get("kind"), url, fields.get("status"), message[:200])
        existing = self._seen.get(key)
        if existing is not None:
            existing["count"] += 1
            return
        if len(self.items) >= self._max:
            self.dropped += 1
            return
        item = {"type": event_type, "test": self.test_id, "step": self.step, "step_name": self.step_name,
                "count": 1, **fields}
        self._seen[key] = item
        self.items.append(item)
        self._emit(event_type, **{k: v for k, v in item.items() if k != "type"})

    def flag(self, category: str, message: str, severity: str = "info", **extra: Any) -> None:
        """Non-network review items raised by the runner itself (selector fallback, ignored error...)."""
        key = ("review_item", category, message[:200], self.step)
        if key in self._seen:
            self._seen[key]["count"] += 1
            return
        item = {"type": "review_item", "test": self.test_id, "step": self.step, "step_name": self.step_name,
                "count": 1, "category": category, "severity": severity, "message": message, **extra}
        self._seen[key] = item
        self.items.append(item)
        self._emit("review_item", **{k: v for k, v in item.items() if k != "type"})
