"""HTTP cooldowns and stable per-installation polling times."""
from datetime import timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from sys import float_info
from time import time


def retry_deadline(response):
    """Return the earliest allowed request time from a provider cooldown."""
    if response.status not in (429, 503):
        return 0
    value = response.headers.get("Retry-After", "").strip()
    if value.isascii() and value.isdecimal():
        return min(float_info.max, time() + float(value))
    try:
        date = parsedate_to_datetime(value)
        # The obsolete asctime HTTP-date form has no explicit timezone.
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        return date.timestamp()
    except (TypeError, ValueError, OverflowError, OSError):
        return 0


def poll_offset(entry_id, service_id, interval):
    seed = sha256(f"{entry_id}/{service_id}".encode()).digest()
    return int.from_bytes(seed[:8]) % interval


def next_slot(now, interval, offset, backoff=1, retry_at=0):
    """Use the next fixed phase, skipping missed slots and respecting cooldowns."""
    following = now + interval - ((now - offset) % interval)
    due = following + (backoff - 1) * interval
    if retry_at > due:
        due = retry_at + ((offset - retry_at) % interval)
    return due
