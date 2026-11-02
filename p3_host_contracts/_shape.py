"""Pure construction checks, never access checks or reference authentication.

Diagnostics name fields, not their potentially sensitive contents. External
references are only checked for explicit absence; their suppliers own validity.
"""


def text_fields(**values: object) -> None:
    for name, value in values.items():
        if not isinstance(value, str):
            raise TypeError(f"{name} must be str")


def references(**values: object) -> None:
    for name, value in values.items():
        if value is None:
            raise TypeError(f"{name} requires an external reference")


def integer(name: str, value: object, *, minimum: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be int, not bool")
    if value < minimum:
        raise ValueError(f"{name} is below its domain minimum")


def choice(name: str, value: object, alternatives: tuple[str, ...]) -> None:
    text_fields(**{name: value})
    if value not in alternatives:
        raise ValueError(f"{name} is outside its closed alternatives")


def record(name: str, value: object, expected: type | tuple[type, ...]) -> None:
    if not isinstance(value, expected):
        raise TypeError(f"{name} has the wrong record type")


def optional_record(name: str, value: object, expected: type) -> None:
    if value is not None:
        record(name, value, expected)


def items(name: str, value: object, expected: type | None = None) -> None:
    if type(value) is not tuple:
        raise TypeError(f"{name} must be tuple")
    for item in value:
        if expected is None:
            references(**{name: item})
        else:
            record(name, item, expected)


def words(name: str, value: object) -> None:
    if type(value) is not frozenset:
        raise TypeError(f"{name} must be frozenset")
    for item in value:
        text_fields(**{name: item})
