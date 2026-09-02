"""The merge must be surgical. These tests exist because the target file is
the user's live Claude Code configuration."""

import json

import install_hooks

PYTHON = "C:/repo/.venv/Scripts/python.exe"
CLI = "C:/repo/host/claude_status_led.py"

# A faithful copy of the shape of the real settings file.
EXISTING = {
    "model": "opus[1m]",
    "theme": "dark",
    "statusLine": {"type": "command", "command": "powershell.exe -File x.ps1"},
    "enabledPlugins": {"superpowers@claude-plugins-official": True},
}


def _commands(settings, event):
    return [h["command"] for entry in settings["hooks"][event] for h in entry["hooks"]]


def test_all_five_events_are_installed():
    merged = install_hooks.merge_hooks({}, PYTHON, CLI)
    assert set(merged["hooks"]) == {
        "SessionStart",
        "UserPromptSubmit",
        "Notification",
        "Stop",
        "SessionEnd",
    }


def test_each_event_gets_the_right_subcommand():
    merged = install_hooks.merge_hooks({}, PYTHON, CLI)
    assert _commands(merged, "UserPromptSubmit")[0].endswith("set working")
    assert _commands(merged, "Notification")[0].endswith("set blocked")
    assert _commands(merged, "Stop")[0].endswith("set idle")
    assert _commands(merged, "SessionStart")[0].endswith("set idle")
    assert _commands(merged, "SessionEnd")[0].endswith("clear")


def test_paths_are_quoted_so_spaces_survive():
    command = install_hooks.build_command(
        "C:/Program Files/py.exe", "C:/my repo/cli.py", ["set", "idle"]
    )
    assert command == '"C:/Program Files/py.exe" "C:/my repo/cli.py" set idle'


def test_unrelated_settings_are_untouched():
    merged = install_hooks.merge_hooks(EXISTING, PYTHON, CLI)
    for key, value in EXISTING.items():
        assert merged[key] == value


def test_the_input_dictionary_is_not_mutated():
    original = json.dumps(EXISTING, sort_keys=True)
    install_hooks.merge_hooks(EXISTING, PYTHON, CLI)
    assert json.dumps(EXISTING, sort_keys=True) == original


def test_somebody_elses_hook_on_the_same_event_survives():
    settings = {
        "hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": "echo other tool"}]}]
        }
    }
    merged = install_hooks.merge_hooks(settings, PYTHON, CLI)
    commands = _commands(merged, "Stop")
    assert "echo other tool" in commands
    assert any(install_hooks.MARKER in c for c in commands)


def test_installing_twice_does_not_duplicate_entries():
    once = install_hooks.merge_hooks({}, PYTHON, CLI)
    twice = install_hooks.merge_hooks(once, PYTHON, CLI)
    assert twice == once
    assert len(twice["hooks"]["Stop"]) == 1


def test_reinstalling_from_a_moved_repository_replaces_the_old_path():
    # The old entry has to name the CLI, because that name is the marker by
    # which an entry is recognised as ours.
    once = install_hooks.merge_hooks(
        {}, "C:/old/.venv/python.exe", "C:/old/host/claude_status_led.py"
    )
    twice = install_hooks.merge_hooks(once, PYTHON, CLI)
    commands = _commands(twice, "Stop")
    assert len(commands) == 1
    assert "C:/old" not in commands[0]


def test_a_hooks_key_of_the_wrong_type_is_replaced():
    merged = install_hooks.merge_hooks({"hooks": "nonsense"}, PYTHON, CLI)
    assert isinstance(merged["hooks"], dict)
    assert "Stop" in merged["hooks"]


def test_uninstalling_removes_only_our_entries():
    settings = install_hooks.merge_hooks(
        {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo other"}]}]}},
        PYTHON,
        CLI,
    )
    stripped = install_hooks.remove_hooks(settings)
    assert _commands(stripped, "Stop") == ["echo other"]
    assert "UserPromptSubmit" not in stripped["hooks"]


def test_uninstalling_drops_the_hooks_key_when_nothing_is_left():
    settings = install_hooks.merge_hooks({"model": "opus[1m]"}, PYTHON, CLI)
    stripped = install_hooks.remove_hooks(settings)
    assert "hooks" not in stripped
    assert stripped["model"] == "opus[1m]"


def test_uninstalling_a_clean_file_changes_nothing():
    assert install_hooks.remove_hooks(dict(EXISTING)) == EXISTING


def test_writing_makes_a_backup_and_leaves_valid_json(tmp_path):
    target = tmp_path / "settings.json"
    target.write_text(json.dumps(EXISTING), encoding="utf-8")
    assert install_hooks.main(["--settings", str(target), "--python", PYTHON, "--cli", CLI]) == 0

    written = json.loads(target.read_text(encoding="utf-8"))
    assert written["model"] == "opus[1m]"
    assert "hooks" in written
    backup = tmp_path / "settings.json.bak"
    assert json.loads(backup.read_text(encoding="utf-8")) == EXISTING


def test_writing_into_a_missing_file_starts_from_scratch(tmp_path):
    target = tmp_path / "new.json"
    assert install_hooks.main(["--settings", str(target), "--python", PYTHON, "--cli", CLI]) == 0
    assert "hooks" in json.loads(target.read_text(encoding="utf-8"))


def test_a_corrupt_settings_file_is_refused_rather_than_overwritten(tmp_path):
    target = tmp_path / "settings.json"
    target.write_text("{ broken", encoding="utf-8")
    assert install_hooks.main(["--settings", str(target), "--python", PYTHON, "--cli", CLI]) == 1
    # Refusing to guess is the point: the user's file is left exactly as it was.
    assert target.read_text(encoding="utf-8") == "{ broken"
