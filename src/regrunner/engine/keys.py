"""Parser for the legacy ``SendKeys`` mini-language (Windows ``WScript.Shell.SendKeys`` syntax).

The old runner sent these as *operating-system keystrokes* to whatever window had focus.  Here they
are translated to Playwright ``keyboard`` calls, which are delivered to the browser page over the
DevTools protocol - the real keyboard is never touched, so a run cannot interfere with the user.

Syntax handled: plain text, ``{TAB}`` / ``{ENTER}`` / ``{DOWN 3}`` (repeat), literal braces such as
``{+}``, modifiers ``+`` (Shift) ``^`` (Ctrl) ``%`` (Alt), groups ``+(ab)`` and ``~`` (Enter).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

SPECIAL = {
    "BACKSPACE": "Backspace", "BS": "Backspace", "BKSP": "Backspace", "BREAK": "Pause",
    "CAPSLOCK": "CapsLock", "DEL": "Delete", "DELETE": "Delete", "DOWN": "ArrowDown", "END": "End",
    "ENTER": "Enter", "ESC": "Escape", "HELP": "Help", "HOME": "Home", "INS": "Insert", "INSERT": "Insert",
    "LEFT": "ArrowLeft", "NUMLOCK": "NumLock", "PGDN": "PageDown", "PGUP": "PageUp", "PRTSC": "PrintScreen",
    "RIGHT": "ArrowRight", "SCROLLLOCK": "ScrollLock", "TAB": "Tab", "UP": "ArrowUp", "SPACE": " ",
    **{f"F{i}": f"F{i}" for i in range(1, 17)},
}
_MODIFIER = {"+": "Shift", "^": "Control", "%": "Alt"}


@dataclass(frozen=True)
class KeyOp:
    key: str                          # Playwright key name, or the literal character
    modifiers: tuple[str, ...] = ()
    text: bool = False                # True: plain character (typed with keyboard.type)

    @property
    def combo(self) -> str:
        return "+".join([*self.modifiers, self.key])

    @property
    def is_browser_zoom(self) -> bool:
        """Ctrl +/-/0 change *browser* zoom, which does not exist for a headless page."""
        return "Control" in self.modifiers and self.key in ("-", "+", "=", "0")


def parse_sendkeys(source: str) -> list[KeyOp]:
    ops, pos = _parse(str(source), 0, (), top=True)
    return ops


def _parse(s: str, pos: int, inherited: tuple[str, ...], top: bool) -> tuple[list[KeyOp], int]:
    ops: list[KeyOp] = []
    pending: list[str] = []
    while pos < len(s):
        ch = s[pos]
        if ch == ")" and not top:
            return ops, pos + 1
        if ch in _MODIFIER:
            pending.append(_MODIFIER[ch])
            pos += 1
            continue
        mods = tuple(dict.fromkeys([*inherited, *pending]))
        if ch == "(":
            inner, pos = _parse(s, pos + 1, mods, top=False)
            ops.extend(inner)
            pending = []
            continue
        if ch == "{":
            end = s.find("}", pos + 2 if s[pos + 1:pos + 2] == "}" else pos + 1)
            if end == -1:
                key, repeat, pos = "{", 1, pos + 1
            else:
                body = s[pos + 1:end]
                pos = end + 1
                m = re.match(r"^(\S+)\s+(\d+)$", body)
                name, repeat = (m.group(1), int(m.group(2))) if m else (body, 1)
                key = SPECIAL.get(name.upper(), name)
            ops.extend([_op(key, mods)] * repeat)
        elif ch == "~":
            ops.append(_op("Enter", mods))
            pos += 1
        else:
            ops.append(_op(ch, mods))
            pos += 1
        pending = []
    return ops, pos


def _op(key: str, mods: tuple[str, ...]) -> KeyOp:
    is_char = len(key) == 1 and not mods
    return KeyOp(key, mods, text=is_char)
