"""
Observability buffer for batching database operations.

Reduces N+1 query problem by batching LLM calls, tool calls, and metric updates.
Performance improvement: Reduces queries significantly through batching.
"""
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Union

from src.constants.durations import SECONDS_PER_5_MINUTES, TIMEOUT_VERY_SHORT
from src.observability._buffer_helpers import (
    execute_flush,
    handle_flush_failure,
    merge_agent_metrics,
    move_to_dlq,
    prepare_flush_batch,
    purge_stale_pending_ids,
)
from src.observability.constants import (
    DEFAULT_BUFFER_SIZE,
    DEFAULT_DLQ_MAX_SIZE,
    MAX_RETRY_ATTEMPTS,
)

logger = logging.getLogger(__name__)


@dataclass
class LLMCallBufferParams:
    """Parameters for buffering an LLM call."""
    llm_call_id: str
    agent_id: str
    provider: str
    model: str
    prompt: str
    response: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    estimated_cost_usd: float
    start_time: datetime
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    status: str = "success"
    error_message: Optional[str] = None


@dataclass
class ToolCallBufferParams:
    """Parameters for buffering a tool call."""
    tool_execution_id: str
    agent_id: str
    tool_name: str
    input_params: Dict[str, Any]
    output_data: Dict[str, Any]
    start_time: datetime
    duration_seconds: float
    status: str = "success"
    error_message: Optional[str] = None
    safety_checks: Optional[List[str]] = None
    approval_required: bool = False


@dataclass
class BufferedLLMCall:
    """Buffered LLM call awaiting batch insert."""
    llm_call_id: str
    agent_id: str
    provider: str
    model: str
    prompt: str
    response: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    estimated_cost_usd: float
    start_time: datetime
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    status: str = "success"
    error_message: Optional[str] = None


@dataclass
class BufferedToolCall:
    """Buffered tool call awaiting batch insert."""
    tool_execution_id: str
    agent_id: str
    tool_name: str
    input_params: Dict[str, Any]
    output_data: Dict[str, Any]
    start_time: datetime
    duration_seconds: float
    status: str = "success"
    error_message: Optional[str] = None
    safety_checks: Optional[List[str]] = None
    approval_required: bool = False


@dataclass
class AgentMetricUpdate:
    """Agent metric update to be batched."""
    agent_id: str
    num_llm_calls: int = 0
    num_tool_calls: int = 0
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0


@dataclass
class RetryableItem:
    """
    Wrapper for items with retry metadata.

    Tracks retry attempts for failed flush operations to prevent infinite retry loops.
    """
    item: Union[BufferedLLMCall, BufferedToolCall, AgentMetricUpdate]
    item_type: str  # "llm_call", "tool_call", "agent_metric"
    item_id: str  # Unique identifier for deduplication
    retry_count: int = 0
    first_failed_at: Optional[datetime] = None
    last_error: Optional[str] = None


@dataclass
class DeadLetterItem:
    """
    Item that exceeded max retries.

    Dead-letter queue captures items that failed persistently after exhausting retries.
    """
    item: Union[BufferedLLMCall, BufferedToolCall, AgentMetricUpdate]
    item_type: str
    item_id: str
    retry_count: int
    first_failed_at: datetime
    final_error: str
    failed_at: datetime


class ObservabilityBuffer:
    """
    Batches observability operations to reduce database queries.

    Buffers LLM calls, tool calls, and metric updates, then flushes them
    in batches to reduce the number of database round-trips.

    Performance:
    - Without buffering: 100 LLM calls = 200 queries (1 INSERT + 1 UPDATE per call)
    - With buffering: 100 LLM calls = ~2-4 queries (1 batch INSERT, 1 batch UPDATE)

    Flush strategies:
    - Size-based: Flush when buffer reaches N items (default: 100)
    - Time-based: Flush every T seconds (default: 1.0)
    - Manual: Call flush() explicitly

    Thread-safety:
    - All public methods are thread-safe
    - Uses threading.Lock for concurrent access

    Example:
        >>> buffer = ObservabilityBuffer(flush_size=100, flush_interval=1.0)
        >>> buffer.buffer_llm_call(...)  # Buffers call
        >>> buffer.buffer_tool_call(...)  # Buffers call
        >>> # Automatic flush when flush_size reached or flush_interval elapsed
        >>> buffer.flush()  # Or flush manually
    """

    # Default timeout for pending IDs before they are considered stale
    PENDING_ID_TIMEOUT_SECONDS = SECONDS_PER_5_MINUTES

    def __init__(
        self,
        flush_size: int = DEFAULT_BUFFER_SIZE,
        flush_interval: float = 1.0,
        auto_flush: bool = True,
        max_retries: int = MAX_RETRY_ATTEMPTS,
        enable_dlq: bool = True,
        pending_id_timeout: float = PENDING_ID_TIMEOUT_SECONDS,
        max_dlq_size: int = DEFAULT_DLQ_MAX_SIZE,
    ):
        """
        Initialize observability buffer.

        Args:
            flush_size: Flush when buffer reaches this many items
            flush_interval: Flush every N seconds (if auto_flush enabled)
            auto_flush: Enable automatic background flushing
            max_retries: Maximum retry attempts before moving to dead-letter queue
            enable_dlq: Enable dead-letter queue for permanently failed items
            pending_id_timeout: Seconds before a pending ID is considered stale (default: 300)
            max_dlq_size: Maximum number of items in the dead-letter queue (default: 10000).
                         When exceeded, oldest entries are dropped.
        """
        self.flush_size = flush_size
        self.flush_interval = flush_interval
        self.auto_flush = auto_flush
        self.max_retries = max_retries
        self.enable_dlq = enable_dlq
        self._pending_id_timeout = pending_id_timeout
        self._max_dlq_size = max_dlq_size

        # Buffered operations
        self.llm_calls: List[BufferedLLMCall] = []
        self.tool_calls: List[BufferedToolCall] = []
        self.agent_metrics: Dict[str, AgentMetricUpdate] = defaultdict(lambda: AgentMetricUpdate(agent_id=""))

        # Retry tracking
        self.retry_queue: List[RetryableItem] = []
        # Pending IDs with timestamps for stale-entry purge
        self._pending_ids: Dict[str, float] = {}  # item_id -> timestamp

        # Dead-letter queue
        self.dead_letter_queue: List[DeadLetterItem] = []
        self._dlq_callback: Optional[Callable[[DeadLetterItem], None]] = None

        # Thread synchronization
        self.lock = threading.Lock()
        self.last_flush_time = time.time()

        # Background flush thread
        self._flush_thread: Optional[threading.Thread] = None
        self._stop_flush_thread = threading.Event()

        # Flush callback (injected by backend)
        self._flush_callback: Optional[Callable[[List[BufferedLLMCall], List[BufferedToolCall], Dict[str, AgentMetricUpdate]], None]] = None

        if auto_flush:
            self._start_flush_thread()

    def set_flush_callback(self, callback: Callable[[List[BufferedLLMCall], List[BufferedToolCall], Dict[str, AgentMetricUpdate]], None]) -> None:
        """Set callback function to execute when buffer flushes."""
        self._flush_callback = callback

    def buffer_llm_call(self, params: LLMCallBufferParams) -> None:
        """Buffer LLM call for batch insertion.

        Args:
            params: LLMCallBufferParams with all LLM call parameters
        """
        deferred_flush = None
        with self.lock:
            self.llm_calls.append(BufferedLLMCall(
                llm_call_id=params.llm_call_id, agent_id=params.agent_id,
                provider=params.provider, model=params.model, prompt=params.prompt,
                response=params.response, prompt_tokens=params.prompt_tokens,
                completion_tokens=params.completion_tokens, latency_ms=params.latency_ms,
                estimated_cost_usd=params.estimated_cost_usd, start_time=params.start_time,
                temperature=params.temperature, max_tokens=params.max_tokens,
                status=params.status, error_message=params.error_message
            ))

            # Update agent metrics
            if params.agent_id not in self.agent_metrics:
                self.agent_metrics[params.agent_id] = AgentMetricUpdate(agent_id=params.agent_id)
            metrics = self.agent_metrics[params.agent_id]
            metrics.num_llm_calls += 1
            metrics.total_tokens += params.prompt_tokens + params.completion_tokens
            metrics.prompt_tokens += params.prompt_tokens
            metrics.completion_tokens += params.completion_tokens
            metrics.estimated_cost_usd += params.estimated_cost_usd

            if self._should_flush():
                deferred_flush = self._swap_and_prepare()

        if deferred_flush is not None:
            items_to_flush, flush_cb = deferred_flush
            execute_flush(items_to_flush, flush_cb, self.lock,
                          self._pending_ids, self.retry_queue,
                          self._handle_flush_failure_impl, merge_agent_metrics)

    def buffer_tool_call(self, params: ToolCallBufferParams) -> None:
        """Buffer tool call for batch insertion.

        Args:
            params: ToolCallBufferParams with all tool call parameters
        """
        deferred_flush = None
        with self.lock:
            self.tool_calls.append(BufferedToolCall(
                tool_execution_id=params.tool_execution_id, agent_id=params.agent_id,
                tool_name=params.tool_name, input_params=params.input_params,
                output_data=params.output_data, start_time=params.start_time,
                duration_seconds=params.duration_seconds, status=params.status,
                error_message=params.error_message, safety_checks=params.safety_checks,
                approval_required=params.approval_required
            ))

            if params.agent_id not in self.agent_metrics:
                self.agent_metrics[params.agent_id] = AgentMetricUpdate(agent_id=params.agent_id)
            self.agent_metrics[params.agent_id].num_tool_calls += 1

            if self._should_flush():
                deferred_flush = self._swap_and_prepare()

        if deferred_flush is not None:
            items_to_flush, flush_cb = deferred_flush
            execute_flush(items_to_flush, flush_cb, self.lock,
                          self._pending_ids, self.retry_queue,
                          self._handle_flush_failure_impl, merge_agent_metrics)

    def flush(self) -> None:
        """Flush all buffered operations to database."""
        with self.lock:
            swapped = self._swap_and_prepare()
        if swapped is None:
            return
        items_to_flush, flush_cb = swapped
        execute_flush(items_to_flush, flush_cb, self.lock,
                      self._pending_ids, self.retry_queue,
                      self._handle_flush_failure_impl, merge_agent_metrics)

    def _should_flush(self) -> bool:
        """Check if buffer should be flushed (assumes lock is held)."""
        total_items = len(self.llm_calls) + len(self.tool_calls) + len(self.retry_queue)
        if total_items >= self.flush_size:
            return True
        if time.time() - self.last_flush_time >= self.flush_interval:
            return True
        return False

    def _swap_and_prepare(self) -> Optional[tuple]:
        """Swap buffers and prepare flush batch (assumes lock is held)."""
        purge_stale_pending_ids(self._pending_ids, self._pending_id_timeout)

        if not self._flush_callback:
            logger.warning("No flush callback set, skipping flush")
            return None
        if not self.llm_calls and not self.tool_calls and not self.agent_metrics and not self.retry_queue:
            return None

        from src.observability._buffer_helpers import FlushBatchParams
        items_to_flush = prepare_flush_batch(
            FlushBatchParams(
                llm_calls=self.llm_calls,
                tool_calls=self.tool_calls,
                agent_metrics=self.agent_metrics,
                retry_queue=self.retry_queue,
                pending_ids=self._pending_ids,
                retryable_item_cls=RetryableItem,
                agent_metric_update_cls=AgentMetricUpdate,
                merge_fn=merge_agent_metrics,
            )
        )
        if not items_to_flush:
            return None

        self.llm_calls = []
        self.tool_calls = []
        self.agent_metrics = defaultdict(lambda: AgentMetricUpdate(agent_id=""))
        self.last_flush_time = time.time()
        return items_to_flush, self._flush_callback

    def _handle_flush_failure_impl(self, failed_items: List[RetryableItem], error: str) -> None:
        """Handle flush failure (called under lock by execute_flush)."""
        handle_flush_failure(
            failed_items, error, self.max_retries,
            self.retry_queue, self._pending_ids,
            self._move_to_dlq_impl,
        )

    def _move_to_dlq_impl(self, item: RetryableItem, now: datetime) -> None:
        """Move failed item to dead-letter queue."""
        move_to_dlq(
            item, now, self.enable_dlq, self.dead_letter_queue,
            self._max_dlq_size, self._dlq_callback, DeadLetterItem,
        )

    def _start_flush_thread(self) -> None:
        """Start background flush thread."""
        self._stop_flush_thread.clear()
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()

    def _flush_loop(self) -> None:
        """Background flush loop."""
        while not self._stop_flush_thread.wait(timeout=self.flush_interval):
            self.flush()

    def stop(self) -> None:
        """
        Stop background flush thread and flush remaining data.

        Call this before shutting down to ensure all data is persisted.
        Signals the background thread to stop, waits for it to finish,
        then performs a final flush of any remaining buffered data.
        """
        if self._flush_thread and self._flush_thread.is_alive():
            self._stop_flush_thread.set()
            self._flush_thread.join(timeout=TIMEOUT_VERY_SHORT)
            if self._flush_thread.is_alive():
                logger.warning("Background flush thread did not stop within timeout")
            self._flush_thread = None

        # Final flush
        self.flush()

    def set_dlq_callback(
        self,
        callback: Callable[[DeadLetterItem], None]
    ) -> None:
        """
        Set callback for dead-letter queue events.

        The callback is invoked when an item is moved to the DLQ.
        Use this to persist DLQ items, send alerts, or log to external systems.

        Args:
            callback: Function to call with DeadLetterItem
        """
        self._dlq_callback = callback

    def get_dlq_items(self) -> List[DeadLetterItem]:
        """Get all items in dead-letter queue."""
        with self.lock:
            return self.dead_letter_queue.copy()

    def clear_dlq(self) -> int:
        """
        Clear dead-letter queue.

        Returns:
            Number of items cleared
        """
        with self.lock:
            count = len(self.dead_letter_queue)
            self.dead_letter_queue.clear()
            return count

    def get_stats(self) -> Dict[str, Any]:
        """Get buffer statistics including retry and DLQ metrics."""
        with self.lock:
            return {
                "llm_calls_buffered": len(self.llm_calls),
                "tool_calls_buffered": len(self.tool_calls),
                "agent_metrics_buffered": len(self.agent_metrics),
                "total_buffered": len(self.llm_calls) + len(self.tool_calls),
                "retry_queue_size": len(self.retry_queue),
                "dlq_size": len(self.dead_letter_queue),
                "pending_ids": len(self._pending_ids),
                "flush_size": self.flush_size,
                "flush_interval": self.flush_interval,
                "auto_flush": self.auto_flush,
                "max_retries": self.max_retries,
                "max_dlq_size": self._max_dlq_size,
                "last_flush_time": self.last_flush_time
            }

    def __enter__(self) -> "ObservabilityBuffer":
        """Context manager entry."""
        return self

    def __exit__(self, _exc_type: Any, _exc_val: Any, _exc_tb: Any) -> None:
        """Context manager exit - ensure flush on exit."""
        self.stop()
