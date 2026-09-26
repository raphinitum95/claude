"""Is a UI window still open?  Lets ``regrunner serve --exit-when-closed`` (what the double-click launchers use) stop the server,
and with it the launcher's terminal window, once the last UI window is closed.

Every open page says hello every few seconds and goodbye when it is closed. The server only watches: nothing here ever closes
a page. Deliberately forgiving, because stopping while someone is still looking is far worse than staying a little longer:

* a goodbye is followed by a short grace, because a reload says goodbye and then hello again from the new page;
* a page that stopped saying hello without a goodbye (browser crashed, laptop asleep) only counts as gone after a long silence,
  because a minimised window's timers can be slowed to about one tick a minute;
* nothing stops before the first page has said hello (the window may still be opening).

Whether a run is still going is the caller's question (see ``create_app``): closing the window never stops a run.
"""
from __future__ import annotations

import time
from typing import Callable

GOODBYE_GRACE_S = 4.0      # a reload's new page says hello well within this
SILENT_GONE_S = 150.0      # a hidden window's heartbeat can slow to once a minute: allow two missed ones and some


class UiPresence:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._last_hello: dict[str, float] = {}
        self._last_goodbye: float | None = None
        self.ever_seen = False

    def hello(self, page_id: str) -> None:
        self._last_hello[page_id] = self._clock()
        self.ever_seen = True

    def goodbye(self, page_id: str) -> None:
        self._last_hello.pop(page_id, None)
        self._last_goodbye = self._clock()

    def open_pages(self) -> int:
        now = self._clock()
        return sum(1 for seen in self._last_hello.values() if now - seen < SILENT_GONE_S)

    def all_closed(self) -> bool:
        """True once a page has been open, none is open now, and the last goodbye is older than the reload grace."""
        if not self.ever_seen or self.open_pages():
            return False
        return self._last_goodbye is None or self._clock() - self._last_goodbye >= GOODBYE_GRACE_S
