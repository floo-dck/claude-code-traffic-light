"""The store is where concurrency and crash recovery actually happen, so the
tests cover partial files, stale files and hostile session ids."""

import json
from datetime import datetime, timedelta, timezone

from trafficlight import store

NOW = datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc)


def test_a_written_state_reads_back(tmp_path):
    store.write_state(tmp_path, "abc", "working", now=NOW)
    assert store.read_live_states(tmp_path, 120, now=NOW) == ["working"]


def test_the_sessions_directory_is_created_on_demand(tmp_path):
    target = tmp_path / "deep" / "sessions"
    store.write_state(target, "abc", "idle", now=NOW)
    assert target.is_dir()


def test_the_record_carries_context_for_debugging(tmp_path):
    path = store.write_state(
        tmp_path, "abc", "blocked", cwd="C:/work", hook_event="Notification", now=NOW
    )
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["state"] == "blocked"
    assert record["cwd"] == "C:/work"
    assert record["hook_event"] == "Notification"
    assert record["updated_at"] == NOW.isoformat()


def test_writing_leaves_no_temporary_files_behind(tmp_path):
    # The write is a temp-file-plus-rename, and the temp file must not linger:
    # it would otherwise be picked up as a session of its own.
    store.write_state(tmp_path, "abc", "working", now=NOW)
    assert [p.name for p in tmp_path.iterdir()] == ["abc.json"]


def test_rewriting_replaces_rather_than_duplicates(tmp_path):
    store.write_state(tmp_path, "abc", "working", now=NOW)
    store.write_state(tmp_path, "abc", "idle", now=NOW)
    assert store.read_live_states(tmp_path, 120, now=NOW) == ["idle"]


def test_every_session_contributes_one_state(tmp_path):
    store.write_state(tmp_path, "one", "working", now=NOW)
    store.write_state(tmp_path, "two", "blocked", now=NOW)
    assert sorted(store.read_live_states(tmp_path, 120, now=NOW)) == ["blocked", "working"]


def test_a_malformed_file_is_skipped_but_kept(tmp_path):
    store.write_state(tmp_path, "good", "working", now=NOW)
    broken = tmp_path / "broken.json"
    broken.write_text("{ truncated", encoding="utf-8")
    assert store.read_live_states(tmp_path, 120, now=NOW) == ["working"]
    # A transient write race must not cost that session its file.
    assert broken.exists()


def test_a_file_missing_required_fields_is_skipped(tmp_path):
    (tmp_path / "partial.json").write_text(json.dumps({"cwd": "C:/x"}), encoding="utf-8")
    assert store.read_live_states(tmp_path, 120, now=NOW) == []


def test_a_non_string_state_is_skipped(tmp_path):
    (tmp_path / "weird.json").write_text(
        json.dumps({"state": 7, "updated_at": NOW.isoformat()}), encoding="utf-8"
    )
    assert store.read_live_states(tmp_path, 120, now=NOW) == []


def test_a_state_just_inside_the_window_survives(tmp_path):
    store.write_state(tmp_path, "abc", "working", now=NOW - timedelta(minutes=119))
    assert store.read_live_states(tmp_path, 120, now=NOW) == ["working"]


def test_a_stale_state_is_dropped_and_deleted(tmp_path):
    # This is the crashed-terminal case: without pruning the light stays red.
    path = store.write_state(tmp_path, "abc", "working", now=NOW - timedelta(minutes=121))
    assert store.read_live_states(tmp_path, 120, now=NOW) == []
    assert not path.exists()


def test_pruning_can_be_disabled_for_reporting(tmp_path):
    path = store.write_state(tmp_path, "abc", "working", now=NOW - timedelta(minutes=121))
    assert store.read_live_states(tmp_path, 120, now=NOW, prune=False) == []
    assert path.exists()


def test_a_timestamp_without_a_zone_is_read_as_utc(tmp_path):
    (tmp_path / "naive.json").write_text(
        json.dumps({"state": "idle", "updated_at": NOW.replace(tzinfo=None).isoformat()}),
        encoding="utf-8",
    )
    assert store.read_live_states(tmp_path, 120, now=NOW) == ["idle"]


def test_a_missing_directory_reads_as_empty(tmp_path):
    assert store.read_live_states(tmp_path / "absent", 120, now=NOW) == []


def test_a_safe_session_id_is_kept_recognisable():
    assert store.sanitise_session_id("a1B2-c3._d") == "a1B2-c3._d"


def test_a_dangerous_session_id_is_hashed():
    for hostile in ["../../etc/passwd", "C:\\evil", "with space", "", None, "x" * 200]:
        safe = store.sanitise_session_id(hostile)
        assert safe.startswith("h")
        assert "/" not in safe and "\\" not in safe and " " not in safe


def test_the_same_hostile_id_always_hashes_the_same_way():
    assert store.sanitise_session_id("a b") == store.sanitise_session_id("a b")


def test_clearing_removes_the_file(tmp_path):
    store.write_state(tmp_path, "abc", "working", now=NOW)
    assert store.clear_state(tmp_path, "abc") is True
    assert store.read_live_states(tmp_path, 120, now=NOW) == []


def test_clearing_a_missing_file_is_not_an_error(tmp_path):
    assert store.clear_state(tmp_path, "never-existed") is False
