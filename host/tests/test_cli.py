"""The one behaviour that matters more than the light being right: hook mode
must never fail. Every test here that asserts an exit code of 0 is guarding
Claude Code against this tool."""

import io
import json

import pytest

import claude_status_led as cli
from statusled import store


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Keep every test out of the real %LOCALAPPDATA%."""
    monkeypatch.setenv("CLAUDE_STATUS_LED_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def sent(monkeypatch):
    """Capture what would have gone to the serial port."""
    captured = []

    def fake_send(command, port, baud, **_kwargs):
        captured.append((command, port, baud))
        return True, None

    monkeypatch.setattr(cli.transport, "send_command", fake_send)
    monkeypatch.setattr(cli.transport, "detect_port", lambda *a, **k: "COM9")
    return captured


def _stdin(monkeypatch, payload):
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(json.dumps(payload)))


def test_set_records_the_state_and_sends_the_colour(monkeypatch, isolated_home, sent):
    _stdin(monkeypatch, {"session_id": "sess-1", "cwd": "C:/work", "hook_event_name": "Stop"})
    assert cli.main(["set", "idle"]) == 0
    assert sent == [("G", "COM9", 115200)]
    record = json.loads((isolated_home / "sessions" / "sess-1.json").read_text(encoding="utf-8"))
    assert record["state"] == "idle"
    assert record["cwd"] == "C:/work"
    assert record["hook_event"] == "Stop"


def test_the_most_urgent_of_several_sessions_wins(monkeypatch, isolated_home, sent):
    store.write_state(isolated_home / "sessions", "other", "blocked")
    _stdin(monkeypatch, {"session_id": "mine"})
    assert cli.main(["set", "working"]) == 0
    assert sent[-1][0] == "Y"


def test_the_session_flag_overrides_the_payload(monkeypatch, isolated_home, sent):
    _stdin(monkeypatch, {"session_id": "from-payload"})
    assert cli.main(["set", "working", "--session", "from-flag"]) == 0
    assert (isolated_home / "sessions" / "from-flag.json").exists()


def test_garbage_on_stdin_does_not_stop_the_light(monkeypatch, isolated_home, sent):
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("not json at all"))
    assert cli.main(["set", "working"]) == 0
    assert sent[-1][0] == "R"


def test_a_json_array_on_stdin_is_ignored(monkeypatch, isolated_home, sent):
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("[1, 2, 3]"))
    assert cli.main(["set", "blocked"]) == 0
    assert sent[-1][0] == "Y"


def test_set_exits_zero_when_no_port_can_be_found(monkeypatch, isolated_home):
    monkeypatch.setattr(cli.transport, "detect_port", lambda *a, **k: None)
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(""))
    assert cli.main(["set", "working"]) == 0


def test_set_exits_zero_when_the_transport_explodes(monkeypatch, isolated_home):
    def boom(*_args, **_kwargs):
        raise RuntimeError("USB is on fire")

    monkeypatch.setattr(cli.transport, "detect_port", lambda *a, **k: "COM9")
    monkeypatch.setattr(cli.transport, "send_command", boom)
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(""))
    assert cli.main(["set", "working"]) == 0


def test_set_exits_zero_when_the_state_cannot_be_written(monkeypatch, isolated_home):
    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(cli.store, "write_state", boom)
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(""))
    assert cli.main(["set", "working"]) == 0


def test_failures_are_logged_to_a_file_and_never_to_stderr(monkeypatch, isolated_home, capsys):
    monkeypatch.setattr(cli.transport, "detect_port", lambda *a, **k: None)
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(""))
    cli.main(["set", "working"])
    assert capsys.readouterr().err == ""
    assert "no serial port" in (isolated_home / "led.log").read_text(encoding="utf-8")


def test_the_log_is_rotated_once_it_grows_too_large(isolated_home):
    log = isolated_home / "led.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("x" * (cli.LOG_MAX_BYTES + 1), encoding="utf-8")
    cli._log("fresh entry")
    assert (isolated_home / "led.log.1").exists()
    assert log.read_text(encoding="utf-8").endswith("fresh entry\n")


def test_clear_removes_the_session_and_updates_the_light(monkeypatch, isolated_home, sent):
    store.write_state(isolated_home / "sessions", "sess-1", "working")
    _stdin(monkeypatch, {"session_id": "sess-1"})
    assert cli.main(["clear"]) == 0
    assert not (isolated_home / "sessions" / "sess-1.json").exists()
    # No sessions left, so the light goes out rather than staying red.
    assert sent[-1][0] == "O"


def test_clear_exits_zero_for_a_session_that_never_existed(monkeypatch, isolated_home, sent):
    _stdin(monkeypatch, {"session_id": "ghost"})
    assert cli.main(["clear"]) == 0


def test_status_reports_the_aggregate_without_pruning(monkeypatch, isolated_home, capsys):
    store.write_state(isolated_home / "sessions", "sess-1", "blocked")
    monkeypatch.setattr(cli.transport, "detect_port", lambda *a, **k: "COM9")
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "COM9" in out
    assert "blocked" in out
    assert "Y" in out


def test_status_reports_failure_when_there_is_no_port(monkeypatch, isolated_home):
    monkeypatch.setattr(cli.transport, "detect_port", lambda *a, **k: None)
    assert cli.main(["status"]) == 1


def test_selftest_passes_when_every_reply_matches(monkeypatch, isolated_home, capsys):
    monkeypatch.setattr(cli.transport, "detect_port", lambda *a, **k: "COM9")
    monkeypatch.setattr(
        cli.transport,
        "run_selftest",
        lambda *a, **k: [(c, e, e, True) for c, e in cli.transport.SELFTEST_SEQUENCE],
    )
    assert cli.main(["selftest"]) == 0
    assert "4/4 passed" in capsys.readouterr().out


def test_selftest_reports_a_mismatch(monkeypatch, isolated_home, capsys):
    monkeypatch.setattr(cli.transport, "detect_port", lambda *a, **k: "COM9")
    monkeypatch.setattr(
        cli.transport, "run_selftest", lambda *a, **k: [("R", "OK R", "ERR", False)]
    )
    assert cli.main(["selftest"]) == 1
    assert "MISMATCH" in capsys.readouterr().out


def test_selftest_reports_a_missing_port(monkeypatch, isolated_home, capsys):
    monkeypatch.setattr(cli.transport, "detect_port", lambda *a, **k: None)
    assert cli.main(["selftest"]) == 1
    assert "no serial port" in capsys.readouterr().out.lower()
