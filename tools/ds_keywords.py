#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ds v0.1 关键词表校验与索引生成器。

用法:
    python3 tools/ds_keywords.py check   # 校验 spec/DS-v0.1.md（默认）
    python3 tools/ds_keywords.py build   # 校验并生成 spec/keywords.json
    python3 tools/ds_keywords.py check --json spec/keywords.json  # 校验且要求 JSON 已同步

校验内容:
  1. §1.3 关键词表逐词覆盖用户给定的 77 项清单（11 类）；
  2. 无缺失、无多余、无重复，且每个词落在正确类别；
  3. 各类计数、合计（77 = 73 标识符 + 4 符号）与文档标题一致；
  4. §2.1 运算符表覆盖 26 个运算符；
  5. §7.2 编译指令覆盖 dscc 核心选项；
  6. §3 字面量、§4 注释覆盖给定形式；
  7. build 模式下 keywords.json 与文档内容一致（check --json 会新鲜度校验）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "spec" / "DS-v0.1.md"
INDEX = ROOT / "spec" / "keywords.json"

# ---------------------------------------------------------------------------
# 用户给定的全量清单（唯一事实来源；顺序即规范顺序）
# ---------------------------------------------------------------------------
CANON: dict[str, list[str]] = {
    "定义": ["fn", "let", "var", "type", "class", "trait", "impl", "mod", "package"],
    "控制": ["if", "else", "loop", "while", "for", "break", "continue", "return", "goto"],
    "管道": ["->", "=>", "|>"],
    "错误": ["try", "catch", "panic", "recover", "assert", "res", "opt"],
    "模块": ["use", "as", "export", "pub", "priv", "prot", "static", "extern"],
    "并发": ["spawn", "go", "thread", "chan", "send", "recv", "mutex", "wait"],
    "内存": ["raw", "free", "alloc", "rc", "arc", "gc", "ptr", "ref", "mut"],
    "裸机": ["@", "asm", "volatile", "at", "irq", "section", "packed"],
    "元编程": ["comptime", "macro", "typeinfo", "attr"],
    "OOP": ["self", "super", "new", "drop", "extends", "dyn"],
    "模式": ["match", "when", "where", "in", "is", "sizeof", "alignof"],
}

# 用户给定的运算符（25 个）+ 管道族补入的 `=>`
CANON_OPS = [
    "+", "-", "*", "/", "%", "=", "==", "!=", "<", ">", "<=", ">=",
    "!", "&&", "||", "&", "|", "^", "~", "<<", ">>", ".", "[]", "|>", "->",
    "=>",
]

# 用户给定的 dscc 核心选项（input.ds 为位置参数）
CANON_DSCC = ["input.ds", "-o", "--app", "--bare", "--target", "--opt", "--gc", "--rt"]

# 用户给定的字面量与注释形式
CANON_LITERALS = ["5", "-3", "0xFF", "0b1010", '"str"', 'b"raw"', "[1 2]", "{k:v}", "_"]
CANON_COMMENTS = ["#", "//", "#|", "|#"]

SYMBOLS = {"@", "->", "=>", "|>"}

KEYWORDS_BEGIN = "<!-- KEYWORDS:BEGIN -->"
KEYWORDS_END = "<!-- KEYWORDS:END -->"
OPERATORS_BEGIN = "<!-- OPERATORS:BEGIN -->"
OPERATORS_END = "<!-- OPERATORS:END -->"
DSDC_BEGIN = "<!-- DSDC:BEGIN -->"
DSDC_END = "<!-- DSDC:END -->"

HEADING_RE = re.compile(r"^###\s+(.+?)\s*[（(](\d+)[）)]\s*$")
CELL_SPLIT_RE = re.compile(r"(?<!\\)\|")


class Failure(Exception):
    pass


# ---------------------------------------------------------------------------
# Markdown 表格解析
# ---------------------------------------------------------------------------
def _cells(line: str) -> list[str]:
    """切分一行 Markdown 表格，尊重 \\| 转义，并还原转义。"""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    parts = CELL_SPLIT_RE.split(s)
    return [p.strip().replace("\\|", "|") for p in parts]


def _is_separator(row: list[str]) -> bool:
    return bool(row) and all(re.fullmatch(r":?-{2,}:?", c) for c in row)


def _extract_section(text: str, begin: str, end: str, label: str) -> str:
    try:
        a = text.index(begin) + len(begin)
        b = text.index(end, a)
    except ValueError:
        raise Failure(f"文档缺少标记区间 {label}（{begin} ... {end}）")
    return text[a:b]


def parse_keyword_tables(text: str) -> list[dict]:
    """返回 [{category, tokens}]，按文档顺序。"""
    block = _extract_section(text, KEYWORDS_BEGIN, KEYWORDS_END, "关键词表")
    sections: list[dict] = []
    cur: dict | None = None
    for raw in block.splitlines():
        line = raw.strip()
        m = HEADING_RE.match(line)
        if m:
            cur = {"category": m.group(1).strip(), "declared": int(m.group(2)), "tokens": [], "rows": []}
            sections.append(cur)
            continue
        if cur is None or not line.startswith("|"):
            continue
        cells = _cells(line)
        if len(cells) < 2 or _is_separator(cells):
            continue
        first = cells[0]
        tm = re.fullmatch(r"`([^`]+)`", first)
        if not tm:
            continue  # 表头等
        cur["tokens"].append(tm.group(1))
        cur["rows"].append({
            "word": tm.group(1),
            "form": cells[1],
            "semantic": cells[2] if len(cells) > 2 else "",
            "example": cells[3] if len(cells) > 3 else "",
            "category": cur["category"],
            "declared": cur["declared"],
        })
    return sections


def parse_operator_table(text: str) -> list[str]:
    block = _extract_section(text, OPERATORS_BEGIN, OPERATORS_END, "运算符表")
    ops: list[str] = []
    for raw in block.splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        cells = _cells(line)
        if len(cells) < 2 or _is_separator(cells):
            continue
        tm = re.fullmatch(r"`([^`]+)`", cells[0])
        if tm:
            ops.append(tm.group(1))
    return ops


def parse_dsdc_table(text: str) -> list[str]:
    block = _extract_section(text, DSDC_BEGIN, DSDC_END, "dscc 选项表")
    flags: list[str] = []
    for raw in block.splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        cells = _cells(line)
        if len(cells) < 2 or _is_separator(cells):
            continue
        tm = re.fullmatch(r"`([^`]+)`", cells[0])
        if tm:
            flags.append(tm.group(1))
    return flags


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------
def check(text: str) -> dict:
    errors: list[str] = []
    notes: list[str] = []

    sections = parse_keyword_tables(text)
    if not sections:
        raise Failure("未能从 §1.3 解析出任何关键词表")

    # 1) 类别顺序与集合
    doc_cats = [s["category"] for s in sections]
    if doc_cats != list(CANON):
        errors.append(f"类别顺序/名称不符：文档={doc_cats}；期望={list(CANON)}")

    # 2) 逐类覆盖与计数
    seen: dict[str, str] = {}
    for sec in sections:
        cat = sec["category"]
        expected = CANON.get(cat, [])
        if sec["declared"] != len(expected):
            errors.append(f"[{cat}] 标题计数 {sec['declared']} ≠ 清单 {len(expected)}")
        if len(sec["tokens"]) != len(expected):
            errors.append(f"[{cat}] 表格行数 {len(sec['tokens'])} ≠ 清单 {len(expected)}")
        for tok in expected:
            if tok not in sec["tokens"]:
                errors.append(f"[{cat}] 缺词：{tok!r}")
        for tok in sec["tokens"]:
            if tok not in expected:
                errors.append(f"[{cat}] 多词/串类：{tok!r}")
            if tok in seen:
                errors.append(f"重复词：{tok!r}（已出现在 [{seen[tok]}]）")
            seen[tok] = cat

    all_tokens = [t for s in sections for t in s["tokens"]]
    expected_all = [t for cat in CANON for t in CANON[cat]]
    for tok in expected_all:
        if tok not in all_tokens:
            errors.append(f"全量缺词：{tok!r}")
    for tok in all_tokens:
        if tok not in expected_all:
            errors.append(f"全量多余：{tok!r}")

    if len(all_tokens) != 77:
        errors.append(f"关键词总数 {len(all_tokens)} ≠ 77")
    n_ident = sum(1 for t in expected_all if t not in SYMBOLS)
    n_sym = sum(1 for t in expected_all if t in SYMBOLS)
    if n_ident != 73:
        errors.append(f"标识符关键字 {n_ident} ≠ 73")
    if n_sym != 4:
        errors.append(f"符号关键字 {n_sym} ≠ 4")

    # 3) 运算符
    ops = parse_operator_table(text)
    for op in CANON_OPS:
        if op not in ops:
            errors.append(f"运算符表缺：{op!r}")
    for op in ops:
        if op not in CANON_OPS:
            errors.append(f"运算符表多余：{op!r}")
    dup_ops = {o for o in ops if ops.count(o) > 1}
    if dup_ops:
        errors.append(f"运算符重复：{sorted(dup_ops)}")

    # 4) dscc
    flags = parse_dsdc_table(text)
    joined = " ".join(flags)
    for f in CANON_DSCC:
        if f == "input.ds":
            if "input.ds" not in text:
                errors.append("dscc 缺少位置参数 input.ds")
        elif f not in joined:
            errors.append(f"dscc 选项表缺：{f}")
    for required in ["--app", "--bare"]:
        if required in joined and "互斥" not in text:
            notes.append("提示：--app/--bare 互斥说明未在文中出现")

    # 5) 字面量与注释
    for lit in CANON_LITERALS:
        if lit not in text:
            errors.append(f"字面量缺失：{lit}")
    for cm in CANON_COMMENTS:
        if cm not in text:
            errors.append(f"注释形式缺失：{cm}")

    # 6) 结构完整性
    if text.count(KEYWORDS_BEGIN) != 1 or text.count(KEYWORDS_END) != 1:
        errors.append("关键词标记区间必须恰好一对")

    # 7) 生成索引
    def plain(text: str) -> str:
        """去掉 Markdown 行内代码反引号，保持 JSON 干净可检索。"""
        return text.replace("`", "").strip()

    rows: list[dict] = []
    for sec in sections:
        for i, r in enumerate(sec["rows"], 1):
            rows.append({
                "index": len(rows) + 1,
                "word": r["word"],
                "kind": "symbol" if r["word"] in SYMBOLS else "identifier",
                "category": r["category"],
                "position": i,
                "form": plain(r["form"]),
                "semantic": plain(r["semantic"]),
                "example": plain(r["example"]),
            })

    index = {
        "language": "Ds",
        "version": "0.1.0",
        "status": "definition-only",
        "spec": "spec/DS-v0.1.md",
        "generated_by": "tools/ds_keywords.py build",
        "totals": {
            "keywords": len(rows),
            "identifier_keywords": n_ident,
            "symbol_keywords": n_sym,
            "categories": len(sections),
            "operators": len(CANON_OPS),
        },
        "categories": [
            {
                "name": sec["category"],
                "count": len(sec["tokens"]),
                "keywords": [r for r in rows if r["category"] == sec["category"]],
            }
            for sec in sections
        ],
        "alphabetical": sorted(
            ({"word": r["word"], "category": r["category"], "kind": r["kind"]} for r in rows),
            key=lambda r: r["word"],
        ),
        "operators": [
            {"op": op, "index": i + 1} for i, op in enumerate(ops)
        ],
        "dscc": {
            "positional": "input.ds",
            "options": [f for f in flags],
            "canonical": CANON_DSCC,
        },
        "literals": CANON_LITERALS,
        "comments": CANON_COMMENTS,
    }
    return {"errors": errors, "index": index, "rows": rows, "notes": notes}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ds v0.1 关键词表校验/索引生成")
    ap.add_argument("command", nargs="?", default="check", choices=["check", "build"])
    ap.add_argument("--json", dest="json_path", default=None, help="额外校验的 JSON 索引路径")
    args = ap.parse_args(argv)

    if not SPEC.exists():
        print(f"✗ 找不到规范文档：{SPEC}", file=sys.stderr)
        return 1
    text = SPEC.read_text(encoding="utf-8")

    try:
        result = check(text)
    except Failure as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1

    errors: list[str] = list(result["errors"])
    index = result["index"]

    if args.command == "build":
        INDEX.write_text(
            json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"✓ 已生成 {INDEX.relative_to(ROOT)}（{index['totals']['keywords']} 词）")

    if args.json_path:
        p = Path(args.json_path)
        if not p.is_absolute():
            p = ROOT / p
        if not p.exists():
            errors.append(f"JSON 索引不存在：{p}")
        else:
            existing = json.loads(p.read_text(encoding="utf-8"))
            if existing != index:
                errors.append(
                    f"{p.relative_to(ROOT)} 与文档不一致，请运行 "
                    f"`python3 tools/ds_keywords.py build`"
                )

    if errors:
        print(f"✗ 校验失败，{len(errors)} 个问题：", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    t = index["totals"]
    print("✓ 关键词覆盖：%d/%d 类，合计 %d（标识符 %d + 符号 %d）"
          % (t["categories"], t["categories"], t["keywords"],
             t["identifier_keywords"], t["symbol_keywords"]))
    print("✓ 运算符：%d 个全部在表" % t["operators"])
    print("✓ dscc：位置参数 + 7 个核心选项全部在表")
    print("✓ 字面量 %d 种、注释 %d 种全部在文"
          % (len(CANON_LITERALS), len(CANON_COMMENTS)))
    if args.command == "check" and not args.json_path:
        print("  （提示：加 build 可刷新 spec/keywords.json）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
