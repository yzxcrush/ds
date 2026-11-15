#!/usr/bin/env python3
"""RP2350 UF2 生成器（零依赖，供 Ds/Cut 构建链使用）。

USB Flashing Format: 512 字节/块；RP2350 family id = 0xE48BFF56。
"""
from __future__ import annotations
import argparse
import pathlib
import struct
import sys

MAGIC0 = 0x0A324655
MAGIC1 = 0x9E5D5157
MAGIC_END = 0x0AB16F30
RP2350_FAMILY = 0xE48BFF56
PAYLOAD = 256


def bin_to_uf2(data: bytes, *, family: int = RP2350_FAMILY,
               base: int = 0x10000000, payload: int = PAYLOAD) -> bytes:
    if not 0 < payload <= 476:
        raise ValueError("payload 必须在 1..476")
    blocks = (len(data) + payload - 1) // payload
    out = bytearray()
    for i in range(blocks):
        chunk = data[i * payload:(i + 1) * payload].ljust(payload, b"\0")
        header = struct.pack("<8I", MAGIC0, MAGIC1, 0x00002000,
                             base + i * payload, payload, i, blocks, family)
        body = chunk.ljust(476, b"\0")
        block = header + body + struct.pack("<I", MAGIC_END)
        assert len(block) == 512
        out += block
    return bytes(out)


def parse_uf2(data: bytes) -> dict:
    if len(data) % 512 != 0:
        raise ValueError("UF2 长度必须是 512 的倍数")
    blocks = len(data) // 512
    first = struct.unpack("<8I", data[:32])
    last = struct.unpack("<I", data[-4:])
    return {"blocks": blocks, "num_blocks": first[6], "family": first[7],
            "end_magic": last[0], "magic": (first[0], first[1])}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="uf2conv", description="RP2350 UF2 打包")
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--family", default=hex(RP2350_FAMILY))
    ap.add_argument("--base", default="0x10000000")
    args = ap.parse_args(argv)
    data = pathlib.Path(args.input).read_bytes()
    uf2 = bin_to_uf2(data, family=int(args.family, 0), base=int(args.base, 0))
    pathlib.Path(args.output).write_bytes(uf2)
    info = parse_uf2(uf2)
    print(f"✓ {args.output}: {len(data)} bytes → {info['blocks']} blocks, family=0x{info['family']:08x}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
