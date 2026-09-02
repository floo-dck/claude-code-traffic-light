"""Where runtime state lives, and how it is configured.

Runtime state deliberately sits outside the repository: the hooks are
registered globally, so the light belongs to the machine rather than to one
checkout.
"""

import json
import os
from pathlib import Path

DEFAULTS = {
    "port": None,
    "baud": 115200,
    "stale_after_minutes": 120,
}

# Set this to redirect every path below. Used by the tests, and handy for
# running two independent instances.
HOME_ENV_VAR = "CLAUDE_STATUS_LED_HOME"


def data_dir():
    """Return the directory holding config, session state and the log."""
    override = os.environ.get(HOME_ENV_VAR)
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(local) / "claude-status-led"


def sessions_dir():
    return data_dir() / "sessions"


def config_path():
    return data_dir() / "config.json"


def log_path():
    return data_dir() / "led.log"


def load_config(path=None):
    """Return the merged configuration, falling back to defaults on any fault.

    Every failure mode — missing file, unreadable file, malformed JSON, a
    document that is not an object, a value of the wrong type — yields a
    usable config instead of an exception, because the caller is usually a
    hook that must not fail.
    """
    merged = dict(DEFAULTS)
    target = Path(path) if path is not None else config_path()

    try:
        with target.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return merged

    if not isinstance(data, dict):
        return merged

    for key in DEFAULTS:
        if key in data:
            merged[key] = data[key]

    if not isinstance(merged["baud"], int) or isinstance(merged["baud"], bool) or merged["baud"] <= 0:
        merged["baud"] = DEFAULTS["baud"]

    window = merged["stale_after_minutes"]
    if isinstance(window, bool) or not isinstance(window, (int, float)) or window <= 0:
        merged["stale_after_minutes"] = DEFAULTS["stale_after_minutes"]

    if merged["port"] is not None and not isinstance(merged["port"], str):
        merged["port"] = DEFAULTS["port"]

    return merged
