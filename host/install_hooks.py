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

# What each Claude Code event means for the light.
#
# The rule the layout follows: yellow must appear the moment the user is
# actually needed, and disappear the moment they are not. Waiting for a
# Notification does neither — `permission_prompt` only fires after the prompt
# has sat there for about six seconds, an AskUserQuestion prompt raises no
# notification at all, and `idle_prompt` fires 60 s after every finished turn
# with nobody typing, which is exactly how a quiet green light used to turn
# yellow by itself. So the prompt events drive the light directly and the
# Notification hook keeps only the types that really mean "you are needed".
#
# PostToolUse is the one hook that fires on every tool call. It earns that
# cost by being the only signal that a permission prompt was answered: the
# approved tool then runs, and nothing else reports it. Every entry except
# SessionEnd is async, so none of them can delay the agent; SessionEnd stays
# synchronous because an async hook is killed at teardown and the session file
# would survive its session.
HOOK_SPECS = (
    {"event": "SessionStart", "arguments": ["set", "idle"]},
    {"event": "UserPromptSubmit", "arguments": ["set", "working"]},
    # The interactive question tool: yellow before it renders, red once the
    # answer is in.
    {
        "event": "PreToolUse",
        "matcher": "AskUserQuestion",
        "arguments": ["set", "blocked"],
    },
    {"event": "PostToolUse", "arguments": ["set", "working"]},
    # Fires the instant Claude asks for permission, six seconds before the
    # matching notification would.
    {"event": "PermissionRequest", "arguments": ["set", "blocked"]},
    {"event": "PermissionDenied", "arguments": ["set", "working"]},
    # The remaining prompts that have no dedicated event, minus idle_prompt.
    {
        "event": "Notification",
        "matcher": (
            "permission_prompt|elicitation_dialog|elicitation_url_dialog"
            "|agent_needs_input"
        ),
        "arguments": ["set", "blocked"],
    },
    {"event": "Elicitation", "arguments": ["set", "blocked"]},
    {"event": "ElicitationResult", "arguments": ["set", "working"]},
    # Not "set idle": a turn that ends in a question is still waiting on the
    # user, and only the CLI can see the assistant's last message.
    {"event": "Stop", "arguments": ["stop"]},
    {"event": "SessionEnd", "arguments": ["clear"], "async": False},
)


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

    for event in sorted({spec["event"] for spec in HOOK_SPECS}):
        kept = [e for e in _as_list(hooks.get(event)) if not _is_ours(e)]
        kept.extend(
            _entry(spec, python_exe, cli_path)
            for spec in HOOK_SPECS
            if spec["event"] == event
        )
        hooks[event] = kept

    return merged


def _entry(spec, python_exe, cli_path):
    """Build one settings entry from a spec."""
    hook = {
        "type": "command",
        "command": build_command(python_exe, cli_path, spec["arguments"]),
    }
    if spec.get("async", True):
        hook["async"] = True

    entry = {"hooks": [hook]}
    if "matcher" in spec:
        entry["matcher"] = spec["matcher"]
    return entry


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
    for spec in HOOK_SPECS:
        matcher = spec.get("matcher")
        print(
            "  %-18s %s%s"
            % (
                spec["event"],
                " ".join(spec["arguments"]),
                "  [%s]" % matcher if matcher else "",
            )
        )
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
