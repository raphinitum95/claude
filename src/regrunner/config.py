"""Configuration: ``config.yaml`` (behaviour) + ``secrets.env`` / environment (secrets).

Nothing secret is ever stored in ``config.yaml``: values are written as ``${ENV_VAR}`` and expanded
from the process environment, which ``secrets.env`` (git-ignored) populates.  Tokens for the
workbook itself (e.g. ``DT_ZScalerUser``) come from environment variables named ``RR_VAR_<TOKEN>``.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

import yaml

from . import browsers


@dataclass
class RunnerCfg:
    workers: int = 3                 # concurrent tests (each in its own isolated browser context)
    max_workers: int = 8             # hard ceiling, protects a personal machine
    max_concurrent_runs: int = 1     # UI: runs started at the same time (tests already run in parallel inside one)
    allow_prod: bool = False         # PROD runs place real transactions: refused unless this (or --allow-prod) is set
    low_priority: bool = True        # lower OS scheduling priority of the runner and its browsers
    headless: bool = True            # headless never takes focus or keyboard from the user
    test_timeout_s: int = 1800       # safety net for one whole test
    step_hard_cap_s: int = 180       # safety net for one step
    stagger_s: float = 4.0           # workers start this far apart (worker 2 after 4 s, worker 3 after 8 s...): no synchronised burst of page loads
    min_page_load_gap_s: float = 1.0  # at least this long between the start of two page loads, across all tests (0 = off)
    block_statuses: list[int] = field(default_factory=lambda: [403, 429])   # answers that mean "the WAF is blocking us", not "the app said no"
    block_cooldown_s: float = 60     # after a block: no page loads for this long, and one worker fewer for the rest of the run
    block_retries: int = 2           # a test that was blocked is run again (after the cool-down) this many times; separate from behaviour.retries
    close_timeout_s: float = 15      # closing a window / the browser / Playwright may take this long, then the run moves on
    report_timeout_s: float = 300    # building the report may take this long, then the run finishes without it
    stop_after_failed_steps: int = 5  # a test stops after this many steps in a row that act on an element and could not find or use it (0 = never): the page is
                                      # not where the test expects, and every further step only waits out its timeout.  A step that works, or reads an element and
                                      # only differs from what was expected, starts the count again; Wait / Switch / key presses do not count either way


@dataclass
class BrowserCfg:
    type: str = "chromium"
    viewport_width: int = 1920       # same as the legacy headless window
    viewport_height: int = 1080
    locale: str = "en-US"
    timezone: str | None = None
    ignore_https_errors: bool = False
    user_agent: str | None = None
    args: list[str] = field(default_factory=list)
    name: str | None = None          # chrome | msedge | safari | chromium: the browser a run uses (the UI's Browser setting and --browser override it)
    channel: str | None = None       # older spelling of `name`: "chrome" or "msedge" = the Chrome / Edge already installed instead of the downloaded Chromium

    @property
    def auto(self) -> bool:
        """config.yaml names no browser (and nothing overrode it): the browser is whichever :func:`browsers.pick_default` finds."""
        return not (self.name or self.channel)

    @property
    def kind(self) -> browsers.Browser:
        """The browser this config selects: ``name``, else ``channel``, else the downloaded Chromium - or, on a computer that has none, the
        Chrome / Edge installed there."""
        return browsers.pick_default() if self.auto else browsers.resolve(self.name or self.channel)

    def launch_kwargs(self, headless: bool = True, args: bool = False) -> dict[str, Any]:
        """Options for ``<engine>.launch`` - every place that opens a browser goes through here, so the choice is honoured everywhere.
        ``args`` adds the Chromium command-line switches from config.yaml (only ever to a Chromium-based browser; WebKit has none)."""
        kind = self.kind
        opts: dict[str, Any] = {"headless": headless}
        if kind.channel:
            opts["channel"] = kind.channel
        elif kind.id == "chromium" and self.channel == "chromium":
            opts["channel"] = "chromium"                        # documented: full Chromium (new headless) instead of the headless shell
        if args and self.args and kind.engine == "chromium":
            opts["args"] = list(self.args)
        return opts

    async def launch(self, pw: Any, headless: bool = True, args: bool = True):
        """Start the selected browser (Chrome, Edge, WebKit for Safari, or the downloaded Chromium) on a running Playwright."""
        return await getattr(pw, self.kind.engine).launch(**self.launch_kwargs(headless, args))

    def chromium_family(self) -> list[browsers.Browser]:
        """Browsers for the jobs only a Chromium-based browser can do (the SSO sign-in window, the PDF export): the selected one when it is
        Chromium-based, else whichever of Chrome / Edge / Chromium is there."""
        kind = self.kind
        return [kind] if kind.engine == "chromium" else [browsers.CHROME, browsers.EDGE, browsers.CHROMIUM]

    async def launch_chromium_family(self, pw: Any, headless: bool = True):
        """Start the first of :meth:`chromium_family` that starts."""
        first_error: Exception | None = None
        for kind in self.chromium_family():
            opts: dict[str, Any] = {"headless": headless}
            if kind.channel:
                opts["channel"] = kind.channel
            try:
                return await pw.chromium.launch(**opts)
            except Exception as err:
                first_error = first_error or err
        raise first_error if first_error is not None else RuntimeError("no browser")


@dataclass
class TimeoutCfg:
    element_s: float = 10.0          # find + act on an element (legacy default was 5 s, existence only)
    optional_s: float = 3.0          # rows with Ignore_not_existing_object=Y
    optional_repeat_s: float = 0.5   # ...when the same optional element was already found absent earlier
    optional_mode: str = "quiet"     # quiet: absent once the page is quiet | full: always wait optional_s
    navigation_s: float = 60.0
    poll_ms: int = 100               # element polling interval (legacy: 1000)


@dataclass
class WaitCfg:
    mode: str = "smart"              # smart | legacy | off  (how `Wait` rows behave)
    quiet_ms: int = 400              # smart: DOM + network must be quiet this long
    min_s: float = 0.0               # smart: never return sooner than this
    cap_s: float | None = None       # smart: upper bound; default is the row's own seconds
    window_grace_s: float = 3.0      # SwitchToWindow -1: how long to wait for a popup nobody has seen yet
    ready_max_s: float = 6.0         # before the first click / typing on a freshly loaded page: wait up to this long for it to finish loading (0 = off)
    ready_quiet_ms: int = 1000       # ...i.e. document fully loaded, no requests and no DOM changes for this long
    input_settle_max_s: float = 15.0  # after typing / a key press: wait up to this long for the server calls it started (a zip check...) to return; 0 = off
    input_call_grace_ms: int = 300   # ...and how long to watch for such a call to start after a key press (a check may be debounced)
    call_url_patterns: list[str] = field(default_factory=lambda: ["/bin/"])   # regexes: a first-party XHR/fetch whose URL matches one is a servlet call (AEM: /bin/...); empty = every first-party call
    call_ignore_patterns: list[str] = field(default_factory=list)  # regexes: first-party URLs never waited for (analytics pings, polling...)
    nav_grace_ms: int = 400          # after a click that may navigate: how long to watch for a page load to *start* (a JS click returns before it does)


@dataclass
class OutputCfg:
    match_timeout_s: float = 8.0     # Output with Exact_Match/Contains retries this long for the expected text
    stable_ms: int = 150             # capture-only Output waits for text to stop changing this long
    stable_max_ms: int = 1500
    legacy_text: bool = True         # Selenium-compatible text: hidden -> "", NBSP -> space, trimmed


@dataclass
class ScreenshotCfg:
    mode: str = "every_step"         # every_step | on_failure | off
    quality: int = 60                # JPEG quality
    full_page: bool = False


@dataclass
class SelectorCfg:
    map: str = "selectors.yaml"
    legacy_fallback: bool = True     # keep the sheet's XPath as the last resort
    harvest: bool = False            # record id/name/etc. of every element touched (feeds `selectors harvest`)
    warn_on_fallback: bool = True    # review item when a generic locator missed and the XPath was needed


@dataclass
class CaptchaCfg:
    cookie_name: str = "recaptchaBypassToken"
    values: dict[str, str] = field(default_factory=dict)   # QA/UAT/PROD -> value ("${ENV_VAR}")
    extra_domains: list[str] = field(default_factory=list)
    same_site: str = "None"          # None|Lax|Strict ("None" also works inside cross-site iframes)


@dataclass
class AuthCfg:
    storage_state: str = ".auth/state.json"          # created by `regrunner auth login` (or the UI's "Sign in")
    detect_selectors: list[str] = field(default_factory=lambda: ["#okta-signin-username"])
    login_url: str = ""                              # pre-fills the UI's sign-in dialog (else the workbook's first URL)
    headless: bool = False                           # sign-in needs a visible window; true only for automated tests


@dataclass
class FailureCaptureCfg:
    """What is kept when a step fails, so the run itself says *why* (a click that timed out, an element that was not there)."""
    enabled: bool = True             # the full browser error, what covers the element, how many matches each frame has, the state of the frames
    dom_snapshot: bool = True        # also save the page's and the frame's HTML next to the screenshots (tests/<test>/dom/)
    dom_max_kb: int = 1024           # a snapshot bigger than this is cut
    dom_max_per_test: int = 3        # snapshots are kept for the first few failures of a test only (the rest is usually the same page)
    budget_s: float = 8.0            # gathering it never holds a run up longer than this
    full_page_screenshot: bool = True    # a failed step also gets a screenshot of the whole page (the viewport one misses what is below the fold)
    full_page_max_per_test: int = 10     # ... for the first this many failures of a test (a cascade of failures shows the same page)


@dataclass
class ReviewCfg:
    ignore_url_patterns: list[str] = field(default_factory=list)
    ignore_message_patterns: list[str] = field(default_factory=list)
    max_items_per_test: int = 500


@dataclass
class ReportCfg:
    html: bool = True
    pdf: bool = False
    screenshots: str = "all"         # all | failures | none  (embedded in the self-contained report)


@dataclass
class ApiCfg:
    """API (web service) tests: the ``WEBSERVICE_URL`` sheets of a workbook."""
    timeout_s: float = 60
    templates_dir: str = ""                  # where request templates (JSON bodies) are looked for when the workbook's own path (L:\\...) is not there;
                                             # empty = the RR_API_TEMPLATES_DIR variable of secrets.env, then the folder beside the workbook
    ignore_https_errors: bool | None = None   # None = follow browser.ignore_https_errors
    proxy: str = ""                          # e.g. http://proxy.example:8080 when API calls must go through one


@dataclass
class AskCfg:
    """The ASK_USER step: the run stops and asks a person (on the run screen, or in the terminal)."""
    timeout_s: float = 300                   # how long a question waits for its answer (the step's Timeout column overrides it); then the step fails


@dataclass
class CaptchaWatchCfg:
    """A captcha challenge on the page (reCAPTCHA / hCaptcha asking to pick pictures) is a person's job: the test stops there instead of carrying on behind it."""
    detect: bool = True                      # look for a challenge after every step
    solve: str = "ask"                       # ask: when someone can answer (a run started from the web UI or a terminal) a browser window opens and the
                                             #      test carries on once they have solved it | fail: the test just ends with the reason
    timeout_s: float = 300                   # how long the window waits for the captcha to be solved
    headless: bool = False                   # the solving window has to be visible: true only for automated tests


@dataclass
class PublishCfg:
    """A second, shared copy of every finished run: the report and a pass/fail summary (not the screenshots folder)."""
    dir: str = ""                    # e.g. /Volumes/QA-Share/regression-runs  or  '\\server\share\regression-runs'; empty = off
    screenshots: str = "failures"    # in the shared report.html: failures (only failed steps) | all | none
    timeout_s: float = 60            # copying may take this long, then the run finishes anyway (the local copy is untouched)


@dataclass
class BehaviourCfg:
    unknown_action: str = "warn"     # warn (existence check, like legacy) | fail
    missing_frame: str = "continue"  # continue = stay in the current document (legacy: silent) | fail
    dialogs: str = "dismiss"         # dismiss | accept   (what to do with alert/confirm no step consumed)
    click_ignores_aria_disabled: bool = True   # Click/Tick/... on an element that only aria-disabled="true" (on it or around it) marks disabled: the legacy runner (Selenium)
                                               # clicked it, Playwright waits for it to be "enabled" and times out; true = click like the legacy runner (still checks it is visible, still, not covered)
    click_before_typing: bool = True  # Set / Write / Type click into the field first, like a person: some sites only clear a field's error
                                      # message on click and skip re-validating while it shows (Owner_CRVD: invalid zip, then valid zip)
    retries: int = 0                 # re-run a failed test this many times (attempts are all recorded)


@dataclass
class Config:
    runner: RunnerCfg = field(default_factory=RunnerCfg)
    browser: BrowserCfg = field(default_factory=BrowserCfg)
    timeouts: TimeoutCfg = field(default_factory=TimeoutCfg)
    waits: WaitCfg = field(default_factory=WaitCfg)
    output: OutputCfg = field(default_factory=OutputCfg)
    screenshots: ScreenshotCfg = field(default_factory=ScreenshotCfg)
    selectors: SelectorCfg = field(default_factory=SelectorCfg)
    failure_capture: FailureCaptureCfg = field(default_factory=FailureCaptureCfg)
    captcha_bypass: CaptchaCfg = field(default_factory=CaptchaCfg)
    auth: AuthCfg = field(default_factory=AuthCfg)
    review: ReviewCfg = field(default_factory=ReviewCfg)
    reports: ReportCfg = field(default_factory=ReportCfg)
    publish: PublishCfg = field(default_factory=PublishCfg)
    api: ApiCfg = field(default_factory=ApiCfg)
    ask: AskCfg = field(default_factory=AskCfg)
    captcha: CaptchaWatchCfg = field(default_factory=CaptchaWatchCfg)
    behaviour: BehaviourCfg = field(default_factory=BehaviourCfg)
    tags: dict[str, list[str]] = field(default_factory=dict)      # tag -> test ids (workbook has no tags)
    chains: dict[str, list[list[str]]] = field(default_factory=dict)   # workbook file name (or *) -> ordered test ids that run one after another
    runs_dir: str = "runs"
    workbooks_dir: str = "workbooks"
    base_dir: Path = field(default_factory=Path.cwd)

    # -- helpers -------------------------------------------------------------------------------
    def path(self, value: str) -> Path:
        p = Path(value).expanduser()                  # "~/QA" works
        return p if p.is_absolute() else self.base_dir / p

    @property
    def effective_workers(self) -> int:
        return max(1, min(self.runner.workers, self.runner.max_workers))

    def bypass_token(self, environment: str) -> str:
        env = (environment or "").upper()
        for key, value in self.captcha_bypass.values.items():
            if key.upper() == env:
                return value or ""
        return ""

    def public(self) -> dict[str, Any]:
        """Config as a dict with secret values masked (for run metadata / the UI)."""
        data = _to_dict(self)
        data.pop("base_dir", None)
        data["captcha_bypass"]["values"] = {k: ("set" if v else "missing")
                                            for k, v in self.captcha_bypass.values.items()}
        return data


def _to_dict(obj: Any) -> Any:
    if is_dataclass(obj):
        return {f.name: _to_dict(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_dict(v) for v in obj]
    if isinstance(obj, Path):
        return str(obj)
    return obj


def _merge(target: Any, data: dict[str, Any], where: str = "") -> None:
    known = {f.name: f for f in fields(target)}
    for key, value in data.items():
        if key not in known:
            raise ValueError(f"Unknown config key: {where}{key}")
        current = getattr(target, key)
        if is_dataclass(current) and isinstance(value, dict):
            _merge(current, value, f"{where}{key}.")
        else:
            setattr(target, key, value)


_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV_REF.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), value)
    if isinstance(value, dict):
        return {k: expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env(v) for v in value]
    return value


_FROM_FILE: set[str] = set()      # variables this process took from secrets.env (so edits can refresh them)


def load_env_file(path: Path) -> dict[str, str]:
    """Parse ``KEY=value`` lines; variables set by the real environment win (12-factor style).

    Values that came from this file in an earlier call are refreshed, so editing ``secrets.env`` while
    the web UI is running takes effect on the next run without a restart.
    """
    loaded: dict[str, str] = {}
    parsed: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip():
                parsed[key.strip()] = value.strip().strip('"').strip("'")
    for key in list(_FROM_FILE):                       # a line deleted from the file stops applying
        if key not in parsed:
            os.environ.pop(key, None)
            _FROM_FILE.discard(key)
    for key, value in parsed.items():
        if key not in os.environ or key in _FROM_FILE:
            os.environ[key] = value
            _FROM_FILE.add(key)
        loaded[key] = os.environ.get(key, value)
    return loaded


def workbook_secrets() -> dict[str, str]:
    """Workbook tokens supplied via ``RR_VAR_<TOKEN>`` environment variables (never via Excel)."""
    prefix = "RR_VAR_"
    return {k[len(prefix):].upper(): v for k, v in os.environ.items() if k.startswith(prefix) and v}


def load_config(path: str | Path | None = None, base_dir: str | Path | None = None) -> Config:
    base = Path(base_dir) if base_dir else (Path(path).resolve().parent if path else Path.cwd())
    cfg = Config(base_dir=base)
    load_env_file(base / "secrets.env")
    cfg_path = Path(path) if path else base / "config.yaml"
    if cfg_path.is_file():
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        _merge(cfg, expand_env(raw))
    try:
        cfg.browser.kind
    except browsers.BrowserError as err:
        raise ValueError(f"config.yaml, browser: {err}") from err
    return cfg
