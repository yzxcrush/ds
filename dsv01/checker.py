# -*- coding: utf-8 -*-
"""Ds 语义检查（编译前）：类型标注、返回值、条件、循环上下文、重复定义。

设计原则：保守静态检查——只在能确定错误时报错；未知类型/未知表达式放行，
由运行期兜底。这样不误伤 class/trait/comptime 等尚未静态建模的特性。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import ast
from . import builtins as bi


INT_RANGES = {
    "i8": (-128, 127), "i16": (-32768, 32767), "i32": (-2**31, 2**31 - 1),
    "i64": (-2**63, 2**63 - 1), "isize": (-2**63, 2**63 - 1),
    "u8": (0, 255), "u16": (0, 65535), "u32": (0, 2**32 - 1),
    "u64": (0, 2**64 - 1), "usize": (0, 2**64 - 1),
}
FLOAT_TYPES = {"f32", "f64"}
UNIT_TYPES = {"unit", "void"}
BUILTIN_RET = {
    "len": "int", "str": "str", "concat": "str", "format": "str",
    "range": "array", "error": "error", "ok": "res", "err": "res",
    "println": "unit", "print": "unit", "abs": "int", "pow": "float",
    "math.sqrt": "float", "math.round": "float", "math.floor": "float",
    "math.ceil": "float", "math.abs": "float", "math.pow": "float",
}


class DsCheckError(bi.DsRuntimeError):
    """静态检查错误（CLI 显示为 type error）。"""

    def __init__(self, msg: str, line: int = 0, col: int = 0):
        super().__init__(msg, line, col)
        self.check = True


@dataclass
class Sig:
    params: list[tuple[str, str | None, bool]]  # name, type, has_default
    ret: str | None
    generic: bool = False


@dataclass
class Scope:
    types: dict[str, str] = field(default_factory=dict)
    mutable: set[str] = field(default_factory=set)
    parent: "Scope | None" = None
    loop_depth: int = 0
    ret: str | None = None

    def lookup(self, name: str) -> str | None:
        s = self
        while s:
            if name in s.types:
                return s.types[name]
            s = s.parent
        return None

    def is_mutable(self, name: str) -> bool | None:
        s = self
        while s:
            if name in s.types:
                return name in s.mutable
            s = s.parent
        return None


def _t(t: ast.TypeExpr | None) -> str | None:
    if t is None:
        return None
    return bi.type_name_of(t)


def _lit_type(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "intlit"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, (bytes, bytearray)):
        return "bytes"
    if value is None:
        return "unit"
    return "?"


def _compat(actual: str | None, expected: str | None, lit: Any = None) -> bool:
    if actual is None or actual == "?" or expected is None:
        return True
    if expected in UNIT_TYPES:
        return actual in ("unit", "?")
    if expected in INT_RANGES:
        if actual == "intlit":
            if isinstance(lit, bool):
                return False
            if isinstance(lit, int):
                lo, hi = INT_RANGES[expected]
                return lo <= lit <= hi
            return True
        return actual == expected
    if expected in FLOAT_TYPES:
        return actual == "float"
    if expected == "bool":
        return actual == "bool"
    if expected == "str":
        return actual == "str"
    if expected == "bytes":
        return actual == "bytes"
    if expected.startswith("[]") or expected.startswith("["):
        return actual in ("array", "?")
    if expected in ("map", "ptr", "ref", "raw", "fn", "opt", "res", "dyn", "!"):
        return True
    return actual in (expected, "?") or actual not in ("int", "bool", "str", "float")


class Checker:
    def __init__(self, program: ast.Program):
        self.program = program
        self.sigs: dict[str, Sig] = {}
        self.globals: Scope = Scope()
        self.classes: dict[str, dict[str, Sig]] = {}
        self.current_fn: str | None = None
        self.errors: list[DsCheckError] = []

    # ------------------------------------------------------------------
    def err(self, msg: str, node: Any):
        self.errors.append(DsCheckError(f"{msg}", getattr(node, "line", 0), getattr(node, "col", 0)))

    def check(self) -> None:
        self.collect_items(self.program.items)
        for item in self.program.items:
            self.check_item(item)
        for stmt in self.program.items:
            if isinstance(stmt, ast.Stmt):
                self.check_stmt(stmt, self.globals, in_func=False)
        if self.errors:
            raise self.errors[0]

    # ------------------------------------------------------------------
    def collect_items(self, items: list[Any]) -> None:
        for item in items:
            if isinstance(item, ast.FnDecl):
                self.sigs[item.name] = self.fn_sig(item)
            elif isinstance(item, ast.ClassDecl):
                methods = {}
                for m in item.methods:
                    methods[m.name] = self.fn_sig(m, method=True)
                self.classes[item.name] = methods
                self.globals.types[item.name] = item.name
            elif isinstance(item, ast.TypeDecl):
                self.globals.types[item.name] = item.name
            elif isinstance(item, ast.ImplDecl):
                for m in item.methods:
                    self.sigs.setdefault(m.name, self.fn_sig(m, method=True))
            elif isinstance(item, ast.ModDecl):
                for sub in getattr(item, "items", []) or []:
                    self.collect_items([sub])

    def fn_sig(self, fn: ast.FnDecl, method: bool = False) -> Sig:
        params = []
        if method and not getattr(fn, "is_static", False):
            params.append(("self", None, False))
        for p in fn.params:
            params.append((p.name, _t(p.type), p.default is not None))
        return Sig(params, _t(fn.ret), bool(fn.generics))

    def check_item(self, item: Any) -> None:
        if isinstance(item, ast.FnDecl):
            self.check_fn(item)
        elif isinstance(item, ast.ClassDecl):
            for m in item.methods:
                self.check_fn(m, class_name=item.name)
        elif isinstance(item, ast.ImplDecl):
            for m in item.methods:
                self.check_fn(m)
        elif isinstance(item, ast.ModDecl):
            for sub in getattr(item, "items", []) or []:
                self.check_item(sub)
        elif isinstance(item, (ast.LetItem, ast.StaticDecl)):
            self.check_top_let(item)

    def check_top_let(self, item: Any) -> None:
        if item.name in self.globals.types:
            self.err(f"顶层重复定义 `{item.name}`", item)
            return
        typ = _t(getattr(item, "type", None))
        val = getattr(item, "value", None)
        if val is None:
            self.globals.types[item.name] = typ
            return
        actual = self.infer(val, self.globals)
        if typ and not _compat(actual, typ, getattr(val, "value", None)):
            self.err(f"`{item.name}` 类型不匹配：标注 {typ}，实际 {actual or '?'}", item)
        self.globals.types[item.name] = typ or ("i32" if actual == "intlit" else actual)
        if getattr(item, "mutable", False):
            self.globals.mutable.add(item.name)

    # ------------------------------------------------------------------
    def check_fn(self, fn: ast.FnDecl, class_name: str | None = None) -> None:
        if fn.body is None:
            return
        scope = Scope(parent=self.globals, ret=_t(fn.ret))
        if class_name is not None:
            scope.types["self"] = class_name
        for p in fn.params:
            scope.types[p.name] = _t(p.type)
            if p.mutable:
                scope.mutable.add(p.name)
            if p.default is not None:
                actual = self.infer(p.default, scope)
                if _t(p.type) and not _compat(actual, _t(p.type), getattr(p.default, "value", None)):
                    self.err(f"参数 `{p.name}` 默认值类型不匹配", p)
        self.current_fn = fn.name
        self.check_fn_body(fn, scope)
        self.current_fn = None

    def check_fn_body(self, fn: ast.FnDecl, scope: Scope) -> None:
        ret = _t(fn.ret)
        body = fn.body
        returns: list[ast.ReturnStmt] = []
        has_tail = False
        if isinstance(body, ast.Block):
            for st in body.stmts:
                self.check_stmt(st, scope, in_func=True, returns=returns)
                if isinstance(st, ast.ExprStmt):
                    has_tail = True
                elif isinstance(st, ast.ReturnStmt):
                    has_tail = True
            if body.stmts and isinstance(body.stmts[-1], ast.ExprStmt) and ret not in (None, *UNIT_TYPES):
                actual = self.infer(body.stmts[-1].expr, scope)
                if not _compat(actual, ret):
                    self.err(f"函数 `{fn.name}` 返回类型不匹配：期望 {ret}，尾表达式为 {actual or '?'}",
                             body.stmts[-1])
            if ret not in (None, *UNIT_TYPES) and "!" not in (ret or "") and not has_tail:
                self.err(f"函数 `{fn.name}` 声明返回 {ret}，但没有 return 或尾表达式", fn)
        elif isinstance(body, ast.Expr):
            actual = self.infer(body, scope)
            if ret not in (None, *UNIT_TYPES) and not _compat(actual, ret, getattr(body, "value", None)):
                self.err(f"函数 `{fn.name}` 返回类型不匹配：期望 {ret}，实际 {actual or '?'}", fn)
            elif ret in UNIT_TYPES and actual not in ("unit", "?"):
                self.err(f"函数 `{fn.name}` 声明返回 unit，但表达式类型为 {actual}", fn)

    # ------------------------------------------------------------------
    def check_stmt(self, st: Any, scope: Scope, *, in_func: bool,
                   returns: list[ast.ReturnStmt] | None = None) -> None:
        if isinstance(st, ast.LetStmt):
            typ = _t(st.type)
            actual = self.infer(st.value, scope) if st.value is not None else "unit"
            if typ and not _compat(actual, typ, getattr(st.value, "value", None)):
                self.err(f"`{st.name}` 类型不匹配：标注 {typ}，实际 {actual or '?'}", st)
            if st.name in scope.types:
                self.err(f"同一作用域重复定义 `{st.name}`", st)
            scope.types[st.name] = typ or ("i32" if actual == "intlit" else actual)
            if st.mutable:
                scope.mutable.add(st.name)
            else:
                scope.mutable.discard(st.name)
        elif isinstance(st, ast.AssignStmt):
            actual = self.infer(st.value, scope)
            target_type = self.infer(st.target, scope)
            if isinstance(st.target, ast.Var):
                mut = scope.is_mutable(st.target.name)
                if mut is False:
                    self.err(f"`{st.target.name}` 不可变，不能赋值（用 var 声明）", st)
            if target_type and actual and not _compat(actual, target_type):
                self.err(f"赋值类型不匹配：目标 {target_type}，值 {actual}", st)
        elif isinstance(st, ast.ExprStmt):
            self.infer(st.expr, scope)
        elif isinstance(st, ast.ReturnStmt):
            if not in_func:
                self.err("`return` 只能出现在函数内", st)
                return
            if returns is not None:
                returns.append(st)
            ret = scope.ret
            if st.value is None:
                if ret not in (None, *UNIT_TYPES) and "!" not in (ret or ""):
                    self.err(f"函数声明返回 {ret}，`return` 需要值", st)
            else:
                actual = self.infer(st.value, scope)
                if ret not in (None, *UNIT_TYPES) and "!" not in (ret or ""):
                    if not _compat(actual, ret, getattr(st.value, "value", None)):
                        self.err(f"`return` 类型不匹配：期望 {ret}，实际 {actual or '?'}", st)
                elif ret in UNIT_TYPES and actual not in ("unit", "?"):
                    self.err(f"函数声明返回 unit，但 return 了 {actual}", st)
        elif isinstance(st, ast.IfExpr):
            self.check_cond(st.cond, scope, st)
            self.check_block(st.then_block, self.child(scope), in_func, returns)
            if st.else_:
                if isinstance(st.else_, ast.Block):
                    self.check_block(st.else_, self.child(scope), in_func, returns)
                else:
                    self.check_stmt(st.else_, self.child(scope), in_func=in_func, returns=returns)
        elif isinstance(st, ast.WhileStmt):
            self.check_cond(st.cond, scope, st)
            inner = self.child(scope); inner.loop_depth += 1
            self.check_block(st.body, inner, in_func, returns)
        elif isinstance(st, ast.LoopStmt):
            inner = self.child(scope); inner.loop_depth += 1
            self.check_block(st.body, inner, in_func, returns)
        elif isinstance(st, ast.ForStmt):
            self.infer(st.iterable, scope)
            inner = self.child(scope); inner.loop_depth += 1
            if isinstance(st.pattern, ast.BindPat):
                inner.types[st.pattern.name] = None
            self.check_block(st.body, inner, in_func, returns)
        elif isinstance(st, (ast.BreakStmt, ast.ContinueStmt)):
            if scope.loop_depth <= 0:
                self.err("`break`/`continue` 只能出现在循环内", st)
        elif isinstance(st, ast.Block):
            self.check_block(st, self.child(scope), in_func, returns)
        elif isinstance(st, ast.AssertStmt):
            if st.cond is not None:
                self.check_cond(st.cond, scope, st)
        else:
            # 其他语句：尽量检查其表达式字段
            for f in ("expr", "value", "cond", "iterable"):
                node = getattr(st, f, None)
                if isinstance(node, ast.Expr):
                    self.infer(node, scope)

    def check_block(self, block: ast.Block, scope: Scope, in_func: bool,
                    returns: list[ast.ReturnStmt] | None) -> None:
        for st in block.stmts:
            self.check_stmt(st, scope, in_func=in_func, returns=returns)

    def child(self, scope: Scope) -> Scope:
        return Scope(parent=scope, loop_depth=scope.loop_depth, ret=scope.ret)

    def check_cond(self, cond: Any, scope: Scope, node: Any) -> None:
        if cond is None:
            return
        actual = self.infer(cond, scope)
        if actual not in (None, "bool", "?"):
            self.err(f"条件必须是 bool，实际是 {actual}", node)

    # ------------------------------------------------------------------
    def infer(self, e: Any, scope: Scope) -> str | None:
        try:
            return self._infer(e, scope)
        except Exception:
            return None

    def _infer(self, e: Any, scope: Scope) -> str | None:
        if e is None:
            return "unit"
        if isinstance(e, ast.Lit):
            return _lit_type(e.value)
        if isinstance(e, ast.FString):
            for part in e.parts:
                if isinstance(part, ast.Expr):
                    self.infer(part, scope)
            return "str"
        if isinstance(e, ast.Var):
            return scope.lookup(e.name)
        if isinstance(e, ast.Call):
            return self.infer_call(e, scope)
        if isinstance(e, ast.Binary):
            if e.op == "|>":
                self.infer(e.left, scope)
                if isinstance(e.right, ast.Call):
                    for a in e.right.args: self.infer(a, scope)
                    if isinstance(e.right.fn, ast.Var) and e.right.fn.name in self.sigs:
                        return self.sigs[e.right.fn.name].ret
                    return BUILTIN_RET.get(e.right.fn.name) if isinstance(e.right.fn, ast.Var) else None
                return self.infer(e.right, scope)
            lt, rt = self.infer(e.left, scope), self.infer(e.right, scope)
            if e.op in ("==", "!=", "<", ">", "<=", ">=", "&&", "||"):
                return "bool"
            if e.op == "+" and (lt == "str" or rt == "str"):
                if lt not in (None, "str", "?") or rt not in (None, "str", "?"):
                    self.err("`+` 类型不匹配：字符串只能与字符串相加", e)
                return "str"
            if lt in ("bool", "str") or rt in ("bool", "str"):
                self.err(f"`{e.op}` 不支持 {lt or '?'} 与 {rt or '?'}", e)
            ints = set(INT_RANGES) | {"intlit"}
            if lt == "float" or rt == "float":
                return "float"
            if lt in ints and rt in ints:
                if lt == "intlit" and rt == "intlit":
                    return "intlit"
                if lt == "intlit":
                    return rt
                if rt == "intlit":
                    return lt
                if lt == rt:
                    return lt
                self.err(f"整数类型不同（{lt} 与 {rt}），需要显式 `as`", e)
                return "?"
            return None
        if isinstance(e, ast.Unary):
            t = self.infer(e.expr, scope)
            if e.op == "!": return "bool"
            if e.op == "-": return t
            return t
        if isinstance(e, ast.Cast):
            return _t(e.type)
        if isinstance(e, ast.IfExpr):
            self.check_cond(e.cond, scope, e)
            a = self.infer_block_value(e.then_block, scope)
            b = self.infer(e.else_, scope) if isinstance(e.else_, ast.Expr) else (
                self.infer_block_value(e.else_, scope) if isinstance(e.else_, ast.Block) else None)
            if a and b and a != b:
                return None
            return a or b
        if isinstance(e, ast.BlockExpr):
            return self.infer_block_value(e.block, scope)
        if isinstance(e, ast.ArrayLit):
            for it in e.items: self.infer(it, scope)
            return "array"
        if isinstance(e, ast.MapLit):
            for k in getattr(e, "keys", []): self.infer(k, scope)
            for v in e.items: self.infer(v, scope)
            return "map"
        if isinstance(e, ast.NewExpr):
            return e.type_name
        if isinstance(e, ast.MatchExpr):
            self.infer(e.subject, scope)
            for arm in e.arms:
                if isinstance(arm.body, ast.Block):
                    self.infer_block_value(arm.body, scope)
                else:
                    self.infer(arm.body, scope)
            return None
        if isinstance(e, ast.TryExpr):
            return self.infer(e.expr, scope)
        if isinstance(e, ast.AttrExpr):
            self.infer(e.expr, scope)
            return None
        if isinstance(e, ast.Index):
            self.infer(e.expr, scope); self.infer(e.index, scope)
            return None
        return None

    def infer_block_value(self, block: ast.Block, scope: Scope) -> str | None:
        child = self.child(scope)
        last: str | None = None
        for st in block.stmts:
            self.check_stmt(st, child, in_func=self.current_fn is not None)
            if isinstance(st, ast.ExprStmt):
                last = self.infer(st.expr, child)
            elif not isinstance(st, (ast.ReturnStmt, ast.LetStmt)):
                last = None
        return last

    def infer_call(self, e: ast.Call, scope: Scope) -> str | None:
        for a in e.args: self.infer(a, scope)
        for _n, a in e.kwargs: self.infer(a, scope)
        if not isinstance(e.fn, ast.Var):
            return None
        name = e.fn.name
        if name in self.sigs:
            sig = self.sigs[name]
            if not sig.generic:
                if len(e.args) > len(sig.params) or any(
                        not has_default and i >= len(e.args)
                        for i, (_n, _t, has_default) in enumerate(sig.params)):
                    self.err(f"`{name}` 参数个数不匹配（期望 {len(sig.params)}，实际 {len(e.args)}）", e)
                for (pname, ptype, _d), arg in zip(sig.params, e.args):
                    if pname == "self": continue
                    at = self.infer(arg, scope)
                    if ptype and not _compat(at, ptype, getattr(arg, "value", None)):
                        self.err(f"调用 `{name}` 参数 `{pname}` 类型不匹配：期望 {ptype}，实际 {at or '?'}", arg)
            return sig.ret
        return BUILTIN_RET.get(name)


def check_program(program: ast.Program) -> None:
    Checker(program).check()
