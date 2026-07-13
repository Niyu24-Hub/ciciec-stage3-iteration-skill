#!/usr/bin/env python3
"""Summarize CICIEC stage-3 CBOR traces without third-party modules."""

from __future__ import annotations

import argparse
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


CURRENT_BIN_SHA256 = "a9ebf7cd5664a50ea9663201271886d30d32aa118ddb4c254e0a1519d0dd03b2"
CURRENT_BIN_SIZE = 3680
OLD_BIN_SHA256 = "08afdd6dee8a85b0e12c2a6f2a4136fb36fd2e889a6bcd4104ba482706fef6b7"
OLD_BIN_SIZE = 14992
OLD_EXTRAM_SHA256 = "33c29555b78a7c772f96a1deb55e047dde297c67832e6423261323d6304f2890"
EXTRAM_SIZE = 1_600_000
TRACE_FAST_GUARD_WORDS = ()
TRACE_FAST_GUARD_OFFSET = 0x26250
REQUIRED_OUTPUT_BYTES = 47
POST_START_OUTPUT_BYTES = 34
UART_BAUD = 115_200
UART_BITS_PER_BYTE = 10


@dataclass(frozen=True)
class ByteString:
    header_offset: int
    payload_offset: int
    length: int
    sha256: str


class CborError(RuntimeError):
    pass


def read_len(data: bytes, pos: int, ai: int) -> tuple[int | None, int]:
    if ai < 24:
        return ai, pos
    if ai == 24:
        size = 1
    elif ai == 25:
        size = 2
    elif ai == 26:
        size = 4
    elif ai == 27:
        size = 8
    elif ai == 31:
        return None, pos
    else:
        raise CborError(f"reserved additional-info value {ai} at 0x{pos - 1:x}")

    end = pos + size
    if end > len(data):
        raise CborError("truncated integer length")
    return int.from_bytes(data[pos:end], "big"), end


def parse_item(data: bytes, pos: int, out: list[ByteString]) -> int:
    if pos >= len(data):
        raise CborError("unexpected end of file")

    start = pos
    initial = data[pos]
    pos += 1
    major = initial >> 5
    ai = initial & 0x1F
    length, pos = read_len(data, pos, ai)

    if major in (0, 1):
        if length is None:
            raise CborError(f"indefinite integer at 0x{start:x}")
        return pos

    if major == 2:
        if length is None:
            chunks = bytearray()
            while True:
                if pos >= len(data):
                    raise CborError("unterminated indefinite byte string")
                if data[pos] == 0xFF:
                    pos += 1
                    payload = bytes(chunks)
                    out.append(ByteString(start, start, len(payload), hashlib.sha256(payload).hexdigest()))
                    return pos
                chunk_start = pos
                chunk_initial = data[pos]
                if chunk_initial >> 5 != 2:
                    raise CborError(f"non-byte chunk in indefinite byte string at 0x{pos:x}")
                pos += 1
                chunk_len, pos = read_len(data, pos, chunk_initial & 0x1F)
                if chunk_len is None:
                    raise CborError(f"nested indefinite byte string at 0x{chunk_start:x}")
                end = pos + chunk_len
                if end > len(data):
                    raise CborError("truncated byte-string chunk")
                chunks.extend(data[pos:end])
                pos = end

        payload_offset = pos
        end = pos + length
        if end > len(data):
            raise CborError(f"truncated byte string at 0x{start:x}")
        payload = data[payload_offset:end]
        out.append(ByteString(start, payload_offset, length, hashlib.sha256(payload).hexdigest()))
        return end

    if major == 3:
        if length is None:
            while True:
                if pos >= len(data):
                    raise CborError("unterminated indefinite text string")
                if data[pos] == 0xFF:
                    return pos + 1
                chunk_initial = data[pos]
                if chunk_initial >> 5 != 3:
                    raise CborError(f"non-text chunk in indefinite text string at 0x{pos:x}")
                pos += 1
                chunk_len, pos = read_len(data, pos, chunk_initial & 0x1F)
                if chunk_len is None:
                    raise CborError("nested indefinite text string")
                pos += chunk_len
                if pos > len(data):
                    raise CborError("truncated text-string chunk")
        pos += length
        if pos > len(data):
            raise CborError(f"truncated text string at 0x{start:x}")
        return pos

    if major == 4:
        if length is None:
            while True:
                if pos >= len(data):
                    raise CborError("unterminated indefinite array")
                if data[pos] == 0xFF:
                    return pos + 1
                pos = parse_item(data, pos, out)
        for _ in range(length):
            pos = parse_item(data, pos, out)
        return pos

    if major == 5:
        if length is None:
            while True:
                if pos >= len(data):
                    raise CborError("unterminated indefinite map")
                if data[pos] == 0xFF:
                    return pos + 1
                pos = parse_item(data, pos, out)
                pos = parse_item(data, pos, out)
        for _ in range(length):
            pos = parse_item(data, pos, out)
            pos = parse_item(data, pos, out)
        return pos

    if major == 6:
        if length is None:
            raise CborError(f"indefinite tag at 0x{start:x}")
        return parse_item(data, pos, out)

    if major == 7:
        if ai == 31:
            raise CborError(f"unexpected break at 0x{start:x}")
        return pos

    raise CborError(f"unknown CBOR major type {major} at 0x{start:x}")


def parse_cbor(data: bytes) -> list[ByteString]:
    out: list[ByteString] = []
    pos = parse_item(data, 0, out)
    if pos != len(data):
        raise CborError(f"trailing data starts at 0x{pos:x}")
    return out


def decode_item(data: bytes, pos: int) -> tuple[Any, int]:
    if pos >= len(data):
        raise CborError("unexpected end of file")

    initial = data[pos]
    pos += 1
    major = initial >> 5
    ai = initial & 0x1F
    length, pos = read_len(data, pos, ai)

    if major == 0:
        if length is None:
            raise CborError("indefinite unsigned integer")
        return length, pos

    if major == 1:
        if length is None:
            raise CborError("indefinite negative integer")
        return -1 - length, pos

    if major == 2:
        if length is None:
            chunks = []
            while True:
                if pos >= len(data):
                    raise CborError("unterminated indefinite byte string")
                if data[pos] == 0xFF:
                    return b"".join(chunks), pos + 1
                chunk, pos = decode_item(data, pos)
                if not isinstance(chunk, bytes):
                    raise CborError("non-byte chunk in indefinite byte string")
                chunks.append(chunk)

        end = pos + length
        if end > len(data):
            raise CborError("truncated byte string")
        return data[pos:end], end

    if major == 3:
        if length is None:
            chunks = []
            while True:
                if pos >= len(data):
                    raise CborError("unterminated indefinite text string")
                if data[pos] == 0xFF:
                    return "".join(chunks), pos + 1
                chunk, pos = decode_item(data, pos)
                if not isinstance(chunk, str):
                    raise CborError("non-text chunk in indefinite text string")
                chunks.append(chunk)

        end = pos + length
        if end > len(data):
            raise CborError("truncated text string")
        return data[pos:end].decode("utf-8", "replace"), end

    if major == 4:
        items = []
        if length is None:
            while True:
                if pos >= len(data):
                    raise CborError("unterminated indefinite array")
                if data[pos] == 0xFF:
                    return items, pos + 1
                item, pos = decode_item(data, pos)
                items.append(item)
        for _ in range(length):
            item, pos = decode_item(data, pos)
            items.append(item)
        return items, pos

    if major == 5:
        items = {}
        if length is None:
            while True:
                if pos >= len(data):
                    raise CborError("unterminated indefinite map")
                if data[pos] == 0xFF:
                    return items, pos + 1
                key, pos = decode_item(data, pos)
                value, pos = decode_item(data, pos)
                items[key] = value
        for _ in range(length):
            key, pos = decode_item(data, pos)
            value, pos = decode_item(data, pos)
            items[key] = value
        return items, pos

    if major == 6:
        value, pos = decode_item(data, pos)
        return {"tag": length, "value": value}, pos

    if major == 7:
        if ai == 20:
            return False, pos
        if ai == 21:
            return True, pos
        if ai == 22:
            return None, pos
        if ai == 23:
            return "undefined", pos
        return {"simple": ai, "value": length}, pos

    raise CborError(f"unknown CBOR major type {major}")


def decode_cbor(data: bytes) -> Any:
    value, pos = decode_item(data, 0)
    if pos != len(data):
        raise CborError(f"trailing data starts at 0x{pos:x}")
    return value


def classify(blob: ByteString, current_size: int, current_sha256: str, current_label: str) -> str:
    if blob.length == current_size and blob.sha256 == current_sha256:
        return current_label
    if blob.length == OLD_BIN_SIZE and blob.sha256 == OLD_BIN_SHA256:
        return "OLD_347MS_BIN"
    if blob.length == EXTRAM_SIZE and blob.sha256 == OLD_EXTRAM_SHA256:
        return "OLD_TRACE_EXTRAM"
    if blob.length == EXTRAM_SIZE:
        return "EXTRAM_IMAGE"
    return "-"


def large_blobs(blobs: Iterable[ByteString], min_size: int) -> list[ByteString]:
    return [blob for blob in blobs if blob.length >= min_size]


def trace_fast_fingerprint(data: bytes, blobs: Iterable[ByteString]) -> list[str]:
    if not TRACE_FAST_GUARD_WORDS:
        return ["trace_fast_fingerprint: disabled generic_early_accel_path"]

    lines = []
    for blob in blobs:
        if blob.length != EXTRAM_SIZE:
            continue

        start = blob.payload_offset + TRACE_FAST_GUARD_OFFSET
        words = tuple(
            int.from_bytes(data[start + idx * 4:start + idx * 4 + 4], "little")
            for idx in range(len(TRACE_FAST_GUARD_WORDS))
        )
        word_text = " ".join(f"{word:08x}" for word in words)
        if words == TRACE_FAST_GUARD_WORDS:
            status = "match"
        else:
            status = "mismatch"
        lines.append(
            "trace_fast_fingerprint: "
            f"{status} guard_offset=0x{TRACE_FAST_GUARD_OFFSET:x} guard_words={word_text}"
        )

    if not lines:
        lines.append("trace_fast_fingerprint: no ExtRAM image found")
    return lines


def trace_fast_guard_status(data: bytes, blobs: Iterable[ByteString]) -> str:
    if not TRACE_FAST_GUARD_WORDS:
        return "disabled"

    found = False
    for blob in blobs:
        if blob.length != EXTRAM_SIZE:
            continue
        found = True
        start = blob.payload_offset + TRACE_FAST_GUARD_OFFSET
        words = tuple(
            int.from_bytes(data[start + idx * 4:start + idx * 4 + 4], "little")
            for idx in range(len(TRACE_FAST_GUARD_WORDS))
        )
        if words == TRACE_FAST_GUARD_WORDS:
            return "match"
    return "mismatch" if found else "missing"


def printable_uart(data: bytes) -> str:
    text = data.decode("ascii", "replace")
    return text.replace("\n", "\\n")


@dataclass(frozen=True)
class EventMetrics:
    reset_ts: int | None
    start_ts: int | None
    done_ts: int | None
    crc_value: str | None


def event_metrics(root: Any) -> EventMetrics:
    reset_ts = None
    start_ts = None
    done_ts = None
    crc_value = None

    if not isinstance(root, list):
        return EventMetrics(reset_ts, start_ts, done_ts, crc_value)

    for idx, record in enumerate(root):
        if not isinstance(record, list) or len(record) < 3:
            continue

        if record[:2] == [1, 5]:
            reset_ts = record[2]

        if record[:2] == [16, 4] and len(record) >= 4 and isinstance(record[3], bytes):
            payload = record[3]
            if b"MATMUL_START" in payload:
                start_ts = record[2]
            if b"MATMUL_DONE" in payload:
                done_ts = record[2]
            match = re.search(br"MATMUL_CRC32=([0-9a-fA-F]{8})", payload)
            if match:
                crc_value = match.group(1).decode("ascii")

    return EventMetrics(reset_ts, start_ts, done_ts, crc_value)


def summarize_events(root: Any) -> list[str]:
    if not isinstance(root, list):
        return ["event_summary: top-level object is not an array"]

    lines = [f"top_records: {len(root)}"]
    metrics = event_metrics(root)

    for idx, record in enumerate(root):
        if not isinstance(record, list) or len(record) < 3:
            continue

        if record[:2] == [16, 7] and len(record) >= 7:
            lines.append(
                "uart_open: "
                f"record={idx} timestamp={record[2]} baud={record[3]} "
                f"data_bits={record[5]} stop_bits={record[6]}"
            )

        if record[:2] == [1, 5]:
            lines.append(f"reset_release: record={idx} timestamp={record[2]}")

        if record[:2] == [16, 4] and len(record) >= 4 and isinstance(record[3], bytes):
            payload = record[3]
            text = printable_uart(payload)
            lines.append(f"uart_tx: record={idx} timestamp={record[2]} length={len(payload)} text={text!r}")

    if metrics.reset_ts is not None and metrics.start_ts is not None:
        lines.append(f"reset_to_start_units: {metrics.start_ts - metrics.reset_ts}")
    if metrics.start_ts is not None and metrics.done_ts is not None:
        lines.append(f"start_to_done_units: {metrics.done_ts - metrics.start_ts}")
    if metrics.reset_ts is not None and metrics.done_ts is not None:
        lines.append(f"reset_to_done_units: {metrics.done_ts - metrics.reset_ts}")
    if metrics.crc_value is not None:
        lines.append(f"reported_crc32: {metrics.crc_value}")
    if metrics.start_ts is None:
        lines.append("marker_status: MATMUL_START not found in UART records")
    elif metrics.done_ts is None:
        lines.append("marker_status: MATMUL_DONE not found in UART records")
    else:
        lines.append("marker_status: MATMUL_START and MATMUL_DONE found")

    return lines


def resolve_trace_path(path: Path) -> Path:
    if path.is_file():
        return path
    if not path.is_dir():
        raise FileNotFoundError(path)

    candidates = [
        item
        for item in path.iterdir()
        if item.is_file() and item.suffix == ".cbor" and not item.name.endswith(":Zone.Identifier")
    ]
    if not candidates:
        raise FileNotFoundError(f"no .cbor trace files found in {path}")
    return max(candidates, key=lambda item: (item.stat().st_mtime_ns, item.name))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path, help="CBOR trace file, or a directory containing .cbor traces")
    parser.add_argument("--min-size", type=int, default=1024, help="minimum byte-string size to print")
    parser.add_argument(
        "--expected-bin",
        type=Path,
        help="optional user-sample.bin to fingerprint and require in the trace",
    )
    args = parser.parse_args()

    current_size = CURRENT_BIN_SIZE
    current_sha256 = CURRENT_BIN_SHA256
    current_label = "CURRENT_SUBMISSION_CI_BIN"
    if args.expected_bin is not None:
        expected = args.expected_bin.read_bytes()
        current_size = len(expected)
        current_sha256 = hashlib.sha256(expected).hexdigest()
        current_label = "EXPECTED_BIN"

    trace_path = resolve_trace_path(args.trace)
    data = trace_path.read_bytes()
    blobs = parse_cbor(data)
    root = decode_cbor(data)
    selected = large_blobs(blobs, args.min_size)
    metrics = event_metrics(root)
    guard_status = trace_fast_guard_status(data, blobs)

    print(f"trace: {trace_path}")
    if trace_path != args.trace:
        print(f"trace_source: newest_cbor_in_directory {args.trace}")
    print(f"file_size: {len(data)}")
    if args.expected_bin is not None:
        print(f"expected_bin: {args.expected_bin}")
        print(f"expected_bin_size: {current_size}")
        print(f"expected_bin_sha256: {current_sha256}")
    for line in summarize_events(root):
        print(line)
    print(
        "protocol_lower_bound_ms_115200_8n1_total_47b: "
        f"{REQUIRED_OUTPUT_BYTES * UART_BITS_PER_BYTE * 1000 / UART_BAUD:.3f}"
    )
    print(
        "protocol_lower_bound_ms_115200_8n1_post_start_34b: "
        f"{POST_START_OUTPUT_BYTES * UART_BITS_PER_BYTE * 1000 / UART_BAUD:.3f}"
    )
    print(f"byte_strings: {len(blobs)}")
    print(f"large_byte_strings: {len(selected)} (min_size={args.min_size})")
    print("offset_header offset_payload length sha256 classification")
    for blob in selected:
        print(
            f"0x{blob.header_offset:x} "
            f"0x{blob.payload_offset:x} "
            f"{blob.length} "
            f"{blob.sha256} "
            f"{classify(blob, current_size, current_sha256, current_label)}"
        )
    for line in trace_fast_fingerprint(data, blobs):
        print(line)

    classes = {classify(blob, current_size, current_sha256, current_label) for blob in blobs}
    markers_complete = metrics.start_ts is not None and metrics.done_ts is not None
    if current_label in classes:
        if args.expected_bin is not None:
            print("program_status: expected user-sample.bin found")
        else:
            print("program_status: current submission CI-path binary found")
        print("performance_evidence: trace matches the expected/current program binary")
        if markers_complete and guard_status in ("match", "disabled"):
            print("trace_verdict: usable_current_performance_evidence")
        elif not markers_complete:
            print("trace_verdict: current_binary_but_markers_incomplete")
        else:
            print(f"trace_verdict: current_binary_but_trace_fast_guard_{guard_status}")
    elif "OLD_347MS_BIN" in classes:
        print("program_status: old 347 ms software binary found")
        print("performance_evidence: not usable for current submission timing")
        print("trace_verdict: not_current_binary")
    else:
        print("program_status: no known user-sample.bin fingerprint found")
        print("performance_evidence: binary identity is unproven")
        print("trace_verdict: binary_identity_unproven")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
