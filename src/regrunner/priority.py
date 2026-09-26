"""Keep the runner from getting in the user's way: lower OS scheduling priority.

Browsers are spawned by the runner *after* this call, so they inherit the lowered priority too.
No OS-level input (keyboard/mouse) is used anywhere in this package - see tests/test_no_os_input.py.
"""
from __future__ import annotations

import os
import sys


def lower_priority(nice: int = 10) -> str:
    """Best-effort; returns a short description of what was applied."""
    try:
        if sys.platform == "win32":
            import ctypes
            BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(),
                                                    BELOW_NORMAL_PRIORITY_CLASS)
            return "below-normal priority class"
        os.nice(nice)
        return f"nice +{nice}"
    except Exception as err:                    # never fail a run because we could not be polite
        return f"unchanged ({err})"
