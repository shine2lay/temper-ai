"""An account's limit or refusal is read only where it can be trusted.

The sentences below are the ones subscriptions really handed back where an
answer should have been: two limit banners that "completed" a research step
five minutes in, and a refusal that "completed" one agent in three for a whole
working day at $0 in about a second. Each must still be recognised. But the
same sentences quoted inside an answer -- tonight every department is writing
up this very incident -- are an answer, and must never drop a healthy account
or fail the agent's step.
"""

import pytest

from temper_ai.llm.account_messages import (
    DISABLED,
    LIMIT,
    account_trouble,
    is_disabled,
    is_limit,
)

# What the Claude CLI returned as the whole result (llm.call.completed outputs).
RECORDED_LIMITS = [
    "You've hit your session limit \u00b7 resets 10:50pm (UTC)",  # brief_competition_consumer_next
    "You've hit your session limit \u00b7 resets 6am (UTC)",  # a scan's demand lens
]
RECORDED_REFUSAL = (
    "Your organization has disabled Claude subscription access for Claude Code \u00b7 "
    "Use an Anthropic API key instead, or ask your admin to enable access"
)
# The CLI's other banners, from its own templates.
OTHER_LIMITS = [
    "You've hit your weekly limit \u00b7 resets Oct 9, 4pm (UTC)",
    "You've hit your Opus limit",
    "You've hit your usage credit limit \u00b7 progress saved",
    "You\u2019ve hit your Sonnet limit \u00b7 resets 3pm",
    "Claude AI usage limit reached|1791251400",
]


class TestTheRecordedAnswers:
    @pytest.mark.parametrize("text", RECORDED_LIMITS)
    def test_a_recorded_banner_alone_is_a_limit(self, text):
        assert account_trouble(text) == LIMIT
        assert account_trouble(f"  {text}\n") == LIMIT, "trimmed"

    @pytest.mark.parametrize("text", OTHER_LIMITS)
    def test_the_clis_other_banners_are_limits_too(self, text):
        assert is_limit(text)

    def test_the_recorded_refusal_alone_is_a_disabled_account(self):
        assert account_trouble(RECORDED_REFUSAL) == DISABLED
        assert not is_limit(RECORDED_REFUSAL)

    def test_the_other_refusal_sentence_too(self):
        assert is_disabled("Claude Code is not available for your organization.")

    def test_the_apis_oauth_sentence_alone_too(self):
        """The API's words for a 403 oauth_not_allowed_for_organization, as the whole result
        of a call with no model work (ADR-M4-16's belt-and-braces shape)."""
        text = "OAuth authentication is currently not allowed for this organization."
        assert account_trouble(text) == DISABLED
        assert account_trouble(text, model_work=True) is None
        assert account_trouble(f"Here is what happened: {text}") is None

    def test_the_apis_oauth_sentence_in_an_error_without_its_code(self):
        assert account_trouble("Provider error: OAuth authentication is currently not allowed "
                               "for this organisation", is_error=True) == DISABLED


class TestInAnError:
    @pytest.mark.parametrize("text", RECORDED_LIMITS)
    def test_a_limit_anywhere_in_an_error(self, text):
        assert account_trouble(f"Claude Code returned an error result: {text}", is_error=True) == LIMIT

    def test_a_refusal_anywhere_in_an_error(self):
        assert account_trouble(f"API Error: {RECORDED_REFUSAL}", is_error=True) == DISABLED

    @pytest.mark.parametrize("text", [
        'API Error: 403 {"type":"error","error":{"type":"permission_error",'
        '"message":"OAuth authentication is currently not allowed for this organization."}}',
        '{"error":{"type":"error","details":"oauth_not_allowed_for_organization"}}',
    ], ids=["permission_error", "oauth_not_allowed_for_organization"])
    def test_the_apis_words_for_a_refusal(self, text):
        assert account_trouble(text, is_error=True) == DISABLED

    def test_an_error_that_is_neither(self):
        assert account_trouble("Claude Code CLI timed out after 7200s", is_error=True) is None
        assert account_trouble("", is_error=True) is None
        assert account_trouble(None, is_error=True) is None


class TestNeverInsideAnAnswer:
    """The false-positive guard: a sentence inside real work is real work."""

    @pytest.mark.parametrize("text", [*RECORDED_LIMITS, RECORDED_REFUSAL])
    def test_quoted_inside_a_longer_answer(self, text):
        answer = (
            "## Incident summary\n\n"
            f"At 20:12 one account answered \"{text}\" instead of doing the work, "
            "and the step completed at $0. Recommendation: treat it as a failure."
        )
        assert account_trouble(answer) is None

    @pytest.mark.parametrize("text", [*RECORDED_LIMITS, RECORDED_REFUSAL])
    def test_as_the_first_line_of_a_longer_answer(self, text):
        assert account_trouble(f"{text}\n\nThat is what the account said; here is what it means.") is None

    @pytest.mark.parametrize("text", [*RECORDED_LIMITS, RECORDED_REFUSAL])
    def test_alone_but_after_model_work(self, text):
        assert account_trouble(text, model_work=True) is None

    def test_an_answer_about_limits_in_general(self):
        assert account_trouble("You've hit your limit of three retries; the rate limit is fine.") is None
        assert account_trouble("The weekly limit resets on Thursday.") is None

    def test_other_things_not_available_for_an_organisation_are_not_a_refusal(self):
        # The CLI says this about file sync and projects; neither is the account.
        for text in ("File sync is not available for your organization: its data retention "
                     "policy does not allow it.",
                     "Projects are not available for your organization."):
            assert account_trouble(text) is None
            assert account_trouble(text, is_error=True) is None
