"""Google Authenticator / Okta Verify style one-time codes (RFC 6238: HMAC-SHA1, 30 s steps, 6 digits).

The legacy ``GET_GOOGLE_TOKEN`` keyword did exactly this from the base32 secret in the step's Value cell.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import struct
import time
from dataclasses import dataclass
from pathlib import Path

STEP_S = 30
EXPIRY_MARGIN_S = 4          # a code with less than this left would be stale before Okta sees it


class BadSecret(ValueError):
    pass


def code_at(secret: str, at: float | None = None, digits: int = 6) -> str:
    """The code for ``secret`` at unix time ``at`` (now).  Spaces / dashes / case in the secret do not matter."""
    cleaned = re.sub(r"[\s=-]", "", str(secret)).upper()          # authenticator apps show the key in groups; padding is optional
    if not cleaned:
        raise BadSecret("the secret is empty")
    if not re.fullmatch(r"[A-Z2-7]{8,}", cleaned):
        raise BadSecret("that is not a base32 secret (at least 8 letters A-Z / digits 2-7)")      # never echo it: reports get shared
    try:
        key = base64.b32decode(cleaned + "=" * (-len(cleaned) % 8))
    except (binascii.Error, ValueError):
        raise BadSecret("that is not a valid base32 secret") from None
    counter = int((time.time() if at is None else at) // STEP_S)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(number).zfill(digits)


def seconds_left(at: float | None = None) -> float:
    """How long the current code stays valid."""
    return STEP_S - ((time.time() if at is None else at) % STEP_S)


# -- one code, one login ---------------------------------------------------------------------------------------------------------------------
# Okta (like every TOTP check) accepts a code once.  Tests that log in with the same authenticator secret at the same time - or a run started
# seconds after another one - would otherwise be handed the same code and the second login would be refused ("Each code can only be used once").
_taken: dict[str, int] = {}          # secret fingerprint -> the last 30 s window a code was handed out for (this process)


@dataclass
class Reservation:
    window: int                      # the 30 s window whose code to use (``code_at(secret, window * STEP_S)``)
    wait_s: float                    # how long until that window starts (0 = now)
    reason: str                      # "" | "expiring" (the current code is about to expire) | "used" (another login of this secret already took the current one)


def fingerprint(secret: str) -> str:
    """Who a code belongs to, without keeping the secret: a hash of the cleaned key."""
    cleaned = re.sub(r"[\s=-]", "", str(secret)).upper()
    return hashlib.sha256(cleaned.encode()).hexdigest()[:16]


def _read_store(store: Path | None, key: str) -> int:
    try:
        return int(json.loads(store.read_text(encoding="utf-8")).get(key, -1)) if store is not None else -1
    except (OSError, ValueError, AttributeError):
        return -1


def _write_store(store: Path | None, key: str, window: int) -> None:
    if store is None:
        return
    try:
        try:
            data = json.loads(store.read_text(encoding="utf-8"))
            data = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            data = {}
        cutoff = window - 4                                        # windows older than two minutes are of no use: keep the file tiny
        data = {k: v for k, v in data.items() if isinstance(v, int) and v >= cutoff}
        data[key] = window
        store.parent.mkdir(parents=True, exist_ok=True)
        tmp = store.with_name(store.name + ".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, store)
    except OSError:
        pass                                                       # best effort: the in-process record still protects this run


def reserve_window(secret: str, *, store: Path | None = None, now: float | None = None) -> Reservation:
    """Take the next code window nobody has used for ``secret``: the current one, unless it is about to expire or a code for it was already handed out
    (by another test of this run, or - through ``store`` - by a run that started a moment ago), then the one after.  Synchronous on purpose: two tests
    asking in the same instant cannot both get the same window.  A different secret (another account) never waits for this one."""
    now = time.time() if now is None else now
    key = fingerprint(secret)
    current = int(now // STEP_S)
    last = max(_taken.get(key, -1), _read_store(store, key))
    left = seconds_left(now)
    window, reason = current, ""
    if left < EXPIRY_MARGIN_S:
        window, reason = current + 1, "expiring"
    if window <= last:
        window, reason = last + 1, "used"
    _taken[key] = window
    _write_store(store, key, window)
    if window == current:
        return Reservation(window, 0.0, "")
    start = now + left if window == current + 1 else window * STEP_S
    return Reservation(window, start - now + 0.3, reason)
