# 🚦 claude-code-traffic-light

[![CI](https://github.com/floo-dck/claude-code-traffic-light/actions/workflows/ci.yml/badge.svg)](https://github.com/floo-dck/claude-code-traffic-light/actions/workflows/ci.yml)

A traffic-light status indicator for Claude Code, driven by an ESP32 over USB
serial. Three LEDs mirror what the agent is doing, so you can tell at a glance
whether it is still working, waiting on you, or done.

![Four traffic lights: red for working, yellow for blocked, green for idle, all dark for no session](assets/traffic-light.svg)

| LED | Meaning                                       |
| --- | --------------------------------------------- |
| 🔴  | Working                                       |
| 🟡  | Blocked: waiting for your input or a decision |
| 🟢  | Idle: the turn is finished                    |
| ⚫  | No live session                               |

## 🚦 When each colour shows

Yellow is reserved for "you are needed": a question you have to answer, and
nothing else. Both edges are driven by the event that raises the prompt, so
the light turns the moment the prompt appears and turns back the moment you
answer it.

| Situation                                        | LED | Raised by / cleared by                       |
| ------------------------------------------------ | --- | -------------------------------------------- |
| You send a prompt; Claude thinks or runs a tool   | 🔴  | `UserPromptSubmit`, `PostToolUse`            |
| Multiple-choice question (`AskUserQuestion`)      | 🟡  | `PreToolUse` → `PostToolUse`                 |
| Permission prompt (allow / deny a tool)           | 🟡  | `PermissionRequest` → `PostToolUse` / `PermissionDenied` |
| MCP server opens an elicitation form              | 🟡  | `Elicitation` → `ElicitationResult`          |
| The turn ends by asking you something in prose    | 🟡  | `Stop`                                       |
| The turn ends with a statement                    | 🟢  | `Stop`                                       |
| Nobody types for a minute after a finished turn   | 🟢  | nothing — `idle_prompt` is not wired up      |
| Session ends                                      | ⚫  | `SessionEnd`                                 |

That last row is the one worth spelling out: Claude Code's `idle_prompt`
notification fires 60 s after *every* finished turn with nobody typing.
Treating it as "blocked" is what used to turn a quiet green light yellow all
by itself, so the `Notification` hook keeps only the prompt types that have no
event of their own.

### Asking in prose

A question typed in a message raises no hook at all, so at `Stop` the CLI
reads Claude's last message and decides for itself. It walks the last lines
backwards, stepping over option lists and fenced code blocks, and stops at the
first line that is neither — so the question can sit above what it is about:

~~~text
Done, all tests pass.                     🟢  a statement ends the turn

Shall I commit this?                      🟡  ends in a question

Which one should I build?
- Option A: the hook only                 🟡  options are stepped over
- Option B: the hook and its test

Does this look right?
```diff                                   🟡  code blocks are stepped over
-    for line in reversed(lines):
```

Done:
- fixed the bug                           🟢  a report that ends in a list
- added a test
~~~

The walk gives up after twelve lines, and a whole code block counts as one, so
a question buried above a long summary does not keep the light yellow.

## 💡 How it works

```
 Claude Code hooks            host CLI
┌──────────────┐  hook JSON  ┌───────────────────┐
│ SessionStart │  on stdin   │ traffic_light.py  │
│ UserPrompt   │ ──────────▶ │ set / stop / clear│
│ Pre/PostTool │             └─────────┬─────────┘
│ Permission…  │                       │ one file per session
│ Notification │                       ▼
│ Stop         │   %LOCALAPPDATA%\claude-code-traffic-light\sessions\
│ SessionEnd   │                       │
└──────────────┘                       ▼
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

Every hook but `SessionEnd` carries `"async": true`, so none of them can delay
the agent — that is what makes a hook on every tool call affordable, and a
tool call is the only signal that an approved permission prompt was answered.
`SessionEnd` stays synchronous, because an async hook is killed at teardown
and its session file would outlive the session.

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

One thing is deliberately not clean. The principle is that the board is a dumb
slave and every decision about meaning lives on the host — but the *blink
patterns* of the onboard LED are decided in the firmware, because the host
sends one character per state and nothing else. Moving the patterns to the host
would mean a richer protocol on the wire and more work in a code path that must
never fail. Keeping the protocol at one character was judged worth more than
the purity.

## ⚙️ Setup

1. Create the venv and install the host dependencies:

   ```bash
   py -3.11 -m venv .venv
   .venv\Scripts\python.exe -m pip install -r host\requirements.txt
   ```

2. Flash the firmware:

   ```bash
   .venv\Scripts\python.exe -m platformio run --project-dir firmware -e esp32dev --target upload
   ```

   > Keep the `-e esp32dev`. Two environments are defined, and without it
   > PlatformIO flashes both one after the other, leaving the board running the
   > common-anode build on pins 18/19/21. Pass `-e esp32dev_common_anode`
   > instead if that is the board you have.

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

Wiring — LEDs are active high, GPIO drives the anode through a series
resistor, cathode (the short leg) to ground:

```
GPIO25 ──[220Ω]──▶|── GND   (red)
GPIO26 ──[220Ω]──▶|── GND   (yellow)
GPIO27 ──[220Ω]──▶|── GND   (green)
```

![Wiring diagram: GPIO25, 26 and 27 each drive an LED anode through a 220 ohm series resistor, with the red, yellow and green cathodes returning to a shared ground rail](assets/wiring.svg)

An ESP32 pin sources only about 12 mA, so the resistor is not optional.

On a breadboard, straddle the module across the centre channel and run a jumper
from a `GND` pin to the blue rail. The module body covers rows b to i, so row a
is the only hole of a pin column you can still reach:

![Breadboard layout: the ESP32 DevKit straddles the centre channel with its headers in rows b and j, a jumper ties a board GND pin to the lower blue rail, and GPIO25, 26 and 27 each reach a free column through a 220 ohm resistor whose column carries the LED anode in row a](assets/breadboard.svg)

Reset the board: red, yellow and green light for 200 ms each in turn. Any
colour missing from that sweep is a wiring fault on that leg.

Different pins or a common-anode module (KY-009 and clones): the defaults in
[`firmware/include/pins.h`](firmware/include/pins.h) are all `#ifndef`-guarded,
so build flags override them — see `env:esp32dev_common_anode` in
`firmware/platformio.ini`.

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

## 🖥️ Platforms

Developed and verified on Windows. The host tests also run on Linux in CI, so
the pure-Python half is known to work there. The serial path on Linux and macOS
is **untested** — port detection goes through `pyserial` by USB vendor and
product ID, which is portable by construction, but nobody has run it against a
board on either system.

## 🧪 Development

```bash
.venv\Scripts\python.exe -m pytest host\tests -v
```

Tests never touch real hardware or the real settings file.

## 📄 Licence

MIT — see [LICENSE](LICENSE).
