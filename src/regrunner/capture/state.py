"""What the page held after a step: its form fields, storage and cookie names (``capture.state``), so a value that went missing 40 steps before
anything failed can be found in the run folder.  Read-only: it looks at the page, never touches it, and never decides pass or fail.

``STATE_JS`` runs inside a page (or a first-party frame) and returns what is there; ``flatten`` turns the answers of the frames into one
snapshot; ``StateTracker`` turns a snapshot into the line written to ``tests/<test>/state.jsonl`` (the first look at a page in full, then only what
changed) and into the warnings the Results screens show ("a disabled field with nothing in it").  All of it is plain data, so it is unit-tested
without a browser (tests/test_session_capture.py).  Passwords, one-time codes, card numbers and secret-looking storage are never recorded as text:
the JS says ``(hidden)`` for a field that has one, and the test runner masks the run's own secrets over each line before it is written.
"""
from __future__ import annotations

import re
from typing import Any

HIDDEN = "(hidden)"

# Runs in the page.  ``max`` = the most fields to look at.  Returns {url, title, fields[], storage{}, cookies[], messages[]}.
STATE_JS = r"""
(max) => {
  const SECRET = /(pass(word|code)?|pwd|secret|token|otp|cvv|cvc|card.?n(um|o)|cc-(num|csc|exp)|ssn|credential|csrf|jwt|authori[sz])/i;
  const out = { url: location.href, title: document.title || '', fields: [], storage: {}, cookies: [], messages: [] };
  const text = (el) => ((el && (el.innerText || el.textContent)) || '').replace(/\s+/g, ' ').trim();
  const shown = (el) => {
    const r = el.getClientRects();
    if (!r.length || (r[0].width === 0 && r[0].height === 0)) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== 'hidden' && cs.display !== 'none';
  };
  const labelOf = (el) => {
    let t = '';
    try { if (el.labels && el.labels.length) t = text(el.labels[0]); } catch (e) {}
    if (!t) t = el.getAttribute('aria-label') || '';
    if (!t) {
      const by = el.getAttribute('aria-labelledby');
      if (by) t = by.split(/\s+/).map((id) => text(document.getElementById(id))).join(' ').trim();
    }
    if (!t) {
      const box = el.closest('label, .form-group, .field, fieldset, [class*="field"], [class*="form-"]');
      const lab = box && (box.tagName === 'LABEL' ? box : box.querySelector('label, legend'));
      if (lab) t = text(lab);
    }
    return (t || el.placeholder || '').slice(0, 80);
  };
  const used = new Map();
  const nodes = document.querySelectorAll('input, select, textarea');
  for (const el of nodes) {
    if (out.fields.length >= max) break;
    const tag = el.tagName.toLowerCase();
    const type = tag === 'input' ? (el.type || 'text').toLowerCase() : tag;
    if (['hidden', 'submit', 'button', 'image', 'reset'].includes(type)) continue;
    let key = el.id || el.getAttribute('name') || el.getAttribute('data-testid') || el.getAttribute('aria-label') || (tag + '[' + type + ']');
    if (type === 'radio') key += '=' + el.value;
    const n = (used.get(key) || 0) + 1;
    used.set(key, n);
    if (n > 1) key += '#' + n;
    const hide = SECRET.test([el.id, el.name, el.getAttribute('autocomplete'), el.getAttribute('aria-label')].join(' '));
    let value = '', empty = false, checked = null;
    if (tag === 'select') {
      const o = el.selectedOptions && el.selectedOptions[0];
      value = o ? text(o) : '';
      empty = !o || o.disabled || o.value === '';
    } else if (type === 'checkbox' || type === 'radio') {
      checked = !!el.checked;
      value = checked ? 'checked' : '';
    } else {
      value = el.value || '';
      empty = value.trim() === '';
    }
    if ((type === 'password' || hide) && value) value = '(hidden)';
    const aria = el.getAttribute('aria-disabled') === 'true' || !!el.closest('[aria-disabled="true"]');
    out.fields.push({
      key, label: labelOf(el), type, value: value.slice(0, 200), empty, checked,
      disabled: !!el.disabled, readonly: !!el.readOnly, ariaDisabled: aria,
      placeholder: (el.getAttribute('placeholder') || '').slice(0, 80), visible: shown(el),
    });
  }
  for (const [name, store] of [['local', 'localStorage'], ['session', 'sessionStorage']]) {
    try {
      const s = window[store];
      for (let i = 0; i < Math.min(s.length, 100); i++) {
        const k = s.key(i);
        let v = String(s.getItem(k) || '');
        if (SECRET.test(k) || /^eyJ[\w-]+\.[\w-]+\./.test(v)) v = '(hidden)';
        out.storage[name + ':' + k] = v.slice(0, 1000);
      }
    } catch (e) {}
  }
  try { out.cookies = document.cookie.split(';').map((c) => c.split('=')[0].trim()).filter(Boolean).slice(0, 60); } catch (e) {}
  const alerts = document.querySelectorAll('[role="alert"], [aria-live="assertive"], .error, .error-message, [class*="error-msg"], [class*="errorMessage"]');
  for (const el of alerts) {
    if (out.messages.length >= 5) break;
    if (!shown(el)) continue;
    const t = text(el);
    if (t && !out.messages.includes(t.slice(0, 200))) out.messages.push(t.slice(0, 200));
  }
  return out;
}
"""


def flatten(frames: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    """One snapshot out of what the main frame (label ``""``) and the first-party frames answered: fields keyed by name (a frame's own are
    prefixed ``<frame>/``), storage and cookies from the main frame only (a frame shares them or is another site's)."""
    main = dict(frames[0][1])
    fields: dict[str, dict[str, Any]] = {}
    for label, snap in frames:
        for f in snap.get("fields", []):
            key = f"{label}/{f['key']}" if label else f["key"]
            entry = {k: v for k, v in f.items() if k != "key"}
            if label:
                entry["frame"] = label
            fields[key] = entry
    return {"url": main.get("url", ""), "title": main.get("title", ""), "fields": fields, "storage": dict(main.get("storage") or {}),
            "cookies": list(main.get("cookies") or []), "messages": list(main.get("messages") or [])}


def _page_of(url: str) -> str:
    """The address without its query and fragment: a new page, as opposed to the same page showing something else."""
    return re.split(r"[?#]", url or "", maxsplit=1)[0]


def locked(field: dict[str, Any]) -> str:
    """How a field is switched off ("disabled" | "read-only" | "not editable"), or "" when a person could type in it."""
    if field.get("disabled"):
        return "disabled"
    if field.get("readonly"):
        return "read-only"
    if field.get("ariaDisabled"):
        return "not editable"
    return ""


def locked_without_value(fields: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    """Fields that are on the page, switched off and yet show nothing but their placeholder (or nothing at all).  A switched-off field is filled by
    the site (from the session, a look-up, another field), so an empty one means that fill did not happen.  Checkboxes and radios are skipped:
    an unticked one is a normal answer."""
    found = []
    for key, f in fields.items():
        how = locked(f)
        if not how or not f.get("visible") or f.get("type") in ("checkbox", "radio", "file"):
            continue
        value, placeholder = str(f.get("value") or "").strip(), str(f.get("placeholder") or "").strip()
        shows_placeholder = bool(placeholder) and value.lower() == placeholder.lower()
        if not (f.get("empty") or shows_placeholder):
            continue
        name = f.get("label") or key
        if shows_placeholder:
            text = f'"{name}" is {how} and shows its placeholder "{placeholder}" as its value'
        elif placeholder:
            text = f'"{name}" is {how} and has no value (it shows the placeholder "{placeholder}")'
        else:
            text = f'"{name}" is {how} and has no value'
        found.append({"key": key, "label": str(name), "how": how, "placeholder": placeholder, "text": text})
    return found


class StateTracker:
    """Per test: remembers the last snapshot so each step's line holds only what changed, and which empty switched-off fields were already reported
    (they are said again on a failed step, where they matter most, and when they stop and start again)."""

    def __init__(self, mode: str = "changes"):
        self.mode = mode
        self.prev: dict[str, Any] | None = None
        self.warned: set[str] = set()

    def observe(self, snap: dict[str, Any], *, seq: int, row: int, name: str, failed: bool = False) -> tuple[dict[str, Any], list[dict[str, str]]]:
        """The line for ``state.jsonl`` and the warnings to show for this step."""
        prev = self.prev
        full = self.mode == "every_step" or prev is None or _page_of(prev["url"]) != _page_of(snap["url"])
        line: dict[str, Any] = {"step": seq, "row": row, "name": name, "url": snap["url"], "title": snap["title"], "full": full}
        if full:
            line.update(fields=snap["fields"], storage=snap["storage"], cookies=snap["cookies"], messages=snap["messages"])
        else:
            assert prev is not None
            changed = {k: v for k, v in snap["fields"].items() if prev["fields"].get(k) != v}
            storage = {k: v for k, v in snap["storage"].items() if prev["storage"].get(k) != v}
            gone = [k for k in prev["fields"] if k not in snap["fields"]]
            storage_gone = [k for k in prev["storage"] if k not in snap["storage"]]
            for key, value in (("fields", changed), ("storage", storage), ("gone", gone), ("storage_gone", storage_gone)):
                if value:
                    line[key] = value
            added = [c for c in snap["cookies"] if c not in prev["cookies"]]
            removed = [c for c in prev["cookies"] if c not in snap["cookies"]]
            if added:
                line["cookies_added"] = added
            if removed:
                line["cookies_gone"] = removed
            if snap["messages"] != prev["messages"]:
                line["messages"] = snap["messages"]
        self.prev = snap
        every = locked_without_value(snap["fields"])
        now = {w["key"] for w in every}
        warnings = [w for w in every if failed or w["key"] not in self.warned]
        self.warned = now
        if warnings:
            line["warnings"] = warnings
        return line, warnings


def replay(lines: list[dict[str, Any]], upto: int) -> dict[str, Any]:
    """The page as it was after step ``upto``: the lines of ``state.jsonl`` applied in order (what the Results screen shows as "all fields now")."""
    fields: dict[str, Any] = {}
    storage: dict[str, str] = {}
    cookies: list[str] = []
    messages: list[str] = []
    url = ""
    for line in lines:
        if line.get("step", 0) > upto:
            break
        url = line.get("url", url)
        if line.get("full"):
            fields, storage, cookies = dict(line.get("fields") or {}), dict(line.get("storage") or {}), list(line.get("cookies") or [])
        else:
            fields.update(line.get("fields") or {})
            storage.update(line.get("storage") or {})
            for k in line.get("gone") or []:
                fields.pop(k, None)
            for k in line.get("storage_gone") or []:
                storage.pop(k, None)
            cookies = [c for c in cookies if c not in (line.get("cookies_gone") or [])] + list(line.get("cookies_added") or [])
        if "messages" in line:
            messages = list(line["messages"])
    return {"url": url, "fields": fields, "storage": storage, "cookies": cookies, "messages": messages}
