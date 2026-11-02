"""N3 format refusals only; no legacy code table or authority outcome."""

from typing import Literal, NoReturn

FormatCode = Literal["TARGET_BINDING_INVALID", "TARGET_SCHEMA_MISMATCH"]


class TargetRefused(ValueError):
    """N3-local format error. The payload is a fixed code, never supplied data."""

    def __init__(self, code: FormatCode) -> None:
        if type(code) is not str or code not in ("TARGET_BINDING_INVALID", "TARGET_SCHEMA_MISMATCH"):
            raise TypeError("unsupported N3 format code")
        super().__init__(code)

    @property
    def code(self) -> str:
        return self.args[0]


def _refuse(code: FormatCode) -> NoReturn:
    raise TargetRefused(code)
