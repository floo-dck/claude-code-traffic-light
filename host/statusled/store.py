"""Per-session state files.

Each session writes only its own file. That single rule removes write
contention between concurrent Claude Code sessions and with it the need for
cross-process locking, which is the part that would have been genuinely
awkward on Windows.
"""

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Conservative enough to be a safe filename on every platform.
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

# Prefix for the temporary file used by the atomic write. Readers skip these.
_TEMP_PREFIX = ".tmp-"


def sanitise_session_id(session_id):
    """Return a filename-safe session id.

    Ids that are already safe pass through unchanged, so the files on disk stay
    recognisable when debugging. Anything else is hashed rather than rejected:
    a hook must never fail because an id looked surprising.
    """
    if session_id and _SAFE_ID.match(session_id):
        return session_id
    raw = session_id if isinstance(session_id, str) else ""
    return "h" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def session_path(sessions_dir, session_id):
    """Return the path of one session's state file."""
    return Path(sessions_dir) / (sanitise_session_id(session_id) + ".json")


def write_state(sessions_dir, session_id, state, cwd=None, hook_event=None, now=None):
    """Record a session's state atomically and return the file's path.

    The write goes to a temporary file in the same directory and is then
    renamed over the target, so a concurrent reader never observes a
    half-written document. os.replace is atomic on Windows as well as POSIX.
    """
    sessions = Path(sessions_dir)
    sessions.mkdir(parents=True, exist_ok=True)
    target = session_path(sessions, session_id)

    payload = {
        "state": state,
        "updated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "cwd": cwd if cwd is not None else os.getcwd(),
        "hook_event": hook_event or "",
    }

    descriptor, temporary = tempfile.mkstemp(
        dir=str(sessions), prefix=_TEMP_PREFIX, suffix=".json"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(temporary, target)
    except BaseException:
        # Never leave debris that a later read would mistake for a session.
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise

    return target


def clear_state(sessions_dir, session_id):
    """Delete a session's file. Returns False if there was nothing to delete."""
    try:
        session_path(sessions_dir, session_id).unlink()
    except FileNotFoundError:
        return False
    return True


def read_live_states(sessions_dir, stale_after_minutes, now=None, prune=True):
    """Return the states of every session still considered alive.

    Unparseable files are skipped but kept: they are most likely a transient
    write race, and destroying a session's state over one bad read would be a
    worse bug than ignoring it for a moment.

    Files older than the staleness window are skipped and deleted. Those
    belong to terminals killed without running SessionEnd, and keeping them
    would pin the light to a state that will never be cleared.
    """
    sessions = Path(sessions_dir)
    if not sessions.is_dir():
        return []

    moment = now or datetime.now(timezone.utc)
    cutoff = moment - timedelta(minutes=stale_after_minutes)

    states = []
    for path in sorted(sessions.glob("*.json")):
        if path.name.startswith(_TEMP_PREFIX):
            continue
        record = _read_record(path)
        if record is None:
            continue
        updated_at, state = record
        if updated_at < cutoff:
            if prune:
                try:
                    path.unlink()
                except OSError:
                    pass
            continue
        states.append(state)
    return states


def _read_record(path):
    """Parse one session file into (updated_at, state), or None if unusable."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        state = data["state"]
        updated_at = datetime.fromisoformat(data["updated_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None

    if not isinstance(state, str):
        return None
    if updated_at.tzinfo is None:
        # Older or hand-edited files may lack a zone; treat them as UTC.
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    return updated_at, state
