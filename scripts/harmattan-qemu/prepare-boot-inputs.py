#!/usr/bin/env python3
"""Prepare private boot/modem payloads from the exact supported retail FIASCO.

Independent bounded parser; container fields cross-checked against 0xFFFF
src/fiasco.c (pancake and Pali Rohar). No flashing, signature bypass or boot.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct

ROOT = Path(__file__).resolve().parents[2]
MEDIA = json.loads((ROOT / "docs/guest-media.json").read_text())["firmware"]
TYPES = {"cert-sw", "1st", "2nd", "xloader", "secondary", "kernel", "rootfs",
         "ape-algo", "cmt-2nd", "cmt-algo", "cmt-mcusw"}


def read_exact(stream, length):
    data = stream.read(length)
    if len(data) != length:
        raise ValueError("truncated FIASCO field")
    return data


def text_field(data):
    value, _, padding = data.partition(b"\0")
    if padding.strip(b"\0") or any(x < 32 or x > 126 for x in value):
        raise ValueError("invalid FIASCO text field")
    return value.decode("ascii")


def inspect_fiasco(stream, size):
    """Read every record, retaining repeated target/layout metadata in order."""
    stream.seek(0)
    if read_exact(stream, 1) != b"\xb4":
        raise ValueError("invalid FIASCO signature")
    length, count = struct.unpack(">II", read_exact(stream, 8))
    if not 4 <= length <= 8192 or not 1 <= count <= 32 or 5 + length > size:
        raise ValueError("invalid FIASCO container header bounds")
    headers = []
    for _ in range(count):
        tag, length8 = read_exact(stream, 2)
        headers.append({"tag": tag, "value": text_field(read_exact(stream, length8))})
    if stream.tell() != 5 + length:
        raise ValueError("FIASCO container header length mismatch")
    records = []
    while stream.tell() < size:
        offset = stream.tell()
        marker, count = read_exact(stream, 2)
        if marker != 0x54 or not 1 <= count <= 32 or len(records) >= 512:
            raise ValueError("invalid or excessive FIASCO records")
        header = bytearray([count])
        fields = []
        for _ in range(count):
            tag, length8 = read_exact(stream, 2)
            value = read_exact(stream, length8)
            header.extend(bytes([tag, length8]) + value)
            fields.append((tag, value))
        checksum = read_exact(stream, 1)[0]
        if (sum(header) + checksum) & 255 != 255:
            raise ValueError("FIASCO record header checksum mismatch")
        if fields[0][0] != 0x2e or len(fields[0][1]) != 25:
            raise ValueError("invalid FIASCO file-data section")
        asic, device_type, device_index, hash16, name, length, address = struct.unpack(
            ">3BH12sII", fields[0][1])
        kind = text_field(name)
        if kind not in TYPES or not 0 < length <= size - stream.tell():
            raise ValueError("unsupported type or out-of-bounds FIASCO payload")
        metadata = []
        for tag, value in fields[1:]:
            if tag == 0x32:
                if len(value) < 16 or (len(value) - 16) % 8:
                    raise ValueError("invalid FIASCO device/revision field")
                revisions = [text_field(value[i:i+8]) for i in range(16, len(value), 8)]
                if any(not re.fullmatch(r"[0-9]+", x) for x in revisions):
                    raise ValueError("invalid hardware revision")
                metadata.append({"tag": tag, "device": text_field(value[:16]),
                                 "hardware_revisions": revisions})
            elif tag == 0x31:
                metadata.append({"tag": tag, "version": text_field(value)})
            elif tag == 0x33:
                # Rootfs layout can span several sections; preserve exact bytes.
                metadata.append({"tag": tag, "layout_hex": value.hex()})
            else:
                raise ValueError("unsupported FIASCO metadata section")
        records.append({"index": len(records), "type": kind, "header_offset": offset,
                        "offset": stream.tell(), "bytes": length, "address": address,
                        "asic_index": asic, "device_type": device_type,
                        "device_index": device_index, "container_hash16": hash16,
                        "metadata": metadata})
        stream.seek(length, os.SEEK_CUR)
    if stream.tell() != size or not records:
        raise ValueError("incomplete FIASCO container")
    return headers, records


def verify_media(stream, identity):
    info = os.fstat(stream.fileno())
    if not stat.S_ISREG(info.st_mode) or info.st_size != identity["bytes"]:
        raise ValueError("wrong firmware size or non-regular input")
    stream.seek(0)
    if hashlib.file_digest(stream, "sha256").hexdigest() != identity["sha256"]:
        raise ValueError("firmware SHA-256 mismatch")
    return info


def prepare(firmware, output, identity=MEDIA):
    if output.exists() or output.is_symlink():
        raise ValueError("output already exists; select a fresh private directory")
    with firmware.open("rb") as stream:
        before = verify_media(stream, identity)
        headers, records = inspect_fiasco(stream, before.st_size)
        output.mkdir(parents=True, exist_ok=False)
        for record in records:
            # Numeric names prevent collisions between multi-target modem variants.
            if record["type"] == "rootfs":
                continue
            name = f'{record["index"]:03d}-{record["type"]}.bin'
            digest = hashlib.sha256()
            stream.seek(record["offset"])
            remaining = record["bytes"]
            with (output / name).open("xb") as target:
                while remaining:
                    data = read_exact(stream, min(remaining, 1024**2))
                    target.write(data)
                    digest.update(data)
                    remaining -= len(data)
            record.update(file=name, sha256=digest.hexdigest())
        after = verify_media(stream, identity)
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError("firmware changed during preparation; output is incomplete")
    report = {"schema_version": 1, "firmware_sha256": identity["sha256"],
              "scope": "Original payload preparation only; no boot or signature verification",
              "secure_boot": "UNVERIFIED", "hardware_variant_selected": False,
              "kci_selected": False, "headers": headers, "records": records}
    (output / "boot-inputs.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firmware", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="new private output directory")
    args = parser.parse_args()
    report = prepare(args.firmware, args.output)
    print(f'Prepared {sum("file" in x for x in report["records"])} private payloads; '
          'secure boot and modem execution remain UNVERIFIED.')


if __name__ == "__main__":
    main()
