"""Tests for temper_ai/llm/conversation.py.

Covers conversation history management:
- ConversationMessage: immutable frozen dataclass
- ConversationHistory: append_turn, turn limit, to_message_list, len, serialization
- make_history_key: composite key construction
"""

from dataclasses import FrozenInstanceError

import pytest

from temper_ai.llm.conversation import (
    MAX_CONVERSATION_TURNS,
    ConversationHistory,
    ConversationMessage,
    make_history_key,
)


class TestConversationMessage:
    """Tests for the ConversationMessage frozen dataclass."""

    def test_creation_with_role_and_content(self):
        """Creates message with given role and content."""
        msg = ConversationMessage(role="user", content="Hello!")
        assert msg.role == "user"
        assert msg.content == "Hello!"

    def test_assistant_role(self):
        """Supports assistant role."""
        msg = ConversationMessage(role="assistant", content="Hi there!")
        assert msg.role == "assistant"
        assert msg.content == "Hi there!"

    def test_frozen_immutable(self):
        """ConversationMessage is frozen — setting any attribute raises FrozenInstanceError."""
        msg = ConversationMessage(role="user", content="test")
        with pytest.raises(FrozenInstanceError):
            msg.role = "assistant"

    def test_content_immutable(self):
        """Content field is also immutable on frozen dataclass."""
        msg = ConversationMessage(role="user", content="original")
        with pytest.raises(FrozenInstanceError):
            msg.content = "modified"


class TestConversationHistory:
    """Tests for ConversationHistory — append, trim, and list conversion."""

    def test_append_turn_adds_two_messages(self):
        """append_turn adds exactly one user and one assistant message."""
        history = ConversationHistory()
        history.append_turn("Hello", "Hi!")
        assert len(history) == 2
        assert history.messages[0].role == "user"
        assert history.messages[0].content == "Hello"
        assert history.messages[1].role == "assistant"
        assert history.messages[1].content == "Hi!"

    def test_empty_history_has_zero_length(self):
        """Freshly created history has length 0."""
        history = ConversationHistory()
        assert len(history) == 0

    def test_len_returns_message_count(self):
        """__len__ returns the total number of individual messages."""
        history = ConversationHistory()
        history.append_turn("Q1", "A1")
        history.append_turn("Q2", "A2")
        assert len(history) == 4

    def test_turn_limit_trims_oldest_messages(self):
        """Adding more than MAX_CONVERSATION_TURNS pairs trims oldest messages."""
        history = ConversationHistory()
        # Fill to the limit
        for i in range(MAX_CONVERSATION_TURNS):
            history.append_turn(f"Q{i}", f"A{i}")
        assert len(history) == MAX_CONVERSATION_TURNS * 2

        # One more turn exceeds the limit — oldest pair is removed
        history.append_turn("QExtra", "AExtra")
        assert len(history) == MAX_CONVERSATION_TURNS * 2
        # Oldest messages trimmed — first message should now be Q1 not Q0
        assert history.messages[0].content == "Q1"
        assert history.messages[-1].content == "AExtra"

    def test_to_message_list_format(self):
        """to_message_list returns list of role/content dicts."""
        history = ConversationHistory()
        history.append_turn("user message", "assistant reply")
        msg_list = history.to_message_list()
        assert msg_list == [
            {"role": "user", "content": "user message"},
            {"role": "assistant", "content": "assistant reply"},
        ]

    def test_to_message_list_empty(self):
        """to_message_list returns empty list for empty history."""
        history = ConversationHistory()
        assert history.to_message_list() == []

    def test_multiple_turns_preserved_in_order(self):
        """Multiple turns are stored and retrieved in chronological order."""
        history = ConversationHistory()
        history.append_turn("first Q", "first A")
        history.append_turn("second Q", "second A")
        msgs = history.to_message_list()
        assert msgs[0]["content"] == "first Q"
        assert msgs[1]["content"] == "first A"
        assert msgs[2]["content"] == "second Q"
        assert msgs[3]["content"] == "second A"


class TestConversationSerialization:
    """Tests for ConversationHistory to_dict / from_dict round-trip."""

    def test_to_dict_round_trip(self):
        """to_dict / from_dict preserves all messages."""
        history = ConversationHistory()
        history.append_turn("Q1", "A1")
        history.append_turn("Q2", "A2")

        data = history.to_dict()
        restored = ConversationHistory.from_dict(data)

        assert len(restored) == len(history)
        assert restored.to_message_list() == history.to_message_list()

    def test_from_dict_empty(self):
        """from_dict with empty messages list creates empty history."""
        history = ConversationHistory.from_dict({"messages": []})
        assert len(history) == 0

    def test_from_dict_applies_turn_limit(self):
        """from_dict trims oversized data to MAX_CONVERSATION_TURNS pairs."""
        # Build more messages than the limit allows
        messages = []
        for i in range(MAX_CONVERSATION_TURNS + 5):
            messages.append({"role": "user", "content": f"Q{i}"})
            messages.append({"role": "assistant", "content": f"A{i}"})

        history = ConversationHistory.from_dict({"messages": messages})
        assert len(history) == MAX_CONVERSATION_TURNS * 2

    def test_to_dict_structure(self):
        """to_dict returns a dict with a 'messages' list of role/content dicts."""
        history = ConversationHistory()
        history.append_turn("hello", "world")
        data = history.to_dict()
        assert "messages" in data
        assert data["messages"] == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ]


class TestMakeHistoryKey:
    """Tests for make_history_key — composite key construction."""

    def test_format_is_stage_colon_agent(self):
        """Returns 'stage:agent' formatted key."""
        key = make_history_key("main_stage", "planner")
        assert key == "main_stage:planner"

    def test_different_stages_different_keys(self):
        """Different stage names produce different keys."""
        key1 = make_history_key("stage_a", "agent")
        key2 = make_history_key("stage_b", "agent")
        assert key1 != key2

    def test_different_agents_different_keys(self):
        """Different agent names produce different keys."""
        key1 = make_history_key("stage", "agent_a")
        key2 = make_history_key("stage", "agent_b")
        assert key1 != key2

    def test_separator_is_colon(self):
        """The separator between stage and agent is a colon."""
        key = make_history_key("s", "a")
        parts = key.split(":")
        assert len(parts) == 2
        assert parts[0] == "s"
        assert parts[1] == "a"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
