"""Cross-pollination schemas for M9 persistent agents."""

from pydantic import BaseModel, Field

MAX_PUBLISHED_ENTRIES = 50
DEFAULT_RETRIEVAL_K_POLLINATION = 5
DEFAULT_RELEVANCE_THRESHOLD_POLLINATION = 0.7


class CrossPollinationConfig(BaseModel):
    """Configuration for cross-agent knowledge sharing."""

    enabled: bool = False
    publish_output: bool = False
    subscribe_to: list[str] = Field(default_factory=list)
    max_published_entries: int = Field(default=MAX_PUBLISHED_ENTRIES, gt=0)
    retrieval_k: int = Field(default=DEFAULT_RETRIEVAL_K_POLLINATION, gt=0)
    relevance_threshold: float = Field(
        default=DEFAULT_RELEVANCE_THRESHOLD_POLLINATION, ge=0.0, le=1.0
    )
