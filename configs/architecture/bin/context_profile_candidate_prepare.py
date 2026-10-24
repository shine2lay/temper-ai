#!/usr/bin/env python3
"""Offline write-once packaging, not a runner, adapter or admission authority.

No credentials, network, engine imports, sends, repair, retry or cleanup deletion.
Sizing uses native byte-price arithmetic, NEVER an estimated input token count.
Unknown provider framing stays null. The native final-wire-body cap still decides.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import sys
from decimal import Decimal, localcontext
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STAGE = Path("configs/architecture/stages/context_profile")
KNOWN = Path("configs/architecture/fixtures/context_profile/known")
CASES = (
    "k01-idea-pantry", "k02-startup-invoicing", "k03-growing-scheduling", "k04-large-photos",
    "k05-small-therapy", "k06-large-simple-transit", "k07-conflict-marketplace", "k08-missing-volunteers",
    "k09-projected-fitness", "k10-misleading-logistics", "k11-privacy-reading", "k12-internal-expenses",
    "k13-performance-docks", "k14-large-org-roomkeys",
)
STANDARD_SHA256 = "696f12c42886cf97395e793e7add19bc23007988f1b84dcda21a2bba08feb437"
SCHEMA_SHA256 = "965a75c384ab0b72220c507a78004aafc478bdcb4916ec1f050d8780ad377fbe"
PROMPT_SHA256 = "aee4f3b2ce88721c25e49ae6528c3de663e2dc1edfda30e9b2488ee193da3d58"
FORMAT = "context-profile-candidate-packet/v1"
OUTPUT_LIMIT, CALLS = 8192, 42
EXPOSURE_CAP = Decimal("12")
FILES = ("instructions.md", "schema.json", "brief.md", "prompt.txt", "route.json", "pricing.json")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class Refused(ValueError):
    """Content-free failure; never echo rejected text or exception details."""


def need(condition: bool, reason: str) -> None:
    if not condition:
        raise Refused(reason)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def strict_json(data: bytes, *, decimals: bool = False):
    def pairs(items):
        result = {}
        for key, value in items:
            need(key not in result, "duplicate_json_member")
            result[key] = value
        return result

    def constant(_value):
        raise Refused("nonfinite_json")

    def real(token):
        result = Decimal(token) if decimals else float(token)
        need(result.is_finite() if decimals else math.isfinite(result), "nonfinite_json")
        return result

    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                          parse_constant=constant, parse_float=real)
    except (UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, Refused):
            raise
        raise Refused("invalid_json") from None


def json_bytes(value) -> bytes:
    """Exact small encoder: Decimal is a JSON number, never converted to float."""
    def encode(node):
        if node is None or type(node) in (bool, int, str):
            return json.dumps(node, ensure_ascii=False, allow_nan=False)
        if isinstance(node, Decimal):
            need(node.is_finite(), "nonfinite_json")
            return format(node, "f")
        if isinstance(node, list):
            return "[" + ",".join(encode(x) for x in node) + "]"
        if isinstance(node, dict) and all(isinstance(k, str) for k in node):
            return "{" + ",".join(encode(k) + ":" + encode(node[k]) for k in sorted(node)) + "}"
        raise Refused("unserializable_metadata")
    return (encode(value) + "\n").encode("utf-8")


def fields(value, names: set[str], reason: str) -> dict:
    need(isinstance(value, dict) and set(value) == names, reason)
    return value


def digest(value) -> str:
    need(isinstance(value, str) and bool(_SHA.fullmatch(value)), "invalid_digest")
    return value


def identifier(value) -> str:
    need(isinstance(value, str) and bool(_ID.fullmatch(value)), "invalid_identifier")
    need(value.casefold() not in {"unknown", "pending", "todo", "placeholder", "unresolved"}, "unresolved_metadata")
    return value


def count(value, *, minimum: int = 0) -> int:
    need(type(value) is int and minimum <= value <= 2**53 - 1, "invalid_count")
    return value


def money(value) -> Decimal:
    need(type(value) is int or isinstance(value, (str, Decimal)), "invalid_money")
    if isinstance(value, str):
        need(bool(re.fullmatch(r"\d+(?:\.\d{1,12})?", value)), "invalid_money")
    try:
        result = Decimal(value)
    except (ValueError, ArithmeticError):
        raise Refused("invalid_money") from None
    need(result.is_finite() and 0 <= result <= Decimal("1000000000"), "invalid_money")
    need(result.as_tuple().exponent >= -12, "price_precision")
    return result


def exact_cost(input_quantity: int, output_quantity: int, input_rate, output_rate) -> Decimal:
    """Native reservation uses body bytes; reported-usage cost uses reported counts."""
    count(input_quantity)
    count(output_quantity)
    with localcontext() as context:
        context.prec = 100
        return (Decimal(input_quantity) * money(input_rate) + Decimal(output_quantity) * money(output_rate)) / 1000000


def prices(data: bytes) -> tuple[Decimal, Decimal]:
    value = fields(strict_json(data, decimals=True), {"currency", "models"}, "pricing_shape")
    need(value["currency"] == "USD", "pricing_currency")
    models = fields(value["models"], {"claude-opus-5-5"}, "pricing_model")
    entry = fields(models["claude-opus-5-5"], {"input_usd_per_million", "output_usd_per_million", "request_limit_evidence"},
                   "pricing_fields")
    input_rate, output_rate = money(entry["input_usd_per_million"]), money(entry["output_usd_per_million"])
    need((input_rate, output_rate) == (Decimal("4"), Decimal("20")), "prices_not_admitted")
    https(entry["request_limit_evidence"])
    return input_rate, output_rate


def https(value) -> str:
    need(isinstance(value, str) and bool(re.fullmatch(r"https://[A-Za-z0-9.-]+(?::\d+)?/[^\s]*", value)), "unresolved_evidence")
    return value


def budget(exposure, next_reservation) -> str:
    if exposure is None or next_reservation is None:
        return "STOP_UNKNOWN"
    with localcontext() as context:
        context.prec = 100
        return "STOP_CAP" if money(exposure) + money(next_reservation) > EXPOSURE_CAP else "WITHIN_CAP"


def absolute(path: Path) -> Path:
    path = Path(path)
    need(path.is_absolute(), "absolute_path_required")
    try:
        need(path.resolve(strict=True) == path, "noncanonical_or_symlink_path")
    except OSError:
        raise Refused("missing_path") from None
    return path


def read_file(path: Path, *, private: bool = False, maximum: int = 1048576) -> bytes:
    path = absolute(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            before = os.fstat(fd)
            need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, "unsafe_file")
            if private:
                need(before.st_uid == os.geteuid() and stat.S_IMODE(before.st_mode) == 0o600, "private_file_required")
            need(before.st_size <= maximum, "file_too_large")
            with os.fdopen(os.dup(fd), "rb") as stream:
                data = stream.read(maximum + 1)
            after = os.fstat(fd)
            stable = ("st_dev", "st_ino", "st_mode", "st_uid", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
            need(len(data) == before.st_size <= maximum
                 and all(getattr(before, key) == getattr(after, key) for key in stable), "file_changed")
            return data
        finally:
            os.close(fd)
    except OSError:
        raise Refused("file_io") from None


def root_fd(root: Path) -> int:
    root = absolute(root)
    try:
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        value = os.fstat(fd)
        if value.st_uid != os.geteuid() or stat.S_IMODE(value.st_mode) != 0o700:
            os.close(fd)
            raise Refused("private_root_required")
        return fd
    except OSError:
        raise Refused("root_io") from None


def bound_file(path: Path, descriptor: dict, *, maximum: int) -> bytes:
    fields(descriptor, {"bytes", "sha256"}, "file_descriptor")
    data = read_file(path, maximum=maximum)
    need(count(descriptor["bytes"]) == len(data), "byte_mismatch")
    need(digest(descriptor["sha256"]) == sha(data), "digest_mismatch")
    try:
        data.decode("utf-8")
    except UnicodeError:
        raise Refused("invalid_utf8") from None
    return data


def sizing(text: bytes, framing_bytes, cap, input_rate, output_rate) -> dict:
    decoded = text.decode("utf-8")
    text_bound = len(json.dumps(decoded, ensure_ascii=True))
    if framing_bytes is not None:
        count(framing_bytes, minimum=1)  # Unknown framing must NEVER be invented as zero.
    lower = exact_cost(len(text), OUTPUT_LIMIT, input_rate, output_rate)
    upper = None if framing_bytes is None else exact_cost(text_bound + framing_bytes, OUTPUT_LIMIT, input_rate, output_rate)
    need(lower <= money(cap), "certain_native_cap_refusal")
    return {"text_utf8_bytes": len(text), "text_json_bound_bytes": text_bound, "framing_bytes": framing_bytes,
            "reservation_lower_usd": lower, "reservation_upper_usd": upper, "sizing_status": "NATIVE_CAP_DECIDES"}


def route_metadata(data: bytes) -> dict:
    route = fields(strict_json(data, decimals=True), {
        "format", "status", "agent_type", "provider", "model", "route", "auth_mode", "family",
        "max_tokens", "output_bound_mode", "deadline_s", "route_evidence_sha256",
        "request_limit_evidence", "request_limit_evidence_sha256", "framing_bytes", "framing_evidence_sha256",
    }, "route_shape")
    fixed = {"format": "context-profile-candidate-route/v1", "status": "RESOLVED", "agent_type": "single_call",
             "provider": "anthropic", "model": "claude-opus-5-5", "route": "anthropic-oauth-named-token",
             "auth_mode": "oauth", "family": "A", "output_bound_mode": "request_limit",
             "max_tokens": OUTPUT_LIMIT, "deadline_s": 900}
    need(all(type(route[k]) is type(v) and route[k] == v for k, v in fixed.items()), "unresolved_route")
    digest(route["route_evidence_sha256"])
    digest(route["request_limit_evidence_sha256"])
    https(route["request_limit_evidence"])
    if route["framing_bytes"] is None:
        need(route["framing_evidence_sha256"] is None, "framing_evidence_mismatch")
    else:
        count(route["framing_bytes"], minimum=1)
        digest(route["framing_evidence_sha256"])
    return route


def fixed_text(instructions: bytes, brief: bytes, brief_sha256: str) -> bytes:
    # The accepted instructions already embed the schema. No duplicated schema/body.
    return instructions + b"\n\nBRIEF_SHA256\n" + brief_sha256.encode("ascii") + b"\n\nBRIEF_DATA_UTF8\n" + brief


def binding_check(binding: dict, root: Path) -> None:
    fields(binding, {"format", "root", "root_id", "packet_slot", "case_id", "repetition", "experiment_id", "binding_id",
                     "output_root", "slot", "family", "cost_cap_usd", "source_sha256", "config_sha256", "packet_sha256",
                     "brief", "instructions", "schema", "route", "pricing"}, "binding_shape")
    need(binding["format"] == "context-profile-candidate-binding/v1", "binding_version")
    case_id, repetition = binding["case_id"], binding["repetition"]
    need(case_id in CASES and type(repetition) is int and repetition in (1, 2, 3), "invalid_position")
    need(binding["packet_slot"] == f"{case_id}-r{repetition}", "packet_slot_binding")
    need(binding["family"] == "A" and binding["slot"] == f"A{repetition}", "native_slot_binding")
    for name in ("root_id", "packet_slot", "experiment_id", "binding_id"):
        identifier(binding[name])
    for name in ("source_sha256", "config_sha256", "packet_sha256"):
        digest(binding[name])
    need(binding["root"] == str(root), "root_binding")
    money(binding["cost_cap_usd"])  # Supplied at future dev-run admission, never a helper default.


def make_manifest(binding: dict, route: dict, snapshots: dict, directory: Path) -> dict:
    input_rate, output_rate = prices(snapshots["pricing.json"])
    price_entry = strict_json(snapshots["pricing.json"])["models"]["claude-opus-5-5"]
    need(price_entry["request_limit_evidence"] == route["request_limit_evidence"], "price_evidence_mismatch")
    measurements = sizing(snapshots["prompt.txt"], route["framing_bytes"], binding["cost_cap_usd"], input_rate, output_rate)
    single_call = {key: binding[key] for key in ("output_root", "slot", "family", "cost_cap_usd", "experiment_id",
                                                "binding_id", "source_sha256", "config_sha256", "packet_sha256")}
    single_call["cost_cap_usd"] = money(binding["cost_cap_usd"])
    single_call.update({key: route[key] for key in ("route", "auth_mode", "max_tokens", "output_bound_mode", "deadline_s")})
    single_call.update({"prompt_path": str(directory / "prompt.txt"), "prompt_sha256": sha(snapshots["prompt.txt"]),
                        "prompt_bytes": len(snapshots["prompt.txt"]), "pricing_path": str(directory / "pricing.json"),
                        "pricing_sha256": sha(snapshots["pricing.json"])})
    return {"format": FORMAT, "contract": "context_profile/v2", "standard_sha256": STANDARD_SHA256,
            "binding": binding, "provider": route["provider"], "model": route["model"], "single_call": single_call,
            "route_metadata": route, "input_usd_per_million": input_rate, "output_usd_per_million": output_rate,
            **measurements, "pool_reservation_usd": None,
            "files": {name: {"bytes": len(data), "sha256": sha(data)} for name, data in snapshots.items()},
            "self_check": "STRUCTURAL_ONLY", "semantic_status": "NOT_MEASURED", "activation": "DORMANT"}


def prepare(*, brief: Path, instructions: Path, schema: Path, route_path: Path,
            pricing_path: Path, root: Path, binding: dict) -> dict:
    root = absolute(root)
    binding_check(binding, root)
    case_id = binding["case_id"]
    need(Path(brief) == REPO / KNOWN / case_id / "brief.md", "brief_not_allowlisted")
    need(Path(instructions) == REPO / STAGE / "PROMPT-CANDIDATE.md", "instructions_not_approved")
    need(Path(schema) == REPO / STAGE / "contract.v2.schema.json", "schema_not_approved")
    brief_data = bound_file(brief, binding["brief"], maximum=65536)
    prompt_data = bound_file(instructions, binding["instructions"], maximum=32768)
    schema_data = bound_file(schema, binding["schema"], maximum=32768)
    need(sha(schema_data) == SCHEMA_SHA256, "schema_not_frozen_v2")
    need(sha(prompt_data) == PROMPT_SHA256, "prompt_not_accepted")
    route_data = bound_file(route_path, binding["route"], maximum=16384)
    price_data = bound_file(pricing_path, binding["pricing"], maximum=16384)
    route = route_metadata(route_data)
    text = fixed_text(prompt_data, brief_data, sha(brief_data))
    snapshots = dict(zip(FILES, (prompt_data, schema_data, brief_data, text, route_data, price_data), strict=True))
    directory = root / binding["packet_slot"]
    manifest = make_manifest(binding, route, snapshots, directory)
    engine_root = absolute(Path(binding["output_root"]))
    engine_fd = root_fd(engine_root)
    os.close(engine_fd)
    for suffix in ("claim", "raw", "call.json", "attempt.json"):
        need(not os.path.lexists(engine_root / f"{binding['slot']}.{suffix}"), "native_slot_already_used")
    fd = root_fd(root)
    slot_fd = None
    try:
        os.mkdir(binding["packet_slot"], 0o700, dir_fd=fd)
        os.fsync(fd)
        slot_fd = os.open(binding["packet_slot"], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        os.fchmod(slot_fd, 0o700)
        snapshots["manifest.json"] = json_bytes(manifest)
        snapshots["SHA256SUMS"] = "".join(f"{sha(data)}  {name}\n" for name, data in sorted(snapshots.items())).encode("ascii")
        for name, data in snapshots.items():
            target = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=slot_fd)
            try:
                os.fchmod(target, 0o600)
                with os.fdopen(os.dup(target), "wb") as stream:
                    need(stream.write(data) == len(data), "short_write")
                    stream.flush()
                    os.fsync(stream.fileno())
            finally:
                os.close(target)
        os.fsync(slot_fd)
        os.fsync(fd)
    except OSError:
        raise Refused("slot_or_persistence_refused") from None
    finally:
        if slot_fd is not None:
            os.close(slot_fd)
        os.close(fd)
    return {"status": "PREPARED", "semantic_status": "NOT_MEASURED", "files": len(snapshots),
            "manifest_sha256": sha(snapshots["manifest.json"]),
            **{key: manifest[key] for key in ("text_utf8_bytes", "text_json_bound_bytes", "framing_bytes",
               "reservation_lower_usd", "reservation_upper_usd", "sizing_status", "pool_reservation_usd")}}


def verify_packet(directory: Path, expected_sha256: str) -> dict:
    directory = absolute(directory)
    fd = root_fd(directory)
    os.close(fd)
    manifest_data = read_file(directory / "manifest.json", private=True)
    need(sha(manifest_data) == digest(expected_sha256), "packet_digest_mismatch")
    manifest = strict_json(manifest_data, decimals=True)
    need(isinstance(manifest, dict) and manifest.get("format") == FORMAT, "packet_format")
    need(set(manifest["files"]) == set(FILES)
         and set(os.listdir(directory)) == {*FILES, "manifest.json", "SHA256SUMS"}, "packet_files")
    snapshots = {}
    for name in FILES:
        data = read_file(directory / name, private=True)
        descriptor = fields(manifest["files"][name], {"bytes", "sha256"}, "file_descriptor")
        need(len(data) == count(descriptor["bytes"]) and sha(data) == digest(descriptor["sha256"]), "packet_snapshot_changed")
        snapshots[name] = data
    sums = "".join(f"{sha(data)}  {name}\n" for name, data in sorted({**snapshots, "manifest.json": manifest_data}.items())).encode("ascii")
    need(read_file(directory / "SHA256SUMS", private=True) == sums, "packet_checksum_manifest")
    binding = manifest["binding"]
    binding_check(binding, directory.parent)
    need(binding["packet_slot"] == directory.name, "packet_root_binding")
    for field, name in (("brief", "brief.md"), ("instructions", "instructions.md"),
                        ("schema", "schema.json"), ("route", "route.json"), ("pricing", "pricing.json")):
        need(binding[field] == manifest["files"][name], "packet_binding_changed")
    need(sha(snapshots["schema.json"]) == SCHEMA_SHA256
         and sha(snapshots["instructions.md"]) == PROMPT_SHA256, "packet_foundation_changed")
    need(snapshots["prompt.txt"] == fixed_text(snapshots["instructions.md"], snapshots["brief.md"], sha(snapshots["brief.md"])),
         "packet_input_changed")
    expected = make_manifest(binding, route_metadata(snapshots["route.json"]), snapshots, directory)
    need(manifest == expected, "packet_manifest_changed")
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("brief", "instructions", "schema", "route", "pricing", "root", "binding"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = prepare(brief=args.brief, instructions=args.instructions, schema=args.schema,
                         route_path=args.route, pricing_path=args.pricing, root=args.root,
                         binding=strict_json(read_file(args.binding), decimals=True))
    except (Refused, OSError, KeyError, TypeError, ArithmeticError):
        print('{"status":"REFUSED","semantic_status":"NOT_MEASURED"}')
        return 2
    print(json_bytes(result).decode("utf-8"), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
