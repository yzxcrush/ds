# -*- coding: utf-8 -*-
"""Ds v0.1 抽象语法树（AST）。

解析器（parser.py）产出这些节点，解释器（interp.py）消费它们。
所有节点都是普通 dataclass；`line`/`col` 仅用于诊断，解析器可留默认值。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class Node:
    """所有 AST 节点的基类（无字段，方便 dataclass 继承）。"""


# ---------------------------------------------------------------------------
# 类型（大多数在运行时只用于 is/sizeof/typeinfo/诊断）
# ---------------------------------------------------------------------------
@dataclass
class TypeExpr(Node):
    pass


@dataclass
class TypeName(TypeExpr):
    name: str
    args: list["TypeExpr"] = field(default_factory=list)
    line: int = 0
    col: int = 0


@dataclass
class ArrayType(TypeExpr):
    elem: TypeExpr
    size: Any = None          # int | Expr | None
    line: int = 0
    col: int = 0


@dataclass
class SliceType(TypeExpr):
    elem: TypeExpr
    line: int = 0
    col: int = 0


@dataclass
class PtrType(TypeExpr):
    inner: TypeExpr
    mutable: bool = False
    line: int = 0
    col: int = 0


@dataclass
class RefType(TypeExpr):
    inner: TypeExpr
    mutable: bool = False
    line: int = 0
    col: int = 0


@dataclass
class VolatileType(TypeExpr):
    inner: TypeExpr
    line: int = 0
    col: int = 0


@dataclass
class DynType(TypeExpr):
    inner: TypeExpr
    line: int = 0
    col: int = 0


@dataclass
class FnType(TypeExpr):
    params: list["TypeExpr"] = field(default_factory=list)
    ret: "TypeExpr | None" = None
    line: int = 0
    col: int = 0


@dataclass
class OptType(TypeExpr):
    inner: TypeExpr
    line: int = 0
    col: int = 0


@dataclass
class ResType(TypeExpr):
    ok: TypeExpr
    err: "TypeExpr | None" = None
    line: int = 0
    col: int = 0


@dataclass
class BoxType(TypeExpr):
    kind: str                 # rc | arc | gc | chan | mutex | task
    inner: "TypeExpr | None" = None
    size: Any = None
    line: int = 0
    col: int = 0


@dataclass
class UnitType(TypeExpr):
    line: int = 0
    col: int = 0


@dataclass
class RawType(TypeExpr):
    line: int = 0
    col: int = 0


@dataclass
class InferredType(TypeExpr):
    line: int = 0
    col: int = 0


# ---------------------------------------------------------------------------
# 模式
# ---------------------------------------------------------------------------
@dataclass
class Pattern(Node):
    pass


@dataclass
class WildcardPat(Pattern):
    line: int = 0
    col: int = 0


@dataclass
class LitPat(Pattern):
    value: Any = None
    line: int = 0
    col: int = 0


@dataclass
class BindPat(Pattern):
    name: str = ""
    sub: "Pattern | None" = None
    line: int = 0
    col: int = 0


@dataclass
class ArrayPat(Pattern):
    items: list[Pattern] = field(default_factory=list)
    line: int = 0
    col: int = 0


@dataclass
class MapPat(Pattern):
    pairs: list[tuple[str, Pattern]] = field(default_factory=list)
    line: int = 0
    col: int = 0


@dataclass
class CtorPat(Pattern):
    name: str = ""
    args: list[Pattern] = field(default_factory=list)
    line: int = 0
    col: int = 0


@dataclass
class OrPat(Pattern):
    alts: list[Pattern] = field(default_factory=list)
    line: int = 0
    col: int = 0


# ---------------------------------------------------------------------------
# 表达式
# ---------------------------------------------------------------------------
@dataclass
class Expr(Node):
    pass


@dataclass
class Lit(Expr):
    value: Any = None
    line: int = 0
    col: int = 0


@dataclass
class FString(Expr):
    """f"...{expr}..." 插值字符串；parts 为 str 与 Expr 的混合列表。"""

    parts: list[Any] = field(default_factory=list)
    line: int = 0
    col: int = 0


@dataclass
class ArrayLit(Expr):
    items: list[Expr] = field(default_factory=list)
    line: int = 0
    col: int = 0


@dataclass
class MapLit(Expr):
    pairs: list[tuple[Expr, Expr]] = field(default_factory=list)
    line: int = 0
    col: int = 0


@dataclass
class Var(Expr):
    name: str = ""
    line: int = 0
    col: int = 0


@dataclass
class Path(Expr):
    parts: list[str] = field(default_factory=list)
    line: int = 0
    col: int = 0


@dataclass
class AttrExpr(Expr):
    obj: Expr = None
    name: str = ""
    line: int = 0
    col: int = 0


@dataclass
class Index(Expr):
    obj: Expr = None
    index: Expr = None
    line: int = 0
    col: int = 0


@dataclass
class SliceExpr(Expr):
    obj: Expr = None
    lo: "Expr | None" = None
    hi: "Expr | None" = None
    line: int = 0
    col: int = 0


@dataclass
class Call(Expr):
    fn: Expr = None
    args: list[Expr] = field(default_factory=list)
    kwargs: list[tuple[str, Expr]] = field(default_factory=list)
    line: int = 0
    col: int = 0


@dataclass
class Unary(Expr):
    op: str = ""
    expr: Expr = None
    line: int = 0
    col: int = 0


@dataclass
class Binary(Expr):
    op: str = ""
    left: Expr = None
    right: Expr = None
    line: int = 0
    col: int = 0


@dataclass
class Cast(Expr):
    expr: Expr = None
    type: TypeExpr = None
    line: int = 0
    col: int = 0


@dataclass
class IsTest(Expr):
    expr: Expr = None
    target: Any = None        # TypeExpr | Pattern
    line: int = 0
    col: int = 0


@dataclass
class InTest(Expr):
    item: Expr = None
    container: Expr = None
    line: int = 0
    col: int = 0


@dataclass
class BlockExpr(Expr):
    block: "Block" = None
    line: int = 0
    col: int = 0


@dataclass
class IfExpr(Expr):
    cond: Expr = None
    then_block: "Block" = None
    else_: Any = None         # Block | Expr | None
    line: int = 0
    col: int = 0


@dataclass
class MatchArm(Node):
    pattern: Pattern = None
    guard: "Expr | None" = None
    body: Any = None          # Expr | Block
    line: int = 0
    col: int = 0


@dataclass
class MatchExpr(Expr):
    subject: Expr = None
    arms: list[MatchArm] = field(default_factory=list)
    line: int = 0
    col: int = 0


@dataclass
class FnLit(Expr):
    params: list["Param"] = field(default_factory=list)
    ret: "TypeExpr | None" = None
    body: Any = None          # Block | Expr
    line: int = 0
    col: int = 0


@dataclass
class TryExpr(Expr):
    expr: Expr = None
    line: int = 0
    col: int = 0


@dataclass
class CatchArm(Node):
    kind: str = "error"       # error | panic
    name: "str | None" = None
    block: "Block" = None
    line: int = 0
    col: int = 0


@dataclass
class TryCatch(Expr):
    block: "Block" = None
    catches: list[CatchArm] = field(default_factory=list)
    line: int = 0
    col: int = 0


@dataclass
class RecvExpr(Expr):
    ch: Expr = None
    line: int = 0
    col: int = 0


@dataclass
class WaitExpr(Expr):
    handle: Expr = None
    line: int = 0
    col: int = 0


@dataclass
class SpawnExpr(Expr):
    body: Any = None          # Block | Expr
    line: int = 0
    col: int = 0


@dataclass
class GoExpr(Expr):
    call: Expr = None
    line: int = 0
    col: int = 0


@dataclass
class ThreadExpr(Expr):
    fn: Expr = None
    line: int = 0
    col: int = 0


@dataclass
class NewExpr(Expr):
    type_name: str = ""
    args: list[Expr] = field(default_factory=list)
    kwargs: list[tuple[str, Expr]] = field(default_factory=list)
    line: int = 0
    col: int = 0


@dataclass
class ComptimeExpr(Expr):
    inner: Any = None         # Expr | Block | IfExpr | ForStmt
    line: int = 0
    col: int = 0


@dataclass
class SizeofExpr(Expr):
    target: Any = None        # TypeExpr | Expr
    line: int = 0
    col: int = 0


@dataclass
class AlignofExpr(Expr):
    target: Any = None        # TypeExpr
    line: int = 0
    col: int = 0


@dataclass
class TypeinfoExpr(Expr):
    target: Any = None        # TypeExpr | Expr
    line: int = 0
    col: int = 0


@dataclass
class AsmExpr(Expr):
    text: str = ""
    operands: list[Any] = field(default_factory=list)
    line: int = 0
    col: int = 0


@dataclass
class Deref(Expr):
    expr: Expr = None
    line: int = 0
    col: int = 0


@dataclass
class AddrOf(Expr):
    expr: Expr = None
    mutable: bool = False
    line: int = 0
    col: int = 0


@dataclass
class UnsafeBlock(Expr):
    block: "Block" = None
    line: int = 0
    col: int = 0


# ---------------------------------------------------------------------------
# 语句
# ---------------------------------------------------------------------------
@dataclass
class Stmt(Node):
    pass


@dataclass
class ExprStmt(Stmt):
    expr: Expr = None
    line: int = 0
    col: int = 0


@dataclass
class LetStmt(Stmt):
    name: str = ""
    pattern: "Pattern | None" = None
    type: "TypeExpr | None" = None
    value: "Expr | None" = None
    mutable: bool = False
    line: int = 0
    col: int = 0


@dataclass
class AssignStmt(Stmt):
    target: Expr = None
    value: Expr = None
    op: str = "="
    line: int = 0
    col: int = 0


@dataclass
class WhileStmt(Stmt):
    cond: Expr = None
    body: "Block" = None
    line: int = 0
    col: int = 0


@dataclass
class LoopStmt(Stmt):
    body: "Block" = None
    line: int = 0
    col: int = 0


@dataclass
class ForStmt(Stmt):
    pattern: Pattern = None
    iterable: Expr = None
    body: "Block" = None
    line: int = 0
    col: int = 0


@dataclass
class BreakStmt(Stmt):
    value: "Expr | None" = None
    line: int = 0
    col: int = 0


@dataclass
class ContinueStmt(Stmt):
    line: int = 0
    col: int = 0


@dataclass
class ReturnStmt(Stmt):
    value: "Expr | None" = None
    line: int = 0
    col: int = 0


@dataclass
class LabelStmt(Stmt):
    name: str = ""
    line: int = 0
    col: int = 0


@dataclass
class GotoStmt(Stmt):
    name: str = ""
    line: int = 0
    col: int = 0


@dataclass
class SendStmt(Stmt):
    ch: Expr = None
    value: Expr = None
    line: int = 0
    col: int = 0


@dataclass
class AssertStmt(Stmt):
    cond: Expr = None
    msg: "Expr | None" = None
    line: int = 0
    col: int = 0


@dataclass
class ComptimeStmt(Stmt):
    inner: Any = None
    line: int = 0
    col: int = 0


@dataclass
class Block(Stmt):
    stmts: list[Stmt] = field(default_factory=list)
    line: int = 0
    col: int = 0


# ---------------------------------------------------------------------------
# 项（声明）
# ---------------------------------------------------------------------------
@dataclass
class Param(Node):
    name: str = ""
    type: "TypeExpr | None" = None
    default: "Expr | None" = None
    mutable: bool = False
    by_ref: bool = False
    line: int = 0
    col: int = 0


@dataclass
class FieldDecl(Node):
    name: str = ""
    type: "TypeExpr | None" = None
    default: "Expr | None" = None
    line: int = 0
    col: int = 0


@dataclass
class Item(Node):
    vis: str = "priv"         # priv | pub | prot
    attrs: list[str] = field(default_factory=list)
    line: int = 0
    col: int = 0


@dataclass
class Package(Item):
    name: str = ""


@dataclass
class Use(Item):
    parts: list[str] = field(default_factory=list)
    alias: "str | None" = None
    names: "list[str] | None" = None    # use a.{b, c}
    line: int = 0
    col: int = 0


@dataclass
class FnDecl(Item):
    name: str = ""
    params: list[Param] = field(default_factory=list)
    generics: list[str] = field(default_factory=list)
    ret: "TypeExpr | None" = None
    body: Any = None          # Block | Expr (None for extern/trait sig)
    is_comptime: bool = False
    is_irq: bool = False
    is_unsafe: bool = False
    is_static: bool = False
    is_new: bool = False
    is_drop: bool = False
    abi: "str | None" = None  # extern "C"
    at_addr: Any = None       # at 常量
    line: int = 0
    col: int = 0


@dataclass
class LetItem(Item):
    name: str = ""
    type: "TypeExpr | None" = None
    value: "Expr | None" = None
    mutable: bool = False
    line: int = 0
    col: int = 0


@dataclass
class TypeDecl(Item):
    name: str = ""
    generics: list[str] = field(default_factory=list)
    fields: "list[FieldDecl] | None" = None
    alias: "TypeExpr | None" = None
    packed: bool = False
    line: int = 0
    col: int = 0


@dataclass
class ClassDecl(Item):
    name: str = ""
    extends: "TypeExpr | None" = None
    generics: list[str] = field(default_factory=list)
    fields: list[FieldDecl] = field(default_factory=list)
    methods: list[FnDecl] = field(default_factory=list)
    line: int = 0
    col: int = 0


@dataclass
class TraitDecl(Item):
    name: str = ""
    generics: list[str] = field(default_factory=list)
    methods: list[FnDecl] = field(default_factory=list)
    line: int = 0
    col: int = 0


@dataclass
class ImplDecl(Item):
    trait: "str | None" = None
    type: "TypeExpr | None" = None
    methods: list[FnDecl] = field(default_factory=list)
    line: int = 0
    col: int = 0


@dataclass
class ModDecl(Item):
    name: str = ""
    items: "list[Item] | None" = None      # None = 外部文件
    line: int = 0
    col: int = 0


@dataclass
class StaticDecl(Item):
    name: str = ""
    mutable: bool = False
    type: "TypeExpr | None" = None
    value: "Expr | None" = None
    at_addr: Any = None
    line: int = 0
    col: int = 0


@dataclass
class NopItem(Item):
    """编译期无操作项（Cut @asm 在 base 层的兼容占位）。"""
    line: int = 0
    col: int = 0


@dataclass
class ExternDecl(Item):
    abi: str = "C"
    name: "str | None" = None
    params: list[Param] = field(default_factory=list)
    ret: "TypeExpr | None" = None
    members: "list[ExternDecl] | None" = None
    line: int = 0
    col: int = 0


@dataclass
class MacroParam(Node):
    name: str = ""
    kind: str = "expr"        # expr|type|pat|stmt|block|ident|lit


@dataclass
class MacroDecl(Item):
    name: str = ""
    params: list[MacroParam] = field(default_factory=list)
    body: Block = None
    line: int = 0
    col: int = 0


@dataclass
class AttrDecl(Item):
    name: str = ""
    target: str = ""
    fields: list[FieldDecl] = field(default_factory=list)
    line: int = 0
    col: int = 0


@dataclass
class SectionBlock(Item):
    name: str = ""
    items: list[Item] = field(default_factory=list)
    line: int = 0
    col: int = 0


@dataclass
class ExportDecl(Item):
    names: list[str] = field(default_factory=list)
    line: int = 0
    col: int = 0


@dataclass
class Program(Node):
    package: "str | None" = None
    uses: list[Use] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)
    filename: str = "<source>"
    line: int = 0
    col: int = 0
