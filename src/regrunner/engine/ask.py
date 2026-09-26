"""Asking a person for something mid-run (the ``ASK_USER`` step; ``GET_GOOGLE_TOKEN`` when it has no key; a captcha that needs solving).

The runner writes a ``user_input_needed`` event and then waits for ``<run folder>/answers/<id>.json``.  Whoever the run belongs to supplies it:

* the web UI shows the question on the run screen and writes the file (``POST /api/runs/<run>/answer``);
* a run started from a terminal prompts there (``cli.TerminalAsker``).

The answer never travels in an event: only the fact that it arrived does.  A file is removed as soon as it is read, and every question that
ended without an answer (timeout, cancel) leaves a ``<id>.closed`` marker so a late answer is refused rather than left lying on disk.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
import uuid
from pathlib import Path

from ..events import EventBus

MODES = ("off", "ui", "terminal")
BEAT_S = 15                   # how often a waiting question is announced again (keeps the run's watchdog and the screen's countdown honest)
CHECK_S = 1.0                 # how often a question that can answer itself (a captcha someone is solving) looks whether it has


class AskUnavailable(Exception):
    """No person can answer: the run was not started from the UI or a terminal."""


class AskTimeout(Exception):
    pass


class AskCancelled(Exception):
    pass


class Asker:
    def __init__(self, run_dir: Path, bus: EventBus, cancel: asyncio.Event, mode: str = "off", default_timeout_s: float = 300):
        self.dir = run_dir / "answers"
        self.bus, self.cancel = bus, cancel
        self.mode = mode if mode in MODES else "off"
        self.default_timeout_s = default_timeout_s
        self._n = 0

    @property
    def available(self) -> bool:
        return self.mode != "off"

    async def ask(self, test: str, step: int, question: str, *, secret: bool = False, timeout_s: float | None = None,
                  kind: str = "text", until=None) -> str:
        """Put ``question`` to the person and wait.  ``kind`` "captcha" needs no typed answer: ``until`` (an async callable) says when the thing
        has been done by hand and the wait ends with "" then; an answer of "skip" is the person giving up on it."""
        if not self.available:
            raise AskUnavailable("This step needs a person to answer, and this run has nobody to ask: start it from the web UI, or from a terminal "
                                 "(regrunner run ...), rather than from a script.")
        self._n += 1
        ask_id = f"a{self._n}-{uuid.uuid4().hex[:6]}"
        wait_s = float(timeout_s or self.default_timeout_s)
        self.dir.mkdir(parents=True, exist_ok=True)
        answer_file, closed_file = self.dir / f"{ask_id}.json", self.dir / f"{ask_id}.closed"
        self.bus.emit("user_input_needed", test=test, step=step, ask=ask_id, question=question, secret=secret, timeout_s=wait_s, mode=self.mode, kind=kind)
        started = time.monotonic()
        next_beat, next_check = started + BEAT_S, started + CHECK_S
        while True:
            if answer_file.exists():
                try:
                    answer = str(json.loads(answer_file.read_text(encoding="utf-8")).get("answer", ""))
                except (OSError, ValueError):
                    await asyncio.sleep(0.1)                       # caught mid-write: look again
                    continue
                answer_file.unlink(missing_ok=True)
                self.bus.emit("user_input_received", test=test, step=step, ask=ask_id)
                return answer
            now = time.monotonic()
            if until is not None and now >= next_check:
                next_check = now + CHECK_S
                try:
                    done = await until()
                except Exception:
                    done = False
                if done:
                    closed_file.write_text("done")
                    self.bus.emit("user_input_closed", test=test, step=step, ask=ask_id, reason="done")
                    return ""
            if self.cancel.is_set():
                closed_file.write_text("cancelled")
                self.bus.emit("user_input_closed", test=test, step=step, ask=ask_id, reason="cancelled")
                raise AskCancelled("The run was cancelled while waiting for an answer.")
            if now - started >= wait_s:
                closed_file.write_text("timeout")
                self.bus.emit("user_input_closed", test=test, step=step, ask=ask_id, reason="timeout")
                raise AskTimeout(f"Nobody answered within {wait_s:g} s.")
            if now >= next_beat:
                next_beat += BEAT_S
                self.bus.emit("user_input_waiting", test=test, step=step, ask=ask_id, seconds_left=int(wait_s - (now - started)))
            await asyncio.sleep(0.3)

    def cleanup(self) -> None:
        """At the end of the run: nothing typed by a person stays behind."""
        shutil.rmtree(self.dir, ignore_errors=True)


def write_answer(run_dir: Path, ask_id: str, answer: str) -> str:
    """Store an answer for a waiting question.  Returns "" when written, else why not: ``closed`` (it timed out / was cancelled) or ``unknown``."""
    folder = run_dir / "answers"
    if (folder / f"{ask_id}.closed").exists():
        return "closed"
    if not folder.is_dir():
        return "unknown"
    tmp = folder / f".{ask_id}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)          # owner only: it may be a password
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"answer": answer}, fh)
    os.replace(tmp, folder / f"{ask_id}.json")
    return ""
