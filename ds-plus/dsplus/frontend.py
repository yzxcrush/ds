"""Ds+ 前端 P1。

流程：扫描 `@` 令牌 → 重写为 base 可解析的占位形式 → 复用 `dsv01.parser`
→ AST 变换注入 `dsplus.ast_plus` 节点。

为什么这样做：
- base 代码（不含 16 个 @ 令牌）直接走 base parser，AST 与 base **完全一致**；
- plus 代码只增加占位调用/空白替换，不复制 base 语法；
- 三档写法（经典/0.1c/Flow）由 base parser 统一处理，plus 节点与表面写法无关。
"""
from __future__ import annotations

import re
from dataclasses import fields, is_dataclass, replace
from typing import Any

from dsv01 import ast
from dsv01.parser import parse_program as base_parse_program
from dsv01.lexer import DsSyntaxError

from . import ast_plus

HARDWARE = {
    "@asm": ("asm", 0),
    "@inb": ("port_in", 8),
    "@outb": ("port_out", 8),
    "@inw": ("port_in", 16),
    "@outw": ("port_out", 16),
    "@inl": ("port_in", 32),
    "@outl": ("port_out", 32),
    "@rdmsr": ("msr_read", 0),
    "@wrmsr": ("msr_write", 0),
    "@mmio": ("mmio", 0),
    "@rdcr": ("cr_read", 0),
    "@wrcr": ("cr_write", 0),
}
REGIONS = {"@stack", "@static", "@raw", "@mmap"}
TOKEN_RE = re.compile(r"@([A-Za-z_][A-Za-z0-9_]*)")
REGION_AFTER = re.compile(r"\s*(?:let\b|var\b|@|[A-Za-z_]\w*\s*(?::[^=\n]+)?=)")


class DsPlusError(Exception):
    """Ds+ 前端错误（带错误码）。"""

    def __init__(self, code: str, message: str, line: int = 0, col: int = 0, filename: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.line = line
        self.col = col
        self.filename = filename

    def __str__(self) -> str:
        loc = f"{self.filename}:{self.line}:{self.col}: " if self.filename else ""
        return f"{loc}error[{self.code}]: {self.message}"


def _mask_literals(src: str) -> str:
    """把注释/字符串替换为空格（保持长度与换行），避免误识别其中的 @ 令牌。"""
    out = list(src)
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == "#":
            j = src.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = " " if src[k] != "\n" else "\n"
            i = j
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = " " if src[k] != "\n" else "\n"
            i = j
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, min(j, n)):
                out[k] = " " if src[k] != "\n" else "\n"
            i = j
            continue
        if c in ('b', 'B', 'f', 'F') and i + 1 < n and src[i + 1] == '"':
            i += 1
            c = '"'
        if c == '"':
            j = i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == '"':
                    j += 1
                    break
                j += 1
            for k in range(i, min(j, n)):
                out[k] = " " if src[k] != "\n" else "\n"
            i = j
            continue
        i += 1
    return "".join(out)


def _skip_space(src: str, i: int) -> int:
    while i < len(src) and src[i] in " \t\r":
        i += 1
    return i


def detect_plus_tokens(src: str) -> list[dict]:
    """返回 Ds+ 令牌列表（按出现顺序）。kind: hardware/region/asm/asm_volatile。"""
    masked = _mask_literals(src)
    found: list[dict] = []
    for m in TOKEN_RE.finditer(masked):
        name = "@" + m.group(1)
        if name not in HARDWARE and name not in REGIONS:
            continue
        j = _skip_space(masked, m.end())
        if name == "@asm":
            volatile = False
            if masked.startswith("volatile", j):
                j2 = _skip_space(masked, j + len("volatile"))
                if j2 < len(masked) and masked[j2] == "(":
                    volatile = True
                    j = j2
                else:
                    continue  # @asm 作为属性
            if j >= len(masked) or masked[j] != "(":
                continue  # @asm 作为属性/块形式留给错误报告
            kind = "asm_volatile" if volatile else "asm"
        elif name in REGIONS:
            if not REGION_AFTER.match(masked[m.end():]):
                continue  # 属性（例如 @raw fn）保持 base 语义
            kind = "region"
        else:
            if j < len(masked) and masked[j] in "({":
                kind = "hardware"
            elif masked.startswith("volatile", j):
                j2 = _skip_space(masked, j + len("volatile"))
                if j2 < len(masked) and masked[j2] == "(":
                    kind = "hardware"
                else:
                    continue
            else:
                continue
        line = masked.count("\n", 0, m.start()) + 1
        col = m.start() - masked.rfind("\n", 0, m.start())
        found.append({"name": name, "kind": kind, "start": m.start(), "end": m.end(),
                      "line": line, "col": col})
    return found


def _rewrite(src: str, tokens: list[dict]) -> tuple[str, list[dict]]:
    out = list(src)
    meta: list[dict] = []
    # 从后往前替换，保持前面的偏移不变
    for t in reversed(tokens):
        name, kind = t["name"], t["kind"]
        if kind == "region":
            for k in range(t["start"], t["end"]):
                out[k] = " "
            meta.append({"kind": "region", "name": name, "line": t["line"], "col": t["col"]})
        elif kind in ("asm", "asm_volatile"):
            span_end = t["end"]
            if kind == "asm_volatile":
                j = _skip_space(src, t["end"])
                if src.startswith("volatile", j):
                    span_end = j + len("volatile")
            repl = "__dsplus_asm_v" if kind == "asm_volatile" else "__dsplus_asm"
            out[t["start"]:span_end] = list(repl)
            meta.append({"kind": "asm", "volatile": kind == "asm_volatile", "line": t["line"]})
        else:
            placeholder = "__dsplus_" + name[1:]
            out[t["start"]:t["end"]] = list(placeholder)
            meta.append({"kind": "hardware", "name": name, "line": t["line"]})
    return "".join(out), meta


def _is_call(node: Any) -> bool:
    return isinstance(node, ast.Call)


def _convert_call(node: ast.Call, asm_meta: list[dict]) -> Any:
    fn = node.fn
    if not (isinstance(fn, ast.Var) and fn.name.startswith("__dsplus_")):
        return node
    placeholder = fn.name
    if placeholder in ("__dsplus_asm", "__dsplus_asm_v"):
        if node.kwargs:
            raise DsPlusError("E_DS_PLUS_ASM_FORM_P1", "@asm 的 P1 前端不支持命名参数", node.line, node.col)
        if not node.args or not isinstance(node.args[0], ast.Lit) or not isinstance(node.args[0].value, str):
            raise DsPlusError(
                "E_DS_PLUS_ASM_FORM_P1",
                "@asm 需要字符串模板：`@asm(\"...\"[, 输入...])`",
                node.line, node.col)
        return ast_plus.InlineAsm(
            template=node.args[0].value,
            volatile=placeholder.endswith("_v"),
            inputs=list(node.args[1:]),
            line=node.line, col=node.col,
        )

    token = "@" + placeholder[len("__dsplus_"):]
    if token not in HARDWARE:
        return node
    canonical, width = HARDWARE[token]
    args = list(node.args)
    if node.kwargs:
        raise DsPlusError("E_DS_PLUS_ARGS", f"{token} 不支持命名参数", node.line, node.col)
    expected = {
        "port_in": 1, "port_out": 2, "msr_read": 1, "msr_write": 2,
        "cr_read": 1, "cr_write": 2, "mmio": 2,
    }[canonical]
    if len(args) != expected:
        raise DsPlusError("E_DS_PLUS_ARGS", f"{token} 期望 {expected} 个参数，得到 {len(args)}", node.line, node.col)
    type_name = None
    if canonical == "mmio" and isinstance(args[1], ast.Var):
        type_name = args[1].name
    return ast_plus.Intrinsic(
        name=canonical, token=token, width=width, args=args,
        type_name=type_name, line=node.line, col=node.col,
    )


def _transform(node: Any, asm_meta: list[dict], regions: list[dict]) -> Any:
    if isinstance(node, list):
        return [_transform(x, asm_meta, regions) for x in node]
    if not is_dataclass(node):
        return node
    changes: dict[str, Any] = {}
    for f in fields(node):
        val = getattr(node, f.name)
        new = _transform(val, asm_meta, regions)
        if new is not val:
            changes[f.name] = new
    if changes:
        node = replace(node, **changes)
    if isinstance(node, ast.Call):
        node = _convert_call(node, asm_meta)
    if isinstance(node, (ast.LetStmt, ast.LetItem, ast.AssignStmt)):
        for rec in list(regions):
            if rec.get("used"):
                continue
            if rec["line"] == getattr(node, "line", None):
                rec["used"] = True
                return ast_plus.RegionAnnotated(
                    region=rec["name"], node=node, line=node.line, col=node.col)
    return node


def parse_program(src: str, filename: str = "<source>") -> ast.Program:
    """解析 Ds+ 源码（base 超集）。

    base 代码：AST 与 `dsv01.parser.parse_program` 完全一致。
    plus 代码：在 base AST 上注入 Intrinsic/InlineAsm/RegionAnnotated 节点。
    """
    tokens = detect_plus_tokens(src)
    if not tokens:
        return base_parse_program(src, filename)
    rewritten, meta = _rewrite(src, tokens)
    try:
        prog = base_parse_program(rewritten, filename)
    except DsSyntaxError:
        raise
    regions = [m for m in meta if m["kind"] == "region"]
    asm_meta = [m for m in meta if m["kind"] == "asm"]
    result = _transform(prog, asm_meta, regions)
    leftover = [r for r in regions if not r.get("used")]
    if leftover:
        r = leftover[0]
        raise DsPlusError("E_DS_PLUS_REGION_TARGET",
                          f"{r['name']} 未标注到 let/var/隐式赋值", r["line"], r["col"], filename)
    return result


def collect_plus_features(node: Any) -> list[Any]:
    """提取 plus 节点特征（测试/调试用，忽略 base AST 表面差异）。"""
    out: list[Any] = []

    def walk(x: Any):
        if isinstance(x, list):
            for item in x:
                walk(item)
            return
        if not is_dataclass(x):
            return
        if isinstance(x, ast_plus.Intrinsic):
            out.append(("Intrinsic", x.token, x.name, x.width, x.type_name))
        elif isinstance(x, ast_plus.InlineAsm):
            out.append(("InlineAsm", x.template, x.volatile))
        elif isinstance(x, ast_plus.RegionAnnotated):
            out.append(("Region", x.region, type(x.node).__name__))
        for f in fields(x):
            walk(getattr(x, f.name))

    walk(node)
    return out


def parse_file(path: str) -> ast.Program:
    from pathlib import Path
    p = Path(path)
    return parse_program(p.read_text(encoding="utf-8"), p.name)
