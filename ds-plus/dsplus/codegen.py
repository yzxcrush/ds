"""P4：x86-64 子集代码生成（无运行时 / bare 可用）。

支持：整数/布尔字面量、let/var、赋值、return、算术/比较、if/while、
用户函数调用、@asm、@inb/@outb/@inw/@outw/@inl/@outl、@rdmsr/@wrmsr、
@rdcr/@wrcr、@stack/@static 区域；字符串/GC/@mmio 等暂不支持。

输出：AT&T 语法汇编；可经 cc -nostdlib 组装成 ELF，或用 objcopy 转 raw binary。
"""
from __future__ import annotations

import pathlib
import platform
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Any

from dsv01 import ast

from . import ast_plus

REG64 = ["%rdi", "%rsi", "%rdx", "%rcx", "%r8", "%r9"]


class CodegenError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass
class FnCtx:
    name: str
    ret_label: str
    slots: dict[str, int] = field(default_factory=dict)
    frame: int = 0
    lines: list[str] = field(default_factory=list)
    label_seq: int = 0

    def label(self, prefix: str) -> str:
        self.label_seq += 1
        return f".L{self.name}_{prefix}_{self.label_seq}"


def _slot_map(fn: ast.FnDecl) -> dict[str, int]:
    slots: dict[str, int] = {}
    for p in fn.params:
        slots[p.name] = len(slots)

    def walk(node: Any):
        if isinstance(node, list):
            for x in node:
                walk(x)
        elif isinstance(node, ast.Block):
            for s in node.stmts:
                walk(s)
        elif isinstance(node, (ast.LetStmt, ast.LetItem)):
            slots.setdefault(node.name, len(slots))
        elif isinstance(node, ast_plus.RegionAnnotated):
            walk(node.node)

    walk(fn.body)
    return slots


class Emitter:
    def __init__(self, bare: bool = False):
        self.bare = bare
        self.out: list[str] = [".text"]
        self.globals: dict[str, int] = {}

    def emit(self, *lines: str):
        self.out.extend(lines)

    # ---------------------------------------------------------------- 函数
    def fn(self, fn: ast.FnDecl):
        ctx = FnCtx(name=fn.name, ret_label=f".Lret_{fn.name}")
        ctx.slots = _slot_map(fn)
        ctx.ret_label = f".Lret_{fn.name}"
        n = len(ctx.slots)
        frame = ((8 * n + 15) // 16) * 16
        ctx.frame = frame
        self.emit(f".globl {fn.name}", f"{fn.name}:", "  pushq %rbp", "  movq %rsp, %rbp")
        if frame:
            self.emit(f"  subq ${frame}, %rsp")
        for i, p in enumerate(fn.params):
            if i < len(REG64):
                self.emit(f"  movq {REG64[i]}, -{8 * (i + 1)}(%rbp)")
        body = fn.body
        if isinstance(body, ast.Expr):
            self.expr(body, ctx)
            self.emit(f"  jmp {ctx.ret_label}")
        elif (isinstance(body, ast.Block) and body.stmts
              and isinstance(body.stmts[-1], ast.ExprStmt)):
            # 函数尾表达式是返回值：先执行前面的语句，最后保留 %rax
            for s in body.stmts[:-1]:
                self.stmt(s, ctx)
            self.expr(body.stmts[-1].expr, ctx)
            self.emit(f"  jmp {ctx.ret_label}")
        else:
            self.stmt(body, ctx)
        self.emit("  xorl %eax, %eax", f"{ctx.ret_label}:", "  leave", "  ret", "")

    # ---------------------------------------------------------------- 语句
    def stmt(self, node: Any, ctx: FnCtx):
        if isinstance(node, ast.Block):
            for s in node.stmts:
                self.stmt(s, ctx)
        elif isinstance(node, ast_plus.RegionAnnotated):
            self.stmt(node.node, ctx)
        elif isinstance(node, (ast.LetStmt, ast.LetItem)):
            if node.value is not None:
                self.expr(node.value, ctx)
            else:
                self.emit("  xorl %eax, %eax")
            if node.name in ctx.slots:
                self.emit(f"  movq %rax, -{8 * (ctx.slots[node.name] + 1)}(%rbp)")
        elif isinstance(node, ast.AssignStmt):
            if not isinstance(node.target, ast.Var):
                raise CodegenError("E_DS_PLUS_CODEGEN", "P4 只支持局部变量赋值")
            self.expr(node.value, ctx)
            if node.target.name in ctx.slots:
                self.emit(f"  movq %rax, -{8 * (ctx.slots[node.target.name] + 1)}(%rbp)")
            else:
                raise CodegenError("E_DS_PLUS_CODEGEN", f"未声明变量 {node.target.name}")
        elif isinstance(node, ast.ExprStmt):
            self.expr(node.expr, ctx)
        elif isinstance(node, ast.ReturnStmt):
            if node.value is not None:
                self.expr(node.value, ctx)
            self.emit(f"  jmp {ctx.ret_label}")
        elif isinstance(node, ast.IfExpr):
            self.if_stmt(node, ctx)
        elif isinstance(node, ast.WhileStmt):
            top = ctx.label("while")
            end = ctx.label("wend")
            self.emit(f"{top}:")
            self.expr(node.cond, ctx)
            self.emit("  testq %rax, %rax", f"  je {end}")
            self.stmt(node.body, ctx)
            self.emit(f"  jmp {top}", f"{end}:")
        elif isinstance(node, ast.Block):
            for s in node.stmts:
                self.stmt(s, ctx)
        else:
            raise CodegenError("E_DS_PLUS_CODEGEN", f"P4 不支持语句 {type(node).__name__}")

    def if_stmt(self, node: ast.IfExpr, ctx: FnCtx):
        els = ctx.label("else")
        end = ctx.label("ifend")
        self.expr(node.cond, ctx)
        self.emit("  testq %rax, %rax", f"  je {els}")
        self.stmt(node.then_block, ctx)
        self.emit(f"  jmp {end}", f"{els}:")
        if isinstance(node.else_, ast.Block):
            self.stmt(node.else_, ctx)
        elif isinstance(node.else_, ast.Expr):
            self.expr(node.else_, ctx)
        self.emit(f"{end}:")

    # ---------------------------------------------------------------- 表达式
    def expr(self, node: Any, ctx: FnCtx):
        if isinstance(node, ast.Lit):
            v = node.value
            if isinstance(v, bool):
                v = 1 if v else 0
            if not isinstance(v, int):
                raise CodegenError("E_DS_PLUS_CODEGEN", f"P4 只支持整数/布尔字面量，得到 {v!r}")
            self.emit(f"  movq ${v}, %rax")
        elif isinstance(node, ast.Var):
            if node.name in ctx.slots:
                self.emit(f"  movq -{8 * (ctx.slots[node.name] + 1)}(%rbp), %rax")
            elif node.name in self.globals:
                self.emit(f"  movq {node.name}(%rip), %rax")
            else:
                raise CodegenError("E_DS_PLUS_CODEGEN", f"未知变量 {node.name}")
        elif isinstance(node, ast.Binary):
            self.binary(node, ctx)
        elif isinstance(node, ast.Unary):
            self.expr(node.expr, ctx)
            if node.op == "-":
                self.emit("  negq %rax")
            elif node.op == "~":
                self.emit("  notq %rax")
            elif node.op == "!":
                self.emit("  testq %rax, %rax", "  sete %al", "  movzbl %al, %eax")
            else:
                raise CodegenError("E_DS_PLUS_CODEGEN", f"P4 不支持一元 {node.op}")
        elif isinstance(node, ast.Call):
            self.call(node, ctx)
        elif isinstance(node, ast.Cast):
            self.expr(node.expr, ctx)
        elif isinstance(node, ast_plus.InlineAsm):
            self.asm(node, ctx)
        elif isinstance(node, ast_plus.Intrinsic):
            self.intrinsic(node, ctx)
        elif isinstance(node, ast_plus.RegionAnnotated):
            self.expr(node.node, ctx)
        else:
            raise CodegenError("E_DS_PLUS_CODEGEN", f"P4 不支持表达式 {type(node).__name__}")

    def binary(self, node: ast.Binary, ctx: FnCtx):
        op = node.op
        if op in ("&&", "||"):
            # 非短路的简化实现
            self.expr(node.left, ctx)
            self.emit("  pushq %rax")
            self.expr(node.right, ctx)
            self.emit("  popq %rcx")
            self.emit("  andq %rcx, %rax" if op == "&&" else "  orq %rcx, %rax")
            return
        self.expr(node.left, ctx)
        self.emit("  pushq %rax")
        self.expr(node.right, ctx)
        self.emit("  movq %rax, %rcx", "  popq %rax")
        ops = {
            "+": "  addq %rcx, %rax", "-": "  subq %rcx, %rax",
            "*": "  imulq %rcx, %rax", "/": "  cqto\n  idivq %rcx",
            "%": "  cqto\n  idivq %rcx\n  movq %rdx, %rax",
            "&": "  andq %rcx, %rax", "|": "  orq %rcx, %rax", "^": "  xorq %rcx, %rax",
            "<<": "  shlq %cl, %rax", ">>": "  sarq %cl, %rax",
        }
        if op in ops:
            self.out.extend(("  " + l if not l.startswith("  ") else l) for l in ops[op].split("\n"))
        elif op in ("==", "!=", "<", ">", "<=", ">="):
            cc = {"==": "e", "!=": "ne", "<": "l", ">": "g", "<=": "le", ">=": "ge"}[op]
            self.emit("  cmpq %rcx, %rax", f"  set{cc} %al", "  movzbl %al, %eax")
        else:
            raise CodegenError("E_DS_PLUS_CODEGEN", f"P4 不支持运算符 {op}")

    def call(self, node: ast.Call, ctx: FnCtx):
        if not isinstance(node.fn, ast.Var):
            raise CodegenError("E_DS_PLUS_CODEGEN", "P4 只支持直接函数调用")
        if len(node.args) > len(REG64):
            raise CodegenError("E_DS_PLUS_CODEGEN", "P4 最多 6 个参数")
        for a in node.args:
            self.expr(a, ctx)
            self.emit("  pushq %rax")
        for i in range(len(node.args) - 1, -1, -1):
            self.emit(f"  popq {REG64[i]}")
        self.emit(f"  call {node.fn.name}")

    def intrinsic(self, node: ast_plus.Intrinsic, ctx: FnCtx):
        tok = node.token
        if tok in ("@inb", "@inw", "@inl"):
            port = node.args[0]
            if not isinstance(port, ast.Lit) or not isinstance(port.value, int):
                raise CodegenError("E_DS_PLUS_CODEGEN", "P4 端口号必须是整数字面量")
            size = {"@inb": (8, "inb %dx, %al\n  movzbl %al, %eax"),
                    "@inw": (16, "inw %dx, %ax\n  movzwl %ax, %eax"),
                    "@inl": (32, "inl %dx, %eax")}[tok][1]
            self.emit(f"  movw ${port.value & 0xFFFF}, %dx", "  " + size.replace("\n", "\n  "))
        elif tok in ("@outb", "@outw", "@outl"):
            port = node.args[0]
            if not isinstance(port, ast.Lit) or not isinstance(port.value, int):
                raise CodegenError("E_DS_PLUS_CODEGEN", "P4 端口号必须是整数字面量")
            self.expr(node.args[1], ctx)
            ins = {"@outb": "outb %al, %dx", "@outw": "outw %ax, %dx", "@outl": "outl %eax, %dx"}[tok]
            self.emit(f"  movw ${port.value & 0xFFFF}, %dx", f"  {ins}")
        elif tok == "@rdmsr":
            msr = node.args[0]
            if not isinstance(msr, ast.Lit):
                raise CodegenError("E_DS_PLUS_CODEGEN", "P4 MSR 号必须是整数字面量")
            self.emit(f"  movl ${msr.value}, %ecx", "  rdmsr", "  shlq $32, %rdx", "  orq %rdx, %rax")
        elif tok == "@wrmsr":
            msr = node.args[0]
            if not isinstance(msr, ast.Lit):
                raise CodegenError("E_DS_PLUS_CODEGEN", "P4 MSR 号必须是整数字面量")
            self.expr(node.args[1], ctx)
            self.emit(f"  movl ${msr.value}, %ecx", "  movq %rax, %rdx", "  shrq $32, %rdx", "  wrmsr")
        elif tok in ("@rdcr", "@wrcr"):
            cr = node.args[0]
            if not isinstance(cr, ast.Lit) or cr.value not in (0, 2, 3, 4):
                raise CodegenError("E_DS_PLUS_CODEGEN", "P4 CR 必须是 0/2/3/4")
            if tok == "@rdcr":
                self.emit(f"  movq %cr{cr.value}, %rax")
            else:
                self.expr(node.args[1], ctx)
                self.emit(f"  movq %rax, %cr{cr.value}")
        else:
            raise CodegenError("E_DS_PLUS_CODEGEN", f"P4 暂不支持 {tok}")

    def asm(self, node: ast_plus.InlineAsm, ctx: FnCtx):
        for i, inp in enumerate(node.inputs):
            self.expr(inp, ctx)
            self.emit(f"  pushq %rax")
        regs = ["%r10", "%r11", "%r12", "%r13", "%r14", "%r15"]
        for i in range(len(node.inputs) - 1, -1, -1):
            self.emit(f"  popq {regs[i]}")
        text = node.template
        for i in range(len(node.inputs)):
            text = text.replace(f"%{i}", regs[i])
        for line in text.split(";"):
            line = line.strip()
            if line:
                self.emit("  " + line)

    # ---------------------------------------------------------------- 模块
    def program(self, prog: ast.Program):
        fns = [i for i in prog.items if isinstance(i, ast.FnDecl)]
        # @static 全局（P4：仅整数字面量）
        for item in prog.items:
            if isinstance(item, ast_plus.RegionAnnotated) and item.region == "@static":
                node = item.node
                val = getattr(node, "value", None)
                if isinstance(val, ast.Lit) and isinstance(val.value, int):
                    self.globals[node.name] = val.value
        if self.globals:
            self.out.append(".data")
            for name, val in self.globals.items():
                self.emit(f".globl {name}", f"{name}:", f"  .quad {val}")
            self.out.append(".text")
        has_main = any(f.name in ("main", "entry") for f in fns)
        if not has_main:
            # 把顶层语句合成 main
            stmts = [i for i in prog.items if not isinstance(i, (ast.FnDecl, ast.Use))]
            fn = ast.FnDecl(name="main", params=[], ret=ast.TypeName(name="i32"),
                            body=ast.Block(stmts=stmts))
            fns.append(fn)
        if not self.bare:
            self.emit(".globl _start", "_start:", "  call main", "  movl %eax, %edi",
                      "  movl $60, %eax", "  syscall")
        for fn in fns:
            self.fn(fn)
        return "\n".join(self.out) + "\n"


def generate(prog: ast.Program, bare: bool = False) -> str:
    return Emitter(bare=bare).program(prog)


def generate_source(src: str, filename: str = "<dsplus>", bare: bool = False) -> str:
    from .frontend import parse_program
    return generate(parse_program(src, filename), bare=bare)


def _link_x86_64(asm_path: pathlib.Path, exe: pathlib.Path) -> None:
    """本机 x86_64 用 cc；交叉平台用 clang --target + ld.lld。"""
    if platform.machine() in ("x86_64", "AMD64"):
        cc = shutil.which("cc") or shutil.which("gcc")
        if not cc:
            raise CodegenError("E_DS_PLUS_LINK", "找不到 cc/gcc")
        r = subprocess.run([cc, "-nostdlib", "-static", "-no-pie", "-o", str(exe), str(asm_path)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise CodegenError("E_DS_PLUS_LINK", r.stderr.strip()[:400])
        return
    clang = shutil.which("clang")
    lld = shutil.which("ld.lld") or shutil.which("lld")
    if not clang or not lld:
        raise CodegenError("E_DS_PLUS_LINK", "交叉汇编需要 clang + ld.lld（当前平台缺少）")
    obj = asm_path.with_suffix(".o")
    r = subprocess.run([clang, "--target=x86_64-linux-gnu", "-c", "-o", str(obj), str(asm_path)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise CodegenError("E_DS_PLUS_LINK", r.stderr.strip()[:400])
    r = subprocess.run([lld, "-o", str(exe), str(obj)], capture_output=True, text=True)
    if r.returncode != 0:
        raise CodegenError("E_DS_PLUS_LINK", r.stderr.strip()[:400])


def build(src: str, out_path: str, *, filename: str = "<dsplus>", bare: bool = False,
          raw: bool = False, target: str = "x86_64-linux-gnu") -> dict:
    if target != "x86_64-linux-gnu":
        raise CodegenError("E_DS_PLUS_CODEGEN", f"P4 仅支持 x86_64-linux-gnu，得到 {target}")
    asm = generate_source(src, filename, bare=bare)
    with tempfile.TemporaryDirectory() as td:
        asm_path = pathlib.Path(td) / "out.s"
        asm_path.write_text(asm, encoding="utf-8")
        exe = pathlib.Path(out_path)
        _link_x86_64(asm_path, exe)
        info = {"asm": asm, "exe": str(exe)}
        if raw:
            raw_path = str(exe) + ".bin"
            oc = subprocess.run(["objcopy", "-O", "binary", str(exe), raw_path],
                                capture_output=True, text=True)
            if oc.returncode != 0:
                raise CodegenError("E_DS_PLUS_LINK", oc.stderr.strip()[:400])
            info["raw"] = raw_path
        return info
