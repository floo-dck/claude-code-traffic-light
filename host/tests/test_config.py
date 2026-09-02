"""Configuration must degrade to defaults rather than fail: a hook that
crashes on a typo in config.json would break Claude Code."""

import json

from statusled import config


def test_defaults_apply_when_the_file_is_missing(tmp_path):
    loaded = config.load_config(tmp_path / "nope.json")
    assert loaded == {"port": None, "baud": 115200, "stale_after_minutes": 120}


def test_a_partial_file_is_merged_over_the_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"port": "COM7"}), encoding="utf-8")
    loaded = config.load_config(path)
    assert loaded["port"] == "COM7"
    assert loaded["baud"] == 115200
    assert loaded["stale_after_minutes"] == 120


def test_unknown_keys_are_dropped(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"port": "COM7", "nonsense": 1}), encoding="utf-8")
    assert set(config.load_config(path)) == set(config.DEFAULTS)


def test_broken_json_falls_back_to_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    assert config.load_config(path) == config.DEFAULTS


def test_a_non_object_document_falls_back_to_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert config.load_config(path) == config.DEFAULTS


def test_an_unusable_baud_is_replaced(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"baud": "fast"}), encoding="utf-8")
    assert config.load_config(path)["baud"] == 115200


def test_a_non_positive_staleness_window_is_replaced(tmp_path):
    # A zero window would treat every session as stale and pin the light off.
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"stale_after_minutes": 0}), encoding="utf-8")
    assert config.load_config(path)["stale_after_minutes"] == 120


def test_the_home_override_redirects_every_path(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_STATUS_LED_HOME", str(tmp_path))
    assert config.data_dir() == tmp_path
    assert config.sessions_dir() == tmp_path / "sessions"
    assert config.config_path() == tmp_path / "config.json"
    assert config.log_path() == tmp_path / "led.log"


def test_localappdata_is_used_when_there_is_no_override(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_STATUS_LED_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert config.data_dir() == tmp_path / "claude-status-led"
