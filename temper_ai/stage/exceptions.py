"""Stage module exceptions."""

from temper_ai.shared.exceptions import TemperError


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
