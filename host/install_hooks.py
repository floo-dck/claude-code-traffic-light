#!/usr/bin/env python3
"""Register the claude-code-traffic-light hooks in Claude Code's settings.

The merge is deliberately surgical: only entries whose command mentions this
CLI are touched, so unrelated hooks and every other setting survive. The
target is the user's live configuration, so the transformation is a pure
function with its own tests and the file is backed up before it is replaced.
"""

import argparse
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

# How an entry is recognised as ours, both for replacing and for uninstalling.
# MARKER is the name written into new entries; LEGACY_MARKERS are names this
# project used before and must still recognise, so that re-running the
# installer repairs an old installation instead of orphaning it. This is
# permanent, not a migration: dropping it would silently leave dead hooks in
# the settings file of anyone who installed before the rename.
MARKER = "traffic_light.py"
LEGACY_MARKERS = ("claude_status_led.py",)

# The mapping from spec section 8. There is deliberately no per-tool-call hook:
# the cost is a process launch per tool use, and the only symptom of leaving it
# out is a light that stays yellow until the turn ends.
HOOK_EVENTS = {
    "SessionStart": ["set", "idle"],
    "UserPromptSubmit": ["set", "working"],
    "Notification": ["set", "blocked"],
    "Stop": ["set", "idle"],
    "SessionEnd": ["clear"],
}


def build_command(python_exe, cli_path, arguments):
    """Return the shell command for one hook, with both paths quoted."""
    parts = ['"%s"' % python_exe, '"%s"' % cli_path] + list(arguments)
    return " ".join(parts)


def merge_hooks(settings, python_exe, cli_path):
    """Return a copy of settings with our hooks installed.

    Re-running this is safe and is the supported way to repoint the hooks
    after moving the repository: our old entries are dropped by marker before
    the new ones are appended.
    """
    merged = copy.deepcopy(settings)

    hooks = merged.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        merged["hooks"] = hooks

    for event, arguments in sorted(HOOK_EVENTS.items()):
        kept = [e for e in _as_list(hooks.get(event)) if not _is_ours(e)]
        kept.append(
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": build_command(python_exe, cli_path, arguments),
                    }
                ]
            }
        )
        hooks[event] = kept

    return merged


def remove_hooks(settings):
    """Return a copy of settings with only our hook entries removed."""
    merged = copy.deepcopy(settings)

    hooks = merged.get("hooks")
    if not isinstance(hooks, dict):
        return merged

    for event in list(hooks):
        kept = [e for e in _as_list(hooks.get(event)) if not _is_ours(e)]
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]

    if not hooks:
        merged.pop("hooks", None)
    return merged


def _as_list(value):
    return value if isinstance(value, list) else []


def _is_ours(entry):
    """True when a settings entry invokes this CLI, under any name it ever had."""
    if not isinstance(entry, dict):
        return False
    for hook in _as_list(entry.get("hooks")):
        if not isinstance(hook, dict):
            continue
        command = str(hook.get("command", ""))
        if any(name in command for name in (MARKER,) + LEGACY_MARKERS):
            return True
    return False


def _default_paths():
    """Absolute paths to the interpreter and CLI, derived from this file."""
    repo_root = Path(__file__).resolve().parent.parent
    return (
        str(repo_root / ".venv" / "Scripts" / "python.exe"),
        str(repo_root / "host" / "traffic_light.py"),
    )


def main(argv=None):
    default_python, default_cli = _default_paths()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--settings",
        default=str(Path.home() / ".claude" / "settings.json"),
        help="settings file to modify",
    )
    parser.add_argument("--python", default=default_python)
    parser.add_argument("--cli", default=default_cli)
    parser.add_argument(
        "--uninstall", action="store_true", help="remove our hooks instead"
    )
    args = parser.parse_args(argv)

    target = Path(args.settings)
    if target.exists():
        try:
            settings = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            # Never guess at a file we cannot parse; the user's whole Claude
            # Code configuration lives in it.
            print("refusing to touch %s: %s" % (target, error), file=sys.stderr)
            return 1
        if not isinstance(settings, dict):
            print("refusing to touch %s: not a JSON object" % target, file=sys.stderr)
            return 1
        backup = target.with_name(target.name + ".bak")
        backup.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        print("backed up to %s" % backup)
    else:
        settings = {}

    updated = (
        remove_hooks(settings)
        if args.uninstall
        else merge_hooks(settings, args.python, args.cli)
    )
    _write_atomically(target, json.dumps(updated, indent=2) + "\n")

    action = "removed from" if args.uninstall else "installed into"
    print("hooks %s %s" % (action, target))
    for event in sorted(HOOK_EVENTS):
        print("  %s" % event)
    return 0


def _write_atomically(target, text):
    """Replace a file in one step, so a crash cannot truncate it."""
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=str(target.parent), prefix=".tmp-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


if __name__ == "__main__":
    sys.exit(main())
