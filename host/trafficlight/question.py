"""Tell a finished turn apart from a turn that is waiting on an answer.

Claude Code has no hook for "asked the user something in prose": the only
signal at the end of a turn is the assistant's last message. Yellow means
"somebody needs you", so a turn ending in a question earns it just as much as
a permission prompt does.

The test walks the message's last lines backwards rather than looking only at
the final character, because the common shape is a question followed by the
options it offers. It stops at the first line that is neither a question nor
an option, which is what keeps a finished report green: a question explained
mid-message and then answered by Claude is not a prompt for input.
"""

import re

# Formatting that may sit after the final punctuation without changing it.
_DECORATION = " \t\r\n*_~`\"'“”‘’«»"

# A trailing parenthetical, such as "Weiter? *(y/n)*", is decoration too.
_CLOSERS = {")": "(", "]": "[", "}": "{"}

# Enough passes for any realistic nesting; a bound keeps a hostile message
# from spinning, because this runs inside a hook.
_MAX_PASSES = 8

# A line that offers an answer rather than ending the message: a bullet, a
# numbered or lettered item, a table row, a quote, a bold lead-in, or a
# plainly spelled-out option.
_OPTION_LINE = re.compile(
    r"^\s*(?:[-*+•]\s|\d+[.)]\s|[A-Za-z][.)]\s|\||>\s|\*\*"
    r"|(?:Option|Variante|Choice)\b)",
    re.IGNORECASE,
)

# How far back the walk may run. A question buried above a long tail is part
# of the report, not the ending.
_MAX_TAIL_LINES = 12


def looks_like_question(message):
    """True when the assistant's last message ends by asking the user something."""
    if not isinstance(message, str):
        return False

    seen = 0
    for line in reversed(message.splitlines()):
        if not line.strip():
            continue
        if seen >= _MAX_TAIL_LINES:
            return False
        seen += 1
        if _ends_with_question(line):
            return True
        if not _OPTION_LINE.match(line):
            return False
    return False


def _ends_with_question(line):
    """True when one line ends in a question mark, past any decoration."""
    text = line
    for _ in range(_MAX_PASSES):
        stripped = text.rstrip(_DECORATION)
        closer = stripped[-1:]
        if closer in _CLOSERS:
            opening = stripped.rfind(_CLOSERS[closer])
            if opening != -1:
                stripped = stripped[:opening]
        if stripped == text:
            break
        text = stripped

    return text.endswith("?")
