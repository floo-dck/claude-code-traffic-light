"""Deciding whether a finished turn is still waiting on the user.

Yellow means "somebody needs you". A turn that ends in a question needs the
user just as much as a permission prompt does, so the Stop hook has to tell
the two endings apart from the assistant's last message alone.
"""

from trafficlight.question import looks_like_question


def test_a_plain_question_is_one():
    assert looks_like_question("Welche Variante willst du?")


def test_a_statement_is_not():
    assert not looks_like_question("Fertig. Tests laufen durch.")


def test_trailing_whitespace_and_newlines_do_not_hide_the_mark():
    assert looks_like_question("Soll ich das committen?\n\n")


def test_only_the_ending_counts_so_a_recap_after_a_question_is_not_one():
    # Claude often explains a question mid-message and then reports what it
    # did. That ending is not a prompt for input.
    assert not looks_like_question("Warum war es rot? Weil der Hook fehlte. Behoben.")


def test_markdown_decoration_around_the_ending_is_ignored():
    assert looks_like_question("**Soll ich weitermachen?**")
    assert looks_like_question("Weiter? *(y/n)*")


def test_a_question_followed_by_a_code_block_is_one():
    # Showing the change and asking whether it is right is the same prompt for
    # input as asking in prose; the block is what the question is about, not
    # the end of the turn.
    assert looks_like_question("Frage: passt das?\n\n```bash\nls\n```")


def test_a_report_ending_in_a_code_block_is_not_a_question():
    assert not looks_like_question("Fertig. Der Diff:\n\n```diff\n-a\n+b\n```")


def test_a_long_code_block_does_not_use_up_the_tail_budget():
    block = "\n".join("+ line %d" % i for i in range(40))
    assert looks_like_question("Passt das?\n\n```diff\n" + block + "\n```")


def test_a_message_that_ends_inside_an_unterminated_block_is_not_a_question():
    assert not looks_like_question("Passt das?\n\n```diff\n-a\n+b")


def test_a_bullet_list_ending_in_a_question_is_one():
    assert looks_like_question("- A\n- B\n\nWelche nehmen wir?")


def test_missing_or_empty_input_is_never_a_question():
    assert not looks_like_question(None)
    assert not looks_like_question("")
    assert not looks_like_question("   \n ")
    assert not looks_like_question(42)


def test_a_question_followed_by_its_options_is_one():
    # The shape Claude uses most: ask, then list what the answers are. The
    # message no longer ends in the question mark, but the user is just as
    # much on the hook for an answer.
    assert looks_like_question(
        "Was soll ich umsetzen?\n\n- Option A: nur den Hook\n- Option B: Hook plus Test\n- Option C: nichts"
    )


def test_numbered_options_after_a_question_count_too():
    assert looks_like_question("Welche Variante?\n1. schnell\n2. sauber")


def test_a_table_of_options_after_a_question_counts_too():
    assert looks_like_question(
        "Welche nehmen wir?\n\n| Variante | Kosten |\n| --- | --- |\n| A | klein |"
    )


def test_unmarked_option_lines_after_a_question_count_too():
    assert looks_like_question("Was soll ich umsetzen?\nOption A\nOption B")


def test_a_finished_report_ending_in_a_list_is_not_a_question():
    # The mirror image, and the reason the walk stops at the first line that
    # is neither an option nor a question: a summary must stay green.
    assert not looks_like_question("Erledigt:\n- Bug behoben\n- Test ergaenzt")


def test_a_question_far_above_a_long_tail_is_not_one():
    tail = "\n".join("- Schritt %d" % i for i in range(30))
    assert not looks_like_question("Passt das?\n\n" + tail)
