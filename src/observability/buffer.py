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
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Union

from src.observability.constants import (
    DEFAULT_BUFFER_SIZE,
    DEFAULT_DLQ_MAX_SIZE,
    MAX_RETRY_ATTEMPTS,
)
from src.constants.durations import SECONDS_PER_5_MINUTES

logger = logging.getLogger(__name__)


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
        """
        Set callback function to execute when buffer flushes.

        The callback receives (llm_calls, tool_calls, agent_metrics).

        Args:
            callback: Function to call on flush
        """
        self._flush_callback = callback

    def buffer_llm_call(
        self,
        llm_call_id: str,
        agent_id: str,
        provider: str,
        model: str,
        prompt: str,
        response: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int,
        estimated_cost_usd: float,
        start_time: datetime,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        status: str = "success",
        error_message: Optional[str] = None
    ) -> None:
        """Buffer LLM call for batch insertion."""
        deferred_flush = None
        with self.lock:
            self.llm_calls.append(BufferedLLMCall(
                llm_call_id=llm_call_id,
                agent_id=agent_id,
                provider=provider,
                model=model,
                prompt=prompt,
                response=response,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                estimated_cost_usd=estimated_cost_usd,
                start_time=start_time,
                temperature=temperature,
                max_tokens=max_tokens,
                status=status,
                error_message=error_message
            ))

            # Update agent metrics
            if agent_id not in self.agent_metrics:
                self.agent_metrics[agent_id] = AgentMetricUpdate(agent_id=agent_id)

            metrics = self.agent_metrics[agent_id]
            metrics.num_llm_calls += 1
            metrics.total_tokens += prompt_tokens + completion_tokens
            metrics.prompt_tokens += prompt_tokens
            metrics.completion_tokens += completion_tokens
            metrics.estimated_cost_usd += estimated_cost_usd

            # Check if we should flush — swap buffers under lock, flush outside
            if self._should_flush():
                deferred_flush = self._flush_unsafe()

        # Execute flush outside the lock to avoid holding lock during DB I/O
        if deferred_flush is not None:
            items_to_flush, flush_callback = deferred_flush
            self._execute_flush(items_to_flush, flush_callback)

    def buffer_tool_call(
        self,
        tool_execution_id: str,
        agent_id: str,
        tool_name: str,
        input_params: Dict[str, Any],
        output_data: Dict[str, Any],
        start_time: datetime,
        duration_seconds: float,
        status: str = "success",
        error_message: Optional[str] = None,
        safety_checks: Optional[List[str]] = None,
        approval_required: bool = False
    ) -> None:
        """Buffer tool call for batch insertion."""
        deferred_flush = None
        with self.lock:
            self.tool_calls.append(BufferedToolCall(
                tool_execution_id=tool_execution_id,
                agent_id=agent_id,
                tool_name=tool_name,
                input_params=input_params,
                output_data=output_data,
                start_time=start_time,
                duration_seconds=duration_seconds,
                status=status,
                error_message=error_message,
                safety_checks=safety_checks,
                approval_required=approval_required
            ))

            # Update agent metrics
            if agent_id not in self.agent_metrics:
                self.agent_metrics[agent_id] = AgentMetricUpdate(agent_id=agent_id)

            self.agent_metrics[agent_id].num_tool_calls += 1

            # Check if we should flush — swap buffers under lock, flush outside
            if self._should_flush():
                deferred_flush = self._flush_unsafe()

        # Execute flush outside the lock to avoid holding lock during DB I/O
        if deferred_flush is not None:
            items_to_flush, flush_callback = deferred_flush
            self._execute_flush(items_to_flush, flush_callback)

    def flush(self) -> None:
        """
        Flush all buffered operations to database.

        Thread-safe. Uses swap-and-flush: swaps buffer references under lock,
        then flushes outside the lock to reduce lock contention.
        """
        # Phase 1: Swap buffers under lock
        with self.lock:
            swapped = self._swap_buffers()

        if swapped is None:
            return

        items_to_flush, flush_callback = swapped

        # Phase 2: Flush outside lock (no lock contention during DB I/O)
        self._execute_flush(items_to_flush, flush_callback)

    def _purge_stale_pending_ids(self) -> int:
        """Remove pending IDs older than timeout (assumes lock is held).

        Returns:
            Number of stale IDs purged.
        """
        cutoff = time.time() - self._pending_id_timeout
        stale = [k for k, ts in self._pending_ids.items() if ts < cutoff]
        for k in stale:
            del self._pending_ids[k]
        if stale:
            logger.debug(f"Purged {len(stale)} stale pending IDs")
        return len(stale)

    def _should_flush(self) -> bool:
        """Check if buffer should be flushed (assumes lock is held)."""
        # Size-based flush
        total_items = len(self.llm_calls) + len(self.tool_calls) + len(self.retry_queue)
        if total_items >= self.flush_size:
            return True

        # Time-based flush
        if time.time() - self.last_flush_time >= self.flush_interval:
            return True

        return False

    def _flush_unsafe(self) -> Optional[tuple]:
        """Swap buffers under lock for deferred flush (assumes lock is held).

        Uses swap-and-flush pattern: swaps buffer references under the lock,
        then returns the data so the caller can flush OUTSIDE the lock.
        This prevents holding the lock during DB I/O.

        Returns:
            Tuple of (items_to_flush, flush_callback) or None if nothing to flush.
        """
        return self._swap_buffers()

    def _swap_buffers(self):
        """Swap buffer contents to local variables (assumes lock is held).

        Returns:
            Tuple of (items_to_flush, flush_callback) or None if nothing to flush.
        """
        # Purge stale pending IDs to prevent unbounded growth
        self._purge_stale_pending_ids()

        if not self._flush_callback:
            logger.warning("No flush callback set, skipping flush")
            return None

        # Skip if nothing to flush
        if not self.llm_calls and not self.tool_calls and not self.agent_metrics and not self.retry_queue:
            return None

        # Prepare batch for flushing (combines new items + retry queue)
        items_to_flush = self._prepare_flush_batch()

        if not items_to_flush:
            return None

        # Swap: clear main buffers so new items can accumulate
        self.llm_calls = []
        self.tool_calls = []
        self.agent_metrics = defaultdict(lambda: AgentMetricUpdate(agent_id=""))
        self.last_flush_time = time.time()

        # Capture callback reference
        flush_callback = self._flush_callback

        return items_to_flush, flush_callback

    def _execute_flush(self, items_to_flush: List[RetryableItem], flush_callback: Callable) -> None:
        """Execute flush callback outside the lock.

        Args:
            items_to_flush: Prepared batch of retryable items
            flush_callback: The callback to invoke
        """
        # Extract by type for callback
        llm_calls = [item.item for item in items_to_flush if item.item_type == "llm_call"]
        tool_calls = [item.item for item in items_to_flush if item.item_type == "tool_call"]

        # Batch agent metric updates: merge all metrics per agent into a single
        # AgentMetricUpdate to avoid N+1 updates in the flush callback (M-44).
        agent_metrics: Dict[str, AgentMetricUpdate] = {}
        for item in items_to_flush:
            if item.item_type != "agent_metric":
                continue
            metric = item.item
            if item.item_id in agent_metrics:
                # Merge into existing aggregated metric
                self._merge_agent_metrics(agent_metrics[item.item_id], metric)
            else:
                # First metric for this agent — copy to avoid mutating the RetryableItem
                agent_metrics[item.item_id] = AgentMetricUpdate(
                    agent_id=metric.agent_id,
                    num_llm_calls=metric.num_llm_calls,
                    num_tool_calls=metric.num_tool_calls,
                    total_tokens=metric.total_tokens,
                    prompt_tokens=metric.prompt_tokens,
                    completion_tokens=metric.completion_tokens,
                    estimated_cost_usd=metric.estimated_cost_usd,
                )

        try:
            flush_callback(llm_calls, tool_calls, agent_metrics)

            logger.debug(
                f"Flushed {len(llm_calls)} LLM calls, "
                f"{len(tool_calls)} tool calls, "
                f"{len(agent_metrics)} agent metric updates"
            )

            # Success - clear retry queue and pending IDs under lock
            with self.lock:
                for item in items_to_flush:
                    self._pending_ids.pop(item.item_id, None)
                self.retry_queue.clear()

        except Exception as e:
            logger.error(f"Error flushing buffer: {e}", exc_info=True)
            with self.lock:
                self._handle_flush_failure(items_to_flush, str(e))

    def _prepare_flush_batch(self) -> List[RetryableItem]:
        """
        Prepare batch for flushing, combining new items and retry queue.

        Implements deduplication to prevent double-insertion.
        """
        retryable_items = []

        # Add new LLM calls
        for llm_call in self.llm_calls:
            item_id = llm_call.llm_call_id
            if item_id not in self._pending_ids:
                retryable_items.append(RetryableItem(
                    item=llm_call,
                    item_type="llm_call",
                    item_id=item_id,
                    retry_count=0
                ))
                self._pending_ids[item_id] = time.time()

        # Add new tool calls
        for tool_call in self.tool_calls:
            item_id = tool_call.tool_execution_id
            if item_id not in self._pending_ids:
                retryable_items.append(RetryableItem(
                    item=tool_call,
                    item_type="tool_call",
                    item_id=item_id,
                    retry_count=0
                ))
                self._pending_ids[item_id] = time.time()

        # Add agent metrics (merge if already in retry queue)
        for agent_id, metrics in self.agent_metrics.items():
            # Check if already in retry queue
            existing = next(
                (item for item in self.retry_queue
                 if item.item_type == "agent_metric" and item.item_id == agent_id),
                None
            )

            if existing:
                # Merge new metrics into existing retry item
                self._merge_agent_metrics(existing.item, metrics)
            else:
                retryable_items.append(RetryableItem(
                    item=metrics,
                    item_type="agent_metric",
                    item_id=agent_id,
                    retry_count=0
                ))
                self._pending_ids[agent_id] = time.time()

        # Add items from retry queue
        retryable_items.extend(self.retry_queue)

        return retryable_items

    def _merge_agent_metrics(
        self,
        existing: AgentMetricUpdate,
        new: AgentMetricUpdate
    ) -> None:
        """Merge new metrics into existing metrics (for retry queue)."""
        existing.num_llm_calls += new.num_llm_calls
        existing.num_tool_calls += new.num_tool_calls
        existing.total_tokens += new.total_tokens
        existing.prompt_tokens += new.prompt_tokens
        existing.completion_tokens += new.completion_tokens
        existing.estimated_cost_usd += new.estimated_cost_usd

    def _handle_flush_failure(self, failed_items: List[RetryableItem], error: str) -> None:
        """
        Handle flush failure with retry logic and dead-letter queue.

        Items are retried up to max_retries times, then moved to DLQ.
        """
        now = datetime.now(timezone.utc)
        new_retry_queue = []

        for item in failed_items:
            # Increment retry count
            item.retry_count += 1
            if item.first_failed_at is None:
                item.first_failed_at = now
            item.last_error = error

            # Check if max retries exceeded
            if item.retry_count > self.max_retries:
                # Move to dead-letter queue
                self._move_to_dlq(item, now)
                # Remove from pending IDs
                self._pending_ids.pop(item.item_id, None)
            else:
                # Re-queue for retry
                new_retry_queue.append(item)
                logger.warning(
                    f"Retry {item.retry_count}/{self.max_retries} for {item.item_type} "
                    f"{item.item_id}: {error}"
                )

        # Update retry queue
        self.retry_queue = new_retry_queue

    def _move_to_dlq(self, item: RetryableItem, now: datetime) -> None:
        """Move failed item to dead-letter queue.

        Enforces max_dlq_size by dropping oldest entries when the limit is exceeded.
        """
        if not self.enable_dlq:
            logger.error(
                f"Item {item.item_type} {item.item_id} permanently failed after "
                f"{item.retry_count} retries (DLQ disabled): {item.last_error}"
            )
            return

        dlq_item = DeadLetterItem(
            item=item.item,
            item_type=item.item_type,
            item_id=item.item_id,
            retry_count=item.retry_count,
            first_failed_at=item.first_failed_at or now,
            final_error=item.last_error or "Unknown error",
            failed_at=now
        )

        self.dead_letter_queue.append(dlq_item)

        # Enforce max DLQ size — drop oldest entries if exceeded
        if len(self.dead_letter_queue) > self._max_dlq_size:
            overflow = len(self.dead_letter_queue) - self._max_dlq_size
            self.dead_letter_queue = self.dead_letter_queue[overflow:]
            logger.warning("DLQ overflow: dropped %d oldest items", overflow)

        logger.error(
            f"Moved {item.item_type} {item.item_id} to DLQ after "
            f"{item.retry_count} retries: {item.last_error}"
        )

        # Trigger DLQ callback if set
        if self._dlq_callback:
            try:
                self._dlq_callback(dlq_item)
            except Exception as e:
                logger.error(f"Error in DLQ callback: {e}", exc_info=True)

    def _start_flush_thread(self) -> None:
        """Start background flush thread."""
        self._stop_flush_thread.clear()
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()

    def _flush_loop(self) -> None:
        """Background flush loop.

        Uses Event.wait() instead of time.sleep() so the thread
        responds promptly to stop requests.
        """
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
            self._flush_thread.join(timeout=5.0)
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
