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


class RunParked(Exception):  # noqa: N818 - a state the run is put in, not an error
    """A Pi workflow's gate saved where the run is and let its worker go.

    Not a failure and not a stop: the run is waiting on the owner. It goes up through every
    graph level untouched (a stage, a parallel batch) to the run's top, which writes the
    attempt down as parked and ends without settling anything (docs/gates.md). The owner's
    answer carries the run on through Resume's own path (runner/parked.py).
    """

    def __init__(self, *, event_id: str, node: str, path: str, round: int, checkpoint_id: str):
        super().__init__(f"waiting on you at '{path}'")
        self.event_id = event_id
        self.node = node
        self.path = path
        self.round = round
        self.checkpoint_id = checkpoint_id
        # Steps that finished in the same parallel batch before it parked: the batch hands
        # them up so they are kept (and checkpointed) like any finished step.
        self.finished: list = []
        # Other gates of the same batch that parked too (their as_dict()): an answer at any of
        # them carries the run on.
        self.also: list[dict] = []

    def as_dict(self) -> dict:
        return {"event_id": self.event_id, "node": self.node, "path": self.path,
                "round": self.round, "checkpoint_id": self.checkpoint_id,
                **({"also": list(self.also)} if self.also else {})}
