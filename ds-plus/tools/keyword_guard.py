#!/usr/bin/env python3
"""Ds 基础版对 Ds+ 关键字的 stub 守卫。

用途：Ds 编译器在词法/语法阶段检测到本表内的 @ 令牌时，按注册表给出
E_DS_PLUS_* 诊断，避免"静默按属性解析"。

用法：
    python3 ds-plus/tools/keyword_guard.py FILE...
    python3 ds-plus/tools/keyword_guard.py --json FILE...
    python3 ds-plus/tools/keyword_guard.py --all FILE...

退出码：0 = 未发现 Ds+ 令牌；2 = 发现（base 应拒绝编译）。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "ds-core" / "plus.keywords.json"
TOKEN_RE = re.compile(r"@([A-Za-z_][A-Za-z0-9_]*)")
REGION_NEXT = re.compile(r"\s*(let|var|fn|type|const|@)")


def load_registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def scan_text(text: str, all_tokens: bool = False) -> list[dict]:
    reg = load_registry()
    by_name = {e["name"]: e for e in reg["keywords"]}
    hits: list[dict] = []
    for m in TOKEN_RE.finditer(text):
        name = "@" + m.group(1)
        entry = by_name.get(name)
        if not entry:
            continue
        after = text[m.end():]
        stripped = after.lstrip()
        if not all_tokens:
            rest = stripped
            if rest.startswith("volatile"):
                rest = rest[len("volatile"):].lstrip()
            if entry["kind"] == "hardware" and not rest.startswith(("(", "{")):
                continue  # `@asm` 作为属性名时不属于 Ds+ 语法
            if entry["kind"] == "region" and not REGION_NEXT.match(after):
                continue
        line = text.count("\n", 0, m.start()) + 1
        col = m.start() - text.rfind("\n", 0, m.start())
        hits.append({
            "name": name,
            "line": line,
            "col": col,
            "code": entry["base_stub"]["code"],
            "message": entry["base_stub"]["message"],
            "base_alternative": entry["base_stub"]["base_alternative"],
        })
    return hits


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ds+ 关键字 stub 守卫（base 编译器用）")
    ap.add_argument("files", nargs="+", help="DS/DSF 源文件")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    ap.add_argument("--all", action="store_true", help="不按上下文过滤，报告所有注册令牌")
    args = ap.parse_args(argv)

    all_hits: list[dict] = []
    for fname in args.files:
        path = pathlib.Path(fname)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            all_hits.append({"file": fname, "error": str(exc)})
            continue
        for hit in scan_text(text, args.all):
            hit["file"] = fname
            all_hits.append(hit)

    if args.json:
        print(json.dumps({
            "tool": "ds-plus-keyword-guard",
            "registry": str(REGISTRY_PATH.relative_to(ROOT)),
            "is_ds_plus_token": bool(all_hits),
            "hits": all_hits,
        }, ensure_ascii=False, indent=2))
    else:
        for hit in all_hits:
            if "error" in hit:
                print(f"{hit['file']}: error: {hit['error']}")
            else:
                print(f"{hit['file']}:{hit['line']}:{hit['col']}: error[{hit['code']}]: {hit['message']}")
                print(f"  help: {hit['base_alternative']}")
        if not all_hits:
            print("✓ 未发现 Ds+ 令牌（Ds base 可编译）")
    return 2 if all_hits else 0


if __name__ == "__main__":
    sys.exit(main())
