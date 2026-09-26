"""The browsers a run can use, and the record of which one it did use.

Four choices, all driven through Playwright:

* ``chrome`` / ``msedge``: the Google Chrome / Microsoft Edge installed on this computer (Playwright "channels").
* ``safari``: Playwright's **WebKit** build.  WebKit is the engine Safari is made of, but Playwright cannot drive the Safari
  application itself, so this is Safari's engine, not Safari.app.  It is labelled that way everywhere a person reads it,
  because a report that says "Safari" when it was not would defeat the point of recording the browser.
* ``chromium``: the Chromium Playwright downloads (what a bare config.yaml uses).

Every place that opens a browser goes through :class:`regrunner.config.BrowserCfg`, which asks this module which one.
"""
from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CLOSE_TIMEOUT_S = 15.0
_PROBE_TTL_S = 120.0


class BrowserError(ValueError):
    """An unknown browser name."""


class BrowserUnavailable(Exception):
    """The chosen browser cannot start here.  The message says why and what to do about it (and which browsers this computer does have)."""

    def __init__(self, browser: "Browser", reason: str, others: tuple[str, ...] | list[str] = ()):
        super().__init__(unavailable_message(browser, reason, others))
        self.browser, self.reason = browser, reason


@dataclass(frozen=True)
class Browser:
    id: str                  # the value used in config.yaml, on the command line and in the UI
    label: str               # what a person reads: "Google Chrome"
    short: str               # for chips: "Chrome"
    engine: str              # the Playwright browser type: chromium | webkit
    channel: str | None      # Playwright channel: an installed browser rather than a downloaded build
    engine_label: str        # "Chromium" | "WebKit"
    approximate: bool        # the engine Safari is built on, not the application itself
    what: str                # one honest sentence about what actually runs
    download: str | None     # `playwright install <this>` for builds Playwright downloads

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "short": self.short, "engine": self.engine, "engine_label": self.engine_label,
                "approximate": self.approximate, "what": self.what}


CHROME = Browser("chrome", "Google Chrome", "Chrome", "chromium", "chrome", "Chromium", False,
                 "The Google Chrome installed on this computer.", None)
EDGE = Browser("msedge", "Microsoft Edge", "Edge", "chromium", "msedge", "Chromium", False,
               "The Microsoft Edge installed on this computer.", None)
SAFARI = Browser("safari", "Safari (WebKit)", "Safari", "webkit", None, "WebKit", True,
                 "WebKit, the engine Safari is built on, in the build Playwright downloads. Playwright cannot drive the Safari "
                 "application itself, so this is Safari's engine and not Safari.app.", "webkit")
CHROMIUM = Browser("chromium", "Chromium", "Chromium", "chromium", None, "Chromium", False,
                   "The Chromium build Playwright downloads. It is not one of the browsers installed on this computer.", "chromium")

ORDER = (CHROME, EDGE, SAFARI, CHROMIUM)          # the order the UI offers them in
DEFAULT = CHROMIUM                                # what a config.yaml with no browser line has always used
BY_ID = {b.id: b for b in ORDER}
_ALIASES = {"google-chrome": "chrome", "googlechrome": "chrome", "edge": "msedge", "microsoft-edge": "msedge", "microsoftedge": "msedge",
            "webkit": "safari", "playwright-webkit": "safari"}


def choices() -> list[str]:
    return [b.id for b in ORDER]


def resolve(name: str | None) -> Browser:
    """``chrome`` / ``msedge`` / ``safari`` / ``chromium`` (and a few spellings of them) -> the browser.  Empty means the default."""
    key = str(name or "").strip().lower().replace("_", "-").replace(" ", "-")
    if not key:
        return DEFAULT
    key = _ALIASES.get(key, key)
    if key in BY_ID:
        return BY_ID[key]
    raise BrowserError(f"Unknown browser {name!r}. Choose one of: {', '.join(choices())}.")


# -- where an installed Chrome / Edge lives (the places Playwright itself looks) --------------------------------------
_CHANNEL_PATHS = {
    "chrome": {"linux": ["/opt/google/chrome/chrome"], "darwin": ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"],
               "win32": ["Google\\Chrome\\Application\\chrome.exe"]},
    "msedge": {"linux": ["/opt/microsoft/msedge/msedge"], "darwin": ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"],
               "win32": ["Microsoft\\Edge\\Application\\msedge.exe"]},
}


def platform_key() -> str:
    return "win32" if sys.platform == "win32" else ("darwin" if sys.platform == "darwin" else "linux")


def executable_candidates(browser: Browser) -> list[Path]:
    """Where Playwright looks for an installed Chrome / Edge on this OS (empty for browsers Playwright downloads)."""
    table = _CHANNEL_PATHS.get(browser.channel or "")
    if not table:
        return []
    key = platform_key()
    if key != "win32":
        return [Path(p) for p in table[key]]
    roots = [os.environ.get(k) for k in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)")]
    drive = os.environ.get("HOMEDRIVE")                                   # Playwright also looks here when the variables above are missing
    if drive:
        roots += [drive + "\\Program Files", drive + "\\Program Files (x86)"]
    return [Path(root) / rel for root in roots if root for rel in table["win32"]]


def installed_executable(browser: Browser) -> Path | None:
    return next((p for p in executable_candidates(browser) if p.exists()), None)


def _registry_dir() -> Path:
    """Where Playwright keeps the browsers it downloads (the same rules Playwright itself uses)."""
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env == "0":
        import playwright
        return Path(playwright.__file__).parent / "driver" / "package" / ".local-browsers"
    if env:
        return Path(env) if os.path.isabs(env) else Path.cwd() / env
    key = platform_key()
    if key == "linux":
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    elif key == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return base / "ms-playwright"


def _revision(name: str) -> str | None:
    import json
    import playwright
    try:
        listing = json.loads((Path(playwright.__file__).parent / "driver" / "package" / "browsers.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return next((str(b["revision"]) for b in listing.get("browsers", []) if b.get("name") == name), None)


_DOWNLOADED_AS = {"chromium": ("chromium", "chromium-headless-shell"), "webkit": ("webkit",)}     # what `playwright install <x>` puts in the cache


def downloaded(browser: Browser) -> bool:
    """Has Playwright downloaded this browser (Chromium, WebKit)?  Looks at the files only: nothing is started, so it is instant."""
    parts = _DOWNLOADED_AS.get(browser.download or "")
    if not parts:
        return False
    root = _registry_dir()
    for part in parts:
        revision = _revision(part)
        if revision is None or not (root / f"{part.replace('-', '_')}-{revision}" / "INSTALLATION_COMPLETE").is_file():
            return False
    return True


def pick_default() -> Browser:
    """The browser to use when nothing names one: the downloaded Chromium (what this has always meant), else the Chrome / Edge installed here,
    so a computer that cannot download Chromium works without anyone editing config.yaml.  Nothing else ever falls back: a browser that was
    asked for (config.yaml, --browser, the UI) and cannot start says so."""
    if downloaded(CHROMIUM):
        return CHROMIUM
    return next((b for b in (CHROME, EDGE) if installed_executable(b)), CHROMIUM)


def install_command(name: str = "chromium") -> str:
    """The exact command that downloads a Playwright browser for *this* Python - it works without activating the venv."""
    exe = sys.executable
    quoted = subprocess.list2cmdline([exe]) if os.name == "nt" else shlex.quote(exe)
    return f"{quoted} -m playwright install {name}"


def first_line(err: BaseException | str) -> str:
    return (str(err).strip().splitlines() or [type(err).__name__ if isinstance(err, BaseException) else ""])[0][:300]


def unavailable_message(browser: Browser, reason: str, others: tuple[str, ...] | list[str] = ()) -> str:
    """Why this browser cannot start and the one thing to do about it; the last words are the command to run (when there is one).
    ``others`` names the browsers this computer does have."""
    instead = f" Available on this computer instead: {', '.join(others)} (choose one under Browser)." if others else ""
    if browser.channel:
        if not installed_executable(browser):
            where = executable_candidates(browser)
            spot = f" (Playwright looks for it at {where[0]})" if where else ""
            return f"{browser.label} is not installed on this computer{spot}. Install it, or choose another browser.{instead}"
        return f"{browser.label} is installed but did not start: {reason}.{instead}"
    if browser.download:
        cmd = install_command(browser.download)
        if "doesn't exist" in reason or "playwright install" in reason.lower():          # Playwright's own words for "never downloaded"
            return f"{browser.label} is not downloaded on this computer yet.{instead} It can be downloaded once, if your network allows it. Run: {cmd}"
        return f"{browser.label} did not start: {reason}.{instead} If Playwright has not downloaded it yet, run: {cmd}"
    return f"{browser.label} did not start: {reason}.{instead}"


# -- the record of which browser ran ------------------------------------------------------------------------------------
def text_of(browser: Browser, version: str = "") -> str:
    """The one line a person reads: "Google Chrome 141.0.7390.55", "Safari (WebKit 26.6)"."""
    if browser.approximate:
        return f"{browser.short} ({browser.engine_label} {version})" if version else browser.label
    return f"{browser.label} {version}".strip()


def identity(browser: Browser, *, version: str = "", headless: bool = True, user_agent: str = "", recorded: bool = True) -> dict[str, Any]:
    """What a run stores about its browser (run.json, results.json, the event log, the report)."""
    return {**browser.as_dict(), "version": version, "headless": headless, "user_agent": user_agent,
            "text": text_of(browser, version), "recorded": recorded}


def no_browser(headless: bool = True) -> dict[str, Any]:
    """The record of a run that only has API tests: nothing opened a browser."""
    return {"id": "none", "label": "No browser", "short": "None", "engine": "", "engine_label": "", "approximate": False,
            "what": "Only API tests ran, so no browser was opened.", "version": "", "headless": headless, "user_agent": "",
            "text": "No browser (API tests only)", "recorded": True}


def not_recorded() -> dict[str, Any]:
    """A run that neither recorded its browser nor kept the settings it ran with: nothing to say, and nothing is guessed."""
    return {"id": "unknown", "label": "Browser not recorded", "short": "", "engine": "", "engine_label": "", "approximate": False,
            "what": "This run did not record which browser it used.", "version": "", "headless": True, "user_agent": "",
            "text": "Not recorded", "recorded": False}


def identity_from_config(browser_cfg: dict[str, Any] | None, headless: bool = True) -> dict[str, Any]:
    """Runs made before the browser was recorded: what their saved config says it would have used (the version is unknown)."""
    cfg = browser_cfg or {}
    try:
        kind = resolve(cfg.get("name") or cfg.get("channel"))
    except BrowserError:
        kind = DEFAULT
    return identity(kind, headless=headless, recorded=False)


def identity_of(data: dict[str, Any] | None) -> dict[str, Any]:
    """The browser of a run from its results.json / run.json: the recorded one, else worked out from the config it saved (version unknown),
    else "not recorded" - a run that kept neither is never assumed to have used the default."""
    data = data or {}
    recorded = data.get("browser")
    if isinstance(recorded, dict) and recorded.get("id"):
        return recorded
    saved = (data.get("config") or {}).get("browser")
    if not isinstance(saved, dict):
        return not_recorded()
    headless = (data.get("params") or {}).get("headless")
    if headless is None:
        headless = ((data.get("config") or {}).get("runner") or {}).get("headless", True)
    return identity_from_config(saved, headless=headless is not False)


# -- starting one --------------------------------------------------------------------------------------------------------
_probe_cache: dict[tuple[str, bool], tuple[float, dict[str, str]]] = {}


async def probe(browser: Browser, *, headless: bool = True, timeout_s: float = 60.0, cached: bool = False) -> dict[str, str]:
    """Start the browser, read its version and user agent, close it.  Raises BrowserUnavailable (with advice) if it cannot start.

    ``cached`` reuses an answer from the last two minutes (a process that starts many runs, such as the test suite, does not re-probe).
    """
    key = (browser.id, headless)
    hit = _probe_cache.get(key)
    if cached and hit is not None and time.monotonic() - hit[0] < _PROBE_TTL_S:
        return hit[1]
    from playwright.async_api import async_playwright
    pw = launched = None
    try:
        pw = await asyncio.wait_for(async_playwright().start(), timeout_s)
        opts: dict[str, Any] = {"headless": headless}
        if browser.channel:
            opts["channel"] = browser.channel
        launched = await asyncio.wait_for(getattr(pw, browser.engine).launch(**opts), timeout_s)
        found = {"version": str(launched.version), "user_agent": ""}
        try:
            page = await launched.new_page()
            found["user_agent"] = str(await page.evaluate("navigator.userAgent"))
        except Exception:
            pass                                          # the version is the part that matters
        _probe_cache[key] = (time.monotonic(), found)
        return found
    except asyncio.TimeoutError as err:
        raise BrowserUnavailable(browser, f"it did not start within {timeout_s:g} s") from err
    except Exception as err:
        raise BrowserUnavailable(browser, first_line(err)) from err
    finally:
        if launched is not None:
            try:
                await asyncio.wait_for(launched.close(), CLOSE_TIMEOUT_S)
            except Exception:
                pass
        if pw is not None:
            try:
                await asyncio.wait_for(pw.stop(), CLOSE_TIMEOUT_S)
            except Exception:
                pass
