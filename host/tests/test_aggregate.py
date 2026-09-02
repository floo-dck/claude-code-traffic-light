"""The priority rule is the heart of the project, so it gets exhaustive tests."""

import pytest

from statusled.aggregate import (
    COMMAND_GREEN,
    COMMAND_OFF,
    COMMAND_RED,
    COMMAND_YELLOW,
    aggregate,
)


def test_no_sessions_turns_the_light_off():
    assert aggregate([]) == COMMAND_OFF


@pytest.mark.parametrize(
    "states,expected",
    [
        (["idle"], COMMAND_GREEN),
        (["working"], COMMAND_RED),
        (["blocked"], COMMAND_YELLOW),
        (["off"], COMMAND_OFF),
    ],
)
def test_a_single_session_maps_to_its_own_colour(states, expected):
    assert aggregate(states) == expected


@pytest.mark.parametrize(
    "states,expected",
    [
        (["idle", "working"], COMMAND_RED),
        (["working", "idle"], COMMAND_RED),
        (["working", "blocked"], COMMAND_YELLOW),
        (["blocked", "working"], COMMAND_YELLOW),
        (["idle", "blocked"], COMMAND_YELLOW),
        (["idle", "working", "blocked"], COMMAND_YELLOW),
        (["off", "idle"], COMMAND_GREEN),
        (["off", "working"], COMMAND_RED),
    ],
)
def test_the_most_urgent_session_wins(states, expected):
    assert aggregate(states) == expected


@pytest.mark.parametrize(
    "states,expected",
    [
        (["idle", "idle"], COMMAND_GREEN),
        (["working", "working", "working"], COMMAND_RED),
        (["blocked", "blocked"], COMMAND_YELLOW),
    ],
)
def test_repeats_within_one_priority_level_are_harmless(states, expected):
    assert aggregate(states) == expected


def test_unknown_states_are_ignored_rather_than_blanking_the_light():
    # A state written by a newer CLI must never make the light go dark.
    assert aggregate(["bogus"]) == COMMAND_OFF
    assert aggregate(["bogus", "working"]) == COMMAND_RED
    assert aggregate(["bogus", "blocked", "idle"]) == COMMAND_YELLOW


def test_a_generator_is_accepted():
    assert aggregate(s for s in ["idle", "blocked"]) == COMMAND_YELLOW
