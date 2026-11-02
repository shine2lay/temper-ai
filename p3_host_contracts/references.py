"""Byte locators: no reading, normalization, digest verification or access grant."""

from dataclasses import dataclass

from ._shape import integer, text_fields


@dataclass(frozen=True, slots=True)
class RawRef:
    root_locator: str
    relative_path: str
    byte_length: int
    sha256: str

    def __post_init__(self) -> None:
        text_fields(
            root_locator=self.root_locator,
            relative_path=self.relative_path,
            sha256=self.sha256,
        )
        integer("byte_length", self.byte_length, minimum=0)
