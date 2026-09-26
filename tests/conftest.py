from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from regrunner.config import Config  # noqa: E402
from tests.site import server as mock_server  # noqa: E402


@pytest.fixture(scope="session")
def site():
    srv, url = mock_server.start()
    yield url
    srv.shutdown()


@pytest.fixture
def make_cfg(tmp_path):
    def factory(**overrides) -> Config:
        cfg = Config(base_dir=tmp_path)
        cfg.runs_dir = "runs"
        cfg.runner.workers = 3
        cfg.timeouts.element_s = 6
        cfg.timeouts.optional_s = 1.5
        cfg.timeouts.optional_repeat_s = 0.3
        cfg.output.match_timeout_s = 3
        cfg.output.stable_ms = 300
        cfg.waits.quiet_ms = 400
        cfg.screenshots.quality = 40
        cfg.captcha_bypass.values = {"UAT": "TEST-UAT-TOKEN", "QA": "TEST-QA-TOKEN"}
        cfg.selectors.map = "selectors.yaml"
        cfg.reports.pdf = False
        for dotted, value in overrides.items():
            section, _, key = dotted.partition(".")
            setattr(getattr(cfg, section), key, value) if key else setattr(cfg, section, value)
        return cfg
    return factory


@pytest.fixture(autouse=True)
def _no_codes_handed_out():
    """Codes are single-use per secret (``totp.reserve_window``); what one test took must not make another one wait."""
    from regrunner import totp
    totp._taken.clear()
    totp._gaps.clear()
    yield
    totp._taken.clear()
    totp._gaps.clear()
