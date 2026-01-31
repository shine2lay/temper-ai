"""
Observability buffer for batching database operations.

Reduces N+1 query problem by batching LLM calls, tool calls, and metric updates.
Performance improvement: 200 queries → ~2 queries for 100 LLM calls.
"""
import threading
import time
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict
import logging

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

    def __init__(
        self,
        flush_size: int = 100,
        flush_interval: float = 1.0,
        auto_flush: bool = True
    ):
        """
        Initialize observability buffer.

        Args:
            flush_size: Flush when buffer reaches this many items
            flush_interval: Flush every N seconds (if auto_flush enabled)
            auto_flush: Enable automatic background flushing
        """
        self.flush_size = flush_size
        self.flush_interval = flush_interval
        self.auto_flush = auto_flush

        # Buffered operations
        self.llm_calls: List[BufferedLLMCall] = []
        self.tool_calls: List[BufferedToolCall] = []
        self.agent_metrics: Dict[str, AgentMetricUpdate] = defaultdict(lambda: AgentMetricUpdate(agent_id=""))

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

            # Check if we should flush
            if self._should_flush():
                self._flush_unsafe()

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

            # Check if we should flush
            if self._should_flush():
                self._flush_unsafe()

    def flush(self) -> None:
        """
        Flush all buffered operations to database.

        Thread-safe. Can be called manually or automatically.
        """
        with self.lock:
            self._flush_unsafe()

    def _should_flush(self) -> bool:
        """Check if buffer should be flushed (assumes lock is held)."""
        # Size-based flush
        total_items = len(self.llm_calls) + len(self.tool_calls)
        if total_items >= self.flush_size:
            return True

        # Time-based flush
        if time.time() - self.last_flush_time >= self.flush_interval:
            return True

        return False

    def _flush_unsafe(self) -> None:
        """Flush buffer (assumes lock is held)."""
        if not self._flush_callback:
            logger.warning("No flush callback set, skipping flush")
            return

        # Skip if nothing to flush
        if not self.llm_calls and not self.tool_calls and not self.agent_metrics:
            return

        # Extract data to flush
        llm_calls = self.llm_calls[:]
        tool_calls = self.tool_calls[:]
        agent_metrics = dict(self.agent_metrics)

        # Clear buffers
        self.llm_calls.clear()
        self.tool_calls.clear()
        self.agent_metrics.clear()
        self.last_flush_time = time.time()

        # Execute flush callback
        try:
            self._flush_callback(llm_calls, tool_calls, agent_metrics)
            logger.debug(
                f"Flushed {len(llm_calls)} LLM calls, "
                f"{len(tool_calls)} tool calls, "
                f"{len(agent_metrics)} agent metric updates"
            )
        except Exception as e:
            logger.error(f"Error flushing buffer: {e}", exc_info=True)
            # Re-buffer failed items (simple retry)
            with self.lock:
                self.llm_calls.extend(llm_calls)
                self.tool_calls.extend(tool_calls)
                for agent_id, metrics in agent_metrics.items():
                    if agent_id not in self.agent_metrics:
                        self.agent_metrics[agent_id] = metrics
                    else:
                        # Merge metrics
                        existing = self.agent_metrics[agent_id]
                        existing.num_llm_calls += metrics.num_llm_calls
                        existing.num_tool_calls += metrics.num_tool_calls
                        existing.total_tokens += metrics.total_tokens
                        existing.prompt_tokens += metrics.prompt_tokens
                        existing.completion_tokens += metrics.completion_tokens
                        existing.estimated_cost_usd += metrics.estimated_cost_usd

    def _start_flush_thread(self) -> None:
        """Start background flush thread."""
        self._stop_flush_thread.clear()
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()

    def _flush_loop(self) -> None:
        """Background flush loop."""
        while not self._stop_flush_thread.is_set():
            time.sleep(self.flush_interval)
            self.flush()

    def stop(self) -> None:
        """
        Stop background flush thread and flush remaining data.

        Call this before shutting down to ensure all data is persisted.
        """
        if self._flush_thread:
            self._stop_flush_thread.set()
            self._flush_thread.join(timeout=5.0)

        # Final flush
        self.flush()

    def get_stats(self) -> Dict[str, Any]:
        """Get buffer statistics."""
        with self.lock:
            return {
                "llm_calls_buffered": len(self.llm_calls),
                "tool_calls_buffered": len(self.tool_calls),
                "agent_metrics_buffered": len(self.agent_metrics),
                "total_buffered": len(self.llm_calls) + len(self.tool_calls),
                "flush_size": self.flush_size,
                "flush_interval": self.flush_interval,
                "auto_flush": self.auto_flush,
                "last_flush_time": self.last_flush_time
            }

    def __enter__(self) -> "ObservabilityBuffer":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit - ensure flush on exit."""
        self.stop()
