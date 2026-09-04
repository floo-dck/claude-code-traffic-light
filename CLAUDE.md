# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A traffic-light status indicator for Claude Code: three LEDs on an ESP32,
driven over USB serial by Claude Code hooks. Red = working, yellow = blocked
on the user, green = idle, off = no live session.

Two halves: `firmware/` (PlatformIO/Arduino, ESP32) and `host/` (Python 3.11
CLI plus the `trafficlight` package). The board is a dumb slave; every
decision about what the light means lives on the host, so behaviour changes
never require reflashing.

## Commands

All host commands assume the repo-root venv (`py -3.11 -m venv .venv`):

```bash
.venv\Scripts\python.exe -m pip install -r host\requirements.txt

# Tests
.venv\Scripts\python.exe -m pytest host\tests -v
.venv\Scripts\python.exe -m pytest host\tests\test_store.py::test_name -v   # single test

# Firmware (BOOT button must be held through "Connecting...." and released
# once the chip is identified, or the hard reset ending the upload leaves the
# chip in download mode and nothing answers on serial — this board's
# auto-program circuit does not pull GPIO0 low, so upload fails with
# "Wrong boot mode detected (0x13)" otherwise)
#
# -e is not optional on upload: platformio.ini defines two environments, and
# without it PlatformIO flashes both in turn, so the chip ends up running
# esp32dev_common_anode - pins 18/19/21, inverted - and LEDs on the default
# pins stay dark while the onboard LED still works.
.venv\Scripts\python.exe -m platformio run --project-dir firmware
.venv\Scripts\python.exe -m platformio run --project-dir firmware -e esp32dev --target upload

# Hooks (read at startup — restart Claude Code afterwards)
.venv\Scripts\python.exe host\install_hooks.py
.venv\Scripts\python.exe host\install_hooks.py --uninstall

# Manual checks
.venv\Scripts\python.exe host\traffic_light.py selftest
.venv\Scripts\python.exe host\traffic_light.py status
```

Close any `pio device monitor` before running the CLI or uploading — it holds
the port.

`host/conftest.py` puts `host/` on `sys.path`, so pytest works from the repo
root. Tests never touch real hardware or the real settings file: the serial
layer takes a `factory` parameter that the tests fill with a `FakePort`, and
`install_hooks` merges are pure functions over dicts.

## Architecture

The chain is: hook → CLI → one state file per session → aggregation → one
character over serial → firmware.

- `host/trafficlight/config.py` — where runtime state lives:
  `%LOCALAPPDATA%\claude-code-traffic-light\` (config.json, sessions/,
  led.log).
  Deliberately outside the repo, because hooks are registered globally.
  `CLAUDE_TRAFFIC_LIGHT_HOME` redirects every path; the tests rely on it.
- `host/trafficlight/store.py` — each session writes **only its own file**.
  That rule is what removes cross-process locking on Windows. Writes go via
  `tempfile.mkstemp` + `os.replace` so readers never see a half-written file.
  Files older than `stale_after_minutes` (default 120) are skipped and pruned;
  unparseable files are skipped but kept, since they are usually a write race.
  A write whose timestamp is older than the record already on disk is dropped:
  hooks run async, so two of them are in flight whenever a tool call meets a
  permission prompt, and the newer *event* must win over the faster process.
- `host/trafficlight/aggregate.py` — reduces all live states to one command
  with a fixed priority: `blocked` (Y) > `working` (R) > `idle` (G), else
  off (O).
  "Somebody needs you" must always outrank "still working". Unknown state
  names are ignored rather than blanking the light.
- `host/trafficlight/transport.py` — port detection by USB VID/PID (CH340
  1A86:7523, CH9102 1A86:55D4, CP210x 10C4:EA60); an explicit `port` in the
  config always wins. 3 retries, ~80 ms backoff, 1.5 s hard deadline, returns
  `(ok, reason)` and never raises.
- `host/trafficlight/question.py` — `looks_like_question`, the only way to
  tell "turn finished" from "turn ended by asking you something": Claude Code
  has no hook for a question asked in prose, so `stop` inspects the assistant's
  last message. It walks the last lines backwards, past trailing markdown, a
  trailing parenthetical, and any option lines (bullets, numbered or lettered
  items, table rows, `Option`/`Variante` lines), because the usual shape is a
  question with its answers listed underneath. The walk stops at the first
  line that is neither, which is what keeps a finished report green: a
  question explained mid-message and then answered by Claude is not a prompt
  for input. Bounded to 12 tail lines, so a question buried above a long
  summary does not count.
- `host/traffic_light.py` — subcommands `set`, `stop`, `clear`, `status`,
  `selftest`. `set`/`stop`/`clear` read the hook JSON payload from stdin.
  `stop` is the Stop hook: blocked when `last_assistant_message` ends in a
  question, idle otherwise. Records are stamped with `STARTED_AT`, the process
  start time, because async hooks overlap and the store orders them by that
  stamp rather than by whoever reaches the disk first.
- `host/install_hooks.py` — surgical merge into `~/.claude/settings.json`:
  only entries whose command contains `traffic_light.py` are touched, so
  unrelated hooks and settings survive. Re-running is safe and is the
  supported way to repoint the hooks after moving the repo. Backs up to
  `settings.json.bak` first and refuses to touch an unparseable file.
- `firmware/src/main.cpp` — `R`/`Y`/`G`/`O` set the LEDs and answer `OK <c>`;
  `?` answers `STATE <c>`; anything else answers `ERR`. Boot sweeps R/Y/G for
  200 ms each. The onboard LED (GPIO2) carries the same three states through
  timing, since one monochrome LED cannot show a colour: R solid, Y blinking
  at 150 ms, G an 80 ms heartbeat every 2 s, O off. Every accepted command
  restarts the pattern phase, so a repeat of the current state is visible too
  — that is the verification signal before any LED is wired.

Hook mapping (in `install_hooks.HOOK_SPECS`): SessionStart → idle,
UserPromptSubmit → working, PreToolUse[AskUserQuestion] → blocked, PostToolUse
→ working, PermissionRequest → blocked, PermissionDenied → working,
Notification[permission_prompt|elicitation_*|agent_needs_input] → blocked,
Elicitation → blocked, ElicitationResult → working, Stop → `stop`, SessionEnd
→ clear.

Yellow is deliberately **not** driven by Notification alone. `idle_prompt`
fires 60 s after every finished turn with nobody typing, which turned an idle
green light yellow by itself; `permission_prompt` only fires after the prompt
has waited ~6 s; and an `AskUserQuestion` prompt raises no notification at all.
So the prompt events drive both edges directly and the Notification matcher
keeps only the types that have no event of their own.

PostToolUse fires on every tool call. It is the price of the yellow→red edge
after a permission prompt is approved: the tool then just runs, and nothing
else reports it. Every hook but SessionEnd carries `"async": true`, so none of
them can delay the agent; SessionEnd stays synchronous because an async hook
is killed at teardown and its session file would outlive the session.

## Invariants

- **A hook must never fail or block.** `set`, `stop` and `clear` always exit 0, on
  every error path, and errors go to the size-capped log
  (`%LOCALAPPDATA%\claude-code-traffic-light\led.log`), **never** to stderr —
  hook stderr can surface in the Claude Code UI. This outranks correctness of
  the light. `status` and `selftest` are for humans and do report failure via
  exit code.
- **DTR and RTS are cleared before the port is opened**, not after. On a CH340
  those lines drive the auto-reset circuit; asserting them would reboot the
  ESP32 on every hook invocation, and clearing them after open is already one
  reset too late. Verified 2026-09-02.
- Config loading tolerates every failure mode — missing, unreadable,
  malformed, wrong types — and returns a usable config instead of raising.
- Moving or deleting this repo breaks the light silently, because the hooks
  hold absolute paths and hook mode reports nothing. Re-run
  `host/install_hooks.py`.
