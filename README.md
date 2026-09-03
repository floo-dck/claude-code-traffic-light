# 🚦 claude-code-traffic-light

A traffic-light status indicator for Claude Code, driven by an ESP32 over USB
serial. Three LEDs mirror what the agent is doing, so you can tell at a glance
whether it is still working, waiting on you, or done.

| LED | Meaning                                       |
| --- | --------------------------------------------- |
| 🔴  | Working                                       |
| 🟡  | Blocked: waiting for your input or a decision |
| 🟢  | Idle: the turn is finished                    |
| ⚫  | No live session                               |

## 💡 How it works

```
 Claude Code hooks            host CLI
┌──────────────┐  hook JSON  ┌───────────────────┐
│ SessionStart │  on stdin   │ traffic_light.py  │
│ UserPrompt   │ ──────────▶ │    set / clear    │
│ Notification │             └─────────┬─────────┘
│ Stop         │                       │ one file per session
│ SessionEnd   │                       ▼
└──────────────┘   %LOCALAPPDATA%\claude-code-traffic-light\sessions\
                                       │
                                       ▼
                             ┌───────────────────┐
                             │     aggregate     │
                             │ blocked > working │
                             │   > idle > off    │
                             └─────────┬─────────┘
 ESP32                                 │ one byte: R / Y / G / O
┌──────────────┐                       │
│ GPIO 25/26/27│ ◀─────────────────────┘
│ 🔴 🟡 🟢     │      USB serial, 115200 baud
└──────────────┘
```

Each hook fires the CLI, which writes **only its own session's file** — that is
what removes cross-process locking on Windows, where two Claude Code windows
would otherwise fight over one state file. The aggregation step then reduces
every live session to a single colour, with a fixed priority: "somebody needs
you" must always outrank "still working".

The board is a dumb slave. It knows four commands and nothing about Claude
Code, so changing what the light means never requires reflashing.

The onboard LED on GPIO2 carries the same three states through timing, since
one monochrome LED cannot show a colour: red is solid, yellow blinks every
150 ms, green is an 80 ms heartbeat every 2 s. That makes the whole chain
verifiable before a single external LED is wired up.

## ⚙️ Setup

1. Create the venv and install the host dependencies:

   ```bash
   py -3.11 -m venv .venv
   .venv\Scripts\python.exe -m pip install -r host\requirements.txt
   ```

2. Flash the firmware:

   ```bash
   .venv\Scripts\python.exe -m platformio run --project-dir firmware --target upload
   ```

   > ⚠️ Hold the BOOT button through `Connecting....` and release it once the
   > chip is identified. This board's auto-program circuit does not pull GPIO0
   > low, so without it the upload fails with
   > `Wrong boot mode detected (0x13)` — and holding it too long leaves the
   > chip in download mode, where nothing answers on serial.

3. Install the hooks into `~/.claude/settings.json`:

   ```bash
   .venv\Scripts\python.exe host\install_hooks.py
   ```

   Only entries that mention `traffic_light.py` are touched, so unrelated
   hooks survive. Re-running is safe, and is how you repoint the hooks after
   moving the repo.

4. **Restart Claude Code** — hooks are only read at startup.

Wiring (GPIO25/26/27, 220 Ω each, active high) is in
[docs/wiring.md](docs/wiring.md).

## 🔍 Checking it

```bash
.venv\Scripts\python.exe host\traffic_light.py selftest   # drive all colours
.venv\Scripts\python.exe host\traffic_light.py status     # what should be lit, and why
```

### Nothing lights up

- Close any `pio device monitor` first — it holds the serial port.
- Watch the onboard LED (GPIO2). If it follows the states, the host half works
  and the problem is in the wiring.
- Hook errors are never printed to the terminal — a hook must not interrupt
  you — so they go to `%LOCALAPPDATA%\claude-code-traffic-light\led.log`.
- Moved the repo? The hooks hold absolute paths. Re-run `install_hooks.py`.

To remove the hooks again:

```bash
.venv\Scripts\python.exe host\install_hooks.py --uninstall
```

## 🧪 Development

```bash
.venv\Scripts\python.exe -m pytest host\tests -v
```

Tests never touch real hardware or the real settings file. The design, its
open hardware questions and its rejected alternatives are in
[docs/superpowers/specs](docs/superpowers/specs/2026-09-02-claude-status-led-design.md).

## 📄 Licence

MIT — see [LICENSE](LICENSE).

Not affiliated with or endorsed by Anthropic. Claude is a trademark of
Anthropic PBC.
