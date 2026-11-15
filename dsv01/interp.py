# -*- coding: utf-8 -*-
"""Ds v0.1 参考解释器（树遍历求值）。

语义近似说明（0.1 参考实现，不是规范本身）：
- 类型标注在运行时基本不参与检查（动态类型 + `is`/`sizeof`/`typeinfo` 按标注求值）；
- 借用检查、unsafe 边界、内存安全不做强制，`@unsafe` 只作标注；
- `comptime` 在求值时即时计算（对纯表达式结果等价于编译期）；
- `chan[T]()` 的零容量按无界缓冲近似，避免同线程 send/recv 死锁；
- `spawn` 用 Python 线程实现，作用域结束时自动 `wait`；`go` 为 daemon 线程；
- `ptr` 解引用用 bytearray/地址模拟，越界或空地址读写会报错或返回 0。
"""

from __future__ import annotations

import copy
import dataclasses
import sys
import threading
from dataclasses import dataclass, field
from typing import Any

from . import ast, builtins as bi
from .lexer import DsSyntaxError


# ---------------------------------------------------------------------------
# 控制流信号
# ---------------------------------------------------------------------------
class ReturnSignal(Exception):
    def __init__(self, value: Any):
        self.value = value


class BreakSignal(Exception):
    def __init__(self, value: Any = bi.UNIT):
        self.value = value


class ContinueSignal(Exception):
    pass


class GotoSignal(Exception):
    def __init__(self, name: str):
        self.name = name


# ---------------------------------------------------------------------------
# 作用域
# ---------------------------------------------------------------------------
class Env:
    __slots__ = ("vars", "mutable", "parent", "cleanups", "name")

    def __init__(self, parent: "Env | None" = None, name: str = "<scope>"):
        self.vars: dict[str, Any] = {}
        self.mutable: set[str] = set()
        self.parent = parent
        self.cleanups: list[Any] = []
        self.name = name

    # -- 名字 -------------------------------------------------------------
    def define(self, name: str, value: Any, mutable: bool = False) -> None:
        self.vars[name] = value
        if mutable:
            self.mutable.add(name)
        else:
            self.mutable.discard(name)

    def has_local(self, name: str) -> bool:
        return name in self.vars

    def has(self, name: str) -> bool:
        env: Env | None = self
        while env is not None:
            if name in env.vars:
                return True
            env = env.parent
        return False

    def lookup(self, name: str) -> Any:
        env: Env | None = self
        while env is not None:
            if name in env.vars:
                return env.vars[name]
            env = env.parent
        raise bi.DsRuntimeError(f"未定义的名字 `{name}`")

    def assign(self, name: str, value: Any) -> None:
        env: Env | None = self
        while env is not None:
            if name in env.vars:
                if name not in env.mutable:
                    raise bi.DsRuntimeError(f"`{name}` 不可变，不能赋值（用 var 声明）")
                env.vars[name] = value
                return
            env = env.parent
        raise bi.DsRuntimeError(f"未定义的名字 `{name}`")

    # -- 确定性析构 -------------------------------------------------------
    def register_cleanup(self, value: Any) -> None:
        self.cleanups.append(value)

    def run_cleanups(self, interp: "Interpreter") -> None:
        while self.cleanups:
            value = self.cleanups.pop()
            interp.drop_value(value)


@dataclass
class UnitCtx:
    """一个编译单元的声明/延迟执行上下文。"""

    deferred: list[Any] = field(default_factory=list)
    uses: list[Any] = field(default_factory=list)
    impls: list[Any] = field(default_factory=list)
    macros: list[Any] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 解释器
# ---------------------------------------------------------------------------
class Interpreter:
    def __init__(self, *, stdout=None, bare: bool = False, gc_mode: str = "tracing",
                 rt: str = "full", target: str = "host", opt: int = 2,
                 filename: str = "<string>"):
        self.stdout = stdout if stdout is not None else sys.stdout
        self.bare = bare
        self.gc_mode = gc_mode
        self.rt = rt
        self.target = target
        self.opt = opt
        self.filename = filename

        self.globals = Env(None, "<prelude>")
        for name, value in bi.make_prelude(self).items():
            self.globals.define(name, value, mutable=True)

        self.types: dict[str, bi.TypeDef] = {}
        self.modules: dict[str, bi.Module] = {}
        self.package: str | None = None
        self.depth = 0
        self.max_depth = 250
        self._tls = threading.local()
        self.repl_env = Env(self.globals, "<repl>")

        self._expr_dispatch = {
            ast.Lit: self.ev_lit,
            ast.FString: self.ev_fstring,
            ast.ArrayLit: self.ev_array,
            ast.MapLit: self.ev_map,
            ast.Var: self.ev_var,
            ast.Path: self.ev_path,
            ast.AttrExpr: self.ev_attr,
            ast.Index: self.ev_index,
            ast.SliceExpr: self.ev_slice,
            ast.Call: self.ev_call,
            ast.Unary: self.ev_unary,
            ast.Binary: self.ev_binary,
            ast.Cast: self.ev_cast,
            ast.IsTest: self.ev_is,
            ast.InTest: self.ev_in,
            ast.BlockExpr: self.ev_block_expr,
            ast.IfExpr: self.ev_if,
            ast.MatchExpr: self.ev_match,
            ast.FnLit: self.ev_fn_lit,
            ast.TryExpr: self.ev_try_expr,
            ast.TryCatch: self.ev_try_catch,
            ast.RecvExpr: self.ev_recv,
            ast.WaitExpr: self.ev_wait,
            ast.SpawnExpr: self.ev_spawn,
            ast.GoExpr: self.ev_go,
            ast.ThreadExpr: self.ev_thread,
            ast.NewExpr: self.ev_new,
            ast.ComptimeExpr: self.ev_comptime,
            ast.SizeofExpr: self.ev_sizeof,
            ast.AlignofExpr: self.ev_alignof,
            ast.TypeinfoExpr: self.ev_typeinfo,
            ast.AsmExpr: self.ev_asm,
            ast.Deref: self.ev_deref,
            ast.AddrOf: self.ev_addr_of,
            ast.UnsafeBlock: self.ev_unsafe,
        }
        self._stmt_dispatch = {
            ast.ExprStmt: self.ex_expr,
            ast.LetStmt: self.ex_let,
            ast.AssignStmt: self.ex_assign,
            ast.WhileStmt: self.ex_while,
            ast.LoopStmt: self.ex_loop,
            ast.ForStmt: self.ex_for,
            ast.BreakStmt: self.ex_break,
            ast.ContinueStmt: self.ex_continue,
            ast.ReturnStmt: self.ex_return,
            ast.LabelStmt: self.ex_label,
            ast.GotoStmt: self.ex_goto,
            ast.SendStmt: self.ex_send,
            ast.AssertStmt: self.ex_assert,
            ast.ComptimeStmt: self.ex_comptime,
            ast.Block: self.ex_block,
        }

    # ==================================================================
    # 公共 API
    # ==================================================================
    def run_source(self, src: str, filename: str = "<string>", *, run_main: bool = True) -> Any:
        from .parser import parse_program

        program = parse_program(src, filename)
        return self.run_program(program, run_main=run_main)

    def run_file(self, path: str, *, run_main: bool = True) -> Any:
        from .parser import parse_program

        path = _expand(path)
        with open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
        program = parse_program(src, path)
        return self.run_program(program, run_main=run_main)

    def run_program(self, program: ast.Program, *, run_main: bool = True) -> Any:
        from .checker import check_program
        check_program(program)
        self.package = program.package
        env = self.globals
        base_dir = _dirname(program.filename)
        items = list(program.uses) + list(program.items)   # use 与项一起，但 use 延迟到声明后执行
        self._process_unit(items, env, base_dir, run_main=run_main)
        return getattr(self, "_last_value", bi.UNIT)

    def run_repl_nodes(self, nodes: list[Any], env: "Env | None" = None) -> Any:
        """REPL：逐条执行 AST 节点，返回最后一个表达式值。"""
        env = env if env is not None else self.repl_env
        result: Any = bi.UNIT
        for node in nodes:
            if isinstance(node, ast.Item):
                ctx = UnitCtx()
                self.declare_item(node, env, ".", ctx)
                self._finish_ctx(ctx, env)
            elif isinstance(node, ast.Stmt):
                result = self.exec_stmt(node, env)
        self._last_value = result
        return result

    # ==================================================================
    # 编译单元处理
    # ==================================================================
    def _process_unit(self, items: list[ast.Item], env: Env, base_dir: str,
                      *, run_main: bool) -> None:
        ctx = UnitCtx()
        stmts: list[ast.Stmt] = []
        for item in items:
            if isinstance(item, ast.Item):
                self.declare_item(item, env, base_dir, ctx)
            else:
                # 精简写法：顶层语句 = 隐式入口
                stmts.append(item)
        self._finish_ctx(ctx, env)

        last: Any = bi.UNIT
        for stmt in stmts:
            last = self.exec_stmt(stmt, env)
        if stmts:
            self._last_value = last

        main = None
        if env.has_local("main"):
            main = env.vars["main"]
        else:
            try:
                main = env.lookup("main")
            except bi.DsRuntimeError:
                main = None
        if run_main and not stmts and main is not None:
            self._last_value = self.call_value(main, [], [])
        elif not stmts:
            self._last_value = bi.UNIT

    def _finish_ctx(self, ctx: UnitCtx, env: Env) -> None:
        for use in ctx.uses:
            self.exec_use(use, env)
        self.apply_impls(ctx.impls)
        for item in ctx.deferred:
            self.exec_deferred_item(item, env)

    # ==================================================================
    # 声明
    # ==================================================================
    def declare_item(self, item: ast.Item, env: Env, base_dir: str, ctx: UnitCtx) -> None:
        if isinstance(item, ast.Package):
            self.package = item.name
            return
        if isinstance(item, ast.Use):
            ctx.uses.append(item)
            return
        if isinstance(item, ast.ExportDecl):
            return
        if isinstance(item, ast.FnDecl):
            fn = bi.DsFunction(item, env, self, is_class_method=False)
            env.define(item.name, fn, mutable=False)
            return
        if isinstance(item, ast.LetItem):
            ctx.deferred.append(item)
            return
        if isinstance(item, ast.StaticDecl):
            ctx.deferred.append(item)
            return
        if isinstance(item, ast.TypeDecl):
            td = bi.TypeDef(item.name, "type", item.fields, packed=item.packed,
                            generics=item.generics, alias=item.alias, interp=self)
            self.register_type(td)
            env.define(item.name, td, mutable=False)
            return
        if isinstance(item, ast.ClassDecl):
            parent_name = bi.type_name_of(item.extends) if item.extends else None
            td = bi.TypeDef(item.name, "class", item.fields,
                            parent_expr=item.extends, generics=item.generics, interp=self)
            td.parent = self.find_type(parent_name) if parent_name else None
            self.register_type(td)
            env.define(item.name, td, mutable=False)
            for method in item.methods:
                fn = bi.DsFunction(method, env, self, is_class_method=not method.is_static)
                td.methods[method.name] = fn
            return
        if isinstance(item, ast.TraitDecl):
            td = bi.TypeDef(item.name, "trait", generics=item.generics, interp=self)
            self.register_type(td)
            env.define(item.name, td, mutable=False)
            for sig in item.methods:
                td.methods[sig.name] = bi.DsFunction(sig, env, self, is_class_method=False)
            return
        if isinstance(item, ast.ImplDecl):
            ctx.impls.append((item, env))
            return
        if isinstance(item, ast.ModDecl):
            self.load_module(item, env, base_dir)
            return
        if isinstance(item, ast.ExternDecl):
            if item.members:
                for member in item.members:
                    env.define(member.name, self._extern_stub(member.name), mutable=False)
            elif item.name:
                env.define(item.name, self._extern_stub(item.name), mutable=False)
            return
        if isinstance(item, ast.MacroDecl):
            env.define(item.name, bi.Macro(item, env, self), mutable=False)
            return
        if isinstance(item, ast.AttrDecl):
            env.define(f"@{item.name}", bi.NativeFunction(f"attr {item.name}", lambda a, k: bi.UNIT),
                       mutable=False)
            return
        if isinstance(item, ast.SectionBlock):
            for sub in item.items:
                self.declare_item(sub, env, base_dir, ctx)
            return
        raise bi.DsRuntimeError(f"未知的顶层声明：{type(item).__name__}")

    def _extern_stub(self, name: str) -> bi.NativeFunction:
        def stub(args, kwargs):
            raise bi.DsRuntimeError(f"extern 符号 `{name}` 未链接（参考驱动不加载外部库）")
        return bi.NativeFunction(name, stub)

    def register_type(self, td: bi.TypeDef) -> None:
        self.types[td.name] = td

    def find_type(self, name: str | None) -> bi.TypeDef | None:
        if not name:
            return None
        return self.types.get(name)

    def load_module(self, item: ast.ModDecl, env: Env, base_dir: str) -> None:
        if item.name in self.modules:
            env.define(item.name, self.modules[item.name], mutable=False)
            return
        mod = bi.Module(item.name)
        mod.interp = self
        mod_env = Env(env, f"mod {item.name}")
        mod.env = mod_env
        self.modules[item.name] = mod
        env.define(item.name, mod, mutable=False)
        if item.items is not None:
            ctx = UnitCtx()
            for sub in item.items:
                self.declare_item(sub, mod_env, base_dir, ctx)
            self._finish_ctx(ctx, mod_env)
        else:
            path = _join(base_dir, f"{item.name}.ds")
            ctx = UnitCtx()
            try:
                from .parser import parse_program

                with open(path, "r", encoding="utf-8") as fh:
                    src = fh.read()
                program = parse_program(src, path)
                for sub in list(program.uses) + list(program.items):
                    self.declare_item(sub, mod_env, _dirname(path), ctx)
                self._finish_ctx(ctx, mod_env)
            except FileNotFoundError:
                raise bi.DsRuntimeError(f"找不到外部模块文件：{path}")

    def exec_use(self, use: ast.Use, env: Env) -> None:
        target = self.resolve_path(use.parts, env)
        if use.names:
            for name in use.names:
                value = self.get_attr(target, name)
                env.define(name, value, mutable=False)
            return
        alias = use.alias or use.parts[-1]
        env.define(alias, target, mutable=False)

    def resolve_path(self, parts: list[str], env: Env) -> Any:
        if not parts:
            raise bi.DsRuntimeError("空路径")
        value = env.lookup(parts[0])
        for part in parts[1:]:
            value = self.get_attr(value, part)
        return value

    def apply_impls(self, impls: list[tuple[ast.ImplDecl, "Env"]]) -> None:
        for decl, impl_env in impls:
            name = bi.type_name_of(decl.type)
            td = self.find_type(name)
            if td is None:
                raise bi.DsRuntimeError(f"impl 的目标类型 `{name}` 未定义")
            if decl.trait:
                td.traits.append(decl.trait)
            for method in decl.methods:
                fn = bi.DsFunction(method, impl_env, self, is_class_method=False, owner_type=td)
                td.methods[method.name] = fn

    def exec_deferred_item(self, item: ast.Item, env: Env) -> None:
        if isinstance(item, ast.LetItem):
            value = self.eval_expr(item.value, env) if item.value is not None else bi.UNIT
            env.define(item.name, value, mutable=item.mutable)
            self.register_cleanup_if_owned(env, value)
            return
        if isinstance(item, ast.StaticDecl):
            value = self.eval_expr(item.value, env) if item.value is not None else bi.UNIT
            env.define(item.name, value, mutable=item.mutable)
            return
        raise bi.DsRuntimeError(f"无法延迟执行的声明：{type(item).__name__}")

    def register_cleanup_if_owned(self, env: Env, value: Any) -> None:
        if isinstance(value, bi.DsInstance):
            td = value.type_def
            if td.lookup_method("drop") is not None:
                env.register_cleanup(value)

    # ==================================================================
    # 语句执行
    # ==================================================================
    def exec_block(self, block: ast.Block, parent: Env) -> Any:
        """执行块：新作用域 + 标签跳转 + 退出时确定性析构 + 结构化并发等待。"""
        if block is None:
            return bi.UNIT
        scope = Env(parent, "<block>")
        labels = {s.name: i for i, s in enumerate(block.stmts) if isinstance(s, ast.LabelStmt)}
        groups = self._task_groups()
        group: list[bi.Task] = []
        groups.append(group)
        last_value: Any = bi.UNIT
        pc = 0
        try:
            while pc < len(block.stmts):
                stmt = block.stmts[pc]
                try:
                    last_value = self.exec_stmt(stmt, scope)
                except GotoSignal as jump:
                    if jump.name in labels:
                        pc = labels[jump.name]
                        continue
                    raise  # 交给外层块（标签可能在外层）
                pc += 1
        finally:
            groups.pop()
            self._join_group(group)
            scope.run_cleanups(self)
        return last_value

    def _task_groups(self) -> list[list[bi.Task]]:
        if not hasattr(self._tls, "groups"):
            self._tls.groups = []
        return self._tls.groups

    def _join_group(self, group: list[bi.Task]) -> None:
        first_panic: bi.DsPanic | None = None
        for task in group:
            try:
                task.wait()
            except Exception:
                pass
            if task.error is not None and first_panic is None:
                if isinstance(task.error, bi.DsPanic):
                    first_panic = task.error
                else:
                    first_panic = bi.DsPanic(bi.DsErrorValue(str(task.error)))
        if first_panic is not None:
            raise first_panic

    def exec_stmt(self, stmt: ast.Stmt, env: Env) -> Any:
        handler = self._stmt_dispatch.get(type(stmt))
        if handler is None:
            raise bi.DsRuntimeError(f"未知语句：{type(stmt).__name__}")
        return handler(stmt, env)

    def ex_expr(self, stmt: ast.ExprStmt, env: Env) -> Any:
        return self.eval_expr(stmt.expr, env)

    def ex_block(self, stmt: ast.Block, env: Env) -> Any:
        return self.exec_block(stmt, env)

    def ex_let(self, stmt: ast.LetStmt, env: Env) -> Any:
        value = self.eval_expr(stmt.value, env) if stmt.value is not None else bi.UNIT
        if stmt.pattern is not None:
            self.bind_pattern(stmt.pattern, value, env, mutable=stmt.mutable)
        else:
            env.define(stmt.name, value, mutable=stmt.mutable)
        self.register_cleanup_if_owned(env, value)
        return bi.UNIT

    def ex_assign(self, stmt: ast.AssignStmt, env: Env) -> Any:
        op = getattr(stmt, "op", "=")
        if op == "=":
            value = self.eval_expr(stmt.value, env)
            self.assign_place(stmt.target, value, env, define_if_missing=True)
        else:
            current = self.eval_expr(stmt.target, env)
            rhs = self.eval_expr(stmt.value, env)
            value = self.binop(op[:-1], current, rhs)
            self.assign_place(stmt.target, value, env)
        return bi.UNIT

    def ex_while(self, stmt: ast.WhileStmt, env: Env) -> Any:
        while self.require_bool(self.eval_expr(stmt.cond, env), "while 条件"):
            try:
                self.exec_block(stmt.body, env)
            except BreakSignal:
                break
            except ContinueSignal:
                continue
        return bi.UNIT

    def ex_loop(self, stmt: ast.LoopStmt, env: Env) -> Any:
        while True:
            try:
                self.exec_block(stmt.body, env)
            except BreakSignal as brk:
                return brk.value
            except ContinueSignal:
                continue

    def ex_for(self, stmt: ast.ForStmt, env: Env) -> Any:
        iterable = self.eval_expr(stmt.iterable, env)
        items = self.iter_values(iterable)
        for item in items:
            scope = Env(env, "<for>")
            if stmt.pattern is not None:
                self.bind_pattern(stmt.pattern, item, scope)
            try:
                self.exec_block(stmt.body, scope)
            except BreakSignal:
                break
            except ContinueSignal:
                continue
        return bi.UNIT

    def iter_values(self, value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            return list(value.keys())
        if isinstance(value, str):
            return list(value)
        if isinstance(value, bytes):
            return list(value)
        if isinstance(value, bi.Chan):
            out: list[Any] = []
            while True:
                got = value.recv()
                if got.is_none:
                    break
                out.append(got.value)
            return out
        raise bi.DsRuntimeError(f"值不可迭代：{value!r}")

    def ex_break(self, stmt: ast.BreakStmt, env: Env) -> Any:
        value = self.eval_expr(stmt.value, env) if stmt.value is not None else bi.UNIT
        raise BreakSignal(value)

    def ex_continue(self, stmt: ast.ContinueStmt, env: Env) -> Any:
        raise ContinueSignal()

    def ex_return(self, stmt: ast.ReturnStmt, env: Env) -> Any:
        value = self.eval_expr(stmt.value, env) if stmt.value is not None else bi.UNIT
        raise ReturnSignal(value)

    def ex_label(self, stmt: ast.LabelStmt, env: Env) -> Any:
        return bi.UNIT

    def ex_goto(self, stmt: ast.GotoStmt, env: Env) -> Any:
        raise GotoSignal(stmt.name)

    def ex_send(self, stmt: ast.SendStmt, env: Env) -> Any:
        ch = self.eval_expr(stmt.ch, env)
        value = self.eval_expr(stmt.value, env)
        if not isinstance(ch, bi.Chan):
            raise bi.DsRuntimeError("send 的目标不是 chan")
        return ch.send(value)

    def ex_assert(self, stmt: ast.AssertStmt, env: Env) -> Any:
        cond = self.eval_expr(stmt.cond, env)
        if not self.require_bool(cond, "assert 条件"):
            msg = self.eval_expr(stmt.msg, env) if stmt.msg is not None else "assertion failed"
            raise bi.DsPanic(bi.DsErrorValue(f"assert failed: {bi.to_str(msg)}" if stmt.msg else "assertion failed"))
        return bi.UNIT

    def ex_comptime(self, stmt: ast.ComptimeStmt, env: Env) -> Any:
        return self.eval_expr(stmt.inner, env)

    # ==================================================================
    # 表达式求值
    # ==================================================================
    def eval_expr(self, expr: Any, env: Env) -> Any:
        if expr is None:
            return bi.UNIT
        handler = self._expr_dispatch.get(type(expr))
        if handler is None:
            raise bi.DsRuntimeError(f"未知表达式：{type(expr).__name__}")
        return handler(expr, env)

    def ev_lit(self, expr: ast.Lit, env: Env) -> Any:
        return expr.value

    def ev_fstring(self, expr: ast.FString, env: Env) -> Any:
        out: list[str] = []
        for part in expr.parts:
            if isinstance(part, str):
                out.append(part)
            else:
                out.append(bi.to_str(self.eval_expr(part, env)))
        return "".join(out)

    def ev_array(self, expr: ast.ArrayLit, env: Env) -> Any:
        return [self.eval_expr(item, env) for item in expr.items]

    def ev_map(self, expr: ast.MapLit, env: Env) -> Any:
        out: dict[Any, Any] = {}
        for key, value in expr.pairs:
            out[self.eval_expr(key, env)] = self.eval_expr(value, env)
        return out

    def ev_var(self, expr: ast.Var, env: Env) -> Any:
        name = expr.name
        if name == "_":
            raise bi.DsRuntimeError("`_` 不能在表达式中读取")
        if name == "recover":
            stack = getattr(self._tls, "recover", None)
            if not stack:
                raise bi.DsRuntimeError("`recover` 只能在 catch panic 块内使用")
            return stack[-1]
        return env.lookup(name)

    def ev_path(self, expr: ast.Path, env: Env) -> Any:
        if not expr.parts:
            raise bi.DsRuntimeError("空路径")
        value = self.ev_var(ast.Var(expr.parts[0]), env)
        for part in expr.parts[1:]:
            value = self.get_attr(value, part)
        return value

    def ev_attr(self, expr: ast.AttrExpr, env: Env) -> Any:
        obj = self.eval_expr(expr.obj, env)
        return self.get_attr(obj, expr.name)

    def ev_index(self, expr: ast.Index, env: Env) -> Any:
        obj = self.eval_expr(expr.obj, env)
        idx = self.eval_expr(expr.index, env)
        if isinstance(obj, (list, str, bytes)):
            return obj[int(idx)]
        if isinstance(obj, dict):
            return obj[idx]
        raise bi.DsRuntimeError(f"值不可索引：{obj!r}")

    def ev_slice(self, expr: ast.SliceExpr, env: Env) -> Any:
        obj = self.eval_expr(expr.obj, env)
        lo = self.eval_expr(expr.lo, env) if expr.lo is not None else None
        hi = self.eval_expr(expr.hi, env) if expr.hi is not None else None
        lo = int(lo) if lo is not None else None
        hi = int(hi) if hi is not None else None
        if isinstance(obj, (list, str, bytes)):
            return obj[lo:hi]
        raise bi.DsRuntimeError(f"值不可切片：{obj!r}")

    def ev_call(self, expr: ast.Call, env: Env) -> Any:
        callee = self.eval_expr(expr.fn, env)
        if isinstance(callee, bi.Macro):
            return self.expand_macro(callee, expr, env)
        args = [self.eval_expr(a, env) for a in expr.args]
        kwargs = [(name, self.eval_expr(value, env)) for name, value in expr.kwargs]
        return self.call_value(callee, args, kwargs)

    def ev_unary(self, expr: ast.Unary, env: Env) -> Any:
        op = expr.op
        if op == "&":
            return self.ev_addr_of(ast.AddrOf(expr=expr.expr, mutable=False), env)
        if op == "*":
            return self.ev_deref(ast.Deref(expr=expr.expr), env)
        value = self.eval_expr(expr.expr, env)
        if op == "-":
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return -value
            raise bi.DsRuntimeError("一元 `-` 需要数值")
        if op == "!":
            return not self.require_bool(value, "`!` 运算")
        if op == "~":
            if isinstance(value, int) and not isinstance(value, bool):
                return ~value
            raise bi.DsRuntimeError("`~` 需要整数")
        raise bi.DsRuntimeError(f"未知一元运算符 {op}")

    def ev_binary(self, expr: ast.Binary, env: Env) -> Any:
        op = expr.op
        if op == "&&":
            left = self.require_bool(self.eval_expr(expr.left, env), "`&&` 左操作数")
            return left and self.require_bool(self.eval_expr(expr.right, env), "`&&` 右操作数")
        if op == "||":
            left = self.require_bool(self.eval_expr(expr.left, env), "`||` 左操作数")
            return left or self.require_bool(self.eval_expr(expr.right, env), "`||` 右操作数")
        if op == "|>":
            return self.eval_pipe(expr, env)
        left = self.eval_expr(expr.left, env)
        right = self.eval_expr(expr.right, env)
        return self.binop(op, left, right)

    def eval_pipe(self, expr: ast.Binary, env: Env) -> Any:
        value = self.eval_expr(expr.left, env)
        if isinstance(expr.right, ast.Call):
            callee = self.eval_expr(expr.right.fn, env)
            args = [self.eval_expr(a, env) for a in expr.right.args]
            kwargs = [(n, self.eval_expr(v, env)) for n, v in expr.right.kwargs]
            return self.call_value(callee, [value] + args, kwargs)
        callee = self.eval_expr(expr.right, env)
        return self.call_value(callee, [value], [])

    def binop(self, op: str, left: Any, right: Any) -> Any:
        if op == "+":
            if isinstance(left, bool) or isinstance(right, bool):
                raise bi.DsRuntimeError("`+` 不支持 bool")
            if isinstance(left, str) and isinstance(right, str):
                return left + right
            if isinstance(left, list) and isinstance(right, list):
                return left + right
            if isinstance(left, (int, float)) and isinstance(right, type(left)):
                return left + right
            if isinstance(left, bi.Ptr) and isinstance(right, int):
                return left.shift(right)
            if isinstance(left, int) and isinstance(right, bi.Ptr):
                return right.shift(left)
            raise self._bin_err("+", left, right)
        if op == "-":
            if isinstance(left, (int, float)) and isinstance(right, type(left)):
                return left - right
            if isinstance(left, bi.Ptr) and isinstance(right, int):
                return left.shift(-right)
            raise self._bin_err("-", left, right)
        if op == "*":
            if isinstance(left, (int, float)) and isinstance(right, type(left)):
                return left * right
            raise self._bin_err("*", left, right)
        if op == "/":
            if isinstance(left, (int, float)) and isinstance(right, type(left)):
                if right == 0:
                    raise bi.DsPanic(bi.DsErrorValue("division by zero"))
                if isinstance(left, int):
                    return _trunc_div(left, right)
                return left / right
            raise self._bin_err("/", left, right)
        if op == "%":
            if isinstance(left, int) and isinstance(right, int):
                if right == 0:
                    raise bi.DsPanic(bi.DsErrorValue("division by zero"))
                return left - _trunc_div(left, right) * right
            raise self._bin_err("%", left, right)
        if op in ("<<", ">>"):
            if isinstance(left, int) and isinstance(right, int):
                if right < 0 or right >= 64:
                    raise bi.DsPanic(bi.DsErrorValue("shift amount out of range"))
                return left << right if op == "<<" else left >> right
            raise self._bin_err(op, left, right)
        if op == "&":
            if isinstance(left, int) and isinstance(right, int):
                return left & right
            raise self._bin_err("&", left, right)
        if op == "|":
            if isinstance(left, int) and isinstance(right, int):
                return left | right
            raise self._bin_err("|", left, right)
        if op == "^":
            if isinstance(left, int) and isinstance(right, int):
                return left ^ right
            raise self._bin_err("^", left, right)
        if op == "..":
            if isinstance(left, int) and isinstance(right, int):
                return list(range(left, right))
            raise bi.DsRuntimeError("`..` 需要两个整数端点")
        if op == "==":
            return self.ds_eq(left, right)
        if op == "!=":
            return not self.ds_eq(left, right)
        if op in ("<", ">", "<=", ">="):
            try:
                if op == "<":
                    return left < right
                if op == ">":
                    return left > right
                if op == "<=":
                    return left <= right
                return left >= right
            except TypeError:
                raise bi.DsRuntimeError(f"不可比较：{left!r} {op} {right!r}")
        raise bi.DsRuntimeError(f"未知二元运算符 {op}")

    def _bin_err(self, op: str, left: Any, right: Any) -> bi.DsRuntimeError:
        return bi.DsRuntimeError(f"`{op}` 类型不匹配：{type(left).__name__} 与 {type(right).__name__}")

    def ds_eq(self, a: Any, b: Any) -> bool:
        if isinstance(a, bi.Opt) and isinstance(b, bi.Opt):
            if a.is_none or b.is_none:
                return a.is_none and b.is_none
            return self.ds_eq(a.value, b.value)
        if isinstance(a, bi.Res) and isinstance(b, bi.Res):
            return a.ok == b.ok and self.ds_eq(a.value, b.value)
        if isinstance(a, bi.DsInstance) and isinstance(b, bi.DsInstance):
            return a.type_def.name == b.type_def.name and all(
                self.ds_eq(a.fields.get(k), b.fields.get(k)) for k in set(a.fields) | set(b.fields)
            )
        return bool(a == b) if type(a) is type(b) else False

    def ev_cast(self, expr: ast.Cast, env: Env) -> Any:
        value = self.eval_expr(expr.expr, env)
        return self.cast_value(value, expr.type)

    def ev_is(self, expr: ast.IsTest, env: Env) -> Any:
        value = self.eval_expr(expr.expr, env)
        target = expr.target
        if isinstance(target, ast.Pattern):
            scope = Env(env, "<is>")
            if self.match_pattern(target, value, scope):
                self._tls.is_bindings = dict(scope.vars)
                return True
            self._tls.is_bindings = {}
            return False
        return self.type_test(value, target)

    def ev_in(self, expr: ast.InTest, env: Env) -> Any:
        item = self.eval_expr(expr.item, env)
        container = self.eval_expr(expr.container, env)
        if isinstance(container, dict):
            return item in container
        if isinstance(container, (list, str, bytes)):
            for candidate in container:
                if self.ds_eq(item, candidate):
                    return True
            return False
        raise bi.DsRuntimeError(f"`in` 右侧不可迭代：{container!r}")

    def ev_block_expr(self, expr: ast.BlockExpr, env: Env) -> Any:
        return self.exec_block(expr.block, env)

    def ev_if(self, expr: ast.IfExpr, env: Env) -> Any:
        cond = self.require_bool(self.eval_expr(expr.cond, env), "if 条件")
        bindings = getattr(self._tls, "is_bindings", None)
        self._tls.is_bindings = {}
        if cond:
            scope = env
            if bindings:
                scope = Env(env, "<if>")
                for name, value in bindings.items():
                    scope.define(name, value)
            return self.exec_block(expr.then_block, scope)
        if expr.else_ is None:
            return bi.UNIT
        if isinstance(expr.else_, ast.Block):
            return self.exec_block(expr.else_, env)
        return self.eval_expr(expr.else_, env)

    def ev_match(self, expr: ast.MatchExpr, env: Env) -> Any:
        subject = self.eval_expr(expr.subject, env)
        for arm in expr.arms:
            scope = Env(env, "<match>")
            if not self.match_pattern(arm.pattern, subject, scope):
                continue
            if arm.guard is not None:
                if not self.require_bool(self.eval_expr(arm.guard, scope), "when 守卫"):
                    continue
            body = arm.body
            if isinstance(body, ast.Block):
                return self.exec_block(body, scope)
            if isinstance(body, ast.Stmt):
                return self.exec_stmt(body, scope)
            return self.eval_expr(body, scope)
        raise bi.DsRuntimeError("match 未穷尽：没有分支匹配")

    def ev_fn_lit(self, expr: ast.FnLit, env: Env) -> Any:
        decl = ast.FnDecl(name="<anon>", params=expr.params, ret=expr.ret, body=expr.body)
        return bi.DsFunction(decl, env, self)

    def ev_try_expr(self, expr: ast.TryExpr, env: Env) -> Any:
        value = self.eval_expr(expr.expr, env)
        if isinstance(value, bi.Res):
            if value.ok:
                return value.value
            raise bi.TryPropagate(value.value)
        raise bi.DsRuntimeError("`try` 的操作数必须是 res")

    def ev_try_catch(self, expr: ast.TryCatch, env: Env) -> Any:
        try:
            return self.exec_block(expr.block, env)
        except bi.TryPropagate as prop:
            for arm in expr.catches:
                if arm.kind == "error":
                    scope = Env(env, "<catch>")
                    if arm.name:
                        scope.define(arm.name, prop.err_value)
                    return self.exec_block(arm.block, scope)
            raise
        except bi.DsPanic as panic:
            for arm in expr.catches:
                if arm.kind == "panic":
                    scope = Env(env, "<catch panic>")
                    if arm.name:
                        scope.define(arm.name, panic.value)
                    stack = getattr(self._tls, "recover", None)
                    if stack is None:
                        stack = self._tls.recover = []
                    stack.append(panic.value)
                    try:
                        return self.exec_block(arm.block, scope)
                    finally:
                        stack.pop()
            raise

    def ev_recv(self, expr: ast.RecvExpr, env: Env) -> Any:
        ch = self.eval_expr(expr.ch, env)
        if not isinstance(ch, bi.Chan):
            raise bi.DsRuntimeError("`recv` 的操作数必须是 chan")
        return ch.recv()

    def ev_wait(self, expr: ast.WaitExpr, env: Env) -> Any:
        handle = self.eval_expr(expr.handle, env)
        if isinstance(handle, bi.Task):
            return handle.wait()
        if isinstance(handle, list):
            return [h.wait() if isinstance(h, bi.Task) else h for h in handle]
        raise bi.DsRuntimeError("`wait` 需要 task/thread/任务组")

    def ev_spawn(self, expr: ast.SpawnExpr, env: Env) -> Any:
        body = expr.body
        groups = self._task_groups()

        def runner():
            if isinstance(body, ast.Block):
                return self.exec_block(body, env)
            return self.eval_expr(body, env)

        task = bi.Task(self, "spawn").start(runner)
        if groups:
            groups[-1].append(task)
        return task

    def ev_go(self, expr: ast.GoExpr, env: Env) -> Any:
        call = expr.call
        if isinstance(call, ast.Call):
            callee = self.eval_expr(call.fn, env)
            args = [self.eval_expr(a, env) for a in call.args]
            kwargs = [(n, self.eval_expr(v, env)) for n, v in call.kwargs]
            task = bi.Task(self, "go").start(
                lambda: self.call_value(callee, args, kwargs), detached=True)
            return task
        task = bi.Task(self, "go").start(lambda: self.eval_expr(call, env), detached=True)
        return task

    def ev_thread(self, expr: ast.ThreadExpr, env: Env) -> Any:
        target = self.eval_expr(expr.fn, env)
        handle = bi.ThreadHandle(self, "thread")
        return handle.start(lambda: self.call_value(target, [], []), detached=False)

    def ev_new(self, expr: ast.NewExpr, env: Env) -> Any:
        td = self.lookup_type(expr.type_name, env)
        args = [self.eval_expr(a, env) for a in expr.args]
        kwargs = [(n, self.eval_expr(v, env)) for n, v in expr.kwargs]
        return self.construct(td, args, kwargs, use_ctor=True)

    def ev_comptime(self, expr: ast.ComptimeExpr, env: Env) -> Any:
        return self.eval_expr(expr.inner, env)

    def ev_sizeof(self, expr: ast.SizeofExpr, env: Env) -> Any:
        target = expr.target
        if isinstance(target, ast.TypeExpr):
            return self.type_size(target)
        return self.value_size(self.eval_expr(target, env))

    def ev_alignof(self, expr: ast.AlignofExpr, env: Env) -> Any:
        target = expr.target
        if isinstance(target, ast.TypeExpr):
            return self.type_align(target)
        return self.value_size(self.eval_expr(target, env))

    def ev_typeinfo(self, expr: ast.TypeinfoExpr, env: Env) -> Any:
        target = expr.target
        if isinstance(target, ast.TypeExpr):
            return self.type_info(target)
        value = self.eval_expr(target, env)
        if isinstance(value, bi.DsInstance):
            return self.type_info(ast.TypeName(value.type_def.name))
        return self.type_info(ast.TypeName(self.value_type_name(value)))

    def ev_asm(self, expr: ast.AsmExpr, env: Env) -> Any:
        return bi.UNIT

    def ev_deref(self, expr: ast.Deref, env: Env) -> Any:
        value = self.eval_expr(expr.expr, env)
        if isinstance(value, bi.Ptr):
            return value.read()
        if isinstance(value, bi.RefBox):
            return value.getter()
        if isinstance(value, bi.RefCount):
            return value.value
        if isinstance(value, bi.GcBox):
            return value.value
        raise bi.DsRuntimeError(f"`*` 不能解引用 {type(value).__name__}")

    def ev_addr_of(self, expr: ast.AddrOf, env: Env) -> Any:
        target = expr.expr
        mutable = expr.mutable
        if isinstance(target, ast.Var):
            name = target.name
            env.lookup(name)
            return bi.RefBox(lambda: env.lookup(name),
                             (lambda v: env.assign(name, v)) if mutable else None, mutable)
        if isinstance(target, ast.AttrExpr):
            obj = self.eval_expr(target.obj, env)
            name = target.name
            return bi.RefBox(lambda: self.get_attr(obj, name),
                             (lambda v: setattr(obj, name, v)) if mutable else None, mutable)
        if isinstance(target, ast.Index):
            obj = self.eval_expr(target.obj, env)
            idx = self.eval_expr(target.index, env)
            if isinstance(obj, list):
                return bi.RefBox(lambda: obj[int(idx)],
                                 (lambda v: obj.__setitem__(int(idx), v)) if mutable else None, mutable)
            raise bi.DsRuntimeError("只有数组元素可取可变引用")
        if isinstance(target, ast.Deref):
            return self.eval_expr(target.expr, env)
        raise bi.DsRuntimeError("无法取引用的表达式")

    def ev_unsafe(self, expr: ast.UnsafeBlock, env: Env) -> Any:
        return self.exec_block(expr.block, env)

    # ==================================================================
    # 调用
    # ==================================================================
    def call_value(self, callee: Any, args: list[Any], kwargs: list[tuple[str, Any]]) -> Any:
        if isinstance(callee, bi.NativeFunction):
            return callee.fn(args, kwargs)
        if isinstance(callee, bi.BoundMethod):
            return self.call_function(callee.func, args, kwargs, receiver=callee.receiver)
        if isinstance(callee, bi.DsFunction):
            return self.call_function(callee, args, kwargs)
        if isinstance(callee, bi.TypeDef):
            return self.construct(callee, args, kwargs)
        if isinstance(callee, bi.Macro):
            raise bi.DsRuntimeError("宏只能在调用表达式处展开")
        if isinstance(callee, bi.Ptr):
            raise bi.DsRuntimeError("指针不可调用")
        raise bi.DsRuntimeError(f"不可调用：{callee!r}")

    def call_function(self, fn: bi.DsFunction, args: list[Any],
                      kwargs: list[tuple[str, Any]], receiver: Any = None) -> Any:
        decl = fn.decl
        self.depth += 1
        if self.depth > self.max_depth:
            self.depth -= 1
            raise bi.DsRuntimeError("调用深度超过上限（可能是无限递归）")
        scope = Env(fn.closure, f"fn {decl.name}")
        try:
            self.bind_params(fn, scope, args, kwargs, receiver)
            body = decl.body
            if body is None:
                raise bi.DsRuntimeError(f"`{decl.name}` 没有函数体（extern/trait 签名）")
            if isinstance(body, ast.Block):
                result = self.exec_block(body, scope)
            else:
                result = self.eval_expr(body, scope)
        except ReturnSignal as ret:
            result = ret.value
        except bi.TryPropagate as prop:
            result = bi.err(prop.err_value)
        except GotoSignal as jump:
            raise bi.DsRuntimeError(f"goto 目标标签 `{jump.name}` 不存在")
        except (BreakSignal, ContinueSignal):
            raise bi.DsRuntimeError("break/continue 不能跨函数")
        finally:
            scope.run_cleanups(self)
            self.depth -= 1
        return result

    def bind_params(self, fn: bi.DsFunction, scope: Env, args: list[Any],
                    kwargs: list[tuple[str, Any]], receiver: Any) -> None:
        decl = fn.decl
        params = list(decl.params)
        if receiver is not None:
            scope.define("self", receiver)
            parent = None
            if isinstance(receiver, bi.DsInstance):
                parent = receiver.type_def.resolve_parent()
            scope.define("super", bi.SuperProxy(receiver, parent))
            if fn.is_class_method and params and params[0].name == "self":
                params = params[1:]
        if params and params[0].name == "self" and receiver is not None:
            params = params[1:]
        kwargs_map = dict(kwargs)
        for i, param in enumerate(params):
            if param.name in kwargs_map:
                value = kwargs_map.pop(param.name)
            elif i < len(args):
                value = args[i]
            elif param.default is not None:
                value = self.eval_expr(param.default, scope)
            else:
                raise bi.DsRuntimeError(f"`{decl.name}` 缺少实参 `{param.name}`")
            scope.define(param.name, value)
        extra = args[len(params):]
        if extra:
            raise bi.DsRuntimeError(f"`{decl.name}` 实参过多（{len(args)}）")
        if kwargs_map:
            raise bi.DsRuntimeError(f"`{decl.name}` 未知命名实参：{', '.join(kwargs_map)}")

    # ==================================================================
    # 构造与属性
    # ==================================================================
    def lookup_type(self, name: str, env: Env) -> bi.TypeDef:
        td = self.find_type(name)
        if td is not None:
            return td
        try:
            value = env.lookup(name)
        except bi.DsRuntimeError:
            raise bi.DsRuntimeError(f"未知类型 `{name}`")
        if isinstance(value, bi.TypeDef):
            return value
        raise bi.DsRuntimeError(f"`{name}` 不是类型")

    def all_fields(self, td: bi.TypeDef, seen: set[str] | None = None) -> list[ast.FieldDecl]:
        seen = seen or set()
        out: list[ast.FieldDecl] = []
        parent = td.resolve_parent()
        if parent is not None and parent.name not in seen:
            seen.add(parent.name)
            out.extend(self.all_fields(parent, seen))
        out.extend(td.fields)
        return out

    def construct(self, td: bi.TypeDef, args: list[Any], kwargs: list[tuple[str, Any]],
                  use_ctor: bool = False) -> Any:
        if td.kind == "trait":
            raise bi.DsRuntimeError(f"trait `{td.name}` 不能实例化")
        if td.alias is not None:
            return self.construct_named(td.alias, args, kwargs)
        fields = self.all_fields(td)
        inst = bi.DsInstance(td, {f.name: None for f in fields})
        ctor = td.methods.get("new")
        if ctor is not None and (use_ctor or not fields):
            if td.kind == "class":
                self.call_function(ctor, args, kwargs, receiver=inst)
                return inst
            result = self.call_function(ctor, args, kwargs)
            if isinstance(result, bi.DsInstance):
                return result
            if result is not bi.UNIT:
                return result
            return inst
        # 默认值构造：位置参数按字段顺序，命名参数按字段名
        kwargs_map = dict(kwargs)
        for i, fld in enumerate(fields):
            if fld.name in kwargs_map:
                inst.fields[fld.name] = kwargs_map.pop(fld.name)
            elif i < len(args):
                inst.fields[fld.name] = args[i]
            elif fld.default is not None:
                inst.fields[fld.name] = self.eval_expr(fld.default, self.globals)
        if kwargs_map:
            raise bi.DsRuntimeError(f"`{td.name}` 未知字段：{', '.join(kwargs_map)}")
        if len(args) > len(fields):
            raise bi.DsRuntimeError(f"`{td.name}` 字段过多")
        return inst

    def construct_named(self, type_expr: ast.TypeExpr, args: list[Any],
                        kwargs: list[tuple[str, Any]]) -> Any:
        name = bi.type_name_of(type_expr)
        td = self.find_type(name) if name else None
        if td is None:
            raise bi.DsRuntimeError(f"未知类型 `{name}`")
        return self.construct(td, args, kwargs)

    def get_attr(self, obj: Any, name: str) -> Any:
        if isinstance(obj, bi.DsInstance):
            if name in obj.fields:
                return obj.fields[name]
            method = self.find_method(obj.type_def, name)
            if method is not None:
                return bi.BoundMethod(obj, method)
            raise bi.DsRuntimeError(f"`{obj.type_def.name}` 没有字段或方法 `{name}`")
        if isinstance(obj, bi.TypeDef):
            method = obj.methods.get(name)
            if method is not None:
                return method
            raise bi.DsRuntimeError(f"类型 `{obj.name}` 没有关联函数 `{name}`")
        if isinstance(obj, bi.Module):
            return obj.get(name)
        if isinstance(obj, bi.SuperProxy):
            if name == "init":
                return bi.NativeFunction(
                    "super.init",
                    lambda a, k: self.call_super_ctor(obj, a, k))
            parent = obj.parent
            if parent is None:
                raise bi.DsRuntimeError("`super` 没有父类")
            method = self.find_method(parent, name)
            if method is None:
                raise bi.DsRuntimeError(f"父类没有方法 `{name}`")
            return bi.BoundMethod(obj.instance, method)
        if isinstance(obj, bi.RefCount):
            if name == "clone":
                return bi.NativeFunction("clone", lambda a, k: obj.clone())
            if name == "get":
                return bi.NativeFunction("get", lambda a, k: obj.value)
        if isinstance(obj, bi.GcBox):
            if name == "get":
                return bi.NativeFunction("get", lambda a, k: obj.value)
        if isinstance(obj, (bi.RefCount, bi.GcBox)):
            return self.get_attr(obj.value, name)
        if isinstance(obj, bi.TraitObject):
            return self.get_attr(obj.value, name)
        if isinstance(obj, bi.Ptr):
            if name == "addr":
                return obj.addr if obj.addr is not None else obj.offset
            raise bi.DsRuntimeError(f"ptr 没有属性 `{name}`")
        if isinstance(obj, bi.DsErrorValue):
            if name in ("message", "kind"):
                return getattr(obj, name)
            raise bi.DsRuntimeError(f"error 没有属性 `{name}`")
        if isinstance(obj, bi.TypeInfo):
            if name in ("name", "size", "align", "fields", "traits", "kind"):
                return getattr(obj, name)
            raise bi.DsRuntimeError(f"TypeInfo 没有属性 `{name}`")
        if isinstance(obj, bi.Chan):
            if name == "close":
                return bi.NativeFunction("close", lambda a, k: obj.close())
            if name == "cap":
                return obj.cap
            raise bi.DsRuntimeError(f"chan 没有属性 `{name}`")
        if isinstance(obj, bi.DsMutex):
            if name == "lock":
                return bi.NativeFunction("lock", lambda a, k: obj.lock())
            if name == "value":
                return obj.value
            raise bi.DsRuntimeError(f"mutex 没有属性 `{name}`")
        if isinstance(obj, bi.MutexGuard):
            if name == "unlock":
                return bi.NativeFunction("unlock", lambda a, k: obj.unlock())
            raise bi.DsRuntimeError(f"mutex guard 没有属性 `{name}`")
        if isinstance(obj, (bi.Task, bi.ThreadHandle)):
            if name == "wait":
                return bi.NativeFunction("wait", lambda a, k: obj.wait())
            raise bi.DsRuntimeError(f"task 没有属性 `{name}`")
        if isinstance(obj, dict):
            if name == "len":
                return bi.NativeFunction("len", lambda a, k: len(obj))
            if name == "get":
                return bi.NativeFunction("get", lambda a, k: obj.get(a[0], a[1] if len(a) > 1 else bi.NONE))
            raise bi.DsRuntimeError(f"映射没有属性 `{name}`")
        if isinstance(obj, list):
            if name == "len":
                return bi.NativeFunction("len", lambda a, k: len(obj))
            if name == "push":
                return bi.NativeFunction("push", lambda a, k: obj.append(a[0]) or bi.UNIT)
            if name == "pop":
                return bi.NativeFunction("pop", lambda a, k: obj.pop())
            raise bi.DsRuntimeError(f"数组没有属性 `{name}`")
        if isinstance(obj, str):
            if name == "len":
                return bi.NativeFunction("len", lambda a, k: len(obj))
            raise bi.DsRuntimeError(f"str 没有属性 `{name}`")
        raise bi.DsRuntimeError(f"{type(obj).__name__} 没有属性 `{name}`")

    def find_method(self, td: bi.TypeDef, name: str) -> bi.DsFunction | None:
        method = td.lookup_method(name)
        if method is not None:
            return method
        for trait_name in td.traits:
            trait = self.find_type(trait_name)
            if trait is not None and name in trait.methods and trait.methods[name].decl.body is not None:
                return trait.methods[name]
        return None

    def call_super_ctor(self, proxy: bi.SuperProxy, args: list[Any],
                        kwargs: list[tuple[str, Any]]) -> Any:
        parent = proxy.parent
        if parent is None:
            raise bi.DsRuntimeError("`super.init` 没有父类")
        ctor = parent.methods.get("new")
        if ctor is not None:
            self.call_function(ctor, args, kwargs, receiver=proxy.instance)
        return bi.UNIT

    # ==================================================================
    # 赋值 / 析构
    # ==================================================================
    def assign_place(self, target: ast.Expr, value: Any, env: Env,
                     define_if_missing: bool = False) -> None:
        if isinstance(target, ast.Var):
            if target.name == "_":
                self.drop_value(value)
                return
            if define_if_missing and not env.has(target.name):
                env.define(target.name, value, mutable=False)
            else:
                env.assign(target.name, value)
            return
        if isinstance(target, ast.AttrExpr):
            obj = self.eval_expr(target.obj, env)
            if isinstance(obj, bi.DsInstance):
                obj.fields[target.name] = value
                return
            if isinstance(obj, bi.DsMutex):
                obj.value = value
                return
            if isinstance(obj, (bi.RefCount, bi.GcBox)):
                self.assign_place(ast.AttrExpr(obj=ast.Var("<ref>"), name=target.name), value, env)
                return
            setattr(obj, target.name, value)
            return
        if isinstance(target, ast.Index):
            obj = self.eval_expr(target.obj, env)
            idx = self.eval_expr(target.index, env)
            if isinstance(obj, list):
                obj[int(idx)] = value
            elif isinstance(obj, dict):
                obj[idx] = value
            else:
                raise bi.DsRuntimeError(f"不可索引赋值：{obj!r}")
            return
        if isinstance(target, ast.Deref):
            obj = self.eval_expr(target.expr, env)
            if isinstance(obj, bi.Ptr):
                obj.write(value)
                return
            if isinstance(obj, bi.RefBox):
                if obj.setter is None:
                    raise bi.DsRuntimeError("不可变引用不能赋值")
                obj.setter(value)
                return
            raise bi.DsRuntimeError(f"`*` 不能赋值给 {type(obj).__name__}")
        raise bi.DsRuntimeError(f"非法赋值目标：{type(target).__name__}")

    def drop_value(self, value: Any) -> None:
        if isinstance(value, bi.DsInstance):
            method = value.type_def.lookup_method("drop")
            if method is not None:
                try:
                    self.call_function(method, [], [], receiver=value)
                except bi.DsPanic:
                    raise
                except Exception:
                    pass
        elif isinstance(value, bi.RefCount):
            value.release()
        elif isinstance(value, list):
            for item in value:
                self.drop_value(item)

    # ==================================================================
    # 模式匹配
    # ==================================================================
    def bind_pattern(self, pattern: ast.Pattern, value: Any, env: Env, mutable: bool = False) -> None:
        if not self.match_pattern(pattern, value, env):
            raise bi.DsRuntimeError(
                f"模式不匹配：{value!r}（行 {getattr(pattern, 'line', 0)}）")
        if mutable and isinstance(pattern, ast.BindPat):
            env.mutable.add(pattern.name)

    def match_pattern(self, pattern: ast.Pattern, value: Any, scope: Env) -> bool:
        if pattern is None:
            return True
        if isinstance(pattern, ast.WildcardPat):
            return True
        if isinstance(pattern, ast.LitPat):
            return self.ds_eq(pattern.value, value)
        if isinstance(pattern, ast.BindPat):
            if pattern.sub is not None:
                if not self.match_pattern(pattern.sub, value, scope):
                    return False
            scope.define(pattern.name, value)
            return True
        if isinstance(pattern, ast.ArrayPat):
            if not isinstance(value, (list, tuple)):
                return False
            if len(pattern.items) != len(value):
                return False
            return all(self.match_pattern(p, v, scope) for p, v in zip(pattern.items, value))
        if isinstance(pattern, ast.MapPat):
            if not isinstance(value, dict):
                return False
            for key, sub in pattern.pairs:
                if key not in value or not self.match_pattern(sub, value[key], scope):
                    return False
            return True
        if isinstance(pattern, ast.OrPat):
            for alt in pattern.alts:
                attempt = Env(scope, "<or>")
                if self.match_pattern(alt, value, attempt):
                    for name, val in attempt.vars.items():
                        scope.define(name, val)
                    return True
            return False
        if isinstance(pattern, ast.CtorPat):
            return self.match_ctor(pattern, value, scope)
        return False

    def match_ctor(self, pattern: ast.CtorPat, value: Any, scope: Env) -> bool:
        name = pattern.name
        if name == "some":
            if isinstance(value, bi.Opt) and not value.is_none:
                return self.match_pattern(pattern.args[0], value.value, scope)
            return False
        if name == "none":
            return isinstance(value, bi.Opt) and value.is_none
        if name == "ok":
            if isinstance(value, bi.Res) and value.ok:
                return self.match_pattern(pattern.args[0], value.value, scope)
            return False
        if name == "err":
            if isinstance(value, bi.Res) and not value.ok:
                return self.match_pattern(pattern.args[0], value.value, scope)
            return False
        if isinstance(value, bi.DsInstance):
            td = value.type_def
            if td.name != name and not any(t == name for t in td.traits):
                parent = td.resolve_parent()
                if parent is None or parent.name != name:
                    return False
            fields = self.all_fields(td)
            if len(pattern.args) > len(fields):
                return False
            for sub, fld in zip(pattern.args, fields):
                if not self.match_pattern(sub, value.fields.get(fld.name), scope):
                    return False
            return True
        if isinstance(value, bi.TraitObject):
            if value.trait_name != name:
                return False
            return all(self.match_pattern(sub, bi.UNIT, scope) for sub in pattern.args) if pattern.args else True
        return False

    # ==================================================================
    # 类型相关
    # ==================================================================
    def type_test(self, value: Any, t: ast.TypeExpr) -> bool:
        if isinstance(t, ast.TypeName):
            name = t.name
            if name in bi.INT_KINDS:
                if isinstance(value, bool) or not isinstance(value, int):
                    return False
                lo, hi = bi.BUILTIN_RANGES[name]
                return lo <= value <= hi
            if name in bi.FLOAT_KINDS:
                return isinstance(value, float) and not isinstance(value, bool)
            if name == "bool":
                return isinstance(value, bool)
            if name == "str":
                return isinstance(value, str)
            if name == "bytes":
                return isinstance(value, bytes)
            if name == "unit":
                return value is bi.UNIT
            td = self.find_type(name)
            if td is not None:
                if isinstance(value, bi.DsInstance):
                    return value.type_def.is_subclass_of(td)
                if td.kind == "trait":
                    return name in (value.type_def.traits if isinstance(value, bi.DsInstance) else [])
                return False
            return False
        if isinstance(t, ast.RawType) or isinstance(t, ast.PtrType) or isinstance(t, ast.RefType):
            return isinstance(value, (bi.Ptr, bi.RefBox))
        if isinstance(t, ast.VolatileType):
            return isinstance(value, bi.Ptr)
        if isinstance(t, ast.OptType):
            return isinstance(value, bi.Opt)
        if isinstance(t, ast.ResType):
            return isinstance(value, bi.Res)
        if isinstance(t, ast.BoxType):
            if t.kind in ("rc", "arc"):
                return isinstance(value, bi.RefCount)
            if t.kind == "gc":
                return isinstance(value, bi.GcBox)
            if t.kind == "chan":
                return isinstance(value, bi.Chan)
            if t.kind == "mutex":
                return isinstance(value, bi.DsMutex)
            return isinstance(value, (bi.Task, bi.ThreadHandle))
        if isinstance(t, ast.DynType):
            inner = bi.type_name_of(t.inner)
            return isinstance(value, bi.DsInstance) and inner in value.type_def.traits
        if isinstance(t, ast.SliceType):
            return isinstance(value, (list, bytes, str))
        if isinstance(t, ast.ArrayType):
            return isinstance(value, (list, bytes, str))
        if isinstance(t, ast.FnType):
            return isinstance(value, (bi.DsFunction, bi.NativeFunction, bi.BoundMethod))
        if isinstance(t, ast.UnitType):
            return value is bi.UNIT
        return False

    def type_size(self, t: ast.TypeExpr | None) -> int:
        if t is None:
            return 0
        name = bi.type_name_of(t)
        if isinstance(t, ast.ArrayType):
            count = int(t.size) if isinstance(t.size, int) else (
                int(self.eval_expr(t.size, self.globals)) if t.size is not None else 0)
            return self.type_size(t.elem) * count
        if isinstance(t, ast.SliceType):
            return 16
        if isinstance(t, ast.PtrType) or isinstance(t, ast.RefType):
            return 8
        if isinstance(t, ast.VolatileType):
            return self.type_size(t.inner)
        if isinstance(t, ast.DynType):
            return 16
        if isinstance(t, ast.FnType):
            return 8
        if isinstance(t, ast.OptType):
            return self.type_size(t.inner)
        if isinstance(t, ast.ResType):
            return self.type_size(t.ok) + self.type_size(t.err)
        if isinstance(t, ast.RawType):
            return 8
        if isinstance(t, ast.UnitType):
            return 0
        if isinstance(t, ast.BoxType):
            return 8
        if name in bi.BUILTIN_SIZES:
            return bi.BUILTIN_SIZES[name]
        td = self.find_type(name)
        if td is not None:
            if td.alias is not None:
                return self.type_size(td.alias)
            fields = self.all_fields(td)
            if td.packed:
                return sum(self.type_size(f.type) for f in fields)
            total, align = 0, 1
            for fld in fields:
                fsize = self.type_size(fld.type)
                falign = self.type_align(fld.type)
                align = max(align, falign)
                total = _pad(total, falign) + fsize
            return _pad(total, align)
        return 0

    def type_align(self, t: ast.TypeExpr | None) -> int:
        if t is None:
            return 1
        name = bi.type_name_of(t)
        if isinstance(t, ast.ArrayType):
            return self.type_align(t.elem)
        if isinstance(t, (ast.PtrType, ast.RefType, ast.DynType, ast.FnType, ast.BoxType, ast.RawType)):
            return 8
        if isinstance(t, ast.VolatileType):
            return self.type_align(t.inner)
        if isinstance(t, ast.OptType):
            return self.type_align(t.inner)
        if isinstance(t, ast.ResType):
            return max(self.type_align(t.ok), self.type_align(t.err))
        if isinstance(t, ast.SliceType):
            return 8
        if isinstance(t, ast.UnitType):
            return 1
        if name in bi.BUILTIN_ALIGNS:
            return bi.BUILTIN_ALIGNS[name]
        td = self.find_type(name)
        if td is not None:
            if td.alias is not None:
                return self.type_align(td.alias)
            if td.packed:
                return 1
            fields = self.all_fields(td)
            return max([1] + [self.type_align(f.type) for f in fields])
        return 1

    def value_size(self, value: Any) -> int:
        if isinstance(value, bool):
            return 1
        if isinstance(value, int):
            return 8
        if isinstance(value, float):
            return 8
        if isinstance(value, (str, bytes)):
            return 16
        if isinstance(value, (list, dict)):
            return 16
        if isinstance(value, bi.DsInstance):
            return self.type_size(ast.TypeName(value.type_def.name))
        if isinstance(value, (bi.Ptr, bi.RefBox, bi.RefCount, bi.GcBox, bi.Task, bi.ThreadHandle,
                             bi.Chan, bi.DsMutex)):
            return 8
        if isinstance(value, bi.Opt):
            return 16
        if isinstance(value, bi.Res):
            return 24
        return 8

    def value_type_name(self, value: Any) -> str:
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int):
            return "i32"
        if isinstance(value, float):
            return "f64"
        if isinstance(value, str):
            return "str"
        if isinstance(value, bytes):
            return "bytes"
        if isinstance(value, bi.DsInstance):
            return value.type_def.name
        return "unit"

    def type_info(self, t: ast.TypeExpr) -> bi.TypeInfo:
        name = bi.type_name_of(t) or "?"
        td = self.find_type(name)
        fields: list[dict] = []
        traits: list[str] = []
        kind = "type"
        if td is not None:
            kind = td.kind
            for fld in self.all_fields(td):
                fields.append({
                    "name": fld.name,
                    "type": bi.type_name_of(fld.type) or "?",
                    "size": self.type_size(fld.type),
                    "align": self.type_align(fld.type),
                })
            traits = list(td.traits)
        return bi.TypeInfo(name, self.type_size(t), self.type_align(t), fields, traits, kind)

    def cast_value(self, value: Any, t: ast.TypeExpr) -> Any:
        if isinstance(t, ast.VolatileType):
            inner = t.inner
            result = self.cast_value(value, inner)
            if isinstance(result, bi.Ptr):
                result.volatile = True
            return result
        if isinstance(t, ast.DynType):
            trait_name = bi.type_name_of(t.inner) or "Trait"
            if isinstance(value, bi.TraitObject):
                return value
            return value
        name = bi.type_name_of(t)
        if isinstance(t, ast.TypeName) and name in bi.INT_KINDS:
            lo, hi = bi.BUILTIN_RANGES[name]
            ival = int(value) if not isinstance(value, bool) else int(value)
            ival &= (1 << (8 * bi.BUILTIN_SIZES[name])) - 1
            if name.startswith("i") and ival >= (1 << (8 * bi.BUILTIN_SIZES[name] - 1)):
                ival -= 1 << (8 * bi.BUILTIN_SIZES[name])
            return ival
        if isinstance(t, ast.TypeName) and name in bi.FLOAT_KINDS:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
            raise bi.DsRuntimeError(f"不能把 {type(value).__name__} 转成 {name}")
        if isinstance(t, ast.TypeName) and name == "bool":
            return bool(value)
        if isinstance(t, (ast.PtrType, ast.RawType)):
            if isinstance(value, bi.Ptr):
                if isinstance(t, ast.PtrType):
                    inner = bi.type_name_of(t.inner) or "u8"
                    value.elem_size = max(1, self.type_size(t.inner))
                    value.type_name = inner
                    value.mutable = not (isinstance(t, ast.PtrType) and t.mutable is False)
                return value
            if isinstance(value, int) and not isinstance(value, bool):
                inner = bi.type_name_of(t.inner) if isinstance(t, ast.PtrType) else "u8"
                return bi.Ptr(addr=int(value), elem_size=max(1, self.type_size(
                    t.inner if isinstance(t, ast.PtrType) else None)), type_name=inner or "u8")
            raise bi.DsRuntimeError(f"不能把 {type(value).__name__} 转成指针")
        if isinstance(t, ast.BoxType):
            if t.kind in ("rc", "arc"):
                if isinstance(value, bi.RefCount):
                    return value
                return bi.RefCount(value, atomic=(t.kind == "arc"), interp=self)
            if t.kind == "gc":
                return bi.GcBox(value)
            return value
        if isinstance(t, ast.FnType):
            return value
        if isinstance(t, ast.OptType):
            if isinstance(value, bi.Opt):
                return value
            return bi.some(value)
        if isinstance(t, ast.ResType):
            return value
        if isinstance(t, ast.UnitType):
            return bi.UNIT
        if isinstance(t, ast.TypeName):
            td = self.find_type(name)
            if td is not None:
                if isinstance(value, bi.DsInstance) and value.type_def.is_subclass_of(td):
                    return value
                return value
        return value

    # ==================================================================
    # 宏
    # ==================================================================
    def expand_macro(self, macro: bi.Macro, call: ast.Call, env: Env) -> Any:
        depth = getattr(self._tls, "macro_depth", 0)
        if depth > 32:
            raise bi.DsRuntimeError("宏展开深度超过上限")
        self._tls.macro_depth = depth + 1
        try:
            params = macro.decl.params
            bindings: dict[str, Any] = {}
            for i, param in enumerate(params):
                if i < len(call.args):
                    bindings[param.name] = call.args[i]
                elif i < len(call.kwargs):
                    bindings[param.name] = call.kwargs[i][1]
                else:
                    raise bi.DsRuntimeError(f"宏 `{macro.decl.name}` 缺少参数 `{param.name}`")
            body = self._substitute(macro.decl.body, bindings)
            return self.exec_block(body, macro.closure)
        finally:
            self._tls.macro_depth = depth

    def _substitute(self, node: Any, bindings: dict[str, Any]) -> Any:
        if isinstance(node, ast.Var) and node.name in bindings:
            replacement = bindings[node.name]
            if isinstance(replacement, ast.BlockExpr):
                return copy.deepcopy(replacement)
            return copy.deepcopy(replacement)
        if isinstance(node, list):
            return [self._substitute(item, bindings) for item in node]
        if dataclasses.is_dataclass(node) and isinstance(node, ast.Node):
            cloned = copy.copy(node)
            for fld in dataclasses.fields(node):
                setattr(cloned, fld.name, self._substitute(getattr(node, fld.name), bindings))
            return cloned
        return node

    # ==================================================================
    # 小工具
    # ==================================================================
    def require_bool(self, value: Any, what: str) -> bool:
        if not isinstance(value, bool):
            raise bi.DsRuntimeError(f"{what} 必须是 bool，实际是 {type(value).__name__}")
        return value


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------
def _trunc_div(a: int, b: int) -> int:
    """C/Ds 语义的整数除法：向零截断。"""
    quotient = abs(a) // abs(b)
    return -quotient if (a < 0) != (b < 0) else quotient


def _pad(offset: int, align: int) -> int:
    if align <= 1:
        return offset
    return (offset + align - 1) // align * align


def _expand(path: str) -> str:
    import os

    return os.path.expanduser(path)


def _dirname(path: str) -> str:
    if not path or path.startswith("<"):
        return "."
    return path.rsplit("/", 1)[0] if "/" in path else "."


def _join(base: str, name: str) -> str:
    return f"{base.rstrip('/')}/{name}" if base not in ("", ".") else name
