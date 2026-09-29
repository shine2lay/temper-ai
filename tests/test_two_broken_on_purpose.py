"""Two failures on purpose, to prove CI shows both and not just the first.

Deleted with the branch it lives on. See docs/testing.md.
"""


def test_the_first_break():
    assert 1 == 2, "the first break: CI must name this one"


def test_the_second_break():
    assert "red" == "green", "the second break: CI must name this one too"
