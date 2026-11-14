"""P2：compat 语义 —— 把 Ds+ AST 降级为 base AST，并在模拟硬件上执行。

用途：语义超集差分测试；不用于生产运行。
"""
from __future__ import annotations

import io
from dataclasses import fields, is_dataclass, replace
from typing import Any

from dsv01 import ast, builtins as bi
from dsv01.interp import Interpreter

from . import ast_plus


def lower(node: Any) -> Any:
    if isinstance(node, list):
        return [lower(x) for x in node]
    if not is_dataclass(node):
        return node
    if isinstance(node, ast_plus.RegionAnnotated):
        return lower(node.node)
    if isinstance(node, ast_plus.InlineAsm):
        return ast.AsmExpr(text=node.template, operands=[lower(x) for x in node.inputs],
                           line=node.line, col=node.col)
    if isinstance(node, ast_plus.Intrinsic):
        suffix = ""
        if node.name in ("port_in", "port_out"):
            suffix = str(node.width)
        name = f"__dsplus_{node.name}{suffix}"
        args = [lower(a) for a in node.args]
        if node.name == "mmio" and node.type_name:
            # 类型参数不参与运行期求值，转成字符串交给模拟器
            args = args[:1] + [ast.Lit(value=node.type_name, line=node.line, col=node.col)]
        call = ast.Call(fn=ast.Var(name=name, line=node.line, col=node.col),
                        args=args, line=node.line, col=node.col)
        return call
    changes = {}
    for f in fields(node):
        val = getattr(node, f.name)
        new = lower(val)
        if new is not val:
            changes[f.name] = new
    return replace(node, **changes) if changes else node


class SimMachine:
    def __init__(self):
        self.ports: dict[int, int] = {}
        self.msrs: dict[int, int] = {}
        self.crs: dict[int, int] = {0: 0x50033, 2: 0, 3: 0, 4: 0x20}
        self.asm_log: list[str] = []

    def port_in(self, width: int, port: int) -> int:
        return self.ports.get(port & 0xFFFF, 0) & ((1 << width) - 1)

    def port_out(self, width: int, port: int, value: int) -> Any:
        self.ports[port & 0xFFFF] = value & ((1 << width) - 1)
        return bi.UNIT

    def msr_read(self, msr: int) -> int:
        return self.msrs.get(msr & 0xFFFFFFFF, 0)

    def msr_write(self, msr: int, value: int) -> Any:
        self.msrs[msr & 0xFFFFFFFF] = value
        return bi.UNIT

    def cr_read(self, cr: int) -> int:
        return self.crs.get(cr, 0)

    def cr_write(self, cr: int, value: int) -> Any:
        self.crs[cr] = value
        return bi.UNIT

    def mmio(self, addr: int, type_name: Any = 0) -> list[int]:
        # 模拟：一页可读写内存，初值 0
        return [0] * 16

    def asm(self, *args) -> Any:
        return bi.UNIT


def register_sim(interp: Interpreter, machine: SimMachine) -> None:
    def define(name, fn):
        interp.globals.define(name, bi.NativeFunction(name, fn), mutable=True)

    for width in (8, 16, 32):
        define(f"__dsplus_port_in{width}", lambda a, k, w=width: machine.port_in(w, int(a[0])))
        define(f"__dsplus_port_out{width}", lambda a, k, w=width: machine.port_out(w, int(a[0]), int(a[1])))
    define("__dsplus_msr_read", lambda a, k: machine.msr_read(int(a[0])))
    define("__dsplus_msr_write", lambda a, k: machine.msr_write(int(a[0]), int(a[1])))
    define("__dsplus_cr_read", lambda a, k: machine.cr_read(int(a[0])))
    define("__dsplus_cr_write", lambda a, k: machine.cr_write(int(a[0]), int(a[1])))
    define("__dsplus_mmio", lambda a, k: machine.mmio(int(a[0]), a[1] if len(a) > 1 else 0))


def run_compat(src: str, filename: str = "<dsplus>", *, profile: str = "bare",
               stdout=None) -> tuple[Any, SimMachine, str]:
    """解析 + 检查 + 降级 + 模拟执行。返回 (结果, 机器状态, 输出文本)。"""
    from .frontend import parse_program
    from .checker import check_raise

    prog = parse_program(src, filename)
    check_raise(prog, profile)
    lowered = lower(prog)
    out = io.StringIO() if stdout is None else stdout
    machine = SimMachine()
    interp = Interpreter(stdout=out, filename=filename)
    register_sim(interp, machine)
    result = interp.run_program(lowered)
    text = out.getvalue() if stdout is None else ""
    return result, machine, text
