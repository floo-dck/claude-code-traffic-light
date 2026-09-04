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
- `host/trafficlight/aggregate.py` — reduces all live states to one command
  with a fixed priority: `blocked` (Y) > `working` (R) > `idle` (G), else
  off (O).
  "Somebody needs you" must always outrank "still working". Unknown state
  names are ignored rather than blanking the light.
- `host/trafficlight/transport.py` — port detection by USB VID/PID (CH340
  1A86:7523, CH9102 1A86:55D4, CP210x 10C4:EA60); an explicit `port` in the
  config always wins. 3 retries, ~80 ms backoff, 1.5 s hard deadline, returns
  `(ok, reason)` and never raises.
- `host/traffic_light.py` — subcommands `set`, `clear`, `status`,
  `selftest`. `set`/`clear` read the hook JSON payload from stdin.
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

Hook mapping (in `install_hooks.HOOK_EVENTS`): SessionStart → idle,
UserPromptSubmit → working, Notification → blocked, Stop → idle, SessionEnd →
clear. There is no per-tool-call hook on purpose: it costs a process launch
per tool use, and the only symptom of omitting it is a light that stays yellow
until the turn ends.

## Invariants

- **A hook must never fail or block.** `set` and `clear` always exit 0, on
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
