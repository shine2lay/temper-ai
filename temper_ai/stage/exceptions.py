"""Stage module exceptions."""

import logging
import threading
from collections.abc import Callable
from typing import Any

from temper_ai.shared.exceptions import TemperError

logger = logging.getLogger(__name__)


class StageError(TemperError):
    """Error in stage/graph execution or configuration."""


class WorkflowError(StageError):
    """Error in top-level workflow execution."""


class TopologyError(StageError):
    """Error in topology generation (strategy)."""


class ConditionError(StageError):
    """Error evaluating a condition expression."""


class LoaderError(StageError):
    """Error loading or resolving graph/workflow config."""


class CyclicDependencyError(LoaderError):
    """Graph has circular dependencies."""


class ValidationError(LoaderError):
    """Graph config validation failed."""


class CancellationError(StageError):
    """Workflow was cancelled by the user."""


#: A stopped run's reason when the stop gave no words (or they can't be read).
CANCEL_MESSAGE = "Workflow cancelled by user"


class CancelFlag(threading.Event):
    """A run's cancel flag that also carries the stop's own words (queue #111).

    In the server's process the cancel hands its words over as it sets the flag
    (``cancel``). A box's worker learns of a cancel by a signal, which carries no words: it
    is made with ``words_from``, which reads them from the stop's own record when they're
    first asked for after the flag is set. Without words the run ends with
    ``CANCEL_MESSAGE``, as before.
    """

    def __init__(self, words_from: Callable[[], str | None] | None = None) -> None:
        super().__init__()
        self._words: str | None = None
        self._words_from = words_from

    def cancel(self, words: str | None = None) -> None:
        """Set the flag, keeping the first stop's words."""
        if self._words is None:
            self._words = (words or "").strip() or None
        self.set()

    def words(self) -> str | None:
        """The stop's words, or None when it gave none or the flag isn't set."""
        if self._words is None and self._words_from is not None and self.is_set():
            try:
                self._words = (self._words_from() or "").strip() or None
            except Exception:  # noqa: BLE001 - the run still ends; only its words are missing
                logger.warning("could not read the stop's words", exc_info=True)
        return self._words


def stop_words(cancel_event: Any) -> str | None:
    """The words a run's cancel flag carries: None for a plain ``threading.Event``."""
    words = getattr(cancel_event, "words", None)
    return words() if callable(words) else None


def stopped_by_cancel(cancel_event: Any) -> CancellationError:
    """The error a run raises where it notices its cancel: the stop's own words, else
    ``CANCEL_MESSAGE``."""
    return CancellationError(stop_words(cancel_event) or CANCEL_MESSAGE)


#: The data key an event of a stood-down attempt carries (``cancelled`` with this set): the
#: attempt stood down for a later one; the run itself was not stopped.
REPLACED_MARK = "replaced_by_later_attempt"


class ReplacedByLaterAttempt(CancellationError):  # noqa: N818 - a state, like RunParked
    """A later attempt of the same run took this attempt's work over: this one stands down.

    Raised where an attempt finds it is no longer the run's newest: its wait was retired
    (``replaced``) by the newer attempt, or a check before it takes over a turn finds a newer
    ``workflow.started``. It is a stop, so every ``CancellationError`` handler still treats
    it as one, but it touches only its own attempt: AgentNode passes it up at once (no
    retry), a Pi step leaves the conversation and the ledger to the newer attempt, and the
    run's top writes only this attempt's own events down, never the run's row or a notice
    (docs/pi-agent.md, "A replaced attempt stands down"). The run's cancel signal is never
    set for it: that would stop the newer attempt too.
    """


class RunParked(Exception):  # noqa: N818 - a state the run is put in, not an error
    """A Pi workflow's wait saved where the run is and let its worker go.

    The wait is a gate's, or a step's own (``wait_id``: stage/step_waits.py). Not a failure
    and not a stop: the run is waiting on the owner. It goes up through every graph level
    untouched (the step, a stage, a parallel batch) to the run's top, which writes the
    attempt down as parked and ends without settling anything (docs/gates.md). The owner's
    answer carries the run on through Resume's own path (runner/parked.py).
    """

    def __init__(self, *, event_id: str, node: str, path: str, round: int, checkpoint_id: str,
                 wait_id: str | None = None, wake_at: str | None = None):
        super().__init__(f"waiting on you at '{path}'")
        self.event_id = event_id
        self.node = node
        self.path = path
        self.round = round
        self.checkpoint_id = checkpoint_id
        # The step's own wait id when a step asked from inside its work; None for a gate.
        self.wait_id = wait_id
        # A timed usage-limit wait frees the worker too; the reaper carries it on when due.
        self.wake_at = wake_at
        # Steps that finished in the same parallel batch before it parked: the batch hands
        # them up so they are kept (and checkpointed) like any finished step.
        self.finished: list = []
        # Other gates of the same batch that parked too (their as_dict()): an answer at any of
        # them carries the run on.
        self.also: list[dict] = []

    def as_dict(self) -> dict:
        return {"event_id": self.event_id, "node": self.node, "path": self.path,
                **({"wake_at": self.wake_at, "kind": "usage_limit"} if self.wake_at else
                   {"round": self.round}), "checkpoint_id": self.checkpoint_id,
                **({"wait_id": self.wait_id} if self.wait_id is not None else {}),
                **({"also": list(self.also)} if self.also else {})}
