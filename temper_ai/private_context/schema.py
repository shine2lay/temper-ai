"""Consume application-owned JSON Schema artifacts, never duplicate app schemas.

Artifacts are explicitly supplied by the trusted profile owner. Provenance labels
are metadata, NOT proof of origin or authority. No file/URL loading or registry.
"""
from __future__ import annotations

from typing import Any, Literal

from jsonschema import Draft7Validator, Draft202012Validator
from referencing import Registry

from .errors import PrivateDraftErrorCode as Code
from .errors import PrivateDraftFailure
from .private_json import PrivateJSON, decode_object, encode_private
from .wire import ClosedModel, Identifier, PrivateResult, RegisterContext


class SchemaIdentity(ClosedModel):
    owner: Identifier
    revision: Identifier
    source_kind: Literal["source_generated", "synthetic"]
    context_schema: Identifier
    result_schema: Identifier


def _local_references(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"$ref", "$dynamicRef", "$recursiveRef"}:
                if not isinstance(item, str) or (item != "" and not item.startswith("#")):
                    raise ValueError("external schema")
            _local_references(item)
    elif isinstance(value, list):
        for item in value:
            _local_references(item)


def _validator(raw: bytes) -> Any:
    schema = decode_object(raw, Code.CONFIGURATION_INVALID)
    dialect = schema.get("$schema")
    cls: Any
    if dialect in {"http://json-schema.org/draft-07/schema#", "https://json-schema.org/draft-07/schema"}:
        cls = Draft7Validator
    elif dialect == "https://json-schema.org/draft/2020-12/schema":
        cls = Draft202012Validator
    else:
        raise ValueError("schema dialect")
    _local_references(schema)
    cls.check_schema(schema)
    # An explicit empty referencing.Registry refuses all external retrieval.
    # Omitting it would enable jsonschema's deprecated remote-fetch fallback.
    return cls(schema, registry=Registry(), format_checker=cls.FORMAT_CHECKER)


class ValidatedDraft(PrivateJSON):
    """Application-schema-validated snapshot. Service rechecks current schema at publish."""
    __slots__ = ()


class SchemaArtifact:
    """Own independent immutable schema snapshots; no global settings or imports with I/O."""
    __slots__ = ("__identity", "__context", "__result")

    def __init__(self, identity: SchemaIdentity, *, context: bytes, result: bytes) -> None:
        try:
            if type(identity) is not SchemaIdentity:
                raise ValueError("identity")
            if identity.source_kind == "synthetic" and not (
                identity.context_schema.startswith("synthetic.") and identity.result_schema.startswith("synthetic.")
            ):
                raise ValueError("synthetic schema labels")
            context_validator = _validator(context)
            result_validator = _validator(result)
        except Exception:
            # JSON Schema failures can contain the schema and instance. Do not
            # keep the exception or re-raise from within its handler.
            pass
        else:
            self.__identity = identity
            self.__context = context_validator
            self.__result = result_validator
            return
        raise PrivateDraftFailure(Code.CONFIGURATION_INVALID)

    @property
    def identity(self) -> SchemaIdentity:
        return self.__identity

    def __repr__(self) -> str:
        return "<SchemaArtifact>"

    def validate_registration(self, registration: RegisterContext) -> None:
        value = registration.open_private()
        try:
            valid = value["context_schema"] == self.identity.context_schema and self.__context.is_valid(value["context"])
        except Exception:
            valid = False
        if not valid:
            raise PrivateDraftFailure(Code.CONTEXT_INVALID)

    def validate_draft(self, raw: bytes) -> ValidatedDraft:
        value = decode_object(raw, Code.OUTPUT_INVALID)
        try:
            valid = self.__result.is_valid(value)
        except Exception:
            valid = False
        if not valid:
            raise PrivateDraftFailure(Code.OUTPUT_INVALID)
        return ValidatedDraft(raw)

    def validate_result(self, result: PrivateResult) -> ValidatedDraft:
        value = result.open_private()
        if value["result_schema"] != self.identity.result_schema:
            raise PrivateDraftFailure(Code.OUTPUT_INVALID)
        return self.validate_draft(encode_private(value["draft"]))
