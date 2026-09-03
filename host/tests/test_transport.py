"""Transport is tested against a fake serial port: the retry and deadline
behaviour is exactly what must not be verified by hand."""

from serial import SerialException

from trafficlight import transport


class FakePort:
    """Minimal stand-in for serial.Serial.

    Records what was written and can be told to fail a number of opens, which
    is how a port held by another process behaves.
    """

    def __init__(self, fail_opens=0, error=None, replies=None):
        self.port = None
        self.baudrate = None
        self.timeout = None
        self.write_timeout = None
        self.dtr = None
        self.rts = None
        self.dtr_at_open = None
        self.rts_at_open = None
        self.opens = 0
        self.closes = 0
        self.written = []
        self.flushes = 0
        self._fail_opens = fail_opens
        self._error = error or SerialException("port busy")
        self._replies = list(replies or [])

    def open(self):
        self.opens += 1
        if self.opens <= self._fail_opens:
            raise self._error
        # Captured so a test can prove the lines were cleared before open.
        self.dtr_at_open = self.dtr
        self.rts_at_open = self.rts

    def write(self, payload):
        self.written.append(payload)
        return len(payload)

    def flush(self):
        self.flushes += 1

    def close(self):
        self.closes += 1

    def reset_input_buffer(self):
        pass

    def readline(self):
        if not self._replies:
            return b""
        return self._replies.pop(0)


class FakeInfo:
    """Stand-in for serial.tools.list_ports_common.ListPortInfo."""

    def __init__(self, device, vid, pid):
        self.device = device
        self.vid = vid
        self.pid = pid


def test_a_ch340_bridge_is_detected():
    ports = [FakeInfo("COM1", None, None), FakeInfo("COM3", 0x1A86, 0x7523)]
    assert transport.detect_port(ports) == "COM3"


def test_a_cp210x_bridge_is_detected():
    assert transport.detect_port([FakeInfo("COM5", 0x10C4, 0xEA60)]) == "COM5"


def test_an_unknown_device_is_not_detected():
    assert transport.detect_port([FakeInfo("COM1", 0x1234, 0x5678)]) is None


def test_no_ports_at_all_detects_nothing():
    assert transport.detect_port([]) is None


def test_the_first_recognised_port_wins():
    ports = [FakeInfo("COM3", 0x1A86, 0x7523), FakeInfo("COM4", 0x10C4, 0xEA60)]
    assert transport.detect_port(ports) == "COM3"


def test_the_control_lines_are_cleared_before_the_port_opens():
    # On a CH340 these lines drive the auto-reset circuit. Clearing them after
    # opening would already be one reset too late.
    fake = FakePort()
    transport.open_serial("COM3", 115200, factory=lambda: fake)
    assert fake.dtr_at_open is False
    assert fake.rts_at_open is False
    assert fake.port == "COM3"
    assert fake.baudrate == 115200


def test_a_command_is_sent_with_a_trailing_newline():
    fake = FakePort()
    ok, error = transport.send_command("R", "COM3", 115200, factory=lambda: fake)
    assert (ok, error) == (True, None)
    assert fake.written == [b"R\n"]
    assert fake.closes == 1


def test_a_busy_port_is_retried_and_then_succeeds():
    fake = FakePort(fail_opens=2)
    slept = []
    ok, error = transport.send_command(
        "G", "COM3", 115200, factory=lambda: fake, sleep=slept.append
    )
    assert ok is True
    assert fake.opens == 3
    assert len(slept) == 2


def test_a_permanently_busy_port_gives_up_without_raising():
    fake = FakePort(fail_opens=99)
    ok, error = transport.send_command(
        "Y", "COM3", 115200, factory=lambda: fake, sleep=lambda _s: None
    )
    assert ok is False
    assert "busy" in error
    assert fake.opens == transport.RETRY_ATTEMPTS


def test_the_port_is_closed_even_when_the_write_fails():
    class ExplodingPort(FakePort):
        def write(self, payload):
            raise SerialException("cable yanked")

    fake = ExplodingPort()
    ok, _error = transport.send_command(
        "R", "COM3", 115200, factory=lambda: fake, sleep=lambda _s: None
    )
    assert ok is False
    assert fake.closes == transport.RETRY_ATTEMPTS


def test_an_exceeded_deadline_stops_the_retries():
    fake = FakePort(fail_opens=99)
    clock = iter([0.0, 0.0, 99.0, 99.0])
    ok, error = transport.send_command(
        "R",
        "COM3",
        115200,
        factory=lambda: fake,
        sleep=lambda _s: None,
        monotonic=lambda: next(clock),
    )
    assert ok is False
    assert "deadline" in error
    assert fake.opens == 1


def test_the_selftest_reports_every_matching_acknowledgement():
    fake = FakePort(replies=[b"OK R\n", b"OK Y\n", b"OK G\n", b"OK O\n"])
    results = transport.run_selftest(
        "COM3", 115200, factory=lambda: fake, sleep=lambda _s: None
    )
    assert [r[0] for r in results] == ["R", "Y", "G", "O"]
    assert all(r[3] for r in results)
    assert fake.closes == 1


def test_the_selftest_flags_a_wrong_acknowledgement():
    fake = FakePort(replies=[b"OK R\n", b"ERR\n", b"OK G\n", b""])
    results = transport.run_selftest(
        "COM3", 115200, factory=lambda: fake, sleep=lambda _s: None
    )
    assert [r[3] for r in results] == [True, False, True, False]
    assert results[1][2] == "ERR"
    assert results[3][2] == ""
