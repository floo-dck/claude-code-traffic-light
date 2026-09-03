"""Reduce the states of every live session to a single traffic-light command.

The rule is that "somebody needs you" always wins. The light must never claim
everything is finished while a session is still waiting on input.
"""

STATE_BLOCKED = "blocked"
STATE_WORKING = "working"
STATE_IDLE = "idle"
STATE_OFF = "off"

VALID_STATES = (STATE_BLOCKED, STATE_WORKING, STATE_IDLE, STATE_OFF)

# Single-character commands understood by the firmware.
COMMAND_RED = "R"
COMMAND_YELLOW = "Y"
COMMAND_GREEN = "G"
COMMAND_OFF = "O"

# Descending priority. STATE_OFF is absent on purpose: a session that is
# explicitly off contributes nothing, so it falls through to COMMAND_OFF.
_PRIORITY = (
    (STATE_BLOCKED, COMMAND_YELLOW),
    (STATE_WORKING, COMMAND_RED),
    (STATE_IDLE, COMMAND_GREEN),
)


def aggregate(states):
    """Return the firmware command for the highest-priority state present.

    Unrecognised states are ignored, so a state name written by a newer
    version of the CLI degrades to "no opinion" instead of blanking the light.
    """
    present = set(states)
    for state, command in _PRIORITY:
        if state in present:
            return command
    return COMMAND_OFF
