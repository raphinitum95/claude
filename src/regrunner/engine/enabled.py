"""Playwright will not click what it calls "not enabled": a disabled control - or anything inside an element that says ``aria-disabled="true"``.

The legacy runner (Selenium) never looked at ``aria-disabled``.  The agent portal writes it into a text block whose links people click every
day, so a step that passed for years waits 30 s here and fails.  ``behaviour.click_ignores_aria_disabled`` (on by default) gives the legacy result
without giving up what a click is checked for: the element is still hovered first, and a hover checks that it is visible, standing still and not
covered - everything a click checks except "enabled".  A control that is really disabled (``disabled`` attribute, disabled fieldset) is still
waited for.

The JavaScript is shared with the failure capture, which names the element that makes Playwright say "not enabled".
"""
from __future__ import annotations

from typing import Any

ARIA = 'aria-disabled="true"'

# `short(node)`: "tag#id.class" - how an element is named in a note.
SHORT_JS = r"""const short = (n) => {
    if (!n || !n.tagName) return '';
    let s = n.tagName.toLowerCase();
    if (n.id) s += '#' + n.id;
    const cls = typeof n.className === 'string' ? n.className.trim().split(/\s+/).filter(Boolean).slice(0, 3) : [];
    if (cls.length) s += '.' + cls.join('.');
    if ((n.tagName === 'IFRAME' || n.tagName === 'FRAME') && n.name && n.name !== n.id) s += '[name=' + n.name + ']';
    return s;
  };"""

# `disabledBy(node)`: what makes Playwright call the element not enabled - a disabled control, a disabled fieldset around it, or aria-disabled="true"
# on it or anything around it (the nearest "false" wins) - as {node, kind}, or null.
DISABLED_BY_JS = r"""const disabledBy = (n) => {
    const tag = n.tagName;
    if (['BUTTON', 'INPUT', 'SELECT', 'TEXTAREA', 'OPTION', 'OPTGROUP'].includes(tag) && n.disabled) return {node: n, kind: 'disabled attribute'};
    if (['BUTTON', 'INPUT', 'SELECT', 'TEXTAREA'].includes(tag)) {
      for (let p = n.parentElement; p; p = p.parentElement) if (p.tagName === 'FIELDSET' && p.disabled) return {node: p, kind: 'a disabled fieldset around it'};
    }
    for (let p = n; p; p = p.parentElement || (p.getRootNode && p.getRootNode().host) || null) {
      const v = (p.getAttribute && p.getAttribute('aria-disabled') || '').toLowerCase();
      if (v === 'true') return {node: p, kind: 'aria-disabled="true"'};
      if (v === 'false') return null;
    }
    return null;
  };"""

# Only aria-disabled makes the element "not enabled" (no native disabled state), and it is an element Playwright applies aria-disabled to
# (a link, a button, a form field, or anything with a role).  Answers {desc, self} - who says so - or null.
ARIA_ONLY_JS = ("e => {\n  " + SHORT_JS + "\n  " + DISABLED_BY_JS + r"""
  if (!e.matches('a[href],area[href],button,input:not([type=hidden]),select,textarea,option,summary,[role]')) return null;
  const off = disabledBy(e);
  return off && off.kind === 'aria-disabled="true"' ? {desc: short(off.node), self: off.node === e} : null;
}""")


async def aria_disabled(res) -> dict[str, Any] | None:
    """``{desc, self}`` when the only thing keeping Playwright from clicking the element is ``aria-disabled="true"`` on it or around it, else None."""
    try:
        return await res.locator.evaluate(ARIA_ONLY_JS, timeout=1500)
    except Exception:
        return None


async def pointer(ctx, res, do: str = "click", **kwargs: Any) -> None:
    """``res.locator.<do>(...)`` (click, dblclick, ...) - going past ``aria-disabled`` like the legacy runner when ``behaviour.click_ignores_aria_disabled`` is on."""
    method, ms = getattr(res.locator, do), int(ctx.act_timeout_s * 1000)
    blocked = await aria_disabled(res) if ctx.cfg.behaviour.click_ignores_aria_disabled else None
    if blocked is None:
        await method(timeout=ms, **kwargs)
        return
    who = "the element" if blocked["self"] else f"<{blocked['desc']}>, which contains the element,"
    ctx.out.notes.append(f"{who} has {ARIA}: Playwright would wait for it to become enabled, the legacy runner did not look at it. Clicked anyway after checking "
                         "the element is visible, still and not covered (behaviour.click_ignores_aria_disabled).")
    await res.locator.hover(timeout=ms)                  # visible, stable, receives events: what a click checks, minus "enabled"
    await method(timeout=ms, force=True, **kwargs)
