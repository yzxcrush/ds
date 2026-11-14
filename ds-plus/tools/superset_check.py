#!/usr/bin/env python3
"""Ds+ 严格超集校验器（Step 4）。

静态检查 S1–S12；--compile 追加 S13：用 base 编译器跑 base 示例。
退出码：0 = 全部通过；1 = 有失败。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))   # 确保 import dsv01 来自仓库而非已安装包
CORE = ROOT / "ds-core"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)


def checks(compile_base: bool = False):
    out = []

    def add(sid, name, ok, detail):
        out.append({"id": sid, "name": name, "ok": bool(ok), "detail": detail})

    version = load(CORE / "version.json")
    plus = load(CORE / "plus.keywords.json")
    registry = load(CORE / "keywords.registry.json")
    snapshot = load(CORE / "base.keywords.snapshot.json")
    spec = load(ROOT / "spec" / "keywords.json")
    abi = load(CORE / "abi" / "abi.json")
    ir = load(CORE / "ir" / "ir.schema.json")
    codes = load(CORE / "diagnostics" / "codes.json")

    # S1 版本同步
    ok = (version["version"] == plus["version"] == registry["version"])
    add("S1", "版本同步", ok, f"version={version['version']}, plus={plus['version']}, registry={registry['version']}")

    # S2 base 77 冻结
    base_words = sorted(e["word"] for e in spec["alphabetical"])
    ok = (spec["totals"]["keywords"] == 77 and base_words == sorted(snapshot["words"]))
    add("S2", "base 77 关键字冻结", ok, f"spect={spec['totals']['keywords']}, snapshot={snapshot['count']}")

    # S3 注册表与源一致
    r = _run([sys.executable, str(CORE / "tools" / "build_registry.py"), "--check"])
    add("S3", "注册表可重现", r.returncode == 0, (r.stdout or r.stderr).strip())

    # S4 plus 全部 @ 前缀且与 base 不相交
    plus_tokens = [e["name"] for e in plus["keywords"]]
    ok = all(t.startswith("@") for t in plus_tokens) and not (set(plus_tokens) & set(base_words))
    add("S4", "plus 令牌 @ 前缀 / 与 base 不相交", ok, f"{len(plus_tokens)} tokens")

    # S5 合并注册表计数
    ok = (registry["base_count"] == 77 and registry["plus_count"] == len(plus_tokens)
          and registry["total"] == 77 + len(plus_tokens))
    add("S5", "合并注册表 77 + N", ok, f"total={registry['total']}")

    # S6 三档写法共享 AST
    ok = (version["surfaces"] == ["classic", "concise", "flow"] and version["ast"] == "shared")
    add("S6", "三档写法 / 同一 AST", ok, f"surfaces={version['surfaces']}, ast={version['ast']}")

    # S7 ABI 默认不变、C ABI 显式
    ok = (abi["default_layout"] == "repr(Ds)" and abi["c_layout"] == "repr(C)"
          and "@repr(C)" in abi["c_abi_selector"])
    add("S7", "ABI 默认 repr(Ds)，C ABI 显式", ok, abi["default_layout"])

    # S8 IR 增量
    plus_nodes = {n["name"] for n in ir["plus_nodes"]}
    ok = {"InlineAsm", "Intrinsic", "RegionAlloc", "GlobalStatic", "RawAlloc", "MapPage"} <= plus_nodes
    add("S8", "IR 仅增量节点", ok, f"plus_nodes={sorted(plus_nodes)}")

    # S9 诊断码完整且唯一
    all_codes = [c["code"] for c in codes["codes"]]
    required = {e["base_stub"]["code"] for e in plus["keywords"]}
    ok = (len(all_codes) == len(set(all_codes)) and required <= set(all_codes)
          and {"E_DS_PLUS_PROFILE", "E_DS_PLUS_TARGET", "E_DS_PLUS_UNSAFE"} <= set(all_codes))
    add("S9", "诊断码完整/唯一", ok, f"{len(all_codes)} codes")

    # S10 base 编译器 stub 守卫
    sys.path.insert(0, str(ROOT / "ds-plus" / "tools"))
    import keyword_guard  # type: ignore
    plus_hits = keyword_guard.scan_text(
        (ROOT / "ds-plus" / "examples" / "plus_keywords.ds").read_text(encoding="utf-8"))
    base_hits = keyword_guard.scan_text(
        (ROOT / "examples" / "concise" / "hello.ds").read_text(encoding="utf-8"))
    ok = len(plus_hits) == 16 and not base_hits
    add("S10", "plus 令牌被 base stub 拦截 / base 代码干净", ok,
        f"plus_hits={len(plus_hits)}, base_hits={len(base_hits)}")

    # S11 base AI 包存在且可校验
    ds_check = _run([sys.executable, "tools/make_datasets.py", "--check"])
    ai_check = _run([sys.executable, "tools/build_ai_kit.py", "--check"])
    add("S11", "AI 学习包 base 子集一致", ds_check.returncode == 0 and ai_check.returncode == 0,
        (ds_check.stdout + ai_check.stdout).strip())

    # S12 base 示例与三档写法仍在仓库中
    needed = ["examples/concise/hello.ds", "examples/flow/hello.dsf",
              "examples/concise/fib.ds", "examples/flow/fib.dsf"]
    ok = all((ROOT / p).exists() for p in needed)
    add("S12", "base 三档示例完整", ok, f"{len(needed)} files")

    # S14 P1 前端：base AST 等价 + 16 令牌注入
    if str(ROOT / "ds-plus") not in sys.path:
        sys.path.insert(0, str(ROOT / "ds-plus"))
    from dsplus.frontend import collect_plus_features, parse_program  # type: ignore
    from dsv01.parser import parse_program as base_parse  # type: ignore

    def ser(x):
        if isinstance(x, list):
            return [ser(i) for i in x]
        if dataclasses.is_dataclass(x):
            return {f.name: ser(getattr(x, f.name)) for f in dataclasses.fields(x)}
        return x

    ok = True
    detail = []
    for rel in ("examples/concise/hello.ds", "examples/concise/fib.ds",
                "examples/flow/fib.dsf", "examples/tour.ds"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        same = ser(parse_program(src, rel)) == ser(base_parse(src, rel))
        ok = ok and same
        detail.append(f"{rel}: {'same' if same else 'DIFF'}")
    p1_src = (ROOT / "ds-plus" / "examples" / "p1_hardware.ds").read_text(encoding="utf-8")
    feats = collect_plus_features(parse_program(p1_src, "p1_hardware.ds"))
    regions = [f for f in feats if f[0] == "Region"]
    intrinsics = [f for f in feats if f[0] == "Intrinsic"]
    asm = [f for f in feats if f[0] == "InlineAsm"]
    ok = ok and len(regions) == 4 and len(intrinsics) == 11 and len(asm) == 2
    detail.append(f"p1: regions={len(regions)}, intrinsics={len(intrinsics)}, asm={len(asm)}")
    add("S14", "P1 前端：base AST 等价 + 16 令牌注入", ok, "; ".join(detail))

    # S15 P1 前端：三档写法 plus 特征一致
    classic = "@stack var s: i32 = 42\nfn f() { @outb(0x20, 0x20)\n let k = @inb(0x60) }\n"
    concise = "@stack s = 42\nfn f() { @outb(0x20, 0x20)\n let k = @inb(0x60) }\n"
    flow = "#!flow\n@stack s = 42\n\\f\n    @outb(0x20, 0x20)\n    let k = @inb(0x60)\n.\n"
    def feat(src, fn):
        fs = collect_plus_features(parse_program(src, fn))
        return {
            "regions": sorted(f[1] for f in fs if f[0] == "Region"),
            "intrinsics": [f for f in fs if f[0] == "Intrinsic"],
        }
    a, b, d = feat(classic, "a.ds"), feat(concise, "b.ds"), feat(flow, "c.dsf")
    add("S15", "P1 三档写法共享 plus AST 特征", a == b == d, f"classic={a['regions']}, flow={d['regions']}")


    # S16 P2：语义检查 + compat 模拟执行
    from dsplus.checker import check_program  # type: ignore
    from dsplus.compat import run_compat  # type: ignore
    sim = '@unsafe fn main() { @outb(0x3F8, 65)\n p(@inb(0x3F8)) }\n'
    _, machine, sim_out = run_compat(sim, "sim.ds", profile="bare")
    unsafe_src = 'fn f() { @inb(0x60) }\n'
    unsafe_codes = {d.code for d in check_program(parse_program(unsafe_src, "u.ds"), "bare")}
    ok = (sim_out == "65\n" and machine.ports.get(0x3F8) == 65
          and "E_DS_PLUS_UNSAFE" in unsafe_codes)
    add("S16", "P2 语义检查 + compat 模拟", ok,
        f"sim_out={sim_out!r}, unsafe={sorted(unsafe_codes)}")

    # S17 P3：IR 超集稳定 + ABI 指纹
    from dsplus.ir import abi_fingerprint, fingerprint_hash, ir_hash  # type: ignore
    ok = True
    detail = []
    for rel in ("examples/concise/hello.ds", "examples/flow/fib.dsf"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        same = ir_hash(parse_program(src, rel)) == ir_hash(base_parse(src, rel))
        ok = ok and same
        detail.append(f"{rel}: {'same' if same else 'DIFF'}")
    fp = abi_fingerprint("x86_64-linux-gnu")
    ok = ok and fp["ds_default_layout"] == "repr(Ds)" and fp["pointer"]["size"] == 8
    detail.append(f"abi={fingerprint_hash(fp)[:12]}")
    add("S17", "P3 IR/ABI 超集稳定", ok, "; ".join(detail))

    # S18 P4：x86-64 子集代码生成 → ELF/raw
    import tempfile
    from dsplus.codegen import build, generate_source  # type: ignore
    asm = generate_source('@unsafe fn main() -> i32 { @outb(0x3F8, 65) return @inb(0x3F8) }\n', "io.ds")
    ok = "outb %al, %dx" in asm and "inb %dx, %al" in asm
    detail = ["asm ok"]
    try:
        with tempfile.TemporaryDirectory() as td:
            exe = pathlib.Path(td) / "p4.elf"
            info = build("fn main() -> i32 { return 42 }\n", str(exe), raw=True)
            data = exe.read_bytes()
            ok = ok and data[:4] == b"\x7fELF" and int.from_bytes(data[18:20], "little") == 62
            ok = ok and pathlib.Path(info["raw"]).stat().st_size > 0
            detail.append(f"elf={len(data)}B, raw={pathlib.Path(info['raw']).stat().st_size}B")
    except Exception as exc:  # 工具链缺失时 P4 门禁失败（CI 有工具链）
        ok = False
        detail.append(f"build error: {exc}")
    add("S18", "P4 x86-64 子集后端（ELF/raw）", ok, "; ".join(detail))

    # S13（可选）base 编译器可编译 base 示例
    if compile_base:
        files = ["examples/concise/hello.ds", "examples/concise/fib.ds",
                 "examples/flow/hello.dsf", "examples/flow/fib.dsf"]
        detail = []
        ok = True
        for rel in files:
            r = _run([str(ROOT / "dscc"), str(ROOT / rel)])
            detail.append(f"{rel}: rc={r.returncode}")
            ok = ok and r.returncode == 0
        add("S13", "base 编译器可编译 base 三档示例", ok, "; ".join(detail))

    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Ds+ 严格超集校验器")
    ap.add_argument("--compile", action="store_true", help="追加 base 编译器冒烟（S13）")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    args = ap.parse_args(argv)
    results = checks(compile_base=args.compile)
    ok = all(c["ok"] for c in results)
    if args.json:
        print(json.dumps({"ok": ok, "checks": results}, ensure_ascii=False, indent=2))
    else:
        for c in results:
            print(f"{'✓' if c['ok'] else '✗'} {c['id']} {c['name']} — {c['detail']}")
        print(("\n✓ Ds+ 超集校验全部通过" if ok else "\n✗ Ds+ 超集校验失败"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
