#!/usr/bin/env python3
"""Traffic-light status indicator for Claude Code.

Usually invoked from a Claude Code hook. In `set`, `stop` and `clear` mode it
must never fail: it always exits 0, logs to a file instead of stderr, and
gives up rather than delay the agent. `status` and `selftest` are for humans
and do report failure through their exit code.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from trafficlight import config, store, transport
from trafficlight.aggregate import STATE_BLOCKED, STATE_IDLE, VALID_STATES, aggregate
from trafficlight.question import looks_like_question

LOG_MAX_BYTES = 256 * 1024

# Stamped once, at process start, because most hooks now run async: two of
# them can be in flight at once, and the store orders them by this timestamp
# rather than by whichever process reaches the disk first.
STARTED_AT = datetime.now(timezone.utc)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="traffic_light.py", description=__doc__.splitlines()[0]
    )
    sub = parser.add_subparsers(dest="command", required=True)

    setter = sub.add_parser("set", help="record this session's state")
    setter.add_argument("state", choices=list(VALID_STATES))
    setter.add_argument("--session", default=None, help="override the session id")

    stopper = sub.add_parser(
        "stop", help="end of turn: idle, or blocked if Claude asked something"
    )
    stopper.add_argument("--session", default=None, help="override the session id")

    clearer = sub.add_parser("clear", help="forget this session")
    clearer.add_argument("--session", default=None, help="override the session id")

    sub.add_parser("status", help="show the aggregated colour and every session")
    sub.add_parser("selftest", help="cycle all colours and check the replies")

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "set":
        return _command_set(args)
    if args.command == "stop":
        return _command_stop(args)
    if args.command == "clear":
        return _command_clear(args)
    if args.command == "status":
        return _command_status()
    return _command_selftest()


def _command_set(args):
    """Record a state and refresh the light. Always exits 0."""
    try:
        _record(args.session, _read_hook_payload(), args.state)
    except Exception:  # noqa: BLE001 - a failing hook is worse than a wrong light
        _log_exception("set %s" % args.state)
    return 0


def _command_stop(args):
    """Decide what the end of a turn means and refresh the light. Always exits 0.

    A turn that ends in a question is still waiting on the user, so it stays
    yellow. Everything else is done, and done is green.
    """
    try:
        payload = _read_hook_payload()
        waiting = looks_like_question(payload.get("last_assistant_message"))
        _record(args.session, payload, STATE_BLOCKED if waiting else STATE_IDLE)
    except Exception:  # noqa: BLE001 - see _command_set
        _log_exception("stop")
    return 0


def _record(session, payload, state):
    """Write one session's state and push the resulting colour."""
    store.write_state(
        config.sessions_dir(),
        session or payload.get("session_id") or "",
        state,
        cwd=payload.get("cwd"),
        hook_event=payload.get("hook_event_name"),
        now=STARTED_AT,
    )
    _refresh_light()


def _command_clear(args):
    """Forget a session and refresh the light. Always exits 0."""
    try:
        payload = _read_hook_payload()
        store.clear_state(
            config.sessions_dir(), args.session or payload.get("session_id") or ""
        )
        _refresh_light()
    except Exception:  # noqa: BLE001 - see _command_set
        _log_exception("clear")
    return 0


def _command_status():
    """Print what the light should be showing and why."""
    settings = config.load_config()
    sessions = config.sessions_dir()
    # Reporting must not mutate state, hence prune=False.
    states = store.read_live_states(
        sessions, settings["stale_after_minutes"], prune=False
    )
    port = settings["port"] or transport.detect_port()

    print("data dir:      %s" % config.data_dir())
    print("port:          %s" % (port or "not found"))
    print("baud:          %d" % settings["baud"])
    print("stale after:   %s min" % settings["stale_after_minutes"])
    print("live sessions: %d" % len(states))
    for path in _session_files(sessions):
        print("  %-36s %s" % (path.stem, _describe_session(path)))
    print("aggregate:     %s" % aggregate(states))
    return 0 if port else 1


def _command_selftest():
    """Drive every colour and verify the firmware acknowledges each one."""
    settings = config.load_config()
    port = settings["port"] or transport.detect_port()
    if not port:
        print("FAIL: no serial port found")
        return 1

    print("using %s at %d baud" % (port, settings["baud"]))
    try:
        results = transport.run_selftest(port, settings["baud"])
    except Exception as error:  # noqa: BLE001 - report, do not traceback
        print("FAIL: %s" % error)
        return 1

    failures = 0
    for command, expected, reply, ok in results:
        print(
            "  %s -> %-10s expected %-10s %s"
            % (command, reply or "(no reply)", expected, "OK" if ok else "MISMATCH")
        )
        if not ok:
            failures += 1

    print("selftest: %d/%d passed" % (len(results) - failures, len(results)))
    return 0 if failures == 0 else 1


def _refresh_light():
    """Aggregate every live session and push the resulting colour."""
    settings = config.load_config()
    states = store.read_live_states(
        config.sessions_dir(), settings["stale_after_minutes"]
    )
    command = aggregate(states)

    port = settings["port"] or transport.detect_port()
    if not port:
        _log("no serial port found; light not updated")
        return False

    ok, error = transport.send_command(command, port, settings["baud"])
    if not ok:
        _log("sending %s to %s failed: %s" % (command, port, error))
    return ok


def _read_hook_payload():
    """Parse the hook JSON Claude Code writes to stdin.

    Returns an empty dict when stdin is a terminal, empty, or not a JSON
    object, so the CLI stays usable by hand.
    """
    stream = getattr(sys, "stdin", None)
    if stream is None:
        return {}
    try:
        if stream.isatty():
            return {}
        raw = stream.read()
    except (OSError, ValueError):
        return {}

    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _session_files(sessions):
    directory = Path(sessions)
    if not directory.is_dir():
        return []
    return [p for p in sorted(directory.glob("*.json")) if not p.name.startswith(".tmp-")]


def _describe_session(path):
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "(unreadable)"
    return "%-8s %s  %s" % (
        record.get("state", "?"),
        record.get("updated_at", "?"),
        record.get("cwd", ""),
    )


def _log(message):
    """Append to a size-capped log file.

    Never writes to stderr: hook stderr can surface in the Claude Code UI, and
    a status light is not worth interrupting the user for.
    """
    try:
        path = config.log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > LOG_MAX_BYTES:
            path.replace(path.parent / (path.name + ".1"))
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with path.open("a", encoding="utf-8") as handle:
            handle.write("%s %s\n" % (stamp, message))
    except OSError:
        pass


def _log_exception(context):
    import traceback

    _log("%s raised:\n%s" % (context, traceback.format_exc()))


if __name__ == "__main__":
    sys.exit(main())
