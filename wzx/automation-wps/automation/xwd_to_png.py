#!/usr/bin/env python3
"""Convert the TrueColor XWD screenshots produced by the test VM to PNG."""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

from PIL import Image


def channel(value: int, mask: int) -> int:
    if mask == 0:
        return 0
    shift = (mask & -mask).bit_length() - 1
    maximum = mask >> shift
    return round(((value & mask) >> shift) * 255 / maximum)


def convert(source: Path, target: Path) -> None:
    data = source.read_bytes()
    if len(data) < 100:
        raise ValueError(f"XWD file is too short: {source}")

    header = struct.unpack(">25I", data[:100])
    (
        header_size,
        file_version,
        pixmap_format,
        _depth,
        width,
        height,
        _xoffset,
        byte_order,
        _bitmap_unit,
        _bitmap_bit_order,
        _bitmap_pad,
        bits_per_pixel,
        bytes_per_line,
        _visual_class,
        red_mask,
        green_mask,
        blue_mask,
        _bits_per_rgb,
        _colormap_entries,
        ncolors,
        *_rest,
    ) = header
    if file_version != 7 or pixmap_format != 2:
        raise ValueError(f"Unsupported XWD format: version={file_version}, format={pixmap_format}")
    if bits_per_pixel not in (24, 32):
        raise ValueError(f"Unsupported XWD bits per pixel: {bits_per_pixel}")

    pixel_start = header_size + ncolors * 12
    pixel_bytes = bits_per_pixel // 8
    raw = data[pixel_start:pixel_start + bytes_per_line * height]
    if len(raw) != bytes_per_line * height:
        raise ValueError("XWD pixel payload is truncated")

    output = bytearray(width * height * 3)
    endian = "little" if byte_order == 0 else "big"
    out_pos = 0
    for y in range(height):
        row = raw[y * bytes_per_line:(y + 1) * bytes_per_line]
        for x in range(width):
            start = x * pixel_bytes
            value = int.from_bytes(row[start:start + pixel_bytes], endian)
            output[out_pos] = channel(value, red_mask)
            output[out_pos + 1] = channel(value, green_mask)
            output[out_pos + 2] = channel(value, blue_mask)
            out_pos += 3

    target.parent.mkdir(parents=True, exist_ok=True)
    Image.frombytes("RGB", (width, height), bytes(output)).save(target)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    convert(args.source, args.target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
