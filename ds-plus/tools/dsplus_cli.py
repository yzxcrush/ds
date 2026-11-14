#!/usr/bin/env python3
"""Ds+ 命令行（P5）：check / parse / run / ir / abi / build / version。"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ds-plus"))

from dsplus import frontend  # noqa: E402
from dsplus.checker import check_program, DsPlusCheckError  # noqa: E402
from dsplus.compat import run_compat  # noqa: E402
from dsplus.ir import abi_fingerprint, ir_hash, module_ir  # noqa: E402

VERSION = "0.1.0"


def read(path: str) -> tuple[str, str]:
    p = pathlib.Path(path)
    return p.read_text(encoding="utf-8"), p.name


def cmd_parse(args) -> int:
    src, name = read(args.file)
    prog = frontend.parse_program(src, name)
    feats = frontend.collect_plus_features(prog)
    if args.json:
        print(json.dumps({"file": args.file, "features": [list(f) for f in feats]},
                         ensure_ascii=False, indent=2))
    else:
        for f in feats:
            print(*f)
    return 0


def cmd_check(args) -> int:
    src, name = read(args.file)
    prog = frontend.parse_program(src, name)
    diags = check_program(prog, args.profile)
    if args.json:
        print(json.dumps({"ok": not diags, "diagnostics": [
            {"code": d.code, "message": d.message, "line": d.line, "col": d.col} for d in diags]},
            ensure_ascii=False, indent=2))
    else:
        for d in diags:
            print(d)
        if not diags:
            print(f"✓ {args.file} 通过 ({args.profile})")
    return 1 if diags else 0


def cmd_run(args) -> int:
    src, name = read(args.file)
    try:
        _, machine, out = run_compat(src, name, profile=args.profile)
    except DsPlusCheckError as exc:
        for d in exc.diags:
            print(d, file=sys.stderr)
        return 1
    print(out, end="")
    if args.show_machine:
        print(json.dumps({"ports": {hex(k): v for k, v in machine.ports.items()},
                          "msrs": {hex(k): v for k, v in machine.msrs.items()},
                          "crs": {hex(k): v for k, v in machine.crs.items()}},
                         ensure_ascii=False, indent=2), file=sys.stderr)
    return 0


def cmd_ir(args) -> int:
    src, name = read(args.file)
    prog = frontend.parse_program(src, name)
    if args.hash:
        print(ir_hash(prog))
    else:
        print(json.dumps(module_ir(prog), ensure_ascii=False, indent=2))
    return 0


def cmd_abi(args) -> int:
    fp = abi_fingerprint(args.target, args.layout)
    print(json.dumps(fp, ensure_ascii=False, indent=2))
    return 0


def cmd_build(args) -> int:
    from dsplus.codegen import build, CodegenError
    src, name = read(args.file)
    out = args.output or (pathlib.Path(args.file).stem + (".bin" if args.raw else ".elf"))
    try:
        info = build(src, out, filename=name, bare=args.bare, raw=args.raw, target=args.target)
    except CodegenError as exc:
        print(f"error[{exc.code}]: {exc.message}", file=sys.stderr)
        return 1
    print(f"✓ {out}")
    if "raw" in info:
        print(f"✓ {info['raw']}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="dsplus", description="Ds+ 编译器（P1–P4 预览）")
    ap.add_argument("--version", action="version", version=f"dsplus {VERSION} (ds+ v0.1.0)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("parse"); p.add_argument("file"); p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_parse)

    p = sub.add_parser("check"); p.add_argument("file")
    p.add_argument("--profile", choices=["compat", "bare"], default="compat")
    p.add_argument("--json", action="store_true"); p.set_defaults(fn=cmd_check)

    p = sub.add_parser("run"); p.add_argument("file")
    p.add_argument("--profile", choices=["compat", "bare"], default="bare")
    p.add_argument("--show-machine", action="store_true"); p.set_defaults(fn=cmd_run)

    p = sub.add_parser("ir"); p.add_argument("file"); p.add_argument("--hash", action="store_true")
    p.set_defaults(fn=cmd_ir)

    p = sub.add_parser("abi"); p.add_argument("--target", default="x86_64-linux-gnu")
    p.add_argument("--layout", default="repr(Ds)"); p.set_defaults(fn=cmd_abi)

    p = sub.add_parser("build"); p.add_argument("file"); p.add_argument("-o", "--output")
    p.add_argument("--target", default="x86_64-linux-gnu")
    p.add_argument("--bare", action="store_true"); p.add_argument("--raw", action="store_true")
    p.set_defaults(fn=cmd_build)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
