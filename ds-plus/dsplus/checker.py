"""P2：Ds+ 语义检查（profile / unsafe / 常量 / 对齐 / 区域）。"""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from typing import Any

from dsv01 import ast

from . import ast_plus

PROFILE_BARE = "bare"
PROFILE_COMPAT = "compat"
HW_BARE_ONLY = {"@asm", "@inb", "@outb", "@inw", "@outw", "@inl", "@outl",
                "@rdmsr", "@wrmsr", "@rdcr", "@wrcr"}


@dataclass
class Diagnostic:
    code: str
    message: str
    line: int = 0
    col: int = 0

    def __str__(self) -> str:
        return f"error[{self.code}] {self.line}:{self.col}: {self.message}"


class DsPlusCheckError(Exception):
    def __init__(self, diags: list[Diagnostic]):
        self.diags = diags
        super().__init__("; ".join(str(d) for d in diags))


def _is_const(expr: Any) -> bool:
    if isinstance(expr, ast.Lit):
        return True
    if isinstance(expr, ast.Unary):
        return _is_const(expr.expr)
    if isinstance(expr, ast.Binary):
        return _is_const(expr.left) and _is_const(expr.right)
    if isinstance(expr, (ast.ArrayLit, ast.MapLit)):
        items = list(getattr(expr, "items", [])) + [v for _, v in getattr(expr, "pairs", [])]
        return all(_is_const(i) for i in items)
    return False


def _lit_int(expr: Any) -> int | None:
    if isinstance(expr, ast.Lit) and isinstance(expr.value, int) and not isinstance(expr.value, bool):
        return expr.value
    return None


class Checker:
    def __init__(self, profile: str = PROFILE_COMPAT):
        self.profile = profile
        self.unsafe = False
        self.diags: list[Diagnostic] = []

    def err(self, code: str, msg: str, node: Any):
        self.diags.append(Diagnostic(code, msg, getattr(node, "line", 0), getattr(node, "col", 0)))

    def check(self, prog: ast.Program) -> list[Diagnostic]:
        self.walk(prog)
        return self.diags

    def require_unsafe(self, node: Any, what: str):
        if not self.unsafe:
            self.err("E_DS_PLUS_UNSAFE", f"{what} 必须在 @unsafe 上下文中使用", node)

    def walk(self, node: Any) -> None:
        if isinstance(node, list):
            for n in node:
                self.walk(n)
            return
        if not is_dataclass(node):
            return
        if isinstance(node, ast.FnDecl):
            old = self.unsafe
            self.unsafe = self.unsafe or ("unsafe" in (getattr(node, "attrs", None) or []))
            for f in fields(node):
                self.walk(getattr(node, f.name))
            self.unsafe = old
            return
        if isinstance(node, ast.UnsafeBlock):
            old = self.unsafe
            self.unsafe = True
            self.walk(node.block)
            self.unsafe = old
            return
        if isinstance(node, ast_plus.InlineAsm):
            if self.profile != PROFILE_BARE:
                self.err("E_DS_PLUS_PROFILE", "@asm 仅允许在 bare profile（--bare）中使用", node)
            self.require_unsafe(node, "@asm")
            return
        if isinstance(node, ast_plus.Intrinsic):
            token = node.token
            if token in HW_BARE_ONLY and self.profile != PROFILE_BARE:
                self.err("E_DS_PLUS_PROFILE", f"{token} 仅允许在 bare profile（--bare）中使用", node)
            if token in HW_BARE_ONLY or token == "@mmio":
                self.require_unsafe(node, token)
            if token in ("@rdcr", "@wrcr"):
                cr = _lit_int(node.args[0]) if node.args else None
                if cr not in (0, 2, 3, 4):
                    self.err("E_DS_PLUS_CONST", f"{token} 的 cr 必须是编译期常量 {{0,2,3,4}}", node)
            # @mmio 允许设备寄存器地址（不要求页对齐）；页对齐约束属于 @mmap
            return
        if isinstance(node, ast_plus.RegionAnnotated):
            region = node.region
            if region in ("@raw", "@mmap"):
                self.require_unsafe(node, region)
            if region == "@static":
                val = getattr(node.node, "value", None)
                if val is not None and not _is_const(val):
                    self.err("E_DS_PLUS_CONST", "@static 初始化器必须是编译期常量", node)
            if region == "@mmap":
                val = getattr(node.node, "value", None)
                call = val if isinstance(val, ast.Call) else None
                if call and call.args:
                    addr = _lit_int(call.args[0])
                    if addr is not None and addr % 4096 != 0:
                        self.err("E_DS_PLUS_ALIGN", f"@mmap 地址 0x{addr:x} 未页对齐（4096）", node)
            self.walk(node.node)
            return
        for f in fields(node):
            self.walk(getattr(node, f.name))


def check_program(prog: ast.Program, profile: str = PROFILE_COMPAT) -> list[Diagnostic]:
    if profile not in (PROFILE_BARE, PROFILE_COMPAT):
        raise ValueError(f"未知 profile: {profile}")
    return Checker(profile).check(prog)


def check_raise(prog: ast.Program, profile: str = PROFILE_COMPAT) -> None:
    diags = check_program(prog, profile)
    if diags:
        raise DsPlusCheckError(diags)
