"""Conversation history for stage:agent pair re-invocations.

Provides persistent, per-workflow-run conversation history keyed by
``stage_name:agent_name``, so re-invoked agents in loops/branches see
their full prior conversation as natural multi-turn chat.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

# Maximum turn pairs stored per stage:agent history
MAX_CONVERSATION_TURNS = 20


@dataclass(frozen=True)
class ConversationMessage:
    """A single message in a conversation history."""

    role: str  # "user" or "assistant"
    content: str


@dataclass
class ConversationHistory:
    """Container for a sequence of conversation messages.

    Maintains a rolling window of at most ``MAX_CONVERSATION_TURNS``
    user/assistant turn pairs.
    """

    messages: List[ConversationMessage] = field(default_factory=list)

    def append_turn(self, user_content: str, assistant_content: str) -> None:
        """Append a user/assistant turn pair and trim if needed."""
        self.messages.append(ConversationMessage(role="user", content=user_content))
        self.messages.append(ConversationMessage(role="assistant", content=assistant_content))
        self._apply_turn_limit()

    def to_message_list(self) -> List[Dict[str, str]]:
        """Convert to list of dicts suitable for LLM provider ``messages`` param."""
        return [{"role": m.role, "content": m.content} for m in self.messages]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
            "messages": [{"role": m.role, "content": m.content} for m in self.messages],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ConversationHistory:
        """Deserialize from a dict (inverse of ``to_dict``)."""
        messages = [
            ConversationMessage(role=m["role"], content=m["content"])
            for m in data.get("messages", [])
        ]
        history = cls(messages=messages)
        history._apply_turn_limit()
        return history

    def _apply_turn_limit(self) -> None:
        """Trim oldest messages to stay within MAX_CONVERSATION_TURNS pairs."""
        max_messages = MAX_CONVERSATION_TURNS * 2
        if len(self.messages) > max_messages:
            self.messages = self.messages[-max_messages:]

    def __len__(self) -> int:
        return len(self.messages)


def make_history_key(stage_name: str, agent_name: str) -> str:
    """Build the composite key for conversation history lookup."""
    return f"{stage_name}:{agent_name}"
