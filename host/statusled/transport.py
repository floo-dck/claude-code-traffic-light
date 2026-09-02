"""Talking to the ESP32 over USB serial, defensively.

The caller is normally a Claude Code hook, so nothing in here may raise and
nothing may block for long. Failure is reported as a return value.
"""

import time

from serial import Serial, SerialException
from serial.tools import list_ports

# USB-serial bridges found on ESP32 development boards: CH340, CH9102, CP210x.
KNOWN_USB_IDS = frozenset(
    {
        (0x1A86, 0x7523),  # CH340
        (0x1A86, 0x55D4),  # CH9102
        (0x10C4, 0xEA60),  # CP210x
    }
)

RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 0.08
DEFAULT_DEADLINE_SECONDS = 1.5

# What the firmware answers for each command, used by the selftest.
SELFTEST_SEQUENCE = (
    ("R", "OK R"),
    ("Y", "OK Y"),
    ("G", "OK G"),
    ("O", "OK O"),
)


def detect_port(ports=None):
    """Return the device name of the first recognised bridge, or None.

    Detection means the board moving from COM3 to COM4 needs no intervention.
    An explicit port in the config always takes precedence over this.
    """
    candidates = list(ports) if ports is not None else list(list_ports.comports())
    for info in candidates:
        if (info.vid, info.pid) in KNOWN_USB_IDS:
            return info.device
    return None


def open_serial(port, baud, factory=Serial):
    """Open the port without ever asserting DTR or RTS.

    On a CH340 those two lines drive the board's auto-reset circuit. Asserting
    them on open would reboot the ESP32 on every single hook invocation, which
    is why they are cleared *before* the port is opened rather than after —
    afterwards is already one reset too late.
    """
    handle = factory()
    handle.port = port
    handle.baudrate = baud
    handle.timeout = 0.3
    handle.write_timeout = 0.3
    handle.dtr = False
    handle.rts = False
    handle.open()
    return handle


def send_command(
    command,
    port,
    baud,
    deadline=None,
    factory=Serial,
    sleep=time.sleep,
    monotonic=time.monotonic,
):
    """Write one command, retrying while the port is held by someone else.

    Returns (True, None) once the bytes reach the driver, or (False, reason).
    Never raises: a hook that crashes is worse than a light that is briefly
    wrong. A port can legitimately be busy — another session's hook, or an
    open `pio device monitor` — so a short retry is worth the wait.
    """
    limit = DEFAULT_DEADLINE_SECONDS if deadline is None else deadline
    started = monotonic()
    last_error = None

    for attempt in range(RETRY_ATTEMPTS):
        if monotonic() - started > limit:
            return False, "deadline exceeded after %d attempt(s)" % attempt

        handle = None
        try:
            handle = open_serial(port, baud, factory=factory)
            handle.write((command + "\n").encode("ascii"))
            handle.flush()
            return True, None
        except (SerialException, OSError, ValueError) as error:
            last_error = error
        finally:
            if handle is not None:
                try:
                    handle.close()
                except OSError:
                    pass

        if attempt + 1 < RETRY_ATTEMPTS:
            sleep(RETRY_BACKOFF_SECONDS)

    return False, str(last_error) if last_error else "unknown failure"


def run_selftest(port, baud, factory=Serial, sleep=time.sleep):
    """Drive every colour in turn and collect the firmware's replies.

    Returns a list of (command, expected, reply, ok). Unlike send_command this
    holds the port open across the whole sequence and reads the
    acknowledgements, which is what makes it a check of the entire chain
    through to the chip rather than just of the host side.
    """
    results = []
    handle = open_serial(port, baud, factory=factory)
    try:
        handle.timeout = 1.0
        for command, expected in SELFTEST_SEQUENCE:
            handle.reset_input_buffer()
            handle.write((command + "\n").encode("ascii"))
            handle.flush()
            reply = handle.readline().decode("ascii", "replace").strip()
            results.append((command, expected, reply, reply == expected))
            sleep(0.6)
    finally:
        try:
            handle.close()
        except OSError:
            pass
    return results
