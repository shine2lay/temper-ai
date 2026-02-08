"""Helper functions extracted from ObservabilityBuffer to reduce class size.

Contains:
- Dead-letter queue (DLQ) management
- Flush execution logic
- Flush batch preparation
- Retry/failure handling
- Agent metric merging
"""
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


def purge_stale_pending_ids(
    pending_ids: Dict[str, float],
    timeout: float,
) -> int:
    """Remove pending IDs older than timeout.

    Args:
        pending_ids: Dict of item_id -> timestamp
        timeout: Seconds before a pending ID is considered stale

    Returns:
        Number of stale IDs purged.
    """
    cutoff = time.time() - timeout
    stale = [k for k, ts in pending_ids.items() if ts < cutoff]
    for k in stale:
        del pending_ids[k]
    if stale:
        logger.debug(f"Purged {len(stale)} stale pending IDs")
    return len(stale)


def prepare_flush_batch(
    llm_calls: list,
    tool_calls: list,
    agent_metrics: dict,
    retry_queue: list,
    pending_ids: Dict[str, float],
    retryable_item_cls: type,
    _agent_metric_update_cls: type,
    merge_fn: Callable,
) -> list:
    """Prepare batch for flushing, combining new items and retry queue.

    Implements deduplication to prevent double-insertion.

    Args:
        llm_calls: Current buffered LLM calls
        tool_calls: Current buffered tool calls
        agent_metrics: Current buffered agent metrics
        retry_queue: Items pending retry
        pending_ids: Pending ID -> timestamp map
        retryable_item_cls: RetryableItem class
        agent_metric_update_cls: AgentMetricUpdate class (unused but kept for API consistency)
        merge_fn: Function to merge agent metrics

    Returns:
        List of RetryableItem objects ready for flush
    """
    retryable_items = []

    # Add new LLM calls
    for llm_call in llm_calls:
        item_id = llm_call.llm_call_id
        if item_id not in pending_ids:
            retryable_items.append(retryable_item_cls(
                item=llm_call,
                item_type="llm_call",
                item_id=item_id,
                retry_count=0
            ))
            pending_ids[item_id] = time.time()

    # Add new tool calls
    for tool_call in tool_calls:
        item_id = tool_call.tool_execution_id
        if item_id not in pending_ids:
            retryable_items.append(retryable_item_cls(
                item=tool_call,
                item_type="tool_call",
                item_id=item_id,
                retry_count=0
            ))
            pending_ids[item_id] = time.time()

    # Add agent metrics (merge if already in retry queue)
    for agent_id, metrics in agent_metrics.items():
        # Check if already in retry queue
        existing = next(
            (item for item in retry_queue
             if item.item_type == "agent_metric" and item.item_id == agent_id),
            None
        )

        if existing:
            # Merge new metrics into existing retry item
            merge_fn(existing.item, metrics)
        else:
            retryable_items.append(retryable_item_cls(
                item=metrics,
                item_type="agent_metric",
                item_id=agent_id,
                retry_count=0
            ))
            pending_ids[agent_id] = time.time()

    # Add items from retry queue
    retryable_items.extend(retry_queue)

    return retryable_items


def execute_flush(
    items_to_flush: list,
    flush_callback: Callable,
    lock: Any,
    pending_ids: Dict[str, float],
    retry_queue_ref: list,
    handle_failure_fn: Callable,
    merge_fn: Callable,
) -> None:
    """Execute flush callback outside the lock.

    Args:
        items_to_flush: Prepared batch of retryable items
        flush_callback: The callback to invoke
        lock: Threading lock for synchronization
        pending_ids: Pending ID map (modified on success)
        retry_queue_ref: Retry queue list (cleared on success)
        handle_failure_fn: Function to handle flush failures
        merge_fn: Function to merge agent metrics
    """
    from src.observability.buffer import AgentMetricUpdate

    # Extract by type for callback
    llm_calls = [item.item for item in items_to_flush if item.item_type == "llm_call"]
    tool_calls = [item.item for item in items_to_flush if item.item_type == "tool_call"]

    # Batch agent metric updates: merge all metrics per agent into a single
    # AgentMetricUpdate to avoid N+1 updates in the flush callback (M-44).
    agent_metrics: Dict[str, Any] = {}
    for item in items_to_flush:
        if item.item_type != "agent_metric":
            continue
        metric = item.item
        if item.item_id in agent_metrics:
            merge_fn(agent_metrics[item.item_id], metric)
        else:
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
        with lock:
            for item in items_to_flush:
                pending_ids.pop(item.item_id, None)
            retry_queue_ref.clear()

    except Exception as e:
        logger.error(f"Error flushing buffer: {e}", exc_info=True)
        with lock:
            handle_failure_fn(items_to_flush, str(e))


def merge_agent_metrics(existing: Any, new: Any) -> None:
    """Merge new metrics into existing metrics (for retry queue)."""
    existing.num_llm_calls += new.num_llm_calls
    existing.num_tool_calls += new.num_tool_calls
    existing.total_tokens += new.total_tokens
    existing.prompt_tokens += new.prompt_tokens
    existing.completion_tokens += new.completion_tokens
    existing.estimated_cost_usd += new.estimated_cost_usd


def handle_flush_failure(
    failed_items: list,
    error: str,
    max_retries: int,
    retry_queue: list,
    pending_ids: Dict[str, float],
    move_to_dlq_fn: Callable,
) -> None:
    """Handle flush failure with retry logic and dead-letter queue.

    Items are retried up to max_retries times, then moved to DLQ.
    """
    now = datetime.now(timezone.utc)
    new_retry_queue = []

    for item in failed_items:
        item.retry_count += 1
        if item.first_failed_at is None:
            item.first_failed_at = now
        item.last_error = error

        if item.retry_count > max_retries:
            move_to_dlq_fn(item, now)
            pending_ids.pop(item.item_id, None)
        else:
            new_retry_queue.append(item)
            logger.warning(
                f"Retry {item.retry_count}/{max_retries} for {item.item_type} "
                f"{item.item_id}: {error}"
            )

    # Update retry queue
    retry_queue.clear()
    retry_queue.extend(new_retry_queue)


def move_to_dlq(
    item: Any,
    now: datetime,
    enable_dlq: bool,
    dead_letter_queue: list,
    max_dlq_size: int,
    dlq_callback: Optional[Callable],
    dead_letter_item_cls: type,
) -> None:
    """Move failed item to dead-letter queue.

    Enforces max_dlq_size by dropping oldest entries when the limit is exceeded.
    """
    if not enable_dlq:
        logger.error(
            f"Item {item.item_type} {item.item_id} permanently failed after "
            f"{item.retry_count} retries (DLQ disabled): {item.last_error}"
        )
        return

    dlq_item = dead_letter_item_cls(
        item=item.item,
        item_type=item.item_type,
        item_id=item.item_id,
        retry_count=item.retry_count,
        first_failed_at=item.first_failed_at or now,
        final_error=item.last_error or "Unknown error",
        failed_at=now
    )

    dead_letter_queue.append(dlq_item)

    # Enforce max DLQ size
    if len(dead_letter_queue) > max_dlq_size:
        overflow = len(dead_letter_queue) - max_dlq_size
        del dead_letter_queue[:overflow]
        logger.warning("DLQ overflow: dropped %d oldest items", overflow)

    logger.error(
        f"Moved {item.item_type} {item.item_id} to DLQ after "
        f"{item.retry_count} retries: {item.last_error}"
    )

    # Trigger DLQ callback if set
    if dlq_callback:
        try:
            dlq_callback(dlq_item)
        except Exception as e:
            logger.error(f"Error in DLQ callback: {e}", exc_info=True)
