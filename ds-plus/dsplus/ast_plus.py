"""Ds+ 增量 AST 节点（共享 AST 的 plus 部分）。

base AST 仍是 `dsv01.ast`；这些节点只由 Ds+ 前端产生，用于：
- 硬件 intrinsic（端口 IO/MSR/CR/MMIO）
- 内联汇编（P1：零操作数/volatile 形式）
- 内存区域标注（@stack/@static/@raw/@mmap）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dsv01 import ast


@dataclass
class Intrinsic(ast.Expr):
    """硬件 intrinsic：@inb/@outb/@rdmsr/.../@mmio。"""

    name: str = ""          # port_in / port_out / msr_read / msr_write / cr_read / cr_write / mmio
    token: str = ""         # 源令牌，如 "@inb"
    width: int = 0          # 端口位宽：8/16/32；非端口 IO 为 0
    args: list[Any] = field(default_factory=list)
    type_name: str | None = None  # @mmio 的 T
    line: int = 0
    col: int = 0


@dataclass
class InlineAsm(ast.Expr):
    """@asm（P1 支持 `@asm("...")` 与 `@asm volatile("...")`；操作数形式 P2）。"""

    template: str = ""
    volatile: bool = False
    inputs: list[Any] = field(default_factory=list)
    line: int = 0
    col: int = 0


@dataclass
class RegionAnnotated(ast.Node):
    """区域标注包装：@stack/@static/@raw/@mmap 应用于 let/var/隐式赋值。"""

    region: str = ""
    node: Any = None
    line: int = 0
    col: int = 0
