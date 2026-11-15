#!/usr/bin/env python3
"""cutc — Ds/Cut 裸机子语言原型编译器（v0.1）。

输出 ARM Thumb 汇编；可选调用 clang 汇编为 .o。
属性形式 @static/@asm/@irq 是 Ds 既有 static/asm/irq 属性的层内拼写。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
CUT_KEYWORDS = {"let", "fn", "if", "else", "while", "for", "in", "return", "bool", "true", "false"}
CUT_TYPES = {"u8", "u16", "u32", "i32", "bool"}
CUT_ATTRS = {"@static", "@asm", "@irq"}
DS_PLUS_AT = {
    "@asm", "@inb", "@outb", "@inw", "@outw", "@inl", "@outl",
    "@rdmsr", "@wrmsr", "@rdcr", "@wrcr", "@mmio",
    "@stack", "@static", "@raw", "@mmap",
}
DS_KEYWORDS = set()


def _load_ds_keywords() -> set[str]:
    try:
        data = json.loads((ROOT / "spec" / "keywords.json").read_text(encoding="utf-8"))
        return {e["word"] for e in data["alphabetical"]}
    except Exception:
        return set()


DS_KEYWORDS = _load_ds_keywords()


class CutError(Exception):
    def __init__(self, code: str, msg: str, line: int = 0, col: int = 0, filename: str = ""):
        self.code, self.msg, self.line, self.col, self.filename = code, msg, line, col, filename
        super().__init__(f"{filename}:{line}:{col}: error[{code}]: {msg}")


# --------------------------------------------------------------------------
# 词法
# --------------------------------------------------------------------------
@dataclass
class Tok:
    kind: str          # ident / int / str / at / op / punct / eof
    text: str
    line: int
    col: int


_SYMBOLS = ["..", "->", "==", "!=", "<=", ">=", "<<", ">>", "&&", "||", "+=", "-=",
            "*=", "/=", "%=", "+", "-", "*", "/", "%", "&", "|", "^", "!", "~",
            "=", "<", ">", "(", ")", "{", "}", "[", "]", ",", ";", ":", "."]


def lex(src: str, filename: str) -> list[Tok]:
    toks: list[Tok] = []
    i, line, line_start, n = 0, 1, 0, len(src)

    def err(msg: str) -> None:
        raise CutError("E_CUT_LEX", msg, line, i - line_start + 1, filename)

    while i < n:
        c = src[i]
        if c == "\n":
            toks.append(Tok("nl", "\n", line, i - line_start + 1))
            i += 1; line += 1; line_start = i; continue
        if c in " \t\r":
            i += 1; continue
        if c == "#":
            j = src.find("\n", i); i = n if j < 0 else j; continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i); i = n if j < 0 else j; continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            if j < 0: err("块注释未闭合")
            line += src.count("\n", i, j)
            i = j + 2; line_start = src.rfind("\n", 0, i) + 1; continue
        if c == '"':
            start_line, start_col = line, i - line_start + 1
            j = i + 1; buf: list[str] = []
            while j < n and src[j] != '"':
                if src[j] == "\n": err("字符串不可含裸换行")
                if src[j] == "\\" and j + 1 < n:
                    esc = src[j + 1]
                    buf.append({"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}.get(esc, esc))
                    j += 2; continue
                buf.append(src[j]); j += 1
            if j >= n: err("字符串未闭合")
            toks.append(Tok("str", "".join(buf), start_line, start_col))
            i = j + 1; continue
        if c == "@":
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] == "_"): j += 1
            name = src[i:j]
            if len(name) == 1: err("`@` 后需要名字")
            toks.append(Tok("at", name, line, i - line_start + 1)); i = j; continue
        if c.isdigit():
            j = i
            if src.startswith(("0x", "0X"), i):
                j = i + 2
                while j < n and (src[j].isdigit() or src[j].lower() in "abcdef"): j += 1
                val = int(src[i:j], 16)
            elif src.startswith(("0b", "0B"), i):
                j = i + 2
                while j < n and src[j] in "01": j += 1
                val = int(src[i:j], 2)
            else:
                while j < n and src[j].isdigit(): j += 1
                val = int(src[i:j], 10)
            toks.append(Tok("int", str(val), line, i - line_start + 1)); i = j; continue
        if c.isalpha() or c == "_":
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] == "_"): j += 1
            toks.append(Tok("ident", src[i:j], line, i - line_start + 1)); i = j; continue
        matched = False
        for sym in _SYMBOLS:
            if src.startswith(sym, i):
                toks.append(Tok("op" if len(sym) <= 2 and sym not in "(){}[],;:" else "punct",
                                sym, line, i - line_start + 1)); i += len(sym); matched = True; break
        if matched: continue
        err(f"未知字符 {c!r}")
    toks.append(Tok("eof", "<eof>", line, i - line_start + 1))
    return toks


def check_layer(tokens: list[Tok], mode: str, filename: str) -> None:
    """层检查先于语法：用错层必须报精确错误。"""
    allowed_at = CUT_ATTRS
    for t in tokens:
        if t.kind == "ident":
            w = t.text
            if w in CUT_KEYWORDS or w in CUT_TYPES:
                continue
            if w in DS_KEYWORDS:
                if mode == "cut":
                    raise CutError("E_CUT_LAYER_DS", f"`{w}` 属于 Ds 层，请使用 --app 模式",
                                   t.line, t.col, filename)
                continue
        elif t.kind == "at":
            w = t.text
            if w in allowed_at:
                continue
            if w in DS_PLUS_AT:
                if mode in ("cut", "app"):
                    raise CutError("E_CUT_LAYER_PLUS", f"`{w}` 属于 Ds+ 层，请使用 --plus 模式",
                                   t.line, t.col, filename)
                continue
            raise CutError("E_CUT_LAYER_UNKNOWN", f"未知属性 `{w}`", t.line, t.col, filename)


# --------------------------------------------------------------------------
# AST
# --------------------------------------------------------------------------
@dataclass
class Program:
    items: list[Any] = field(default_factory=list)


@dataclass
class Fn:
    name: str; params: list[tuple[str, str]]; ret: str | None; body: list[Any]
    irq: bool = False; irq_no: int | None = None; line: int = 0; col: int = 0


@dataclass
class Static:
    name: str; type: str; addr: int; line: int = 0; col: int = 0


@dataclass
class GlobalAsm:
    text: str; line: int = 0; col: int = 0


@dataclass
class Let:
    name: str; type: str | None; value: Any; line: int = 0; col: int = 0


@dataclass
class Assign:
    target: Any; value: Any; line: int = 0; col: int = 0


@dataclass
class If:
    cond: Any; then: list[Any]; else_: list[Any] | None; line: int = 0; col: int = 0


@dataclass
class While:
    cond: Any; body: list[Any]; line: int = 0; col: int = 0


@dataclass
class For:
    var: str; start: Any; end: Any; body: list[Any]; line: int = 0; col: int = 0


@dataclass
class Return:
    value: Any | None; line: int = 0; col: int = 0


@dataclass
class AsmStmt:
    text: str; inputs: list[tuple[str, Any]] = field(default_factory=list)
    outputs: list[tuple[str, str]] = field(default_factory=list); line: int = 0; col: int = 0


@dataclass
class ExprStmt:
    expr: Any; line: int = 0; col: int = 0


@dataclass
class Int:
    value: int; line: int = 0; col: int = 0


@dataclass
class Bool:
    value: bool; line: int = 0; col: int = 0


@dataclass
class Var:
    name: str; line: int = 0; col: int = 0


@dataclass
class Unary:
    op: str; expr: Any; line: int = 0; col: int = 0


@dataclass
class Binary:
    op: str; left: Any; right: Any; line: int = 0; col: int = 0


@dataclass
class Call:
    name: str; args: list[Any]; line: int = 0; col: int = 0


@dataclass
class Deref:
    expr: Any; line: int = 0; col: int = 0


# --------------------------------------------------------------------------
# 语法
# --------------------------------------------------------------------------
class Parser:
    def __init__(self, toks: list[Tok], filename: str):
        self.toks, self.i, self.filename = [t for t in toks if t.kind != "eof"] + [Tok("eof", "<eof>", 0, 0)], 0, filename

    def cur(self) -> Tok: return self.toks[self.i]
    def adv(self) -> Tok:
        t = self.cur(); self.i += 1; return t
    def at(self, text: str) -> bool: return self.cur().text == text
    def skip_nl(self) -> None:
        while self.cur().kind == "nl": self.adv()
    def expect(self, text: str) -> Tok:
        if not self.at(text):
            raise CutError("E_CUT_SYNTAX", f"期望 {text!r}，得到 {self.cur().text!r}",
                           self.cur().line, self.cur().col, self.filename)
        return self.adv()
    def error(self, msg: str) -> None:
        raise CutError("E_CUT_SYNTAX", msg, self.cur().line, self.cur().col, self.filename)
    def ident(self) -> str:
        if self.cur().kind != "ident": self.error(f"期望标识符，得到 {self.cur().text!r}")
        return self.adv().text

    def program(self) -> Program:
        p = Program()
        while True:
            self.skip_nl()
            if self.cur().kind == "eof": break
            if self.at("@asm"):
                t = self.adv()
                paren = self.at("(")
                if paren: self.adv()
                s = self.string()
                if paren: self.expect(")")
                self.semi()
                p.items.append(GlobalAsm(s, t.line, t.col))
            elif self.at("@static"):
                p.items.append(self.static_decl())
            elif self.at("@irq"):
                irq, no = True, None
                t = self.adv()
                if self.at("("):
                    self.adv(); no = int(self.expect_int()); self.expect(")")
                p.items.append(self.fn_decl(irq, no, t))
            elif self.at("fn"):
                p.items.append(self.fn_decl(False, None, self.cur()))
            else:
                self.error("顶层只允许 @asm / @static / @irq fn / fn")
        return p

    def string(self) -> str:
        if self.cur().kind != "str": self.error("期望汇编字符串")
        return self.adv().text

    def semi(self) -> None:
        while self.at(";") or self.cur().kind == "nl":
            self.adv()

    def expect_int(self) -> int:
        if self.cur().kind != "int": self.error("期望整数")
        return int(self.adv().text)

    def static_decl(self) -> Static:
        t = self.adv(); name = self.ident(); self.expect(":")
        self.skip_nl(); typ = self.type(); self.skip_nl(); self.expect("=")
        sign = 1
        if self.at("-"): self.adv(); sign = -1
        if self.cur().kind != "int": self.error("@static 地址必须是整数字面量")
        addr = sign * int(self.adv().text); self.semi()
        return Static(name, typ, addr, t.line, t.col)

    def type(self) -> str:
        if self.at("*"):
            self.adv(); return "*" + self.type()
        self.skip_nl()
        if self.cur().kind != "ident" or self.cur().text not in CUT_TYPES:
            self.error(f"期望 Cut 类型 {sorted(CUT_TYPES)}")
        return self.adv().text

    def fn_decl(self, irq: bool, no: int | None, start: Tok) -> Fn:
        self.expect("fn"); self.skip_nl(); name = self.ident(); self.expect("(")
        params: list[tuple[str, str]] = []
        if not self.at(")"):
            while True:
                pn = self.ident(); self.expect(":"); self.skip_nl(); pt = self.type()
                params.append((pn, pt))
                if not self.at(","): break
                self.adv()
        self.expect(")"); self.skip_nl(); ret = None
        if self.at("->"):
            self.adv(); self.skip_nl(); ret = self.type()
        self.skip_nl(); body = self.block()
        return Fn(name, params, ret, body, irq, no, start.line, start.col)

    def block(self) -> list[Any]:
        self.expect("{"); body = []; self.skip_nl()
        while not self.at("}"):
            if self.cur().kind == "eof": self.error("块未闭合")
            body.append(self.stmt()); self.skip_nl()
        self.adv(); return body

    def stmt(self) -> Any:
        self.skip_nl()
        t = self.cur()
        if self.at("let"):
            self.adv(); name = self.ident(); typ = None
            if self.at(":"): self.adv(); typ = self.type()
            self.expect("="); val = self.expr(); self.semi()
            return Let(name, typ, val, t.line, t.col)
        if self.at("if"): return self.if_stmt()
        if self.at("while"):
            self.adv(); cond = self.expr(); self.skip_nl()
            return While(cond, self.block(), t.line, t.col)
        if self.at("for"):
            self.adv(); var = self.ident(); self.expect("in")
            start = self.expr(); self.expect(".."); end = self.expr(); self.skip_nl()
            return For(var, start, end, self.block(), t.line, t.col)
        if self.at("return"):
            self.adv(); val = None
            if not self.at(";") and not self.at("}"): val = self.expr()
            self.semi(); return Return(val, t.line, t.col)
        if self.at("@asm"):
            self.adv()
            paren = self.at("(")
            if paren: self.adv()
            text = self.string(); inputs, outputs = [], []
            while self.at(","):
                self.adv()
                if self.at("in"):
                    self.adv(); self.expect("("); reg = self.string() if self.cur().kind == "str" else self.ident()
                    self.expect(")"); self.skip_nl(); inputs.append((reg, self.expr()))
                elif self.at("out"):
                    self.adv(); self.expect("("); reg = self.string() if self.cur().kind == "str" else self.ident()
                    self.expect(")"); outputs.append((reg, self.ident()))
                else: self.error("asm 参数只支持 in(...) / out(...)")
            if paren: self.expect(")")
            self.semi()
            return AsmStmt(text, inputs, outputs, t.line, t.col)
        # 表达式 / 赋值
        left = self.expr()
        if self.at("="):
            self.adv(); val = self.expr(); self.semi()
            if not isinstance(left, (Var, Deref)): self.error("赋值目标只能是变量或 *指针")
            return Assign(left, val, t.line, t.col)
        self.semi(); return ExprStmt(left, t.line, t.col)

    def if_stmt(self) -> If:
        t = self.adv(); cond = self.expr(); self.skip_nl(); then = self.block(); other = None
        self.skip_nl()
        if self.at("else"):
            self.adv(); self.skip_nl()
            if self.at("if"):
                other = [self.if_stmt()]
            else:
                other = self.block()
        return If(cond, then, other, t.line, t.col)

    # Pratt
    PREC = {"||": 1, "&&": 2, "|": 3, "^": 4, "&": 5, "==": 6, "!=": 6,
            "<": 7, ">": 7, "<=": 7, ">=": 7, "<<": 8, ">>": 8, "+": 9, "-": 9,
            "*": 10, "/": 10, "%": 10}

    def expr(self, min_prec: int = 1) -> Any:
        self.skip_nl()
        left = self.unary()
        while True:
            op = self.cur().text
            if self.cur().kind != "op" or op not in self.PREC or self.PREC[op] < min_prec:
                break
            t = self.adv(); right = self.expr(self.PREC[op] + 1)
            left = Binary(op, left, right, t.line, t.col)
        return left

    def unary(self) -> Any:
        self.skip_nl()
        t = self.cur()
        if self.at("-") or self.at("!") or self.at("~"):
            op = self.adv().text; return Unary(op, self.unary(), t.line, t.col)
        if self.at("*"):
            self.adv(); return Deref(self.unary(), t.line, t.col)
        if self.at("("):
            self.adv(); e = self.expr(); self.expect(")"); return e
        if t.kind == "int": self.adv(); return Int(int(t.text), t.line, t.col)
        if t.kind == "ident" and t.text in ("true", "false"):
            self.adv(); return Bool(t.text == "true", t.line, t.col)
        if t.kind == "ident":
            name = self.adv().text
            if self.at("("):
                self.adv(); args = []
                if not self.at(")"):
                    while True:
                        args.append(self.expr())
                        if not self.at(","): break
                        self.adv()
                self.expect(")")
                return Call(name, args, t.line, t.col)
            return Var(name, t.line, t.col)
        self.error(f"期望表达式，得到 {t.text!r}")


# --------------------------------------------------------------------------
# 语义检查
# --------------------------------------------------------------------------
class Checker:
    def __init__(self, filename: str):
        self.filename = filename
        self.symbols: dict[str, str] = {}   # 变量/参数名 -> 类型
        self.statics: dict[str, str] = {}   # @static 名 -> 类型
        self.functions: dict[str, Fn] = {}

    def check(self, prog: Program) -> None:
        for item in prog.items:
            if isinstance(item, Static):
                self.statics[item.name] = item.type
            elif isinstance(item, Fn):
                if item.name in self.functions:
                    raise CutError("E_CUT_REDEF", f"函数重名 {item.name}", item.line, item.col, self.filename)
                self.functions[item.name] = item
        for item in prog.items:
            if isinstance(item, Fn):
                self.check_fn(item)

    def err(self, code: str, msg: str, node: Any):
        raise CutError(code, msg, getattr(node, "line", 0), getattr(node, "col", 0), self.filename)

    def check_fn(self, fn: Fn) -> None:
        self.symbols = {name: typ for name, typ in fn.params}
        self.check_block(fn.body)

    def check_block(self, body: list[Any]) -> None:
        for st in body: self.check_stmt(st)

    def type_of(self, e: Any) -> str:
        if isinstance(e, Int): return "u32"
        if isinstance(e, Bool): return "bool"
        if isinstance(e, Var):
            if e.name in self.symbols: return self.symbols[e.name]
            if e.name in self.statics: return self.statics[e.name]
            return "?"
        if isinstance(e, Deref):
            t = self.type_of(e.expr)
            return t[1:] if t.startswith("*") else "?"
        if isinstance(e, Unary):
            if e.op == "!": return "bool"
            return self.type_of(e.expr)
        if isinstance(e, Binary):
            if e.op in ("==", "!=", "<", ">", "<=", ">=", "&&", "||"): return "bool"
            return self.type_of(e.left)
        if isinstance(e, Call): return "u32"
        return "?"

    def is_ptr(self, e: Any) -> bool:
        if isinstance(e, Var): return e.name in self.statics or self.symbols.get(e.name, "").startswith("*")
        if isinstance(e, Deref): return False
        return self.type_of(e).startswith("*")

    def check_stmt(self, st: Any) -> None:
        if isinstance(st, Let):
            typ = st.type
            if typ is None:
                if isinstance(st.value, Var) and st.value.name in self.statics: typ = "*" + "u32"
                else: typ = self.type_of(st.value)
            self.symbols[st.name] = typ
            self.check_expr(st.value)
        elif isinstance(st, Assign):
            self.check_expr(st.value)
            if isinstance(st.target, Var):
                if st.target.name not in self.symbols:
                    self.err("E_CUT_UNDEF", f"未声明变量 {st.target.name}", st)
                self.check_expr(st.target)
            else:
                self.check_expr(st.target)
        elif isinstance(st, ExprStmt): self.check_expr(st.expr)
        elif isinstance(st, Return):
            if st.value is not None: self.check_expr(st.value)
        elif isinstance(st, AsmStmt):
            for _reg, e in st.inputs: self.check_expr(e)
            for _reg, name in st.outputs:
                if name not in self.symbols: self.err("E_CUT_UNDEF", f"未声明变量 {name}", st)
        elif isinstance(st, If):
            self.check_expr(st.cond); self.check_block(st.then)
            if st.else_: self.check_block(st.else_)
        elif isinstance(st, While):
            self.check_expr(st.cond); self.check_block(st.body)
        elif isinstance(st, For):
            self.check_expr(st.start); self.check_expr(st.end)
            self.symbols[st.var] = "u32"; self.check_block(st.body)
            self.symbols.pop(st.var, None)

    def check_expr(self, e: Any) -> None:
        if isinstance(e, Int): return
        if isinstance(e, Bool): return
        if isinstance(e, Var):
            if e.name not in self.symbols and e.name not in self.statics and e.name not in self.functions:
                self.err("E_CUT_UNDEF", f"未定义名字 {e.name}", e)
            return
        if isinstance(e, Unary):
            self.check_expr(e.expr); return
        if isinstance(e, Deref):
            self.check_expr(e.expr)
            if not self.is_ptr(e.expr):
                self.err("E_CUT_DEREF", "`*` 只能解引用 @static 地址或 *T 指针", e)
            return
        if isinstance(e, Binary):
            self.check_expr(e.left); self.check_expr(e.right)
            if e.op in ("+", "-") and (self.is_ptr(e.left) or self.is_ptr(e.right)):
                self.err("E_CUT_PTR_ARITH", "禁止指针算术（p+1 / p-1 非法）", e)
            if e.op in ("*", "/", "%") and (self.is_ptr(e.left) or self.is_ptr(e.right)):
                self.err("E_CUT_PTR_ARITH", "禁止对地址做算术", e)
            return
        if isinstance(e, Call):
            if e.name not in self.functions:
                self.err("E_CUT_UNDEF", f"未定义函数 {e.name}", e)
            fn = self.functions[e.name]
            if len(e.args) != len(fn.params):
                self.err("E_CUT_CALL", f"{e.name} 期望 {len(fn.params)} 参数，得到 {len(e.args)}", e)
            if len(e.args) > 4:
                self.err("E_CUT_CALL", "Cut v0.1 调用最多 4 个参数（AAPCS r0-r3）", e)
            for a in e.args: self.check_expr(a)
            return
        self.err("E_CUT_UNSUPPORTED", f"不支持的表达式 {type(e).__name__}")


# --------------------------------------------------------------------------
# Thumb 代码生成
# --------------------------------------------------------------------------
class Codegen:
    def __init__(self, prog: Program, arch: str = "thumb"):
        self.prog = prog
        self.arch = arch
        if arch == "thumb":
            self.out: list[str] = [".syntax unified", ".thumb", ".text", ""]
        else:
            self.out: list[str] = [".arch armv8-a", ".text", ""]
        self.statics = {i.name: i for i in prog.items if isinstance(i, Static)}
        self.functions = {i.name: i for i in prog.items if isinstance(i, Fn)}
        self.label_n = 0

    def label(self, prefix: str) -> str:
        self.label_n += 1; return f".L{prefix}_{self.label_n}"

    def emit(self, *lines: str): self.out.extend(lines)

    def gen(self) -> str:
        for item in self.prog.items:
            if isinstance(item, Static):
                self.emit(f".equ {item.name}, 0x{item.addr:x}")
        for item in self.prog.items:
            if isinstance(item, GlobalAsm):
                self.asm_text(item.text, 0)
        irqs = [i for i in self.prog.items if isinstance(i, Fn) and i.irq]
        if irqs:
            self.emit('.section .vector_table,"a",%progbits')
            for i, fn in enumerate(irqs):
                self.emit(f".word {fn.name}")
            self.emit(".text")
        for item in self.prog.items:
            if isinstance(item, Fn):
                if self.arch == "aarch64":
                    pure_asm = bool(item.body) and all(isinstance(x, AsmStmt) for x in item.body)
                    if not pure_asm:
                        raise CutError("E_CUT_BACKEND",
                                       "AArch64 v0.1 仅支持纯 @asm 函数（普通函数代码生成待 v0.2）",
                                       item.line, item.col)
                self.fn(item)
        return "\n".join(self.out) + "\n"

    def asm_text(self, text: str, indent: int):
        for line in re.split(r"[;\n]", text):
            line = line.strip()
            if line:
                self.emit((" " * indent) + line)

    def fn(self, fn: Fn):
        pure_asm = bool(fn.body) and all(isinstance(s, AsmStmt) for s in fn.body)
        if pure_asm:
            self.emit(f".globl {fn.name}", f"{fn.name}:")
            for s in fn.body:
                self.asm_stmt(s, None)
            self.emit("")
            return
        slots: dict[str, int] = {}
        for name, _typ in fn.params: slots.setdefault(name, len(slots))
        for st in fn.body:
            self.collect_slots(st, slots)
        frame = ((4 * len(slots) + 7) // 8) * 8
        self.emit(f".globl {fn.name}", f"{fn.name}:")
        if fn.irq:
            self.emit("  push {lr}")
        else:
            self.emit("  push {r4, lr}")
        if frame:
            self.emit(f"  sub sp, #{frame}")
        for i, (_name, _typ) in enumerate(fn.params):
            if i < 4:
                self.emit(f"  str r{i}, [sp, #{4 * i}]")
        end = self.label("ret")
        for st in fn.body:
            self.stmt(st, slots, end)
        self.emit("  movs r0, #0", f"{end}:")
        if frame:
            self.emit(f"  add sp, #{frame}")
        if fn.irq:
            self.emit("  pop {pc}")
        else:
            self.emit("  pop {r4, pc}")
        self.emit("")

    def collect_slots(self, st: Any, slots: dict[str, int]):
        if isinstance(st, Let): slots.setdefault(st.name, len(slots))
        elif isinstance(st, If):
            for x in st.then: self.collect_slots(x, slots)
            if st.else_:
                for x in st.else_: self.collect_slots(x, slots)
        elif isinstance(st, (While, For)):
            if isinstance(st, For): slots.setdefault(st.var, len(slots))
            for x in st.body: self.collect_slots(x, slots)

    def slot(self, slots: dict[str, int], name: str) -> int:
        if name not in slots: slots[name] = len(slots)
        return slots[name]

    def stmt(self, st: Any, slots: dict[str, int], end: str):
        if isinstance(st, Let):
            self.expr(st.value, slots)
            self.emit(f"  str r0, [sp, #{4 * self.slot(slots, st.name)}]")
        elif isinstance(st, Assign):
            if isinstance(st.target, Var):
                self.expr(st.value, slots)
                self.emit(f"  str r0, [sp, #{4 * self.slot(slots, st.target.name)}]")
            else:
                self.expr(st.value, slots); self.emit("  push {r0}")
                self.expr(st.target.expr, slots); self.emit("  mov r1, r0", "  pop {r0}", "  str r0, [r1]")
        elif isinstance(st, ExprStmt):
            self.expr(st.expr, slots)
        elif isinstance(st, Return):
            if st.value is not None: self.expr(st.value, slots)
            self.emit(f"  b {end}")
        elif isinstance(st, AsmStmt):
            self.asm_stmt(st, slots)
        elif isinstance(st, If):
            els, done = self.label("else"), self.label("ifend")
            self.expr(st.cond, slots); self.emit("  cmp r0, #0", f"  beq {els}")
            for s in st.then: self.stmt(s, slots, end)
            self.emit(f"  b {done}", f"{els}:")
            if st.else_:
                for s in st.else_: self.stmt(s, slots, end)
            self.emit(f"{done}:")
        elif isinstance(st, While):
            top, done = self.label("while"), self.label("wend")
            self.emit(f"{top}:")
            self.expr(st.cond, slots); self.emit("  cmp r0, #0", f"  beq {done}")
            for s in st.body: self.stmt(s, slots, end)
            self.emit(f"  b {top}", f"{done}:")
        elif isinstance(st, For):
            top, done = self.label("for"), self.label("fend")
            self.expr(st.start, slots); self.emit(f"  str r0, [sp, #{4 * self.slot(slots, st.var)}]")
            self.emit(f"{top}:")
            self.emit(f"  ldr r0, [sp, #{4 * slots[st.var]}]"); self.emit("  push {r0}")
            self.expr(st.end, slots); self.emit("  mov r1, r0", "  pop {r0}", "  cmp r0, r1", f"  bhs {done}")
            for s in st.body: self.stmt(s, slots, end)
            self.emit(f"  ldr r0, [sp, #{4 * slots[st.var]}]", "  adds r0, r0, #1",
                      f"  str r0, [sp, #{4 * slots[st.var]}]", f"  b {top}", f"{done}:")

    def asm_stmt(self, st: AsmStmt, slots: dict[str, int] | None):
        for reg, expr in st.inputs:
            self.expr(expr, slots or {})
            self.emit(f"  mov {reg}, r0")
        self.asm_text(st.text, 2)
        for reg, name in st.outputs:
            self.emit(f"  mov r0, {reg}")
            if slots is not None:
                self.emit(f"  str r0, [sp, #{4 * self.slot(slots, name)}]")

    def expr(self, e: Any, slots: dict[str, int]):
        if isinstance(e, Int):
            if 0 <= e.value <= 255:
                self.emit(f"  movs r0, #{e.value}")
            else:
                self.emit(f"  ldr r0, ={e.value}")
        elif isinstance(e, Bool):
            self.emit(f"  movs r0, #{1 if e.value else 0}")
        elif isinstance(e, Var):
            if e.name in slots:
                self.emit(f"  ldr r0, [sp, #{4 * slots[e.name]}]")
            elif e.name in self.statics:
                self.emit(f"  ldr r0, ={e.name}")
            else:
                self.emit(f"  ldr r0, ={e.name}")
        elif isinstance(e, Deref):
            self.expr(e.expr, slots); self.emit("  ldr r0, [r0]")
        elif isinstance(e, Unary):
            self.expr(e.expr, slots)
            if e.op == "-": self.emit("  rsbs r0, r0, #0")
            elif e.op == "~": self.emit("  mvns r0, r0")
            elif e.op == "!": self.emit("  cmp r0, #0", "  movs r0, #0", "  moveq r0, #1")
        elif isinstance(e, Binary):
            self.expr(e.left, slots); self.emit("  push {r0}")
            self.expr(e.right, slots); self.emit("  mov r1, r0", "  pop {r0}")
            op = e.op
            if op == "+": self.emit("  adds r0, r0, r1")
            elif op == "-": self.emit("  subs r0, r0, r1")
            elif op == "*": self.emit("  muls r0, r0, r1")
            elif op == "&": self.emit("  ands r0, r0, r1")
            elif op == "|": self.emit("  orrs r0, r0, r1")
            elif op == "^": self.emit("  eors r0, r0, r1")
            elif op == "<<": self.emit("  lsls r0, r0, r1")
            elif op == ">>": self.emit("  asrs r0, r0, r1")
            elif op == "&&": self.emit("  ands r0, r0, r1")
            elif op == "||": self.emit("  orrs r0, r0, r1")
            elif op in ("==", "!=", "<", ">", "<=", ">="):
                cond = {"==": "eq", "!=": "ne", "<": "lt", ">": "gt", "<=": "le", ">=": "ge"}[op]
                self.emit("  cmp r0, r1", "  movs r0, #0", f"  mov{cond} r0, #1")
            elif op in ("/", "%"):
                raise CutError("E_CUT_UNSUPPORTED", "Cut v0.1 不生成除法（无硬件除法保证）")
            else:
                raise CutError("E_CUT_UNSUPPORTED", f"运算符 {op} 未实现")
        elif isinstance(e, Call):
            if len(e.args) > 4:
                raise CutError("E_CUT_CALL", "最多 4 个参数")
            for a in e.args:
                self.expr(a, slots); self.emit("  push {r0}")
            for i in range(len(e.args) - 1, -1, -1):
                self.emit(f"  pop {{r{i}}}")
            self.emit(f"  bl {e.name}")
        else:
            raise CutError("E_CUT_UNSUPPORTED", f"表达式 {type(e).__name__}")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def compile_source(src: str, filename: str, mode: str, arch: str = "thumb") -> str:
    if arch not in ("thumb", "aarch64"):
        raise CutError("E_CUT_BACKEND", f"未知架构 {arch}")
    toks = lex(src, filename)
    check_layer(toks, mode, filename)
    prog = Parser(toks, filename).program()
    Checker(filename).check(prog)
    return Codegen(prog, arch=arch).gen()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="cutc", description="Ds/Cut 原型编译器")
    ap.add_argument("file")
    ap.add_argument("--cut", action="store_const", const="cut", dest="mode")
    ap.add_argument("--app", action="store_const", const="app", dest="mode")
    ap.add_argument("--plus", action="store_const", const="plus", dest="mode")
    ap.add_argument("--emit", choices=["asm", "obj"], default="asm")
    ap.add_argument("-o", "--output")
    ap.add_argument("--arch", choices=["auto", "thumb", "aarch64"], default="auto",
                    help="目标架构；默认按 --target 推断")
    ap.add_argument("--target", default="thumbv8m.main-none-eabi")
    args = ap.parse_args(argv)
    mode = args.mode or "app"
    arch = args.arch
    if arch == "auto":
        arch = "aarch64" if args.target.startswith("aarch64") else "thumb"
    path = pathlib.Path(args.file)
    try:
        src = path.read_text(encoding="utf-8")
        asm = compile_source(src, str(path), mode, arch=arch)
    except CutError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    out = args.output or (path.with_suffix(".s") if args.emit == "asm" else path.with_suffix(".o"))
    if args.emit == "asm":
        pathlib.Path(out).write_text(asm, encoding="utf-8")
        print(f"✓ {out}")
    else:
        if not shutil.which("clang"):
            print("error[E_CUT_TOOLCHAIN]: 需要 clang 进行汇编", file=sys.stderr)
            return 1
        with tempfile.TemporaryDirectory() as td:
            sp = pathlib.Path(td) / "out.s"; sp.write_text(asm, encoding="utf-8")
            r = subprocess.run(["clang", f"--target={args.target}", "-c", "-o", out, str(sp)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                print(r.stderr, file=sys.stderr); return 1
        print(f"✓ {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
