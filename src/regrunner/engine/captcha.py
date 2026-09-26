"""A captcha challenge on the page is a person's job: find it, so the test stops there instead of carrying on behind it.

Only a challenge that is on screen counts (reCAPTCHA / hCaptcha asking to pick pictures).  The v3 badge, an invisible captcha that let the
request through and the hidden copy of the challenge frame that is always in the page are not captchas that need anybody.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# The frame a captcha draws its challenge in.
CHALLENGE_FRAME = re.compile(r"/recaptcha/(?:api2|enterprise)/bframe|hcaptcha\.com/captcha/.*[#&?]frame=challenge", re.I)

# Run in the page that holds the challenge's <iframe>: big enough, not hidden by itself or any ancestor (reCAPTCHA hides the challenge with
# visibility / opacity and parks it at top: -10000px), and inside the window.
ON_SCREEN_JS = """el => {
  const r = el.getBoundingClientRect();
  if (r.width < 100 || r.height < 100) return false;
  for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
    const s = getComputedStyle(n);
    if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity) === 0) return false;
  }
  return r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth;
}"""

PROMPT = {"reCAPTCHA": ".rc-imageselect-desc-wrapper, .rc-imageselect-desc-no-canonical, .rc-imageselect-desc, .rc-audiochallenge-instructions",
          "hCaptcha": ".prompt-text"}
_TAIL = re.compile(r"\s*(?:Click verify|If there are none|Click skip).*", re.I | re.S)


@dataclass(frozen=True)
class Captcha:
    kind: str                                      # "reCAPTCHA" | "hCaptcha"
    prompt: str = ""                               # what it asks: "Select all images with a fire hydrant"
    page: Any = field(default=None, repr=False, compare=False)

    def asks(self) -> str:
        return f'{self.kind} is asking "{self.prompt}"' if self.prompt else f"{self.kind} is asking for a challenge to be solved"


async def _prompt(frame, kind: str) -> str:
    try:
        text = await frame.locator(PROMPT[kind]).first.inner_text(timeout=700)
    except Exception:
        return ""
    return " ".join(_TAIL.sub("", text).split())[:120]


async def find(pages) -> Captcha | None:
    """The first captcha challenge showing in any of ``pages`` (Playwright pages), else None.  Free when no page has a captcha frame."""
    for page in pages:
        if page.is_closed():
            continue
        for frame in page.frames:
            if not CHALLENGE_FRAME.search(frame.url or ""):
                continue
            try:
                shown = await (await frame.frame_element()).evaluate(ON_SCREEN_JS)
            except Exception:
                continue                                # navigating away, detached: not showing
            if shown:
                kind = "hCaptcha" if "hcaptcha" in frame.url.lower() else "reCAPTCHA"
                return Captcha(kind, await _prompt(frame, kind), page)
    return None
