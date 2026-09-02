# claude-status-led

A traffic-light status indicator for Claude Code, driven by an ESP32 over USB
serial. Three LEDs mirror what the agent is doing, so you can tell at a glance
whether it is still working, waiting on you, or done.

| LED    | Meaning                                        |
| ------ | ---------------------------------------------- |
| Red    | Claude Code is working                         |
| Yellow | Blocked: waiting for your input or a decision  |
| Green  | Idle: the turn is finished                     |

Design and implementation notes live in `docs/`.

## How it works

Claude Code hooks report each session's state to a small Python CLI. The CLI
writes one state file per session, reduces every live session to a single
colour (`blocked` beats `working` beats `idle`), and sends one character over
USB serial to an ESP32 that drives the three LEDs.

## Setup

```bash
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r host\requirements.txt
.venv\Scripts\python.exe -m platformio run --project-dir firmware --target upload
.venv\Scripts\python.exe host\install_hooks.py
```

Hooks are read at startup, so restart Claude Code afterwards. Wiring is in
[docs/wiring.md](docs/wiring.md).

## Checking it

```bash
.venv\Scripts\python.exe host\claude_status_led.py selftest   # drive all colours
.venv\Scripts\python.exe host\claude_status_led.py status     # what should be lit, and why
```

Errors are never printed to the terminal — a hook must not interrupt you — so
look in `%LOCALAPPDATA%\claude-status-led\led.log`.

To remove the hooks again:

```bash
.venv\Scripts\python.exe host\install_hooks.py --uninstall
```

## Development

```bash
.venv\Scripts\python.exe -m pytest host\tests -v
```

The design and its rejected alternatives are in
[docs/superpowers/specs](docs/superpowers/specs/2026-09-02-claude-status-led-design.md).
