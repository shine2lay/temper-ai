"""`temper notion check` shows the webhook verification token only while the
owner still has to paste it somewhere: it is the key that signs every event."""

from temper_ai.cli.notion import _verification_line

TOKEN = "secret_example_verification_token"  # noqa: S105


def test_none_received_yet():
    ok, text = _verification_line("", "")
    assert ok is None
    assert "none received yet" in text


def test_shown_until_the_secret_holds_it():
    ok, text = _verification_line(TOKEN, "")
    assert ok is True
    assert TOKEN in text
    assert "NOTION_WEBHOOK_SECRET" in text


def test_hidden_once_the_secret_holds_it():
    ok, text = _verification_line(TOKEN, TOKEN)
    assert ok is True
    assert TOKEN not in text
    assert "holds it" in text


def test_a_different_token_is_shown_and_flagged():
    ok, text = _verification_line("secret_new_one", TOKEN)
    assert ok is False
    assert "secret_new_one" in text
    assert TOKEN not in text
