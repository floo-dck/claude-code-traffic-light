"""The merge must be surgical. These tests exist because the target file is
the user's live Claude Code configuration."""

import json

import install_hooks

PYTHON = "C:/repo/.venv/Scripts/python.exe"
CLI = "C:/repo/host/traffic_light.py"

# A faithful copy of the shape of the real settings file.
EXISTING = {
    "model": "opus[1m]",
    "theme": "dark",
    "statusLine": {"type": "command", "command": "powershell.exe -File x.ps1"},
    "enabledPlugins": {"superpowers@claude-plugins-official": True},
}


def _commands(settings, event):
    return [h["command"] for entry in settings["hooks"][event] for h in entry["hooks"]]


def _entry_for(settings, event, tail):
    """The one entry of an event whose command ends in the given arguments."""
    matches = [
        entry
        for entry in settings["hooks"][event]
        if any(h["command"].endswith(tail) for h in entry["hooks"])
    ]
    assert len(matches) == 1, "expected exactly one %s entry ending in %r" % (event, tail)
    return matches[0]


def test_every_event_in_the_spec_is_installed():
    merged = install_hooks.merge_hooks({}, PYTHON, CLI)
    assert set(merged["hooks"]) == {spec["event"] for spec in install_hooks.HOOK_SPECS}


def test_each_event_gets_the_right_subcommand():
    merged = install_hooks.merge_hooks({}, PYTHON, CLI)
    assert _commands(merged, "UserPromptSubmit")[0].endswith("set working")
    assert _commands(merged, "SessionStart")[0].endswith("set idle")
    assert _commands(merged, "SessionEnd")[0].endswith("clear")
    # Stop no longer hard-codes idle: whether a finished turn is waiting on an
    # answer is decided from the assistant's last message.
    assert _commands(merged, "Stop")[0].endswith("stop")


def test_the_interactive_question_tool_drives_both_edges():
    # This is the whole point of the tool hooks: yellow the moment the question
    # appears, red the moment it is answered. Waiting for a Notification meant
    # a minute of wrong colour at each edge.
    merged = install_hooks.merge_hooks({}, PYTHON, CLI)
    ask = _entry_for(merged, "PreToolUse", "set blocked")
    assert ask["matcher"] == "AskUserQuestion"
    done = _entry_for(merged, "PostToolUse", "set working")
    assert "matcher" not in done  # every tool ends the wait, not just this one


def test_a_permission_prompt_goes_yellow_without_waiting_for_the_notification():
    merged = install_hooks.merge_hooks({}, PYTHON, CLI)
    assert _commands(merged, "PermissionRequest")[0].endswith("set blocked")
    assert _commands(merged, "PermissionDenied")[0].endswith("set working")


def test_the_notification_hook_ignores_the_idle_prompt():
    # idle_prompt fires 60 s after a turn ends with nobody typing. Treating it
    # as "blocked" is what turned an idle green light yellow on its own.
    merged = install_hooks.merge_hooks({}, PYTHON, CLI)
    entry = merged["hooks"]["Notification"][0]
    assert "idle_prompt" not in entry["matcher"]
    assert "permission_prompt" in entry["matcher"]


def test_signalling_hooks_do_not_block_the_agent():
    # A light is never worth delaying a tool call for, and PostToolUse fires on
    # every single one.
    merged = install_hooks.merge_hooks({}, PYTHON, CLI)
    for hook in merged["hooks"]["PostToolUse"][0]["hooks"]:
        assert hook["async"] is True


def test_the_session_end_hook_stays_synchronous():
    # Its whole job is to delete the session file before the process leaves;
    # an async hook is killed at teardown and the light would stay lit.
    merged = install_hooks.merge_hooks({}, PYTHON, CLI)
    for hook in merged["hooks"]["SessionEnd"][0]["hooks"]:
        assert "async" not in hook


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
        {}, "C:/old/.venv/python.exe", "C:/old/host/traffic_light.py"
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


LEGACY_CLI = "C:/old/host/claude_status_led.py"


def test_a_hook_installed_under_the_old_name_is_replaced():
    # Anyone who installed hooks before the rename has entries naming the old
    # CLI. Re-running the installer is the documented repair, so it has to
    # recognise them; otherwise they stay behind and fire a missing script.
    settings = {
        "hooks": {
            "Stop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": '"C:/old/python.exe" "%s" set idle' % LEGACY_CLI,
                        }
                    ]
                }
            ]
        }
    }
    merged = install_hooks.merge_hooks(settings, PYTHON, CLI)
    commands = _commands(merged, "Stop")
    assert len(commands) == 1
    assert "claude_status_led.py" not in commands[0]
    assert install_hooks.MARKER in commands[0]


def test_uninstalling_also_removes_hooks_installed_under_the_old_name():
    settings = {
        "hooks": {
            "Stop": [
                {"hooks": [{"type": "command", "command": '"py" "%s" set idle' % LEGACY_CLI}]},
                {"hooks": [{"type": "command", "command": "echo other tool"}]},
            ]
        }
    }
    stripped = install_hooks.remove_hooks(settings)
    assert _commands(stripped, "Stop") == ["echo other tool"]


def test_the_marker_written_into_new_entries_is_the_current_name():
    assert install_hooks.MARKER == "traffic_light.py"
    assert "claude_status_led.py" in install_hooks.LEGACY_MARKERS


def test_hooks_installed_by_the_old_single_notification_layout_are_replaced():
    # The first version registered one unfiltered Notification hook. Re-running
    # the installer is the documented repair, so that entry must not survive.
    settings = {
        "hooks": {
            "Notification": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": '"py" "%s" set blocked' % CLI,
                        }
                    ]
                }
            ]
        }
    }
    merged = install_hooks.merge_hooks(settings, PYTHON, CLI)
    assert len(merged["hooks"]["Notification"]) == 1
    assert merged["hooks"]["Notification"][0]["matcher"]
