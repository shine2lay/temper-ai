#!/usr/bin/env python3
"""Metadata-only compiler for Temper's candidate-admission v1 wire.

compile: explicit authoring metadata -> canonical v1 descriptor, raw closure
and a safe manifest. verify: recheck existing artifacts. Both modes need the
DescriptorAuthority pins supplied out of band by the approving caller; this
tool never derives, stores or offers authority. It fills no field, resolves no
reference, reads no live configuration, environment or network, and never calls
a candidate runnable. Authoring form: docs/context-profile-admission-authoring.md.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from enum import StrEnum
from pathlib import Path
from types import ModuleType
from typing import Any, NoReturn

# Temper #192 contract pins (commit caf5c16f6d9965cbcbc8e10653d75e1c47b27340).
CODEC_SHA256 = "f9b0f36ed20afaecd12654cd80a203214f3f2d5727f4668fc0c1926fa3df1c34"
SCHEMA_SHA256 = "426e1c5a12eafa5a82e64144d25e0fa08d5b844149723ea001a76fe9a0f2041d"
AUTHORITY_FIELDS = frozenset({
    "expected_descriptor_sha256", "expected_source_sha256",
    "authorized_caller_label", "receipt_id",
})
RAW_IDENTITY = ("kind", "name", "schema_version", "origin")
KNOWN_FIELDS = "_KNOWN_FIELDS"
ARTIFACTS = ("descriptor.json", "raw-records.json", "manifest.json")
AUTHORING = ("descriptor.json", "raw-records.json")


class CompilerCode(StrEnum):
    INPUT = "compiler_input"
    KNOWN = "compiler_known_fields"
    IO = "compiler_io"
    PIN = "compiler_contract_pin"
    AUTHORITY = "compiler_authority"
    MANIFEST = "compiler_manifest"
    OUTPUT = "compiler_output_exists"
    USAGE = "compiler_usage"
    INTERNAL = "compiler_internal"
    JSON = "invalid_json"
    DUPLICATE = "duplicate_key"
    NONFINITE = "nonfinite_number"


class CompilerRefused(Exception):
    """Carries a fixed code only, never rejected data or a cause chain."""

    def __init__(self, code: CompilerCode):
        self.code = code.value
        super().__init__(self.code)


def refuse(code: CompilerCode) -> NoReturn:
    raise CompilerRefused(code) from None


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def strict_json(data: bytes) -> Any:
    """Authoring JSON may be indented; duplicate keys and nonfinite numbers refuse."""
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                refuse(CompilerCode.DUPLICATE)
            result[key] = value
        return result

    def finite(text: str) -> float:
        number = float(text)
        if not math.isfinite(number):
            refuse(CompilerCode.NONFINITE)
        return number

    if type(data) is not bytes:
        refuse(CompilerCode.INPUT)
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_float=finite,
                          parse_constant=lambda _: refuse(CompilerCode.NONFINITE))
    except (ValueError, UnicodeError, RecursionError):
        refuse(CompilerCode.JSON)


def load_contract(codec_path: Path) -> ModuleType:
    """Execute only the verified codec bytes read here, never a second read.

    The module is registered under a pin-derived name because stdlib dataclasses
    look it up. Ordinary temper_ai packages, config/__init__, stores, providers
    and engine entry points are never imported; no bytecode cache is used.
    """
    source = codec_path.read_bytes()
    if sha256(source) != CODEC_SHA256:
        refuse(CompilerCode.PIN)
    name = "_architecture_admission_contract_" + CODEC_SHA256
    spec = importlib.util.spec_from_file_location(name, codec_path)
    if spec is None:
        refuse(CompilerCode.PIN)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    exec(compile(source, str(codec_path), "exec"), module.__dict__)
    return module


def check_known_fields(value: Any, *, raw: bool) -> None:
    """Enforce the contract's only projection: sorted unique strings, engine-owned.

    Effective JSON may carry the projected frozenset as a sorted unique string
    array. Raw candidate configs must not supply it anywhere.
    """
    stack = [value]
    while stack:
        item = stack.pop()
        if type(item) is dict:
            if KNOWN_FIELDS in item:
                names = item[KNOWN_FIELDS]
                if raw or type(names) is not list or any(type(n) is not str for n in names) \
                        or names != sorted(set(names)):
                    refuse(CompilerCode.KNOWN)
            stack.extend(item.values())
        elif type(item) is list:
            stack.extend(item)


def members(container: Any, key: str) -> list[Any]:
    value = container.get(key) if type(container) is dict else None
    return value if type(value) is list else []


class Compiler:
    """Pure compilation/verification after the two explicit contract-file reads."""

    def __init__(self, codec_path: Path, schema_path: Path):
        # Keep the very schema bytes checked here; the codec checks them again.
        schema = schema_path.read_bytes()
        if sha256(schema) != SCHEMA_SHA256:
            refuse(CompilerCode.PIN)
        self.contract = load_contract(codec_path)
        self.codec = self.contract.ContractCodec(schema)

    def authority(self, value: Any) -> Any:
        if type(value) is not dict or set(value) != AUTHORITY_FIELDS:
            refuse(CompilerCode.AUTHORITY)
        if any(type(item) is not str or not item for item in value.values()):
            refuse(CompilerCode.AUTHORITY)
        return self.contract.DescriptorAuthority(**value)

    def own(self, value: Any) -> Any:
        """Fresh copy; aliases, cycles and non-JSON values refuse (CAJ-1)."""
        return self.contract.decode_canonical(self.contract.canonical_bytes(value))

    def encode_member(self, container: Any, key: str) -> None:
        """Replace one authored JSON object by its CAJ-1 text; text is never re-encoded."""
        if type(container) is not dict or key not in container:
            return  # The pinned schema reports the missing or malformed member.
        if type(container[key]) is not dict:
            refuse(CompilerCode.INPUT)
        container[key] = self.contract.canonical_bytes(container[key]).decode("utf-8")

    def _checked(self, descriptor_wire: bytes, records_wire: bytes, authority: Any) -> dict[str, bytes]:
        c = self.contract
        descriptor = self.codec.descriptor(descriptor_wire, self.authority(authority))
        records = c.decode_canonical(records_wire)
        if type(records) is not list:
            refuse(CompilerCode.INPUT)
        closure = self.codec.closure(descriptor, tuple(
            self.codec.raw_record(c.canonical_bytes(record)) for record in records))
        data = descriptor.value()
        unresolved = sum(position["root_policy"] is None for position in data["positions"])
        manifest = {
            "format": "context-profile-admission-artifacts/v1",
            "status": "metadata_verified_not_admitted",
            "runnable": False,
            "mode": data["mode"],
            "custody": "unresolved" if unresolved else "supplied_not_verified",
            "unresolved_root_policies": unresolved,
            "counts": {
                "raw_records": len(records),
                "graph_nodes": len(data["graph"]["nodes"]),
                "positions": len(data["positions"]),
                "scripts": len(data["scripts"]),
            },
            "digests": {
                "descriptor": descriptor.sha256,
                "source": c.digest(c.DigestDomain.SOURCE, c.canonical_bytes(data["source"])),
                "raw_closure": closure.sha256,
                "graph": c.digest(c.DigestDomain.GRAPH, c.canonical_bytes(data["graph"])),
            },
            "contract": {"codec_file_sha256": CODEC_SHA256, "schema_file_sha256": SCHEMA_SHA256},
            "files": {"descriptor.json": sha256(descriptor_wire), "raw-records.json": sha256(records_wire)},
        }
        return {"descriptor.json": descriptor_wire, "raw-records.json": records_wire,
                "manifest.json": c.canonical_bytes(manifest)}

    def compile(self, descriptor: Any, raw_records: Any, authority: Any) -> dict[str, bytes]:
        """Encode the ACTUAL supplied metadata; approval pins are never computed here.

        The authoring descriptor is the v1 descriptor without "records" and with
        JSON objects in place of the JSON-text members. The descriptor's records
        are taken from the supplied raw records, ordered by (kind, name).
        """
        c = self.contract
        descriptor, raw_records = self.own(descriptor), self.own(raw_records)
        if type(descriptor) is not dict or "records" in descriptor or type(raw_records) is not list:
            refuse(CompilerCode.INPUT)
        check_known_fields(descriptor, raw=False)
        records = []
        for raw in raw_records:
            if type(raw) is not dict:
                refuse(CompilerCode.INPUT)
            check_known_fields(raw.get("config_json"), raw=True)
            self.encode_member(raw, "config_json")
            records.append(self.codec.raw_record(c.canonical_bytes(raw)))
        # Duplicates are kept for the codec's closure check to refuse.
        records.sort(key=lambda record: record.key)
        descriptor["records"] = [{**{k: record.value()[k] for k in RAW_IDENTITY},
                                  "raw_sha256": record.sha256} for record in records]
        self.encode_member(descriptor, "metadata_inputs_json")
        self.encode_member(descriptor, "request_options_json")
        graph = descriptor.get("graph")
        self.encode_member(graph, "workflow_json")
        for node in members(graph, "nodes"):
            self.encode_member(node, "node_json")
            self.encode_member(node.get("factory") if type(node) is dict else None, "config_json")
        for position in members(descriptor, "positions"):
            self.encode_member(position, "agent_config_json")
        for script in members(descriptor, "scripts"):
            self.encode_member(script, "variables_json")
        return self._checked(c.canonical_bytes(descriptor),
                             c.canonical_bytes([record.value() for record in records]), authority)

    def verify(self, artifacts: Any, authority: Any) -> dict[str, bytes]:
        """Check canonical bytes against fixed external authority and the manifest."""
        if type(artifacts) is not dict or set(artifacts) != set(ARTIFACTS) \
                or any(type(data) is not bytes for data in artifacts.values()):
            refuse(CompilerCode.INPUT)
        expected = self._checked(artifacts["descriptor.json"], artifacts["raw-records.json"], authority)
        # The manifest is informational; it is compared, never trusted as authority.
        if artifacts["manifest.json"] != expected["manifest.json"]:
            refuse(CompilerCode.MANIFEST)
        return expected


def read_files(directory: Path, names: tuple[str, ...]) -> dict[str, bytes]:
    if sorted(path.name for path in directory.iterdir()) != sorted(names):
        refuse(CompilerCode.INPUT)
    return {name: (directory / name).read_bytes() for name in names}


def write_files(directory: Path, files: dict[str, bytes]) -> None:
    """Never overwrite input or an earlier result; file names are fixed here."""
    try:
        directory.mkdir()
    except FileExistsError:
        refuse(CompilerCode.OUTPUT)
    for name, data in files.items():
        with (directory / name).open("xb") as stream:
            stream.write(data)
    # A failed write can leave an incomplete new directory. It is not valid:
    # verify requires all three fixed files and a matching manifest.


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        refuse(CompilerCode.USAGE)


def main(argv: list[str] | None = None) -> int:
    compiler = None
    try:
        parser = SafeParser(description="Compile or verify candidate-admission v1 metadata.")
        parser.add_argument("mode", choices=("compile", "verify"))
        for flag in ("input", "schema", "codec", "authority", "output"):
            parser.add_argument("--" + flag, type=Path, required=True)
        args = parser.parse_args(argv)
        compiler = Compiler(args.codec, args.schema)
        authority = strict_json(args.authority.read_bytes())
        if args.mode == "compile":
            files = read_files(args.input, AUTHORING)
            result = compiler.compile(strict_json(files["descriptor.json"]),
                                      strict_json(files["raw-records.json"]), authority)
            write_files(args.output, result)
        else:
            result = compiler.verify(read_files(args.input, ARTIFACTS), authority)
            write_files(args.output, {"verification.json": result["manifest.json"]})
        print('{"code":"metadata_verified_not_admitted","runnable":false}')
        return 0
    except CompilerRefused as exc:
        code = exc.code
    except OSError:
        code = CompilerCode.IO.value
    except Exception as exc:  # noqa: BLE001 - reduced to a fixed code below.
        if compiler is not None and isinstance(exc, compiler.contract.AdmissionRefused):
            code = exc.code.value
        else:
            code = CompilerCode.INTERNAL.value
    # No rejected data, paths, authority labels or exception chains escape.
    print(json.dumps({"code": code, "runnable": False}, separators=(",", ":")))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
