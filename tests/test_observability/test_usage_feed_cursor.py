"""Fixed codec stage, no model/provider/HTTP/host operation. Happy path first."""

from __future__ import annotations

import base64
import struct
from dataclasses import replace
from unittest.mock import Mock

import pytest

from temper_ai.observability import usage_feed_cursor as codec
from temper_ai.observability.usage_feed_cursor import (
    MAX_EPOCH,
    MAX_REVISION,
    MAX_SEQ,
    CursorError,
    FinalRowAnchor,
    InitializedNoProgress,
    RowCursor,
    TargetCursor,
    decode_row_cursor,
    decode_target_cursor,
    encode_row_cursor,
    encode_target_cursor,
)

SOURCE = "0000000a-0000-4000-8000-000000000001"
ANCHOR = FinalRowAnchor(9, "fixture:event-9", 2)
ROW = RowCursor(SOURCE, 7, ANCHOR)
TARGET = TargetCursor(SOURCE, 7, ANCHOR)


def test_00_combined_codec_happy_path_and_typed_null():
    row, target = encode_row_cursor(ROW), encode_target_cursor(TARGET)
    assert row != target and len(row) <= 256 and len(target) <= 256
    assert decode_row_cursor(row) == ROW
    assert decode_target_cursor(target) == TARGET
    assert encode_row_cursor(decode_row_cursor(row)) == row
    assert InitializedNoProgress(SOURCE, 7) != ROW
    assert not hasattr(InitializedNoProgress(SOURCE, 7), "anchor")
    for token, decoder in ((target, decode_row_cursor), (row, decode_target_cursor)):
        with pytest.raises(CursorError, match="^usage-cursor-invalid$"):
            decoder(token)
    # No marker/initialized-null object can be turned into a fictitious G.
    with pytest.raises(CursorError):
        encode_row_cursor(InitializedNoProgress(SOURCE, 7))
    for encoder, value in ((encode_row_cursor, TARGET), (encode_target_cursor, ROW)):
        with pytest.raises(CursorError):
            encoder(value)


@pytest.mark.parametrize("anchor", [FinalRowAnchor(1, "a", 0), FinalRowAnchor(MAX_SEQ, "a" * 128, MAX_REVISION)])
def test_exact_schema_extremes(anchor):
    row = RowCursor(SOURCE, MAX_EPOCH, anchor)
    token = encode_row_cursor(row)
    assert len(token) <= 256 and decode_row_cursor(token) == row
    # The private format is closed: 38 fixed bytes + the exact ASCII event id.
    raw = base64.urlsafe_b64decode(token[3:] + "=" * (-len(token[3:]) % 4))
    assert len(raw) == struct.calcsize("!B16sQQIB") + len(anchor.event_id)


@pytest.mark.parametrize("token", [None, 1, b"r1.a", "", "r2.a", "t1.a", "r1.", "r1.a", "r1.aa=",
                                  "r1.a.b", "r1.a/b", "r1.a+b", "r1.\n", "r1.é", "r1." + "a" * 254])
def test_closed_wire_rejects_bad_type_domain_version_alphabet_length(token):
    with pytest.raises(CursorError, match="^usage-cursor-invalid$"):
        decode_row_cursor(token)


@pytest.mark.parametrize("offset,value", [(0, 2), (17, 0), (25, 0), (33, 255), (37, 0), (37, 127)])
def test_closed_binary_version_epoch_seq_revision_and_event_length(offset, value):
    raw = bytearray(base64.urlsafe_b64decode(encode_row_cursor(ROW)[3:] + "=="))
    if offset in (17, 25):  # zero epoch/seq, not just its first byte
        raw[offset:offset + 8] = bytes(8)
    else:
        raw[offset] = value
    token = "r1." + base64.urlsafe_b64encode(raw).decode().rstrip("=")
    with pytest.raises(CursorError):
        decode_row_cursor(token)


def test_noncanonical_unused_bits_and_trailing_bytes_refuse():
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    # 39 bytes is exactly divisible by three; choose an event of length two.
    token = encode_row_cursor(RowCursor(SOURCE, 7, FinalRowAnchor(1, "ab", 0)))
    index = alphabet.index(token[-1])
    mutant = token[:-1] + alphabet[index + 1]
    assert mutant != token
    with pytest.raises(CursorError):
        decode_row_cursor(mutant)
    raw = base64.urlsafe_b64decode(token[3:] + "=" * (-len(token[3:]) % 4))
    with pytest.raises(CursorError):
        decode_row_cursor("r1." + base64.urlsafe_b64encode(raw + b"x").decode().rstrip("="))


@pytest.mark.parametrize("seq,event,revision", [(0, "a", 0), (-1, "a", 0), (True, "a", 0),
    (MAX_SEQ + 1, "a", 0), (1, "", 0), (1, "a" * 129, 0), (1, "bad/id", 0),
    (1, "é", 0), (1, "a", -1), (1, "a", True), (1, "a", MAX_REVISION + 1)])
def test_anchor_bounds_match_final_schema(seq, event, revision):
    with pytest.raises(CursorError):
        FinalRowAnchor(seq, event, revision)


@pytest.mark.parametrize("source,epoch", [(SOURCE.upper(), 7), (SOURCE.replace("-", ""), 7),
    ("x" * 36, 7), (None, 7), (SOURCE, 0), (SOURCE, -1), (SOURCE, True), (SOURCE, MAX_EPOCH + 1)])
def test_exact_source_and_epoch(source, epoch):
    for kind in (RowCursor, TargetCursor):
        with pytest.raises(CursorError):
            kind(source, epoch, ANCHOR)
    with pytest.raises(CursorError):
        InitializedNoProgress(source, epoch)


def test_target_not_row_and_no_live_identity_fields():
    with pytest.raises(CursorError):
        replace(ROW, anchor=None)
    with pytest.raises(TypeError):
        RowCursor(SOURCE, 7, ANCHOR, system_identifier="private-digit-canary")
    # No MAC/prefix/issuance proof: a principal can construct another real ROW.
    forged = replace(ROW, anchor=FinalRowAnchor(10, "another-real-row", 0))
    assert decode_row_cursor(encode_row_cursor(forged)) == forged


@pytest.mark.parametrize("anchor", [None, "anchor", (9, "fixture:event-9", 2), ROW])
def test_target_constructor_requires_its_own_real_anchor_type(anchor):
    with pytest.raises(CursorError, match="^usage-cursor-invalid$"):
        TargetCursor(SOURCE, 7, anchor)


def test_decoder_length_policy_is_checked_before_redundant_format_limits(monkeypatch):
    token = encode_row_cursor(ROW)
    assert codec.MAX_TOKEN_LENGTH == 256
    # A legal format currently cannot exceed256; make the independent policy
    # boundary observable without pretending to have found an accepted exploit.
    monkeypatch.setattr(codec, "MAX_TOKEN_LENGTH", len(token) - 1)
    with pytest.raises(CursorError, match="^usage-cursor-invalid$"):
        codec._decode(token, "r1.")


def test_decoder_uses_the_closed_alphabet_policy_before_base64(monkeypatch):
    token = encode_row_cursor(ROW)
    validator = Mock(wraps=codec._WIRE)
    monkeypatch.setattr(codec, "_WIRE", validator)
    assert codec._decode(token, "r1.") == (SOURCE, 7, ANCHOR)
    validator.fullmatch.assert_called_once_with(token[3:])
    # Instrumented predicate refusal must not be ignored just because a later
    # decoder could accept the bytes. This is an early-policy unit check.
    validator.fullmatch.return_value = None
    with pytest.raises(CursorError, match="^usage-cursor-invalid$"):
        codec._decode(token, "r1.")


def test_decoder_refuses_short_header_before_struct_unpack(monkeypatch):
    raw = bytes(codec._HEADER.size - 1)
    token = "r1." + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    header = Mock(wraps=codec._HEADER)
    header.size = codec._HEADER.size
    monkeypatch.setattr(codec, "_HEADER", header)
    with pytest.raises(CursorError, match="^usage-cursor-invalid$"):
        codec._decode(token, "r1.")
    # struct.error also refuses short input; it must not mask this early guard.
    header.unpack.assert_not_called()


@pytest.mark.parametrize("epoch", [0, MAX_EPOCH + 1])
def test_decoder_checks_epoch_before_public_constructor_can_mask_it(epoch):
    raw = bytearray(base64.urlsafe_b64decode(encode_row_cursor(ROW)[3:] + "=="))
    raw[17:25] = struct.pack("!Q", epoch)
    token = "r1." + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    with pytest.raises(CursorError, match="^usage-cursor-invalid$"):
        codec._decode(token, "r1.")
