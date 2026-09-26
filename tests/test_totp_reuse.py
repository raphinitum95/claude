"""Okta accepts a one-time code once: two logins with the same authenticator secret must not be handed the same code (the 2026-09-25 run: Purchase#1 and #2 both took
037112 and Okta refused the second: "Each code can only be used once")."""
from __future__ import annotations

import asyncio
import base64
import json
from types import SimpleNamespace

from regrunner import totp
from regrunner.config import Config
from regrunner.engine import actions
from regrunner.engine.actions import StepContext, run_action
from regrunner.workbook.model import PreparedStep

SECRET = base64.b32encode(b"12345678901234567890").decode()
OTHER = base64.b32encode(b"another-account-key!").decode()
W = 1000 * 30                                               # the start of window 1000


def test_the_second_login_of_the_same_secret_gets_the_next_window():
    first = totp.reserve_window(SECRET, now=W + 5)
    second = totp.reserve_window(SECRET, now=W + 9)          # same window, seconds later: that code is spent
    third = totp.reserve_window(SECRET, now=W + 10)
    assert (first.window, first.wait_s, first.reason) == (1000, 0.0, "")
    assert (second.window, second.reason) == (1001, "used") and 21.0 < second.wait_s < 21.5      # until 1001 starts (+0.3 s)
    assert (third.window, third.reason) == (1002, "used") and 50.0 < third.wait_s < 51.0           # a third one queues behind the second


def test_another_account_never_waits_for_this_one():
    totp.reserve_window(SECRET, now=W + 5)
    other = totp.reserve_window(OTHER, now=W + 6)
    assert (other.window, other.wait_s, other.reason) == (1000, 0.0, "")


def test_a_code_about_to_expire_is_still_skipped_and_a_used_one_is_not_reused_after_that():
    a = totp.reserve_window(SECRET, now=W + 27)               # 3 s left: stale before Okta sees it
    assert (a.window, a.reason) == (1001, "expiring") and abs(a.wait_s - 3.3) < 0.01
    b = totp.reserve_window(SECRET, now=W + 28)               # window 1001 is now taken
    assert (b.window, b.reason) == (1002, "used")


def test_a_window_that_has_passed_is_free_again():
    totp.reserve_window(SECRET, now=W + 5)
    later = totp.reserve_window(SECRET, now=W + 3 * 30 + 5)
    assert (later.window, later.wait_s) == (1003, 0.0)


def test_a_run_started_a_moment_after_another_does_not_reuse_its_code(tmp_path):
    """The store is what carries it over: a cancelled run restarted within the same 30 s is a different process with an empty memory."""
    store = tmp_path / ".auth" / "totp_last.json"
    totp.reserve_window(SECRET, store=store, now=W + 5)
    totp._taken.clear()                                       # (the new process)
    again = totp.reserve_window(SECRET, store=store, now=W + 12)
    assert (again.window, again.reason) == (1001, "used")
    text = store.read_text()
    assert SECRET not in text and set(json.loads(text)) == {totp.fingerprint(SECRET)}          # only a hash of the key is ever written


def test_an_unreadable_store_is_ignored(tmp_path):
    store = tmp_path / "totp_last.json"
    store.write_text("{not json")
    assert totp.reserve_window(SECRET, store=store, now=W + 5).window == 1000
    (tmp_path / "blocked").write_text("a file, not a folder")
    assert totp.reserve_window(OTHER, store=tmp_path / "blocked" / "x.json", now=W + 5).window == 1000      # cannot write: the run goes on


def ctx_for(tmp_path, secret):
    step = PreparedStep(row=5, values={"METHOD": "GET_GOOGLE_TOKEN", "VALUE": secret})
    return StepContext(step=step, session=SimpleNamespace(is_open=False, typed=set()), cfg=Config(base_dir=tmp_path), selector_map=None, review=None, test_dir=tmp_path)


def test_two_tests_logging_in_together_are_given_different_codes(tmp_path, monkeypatch):
    slept: list[float] = []

    async def no_sleep(seconds, *a, **k):
        slept.append(seconds)

    monkeypatch.setattr(totp.time, "time", lambda: W + 5.0)
    monkeypatch.setattr(actions.asyncio, "sleep", no_sleep)

    async def both():
        one, two = ctx_for(tmp_path, SECRET), ctx_for(tmp_path, SECRET)
        await asyncio.gather(run_action(one), run_action(two))
        return one, two

    one, two = asyncio.run(both())
    assert one.out.error == "" and two.out.error == ""
    assert {one.out.output, two.out.output} == {totp.code_at(SECRET, W), totp.code_at(SECRET, W + 30)}      # the two windows' codes, one each
    late = one if one.out.output == totp.code_at(SECRET, W + 30) else two
    assert any("already used by another login with the same authenticator secret" in n for n in late.out.notes) and len(slept) == 1 and 24.0 < slept[0] < 26.0
    early = two if late is one else one
    assert early.out.notes == []
