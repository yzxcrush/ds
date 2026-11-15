#!/usr/bin/env python3
"""DSOSS manifest 一致性检查器（v0.1）。"""
from __future__ import annotations
import argparse
import pathlib
import sys

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None

PROFILES = {
    "rp2350-m33": {"arch": "thumbv8m.main", "pointer_bits": 32,
                   "image_format": "uf2", "entry": {"reset_handler"},
                   "cut_mode": "--cut"},
    "zero2w-a53": {"arch": "aarch64", "pointer_bits": 64,
                   "image_format": "kernel8", "entry": {"_start"},
                   "cut_mode": "--cut"},
}
REQUIRED_SYSCALLS = {1: "sys_write", 2: "sys_exit"}


def check(path: str) -> list[str]:
    errs: list[str] = []
    if tomllib is None:
        return ["需要 Python 3.11+（tomllib）"]
    try:
        data = tomllib.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"TOML 解析失败：{exc}"]
    std = data.get("standard", {})
    board = data.get("board", {})
    boot = data.get("boot", {})
    kernel = data.get("kernel", {})
    tool = data.get("toolchain", {})
    if std.get("name") != "DSOSS":
        errs.append("standard.name 必须是 DSOSS")
    if std.get("version") != "0.1":
        errs.append("standard.version 必须是 0.1")
    profile = board.get("profile")
    spec = PROFILES.get(profile)
    if not spec:
        errs.append(f"未知 board.profile：{profile!r}")
        return errs
    if kernel.get("arch") != spec["arch"]:
        errs.append(f"kernel.arch 应为 {spec['arch']}，得到 {kernel.get('arch')!r}")
    if kernel.get("pointer_bits") != spec["pointer_bits"]:
        errs.append(f"pointer_bits 应为 {spec['pointer_bits']}，得到 {kernel.get('pointer_bits')!r}")
    if boot.get("image_format") != spec["image_format"]:
        errs.append(f"boot.image_format 应为 {spec['image_format']}，得到 {boot.get('image_format')!r}")
    if boot.get("entry") not in spec["entry"]:
        errs.append(f"boot.entry 应为 {sorted(spec['entry'])}，得到 {boot.get('entry')!r}")
    if tool.get("compiler") != "cutc":
        errs.append("toolchain.compiler 必须是 cutc")
    if tool.get("cut_mode") != spec["cut_mode"]:
        errs.append(f"toolchain.cut_mode 应为 {spec['cut_mode']}")
    syscalls = data.get("syscalls", [])
    if not isinstance(syscalls, list) or not syscalls:
        errs.append("至少声明一个 [[syscalls]]")
    else:
        nums = []
        for s in syscalls:
            n = s.get("number")
            if not isinstance(n, int) or not (1 <= n <= kernel.get("syscall_max", 32)):
                errs.append(f"syscall 号越界：{n!r}")
            nums.append(n)
            name = s.get("name", "")
            if not name.startswith("sys_"):
                errs.append(f"syscall {n} 名称必须以 sys_ 开头")
        if len(nums) != len(set(nums)):
            errs.append("syscall 号重复")
        got = {s.get("number"): s.get("name") for s in syscalls}
        for n, name in REQUIRED_SYSCALLS.items():
            if got.get(n) != name:
                errs.append(f"必须声明 syscall {n} = {name}")
    return errs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="dsoss-check", description="DSOSS 一致性检查")
    ap.add_argument("manifest")
    args = ap.parse_args(argv)
    errs = check(args.manifest)
    if errs:
        for e in errs:
            print(f"✗ {e}", file=sys.stderr)
        return 1
    print(f"✓ {args.manifest} 符合 DSOSS v0.1 结构契约")
    return 0


if __name__ == "__main__":
    sys.exit(main())
