"""Installation / configuration checks, shared by ``regrunner doctor`` and the web UI's Preflight card.

Nothing here opens a visible window or touches a site: the browser probe launches the chosen browser headless and
closes it again.  Token *values* are never returned - only whether one is set.
"""
from __future__ import annotations

import asyncio
import os
import platform
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from . import browsers
from .config import Config, workbook_secrets

ENVIRONMENTS = ("QA", "UAT", "PROD")
_BROWSER_CACHE: dict[str, tuple[float, "Check"]] = {}          # browser id -> (when, its launch check)
_CACHE_TTL_S = 300


@dataclass
class Check:
    id: str
    status: str                 # ok | warn | err
    label: str
    detail: str
    action: str = ""            # a UI hint ("sign_in"), empty when there is nothing to do
    data: dict = field(default_factory=dict)      # facts a UI can use (the browser check: which browser, its version, the line to show)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def install_command(name: str = "chromium") -> str:
    """The exact command that downloads a Playwright browser for *this* Python - it works without activating the venv."""
    return browsers.install_command(name)


async def installed_map(deep: bool = False) -> dict[str, bool]:
    """Which of the browsers are on this computer: Chrome / Edge where Playwright looks for them, the downloaded builds where Playwright puts them.
    Looks at files only (nothing is started); the same answer :func:`browsers.pick_default` uses to choose a default."""
    return {b.id: bool(browsers.installed_executable(b)) if b.channel else browsers.downloaded(b) for b in browsers.ORDER}


async def browser_check(deep: bool = False, browser: str | None = None) -> Check:
    """Can this browser launch headless?  Cached for a few minutes unless ``deep`` (an explicit "run doctor").

    ``browser`` is an id (chrome / msedge / safari / chromium); empty is the downloaded Chromium.  When it cannot start, the message says
    what to install, and which of the other browsers this computer does have.
    """
    kind = browsers.resolve(browser)
    cached = _BROWSER_CACHE.get(kind.id)
    if cached is not None and not deep and time.monotonic() - cached[0] < _CACHE_TTL_S:
        return cached[1]
    try:
        found = await browsers.probe(kind)
        text = browsers.text_of(kind, found["version"])
        check = Check("browser", "ok", kind.label, f"{text} launches headless. No window will open.",
                      data={"id": kind.id, "text": text, "version": found["version"]})
    except browsers.BrowserUnavailable as err:
        have = await installed_map(deep)
        others = [b.label for b in browsers.ORDER if b is not kind and have.get(b.id)]
        check = Check("browser", "err", kind.label, browsers.unavailable_message(kind, err.reason, others), data={"id": kind.id})
    _BROWSER_CACHE[kind.id] = (time.monotonic(), check)
    return check


async def browser_options(cfg: Config, selected: str | None = None, deep: bool = False) -> list[dict[str, Any]]:
    """The browsers the UI offers, each with whether it is on this computer and what to do when it is not."""
    have = await installed_map(deep)
    chosen = browsers.resolve(selected).id if selected else cfg.browser.kind.id
    out = []
    for b in browsers.ORDER:
        if b.channel:
            detail = "" if have.get(b.id) else f"{b.label} is not installed on this computer."
        else:
            detail = "" if have.get(b.id) else f"Not downloaded yet; it can be downloaded once, if your network allows it. Run: {install_command(b.download or b.id)}"
        out.append({**b.as_dict(), "installed": bool(have.get(b.id)), "detail": detail, "selected": b.id == chosen,
                    "configured": b.id == cfg.browser.kind.id})
    return out


def token_state(cfg: Config) -> dict[str, bool]:
    return {env: bool(cfg.bypass_token(env)) for env in ENVIRONMENTS}


def sso_state(cfg: Config) -> dict[str, Any]:
    path = cfg.path(cfg.auth.storage_state)
    present = path.is_file()
    return {"present": present, "path": str(path), "display": cfg.auth.storage_state,
            "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds") if present else None}


def folder_checks(cfg: Config) -> list[Check]:
    out = []
    for label, value in (("workbooks", cfg.workbooks_dir), ("runs", cfg.runs_dir)):
        path = cfg.path(value)
        try:
            path.mkdir(parents=True, exist_ok=True)
            writable = os.access(path, os.W_OK)
        except OSError:
            writable = False
        out.append(Check(f"folder_{label}", "ok" if writable else "err", f"{label}/ folder",
                         f"{path} is writable." if writable else f"{path} is not writable."))
    return out


async def run_preflight(cfg: Config, *, deep: bool = False, browser: str | None = None) -> dict[str, Any]:
    """Every check, structured.  ``checks`` is what ``doctor`` prints; the rest lets the UI compose its card.

    ``browser`` is the one the person picked in the UI (else the one config.yaml selects): its launch is the check that can block a run."""
    checks: list[Check] = []
    checks.append(Check("python", "ok" if sys.version_info >= (3, 9) else "err", "Python",
                        f"Python {platform.python_version()}"))
    chosen = browsers.resolve(browser) if browser else cfg.browser.kind
    launch = await browser_check(deep, chosen.id)
    checks.append(launch)
    options = await browser_options(cfg, chosen.id, deep)
    checks.append(Check("browsers", "ok", "Browsers on this computer",
                        "; ".join(f"{o['label']}: {'installed' if o['installed'] else 'not available'}" for o in options)
                        + f". Runs use {chosen.label} (--browser chrome | msedge | safari | chromium changes it for one run)."
                        + (f" config.yaml names no browser and Chromium is not downloaded here, so the installed {cfg.browser.kind.label} is used."
                           if cfg.browser.auto and cfg.browser.kind is not browsers.CHROMIUM else "")))
    cpus = os.cpu_count() or 1
    workers = cfg.effective_workers
    checks.append(Check("workers", "ok" if workers <= max(cpus - 1, 1) else "warn", "Workers",
                        f"{workers} worker(s) on {cpus} CPUs"
                        + ("" if workers <= max(cpus - 1, 1) else " - leaves little for you; consider fewer")))
    tokens = token_state(cfg)
    for env in ENVIRONMENTS:
        checks.append(Check(f"token_{env}", "ok" if tokens[env] else "warn",
                            f"{cfg.captcha_bypass.cookie_name} - {env}",
                            "Set in secrets.env." if tokens[env]
                            else f"Not set. Add RECAPTCHA_BYPASS_TOKEN_{env} to secrets.env."))
    sso = sso_state(cfg)
    checks.append(Check("sso", "ok" if sso["present"] else "warn", "SSO session (Zscaler / Okta)",
                        f"Saved session at {sso['path']}." if sso["present"]
                        else f"No saved session at {cfg.auth.storage_state}. Sign in once and every headless test reuses it.",
                        "" if sso["present"] else "sign_in"))
    checks.append(Check("workbook_secrets", "ok", "Workbook secrets (RR_VAR_*)", f"{len(workbook_secrets())} defined"))
    checks.extend(folder_checks(cfg))
    from .publish import publish_status
    shared = await publish_status(cfg)
    if shared:
        checks.append(Check(shared["id"], shared["status"], shared["label"], shared["detail"]))
    counts = {s: sum(c.status == s for c in checks) for s in ("ok", "warn", "err")}
    return {"checks": [c.as_dict() for c in checks], "counts": counts, "tokens": tokens, "sso": sso,
            "browser": launch.as_dict(), "browsers": options, "folders": [c.as_dict() for c in folder_checks(cfg)], "publish": shared}
