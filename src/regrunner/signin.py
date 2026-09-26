"""One-time interactive sign-in (Zscaler / Okta SSO), saved as a Playwright storage state.

A single *visible* browser window is opened for the person to sign in themselves - nothing is typed for
them and nothing they type is seen.  The resulting session (cookies + local storage) is written to
``auth.storage_state`` with owner-only permissions and reused by every headless test.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from urllib.parse import urlparse

from .config import Config

IDLE_LIMIT_S = 15 * 60          # an abandoned sign-in window closes itself


class SignInError(RuntimeError):
    pass


def validate_url(url: str) -> str:
    url = (url or "").strip()
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise SignInError("Enter a full web address that starts with http:// or https://")
    return url


class SignInSession:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.url = ""
        self.opened_at = 0.0
        self._pw = None
        self._browser = None
        self._context = None

    @property
    def is_open(self) -> bool:
        return self._browser is not None and self._browser.is_connected() and time.monotonic() - self.opened_at < IDLE_LIMIT_S

    async def open(self, url: str) -> None:
        from playwright.async_api import async_playwright
        self.url = validate_url(url)
        await self.close()
        self._pw = await async_playwright().start()
        try:
            self._browser = await self.cfg.browser.launch_chromium_family(self._pw, self.cfg.auth.headless)
            self._context = await self._browser.new_context(viewport=None)
            page = await self._context.new_page()
        except Exception as err:
            await self.close()
            raise SignInError(f"Could not open a browser window: {(str(err).splitlines() or [err])[0]}") from err
        self.opened_at = time.monotonic()
        try:
            await page.goto(self.url, wait_until="commit", timeout=30000)
        except Exception:
            pass                                         # leave the window open: the person may fix the page themselves

    async def save(self) -> Path:
        if not self.is_open or self._context is None:
            raise SignInError("The sign-in window is not open any more. Open it again and sign in.")
        target = self.cfg.path(self.cfg.auth.storage_state)
        target.parent.mkdir(parents=True, exist_ok=True)
        await self._context.storage_state(path=str(target))
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
        await self.close()
        return target

    async def close(self) -> None:
        browser, pw = self._browser, self._pw
        self._browser = self._context = self._pw = None
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
        if pw is not None:
            try:
                await pw.stop()
            except Exception:
                pass
