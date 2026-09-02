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

Status: design in progress.
