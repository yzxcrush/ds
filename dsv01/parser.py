# -*- coding: utf-8 -*-
"""Ds v0.1 语法分析器：token 流 -> AST（dsv01.ast）。

对外接口::

    parse_program(src, filename="<source>") -> ast.Program
    parse_repl(src, filename="<repl>")      -> list[ast.Node]

错误统一抛 ``dsv01.lexer.DsSyntaxError``（带行列）。

实现策略
--------
* NEWLINE 与 ``;`` 都作为语句终止符；解析器采取"宽松跳过"策略：
  在 ``(``/``[``/``{``、`,`、运算符、`=`、`=>`、`->`、`|>` 之后都跳过换行，
  语句之间允许 ``;``/换行，块 ``}`` 前可省略终止符。
* 表达式使用 Pratt 解析，严格按规范 §2.2 的优先级/结合性。
* ``{`` 的块/映射歧义按 §2.3 R1 与任务约定处理。
"""

from __future__ import annotations

from . import ast
from . import lexer as _lexer
from .lexer import (
    BLANK,
    BYTES,
    COMMENT,
    EOF,
    FLOAT,
    FSTRING,
    IDENT,
    INT,
    KEYWORD,
    NEWLINE,
    OP,
    PUNCT_KIND,
    RAW_IDENT,
    STRING,
    DsSyntaxError,
    tokenize,
)

__all__ = ["Parser", "parse_program", "parse_repl"]


# ---------------------------------------------------------------------------
# 优先级（数字越大绑定越紧）
# ---------------------------------------------------------------------------
_PREC = {
    "|>": 1,
    "..": 2,
    "||": 2,
    "&&": 3,
    "|": 4,
    "^": 5,
    "&": 6,
    "==": 7,
    "!=": 7,
    "<": 8,
    ">": 8,
    "<=": 8,
    ">=": 8,
    "is": 8,
    "in": 8,
    "<<": 9,
    ">>": 9,
    "+": 10,
    "-": 10,
    "*": 11,
    "/": 11,
    "%": 11,
    "as": 12,
}

# 不可链式使用的运算符（§2.2）
_NONASSOC = {"==", "!=", "<", ">", "<=", ">=", "is", "in"}

# 精简写法：复合赋值
_COMPOUND = {"+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="}

_VIS_KEYWORDS = ("pub", "priv", "prot")

# 只能以语句形式出现的起始关键字（match 分支体等位置用）
_STMT_ONLY_START = {
    "break", "continue", "return", "goto",
    "let", "var", "while", "loop", "for",
    "send", "assert",
}

_COMMENT_KINDS = (COMMENT,)


def _quote_string(s: str) -> str:
    out: list[str] = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _token_text(t) -> str:
    """把 token 还原为尽量接近源码的文本（用于属性参数/asm 原文）。"""
    if t.kind == STRING:
        return _quote_string(t.text)
    if t.kind == BYTES:
        payload = t.text.decode("utf-8", "replace") if isinstance(t.text, bytes) else str(t.text)
        return 'b"' + payload + '"'
    if t.kind == NEWLINE:
        return " "
    if t.kind == BLANK:
        return "_"
    return str(t.text)


def _join_tokens(tokens) -> str:
    """把 token 序列拼成可读文本（属性参数 / asm / 宏原始体）。"""
    parts: list[str] = []
    prev: str | None = None
    openers = {"(", "[", "{", ".", "@", "&"}
    closers = {",", ")", "]", "}", ":", ";"}
    no_space_before = openers | closers
    for t in tokens:
        if t.kind == NEWLINE:
            continue
        s = _token_text(t)
        if prev is None:
            parts.append(s)
        elif s in no_space_before:
            parts.append(s)
        elif prev in openers:
            parts.append(s)
        elif prev in (":", ",", ";"):
            parts.append(" " + s)
        else:
            parts.append(" " + s)
        prev = s
    return "".join(parts)


def _type_label(ty) -> str:
    """把 TypeExpr 粗略渲染成字符串（ImplDecl.trait 用）。"""
    if isinstance(ty, ast.TypeName):
        if ty.args:
            inner = ", ".join(
                _type_label(a) if isinstance(a, ast.TypeExpr) else str(getattr(a, "value", a))
                for a in ty.args
            )
            return f"{ty.name}[{inner}]"
        return ty.name
    return type(ty).__name__


class Parser:
    """递归下降 + Pratt 表达式解析器。"""

    def __init__(self, src: str = "", filename: str = "<source>", flow: bool | None = None):
        self.src = src
        self.filename = filename
        # 语法档：经典/精简 或 Flow（`\` 定义、并置调用、`.` 结束块）
        stripped = src.lstrip()
        self.flow = (
            filename.endswith(".dsf")
            or stripped.startswith("\\")
            or stripped.startswith("#!flow")
            if flow is None else flow
        )
        self.toks = [t for t in tokenize(src, filename) if t.kind not in _COMMENT_KINDS]
        self.i = 0
        self.block_guard = 0

    # ------------------------------------------------------------------
    # token 辅助
    # ------------------------------------------------------------------
    @property
    def tok(self):
        if self.i >= len(self.toks):
            return self.toks[-1]
        return self.toks[self.i]

    def at_eof(self) -> bool:
        return self.tok.kind == EOF

    def at_kw(self, word: str) -> bool:
        t = self.tok
        return t.kind == KEYWORD and t.text == word

    def at_op(self, op: str) -> bool:
        t = self.tok
        return t.kind == OP and t.text == op

    def at_punct(self, ch: str) -> bool:
        t = self.tok
        return t.kind == PUNCT_KIND and t.text == ch

    def at_sym(self, text: str) -> bool:
        """OP 或 KEYWORD 形式的符号（`->`、`=>`、`|>`、`=`、`@` 等）。"""
        t = self.tok
        return t.kind in (OP, KEYWORD) and t.text == text

    def advance(self):
        t = self.tok
        if self.i < len(self.toks) - 1:
            self.i += 1
        return t

    def skip_nl(self) -> None:
        while self.tok.kind == NEWLINE:
            self.advance()

    def skip_seps(self) -> None:
        """语句/项之间的终止符：NEWLINE 与 `;`。"""
        while True:
            t = self.tok
            if t.kind == NEWLINE or (t.kind == PUNCT_KIND and t.text == ";"):
                self.advance()
                continue
            break

    def skip_member_seps(self) -> None:
        """结构体/类/impl 成员之间：NEWLINE、`,`、`;`。"""
        while True:
            t = self.tok
            if t.kind == NEWLINE:
                self.advance()
                continue
            if t.kind == PUNCT_KIND and t.text in (",", ";"):
                self.advance()
                continue
            break

    def _sig_index(self, idx: int) -> int:
        while idx < len(self.toks) and self.toks[idx].kind == NEWLINE:
            idx += 1
        return min(idx, len(self.toks) - 1)

    def peek_sig(self, n: int = 1):
        """当前 token 之后的第 n 个"有效" token（跳过 NEWLINE）。"""
        idx = self.i
        seen = 0
        while idx < len(self.toks):
            t = self.toks[idx]
            if t.kind == NEWLINE:
                idx += 1
                continue
            if idx == self.i:
                idx += 1
                continue
            seen += 1
            if seen == n:
                return t
            idx += 1
        return self.toks[-1]

    def _next_is_punct(self, ch: str) -> bool:
        t = self.peek_sig(1)
        return t.kind == PUNCT_KIND and t.text == ch

    def _adjacent_prev(self) -> bool:
        """当前 token 是否紧贴上一个 token（无空白/换行）。"""
        if self.i == 0:
            return False
        prev = self.toks[self.i - 1]
        if prev.kind == NEWLINE:
            return False
        t = self.tok
        return t.line == prev.line and t.col == prev.col + len(str(prev.text))

    def _bracket_adjacent(self, prev_tok) -> bool:
        """当前 token 是否是紧贴 prev_tok 的 `[`（无空白）。"""
        t = self.tok
        if not (t.kind == PUNCT_KIND and t.text == "["):
            return False
        if t.line != prev_tok.line:
            return False
        return t.col == prev_tok.col + len(str(prev_tok.text))

    def error(self, msg: str, tok=None):
        t = self.tok if tok is None else tok
        raise DsSyntaxError(msg, self.filename, t.line, t.col)

    def expect_punct(self, ch: str):
        if not self.at_punct(ch):
            self.error(f"期望 {ch!r}，得到 {self.tok.text!r}")
        return self.advance()

    def expect_kw(self, word: str):
        if not self.at_kw(word):
            self.error(f"期望关键字 {word!r}，得到 {self.tok.text!r}")
        return self.advance()

    def expect_sym(self, text: str):
        if not self.at_sym(text):
            self.error(f"期望 {text!r}，得到 {self.tok.text!r}")
        return self.advance()

    def parse_name(self) -> str:
        """声明名/路径段：标识符、原始标识符，或关键字（`new`/`drop`/`fn` 等）。"""
        t = self.tok
        if t.kind in (IDENT, RAW_IDENT):
            self.advance()
            return t.text
        if t.kind == KEYWORD and t.text not in ("@", "->", "=>", "|>"):
            self.advance()
            return t.text
        self.error(f"期望名字，得到 {t.text!r}", t)

    def parse_binding_name(self, what="变量名") -> str:
        """变量绑定名：硬关键字不能作标识符（`new`/`drop` 只用于方法）。"""
        t = self.tok
        if t.kind not in (IDENT, RAW_IDENT):
            self.error(f"期望{what}，得到 {t.text!r}", t)
        self.advance()
        return t.text

    # ------------------------------------------------------------------
    # 顶层
    # ------------------------------------------------------------------
    def parse_program(self) -> ast.Program:
        package: str | None = None
        uses: list[ast.Use] = []
        items: list[ast.Item] = []
        self.skip_seps()
        while not self.at_eof():
            if self.at_kw("package"):
                if package is not None or items or uses:
                    self.error("package 只能出现一次且位于文件开头")
                self.advance()
                package = self.parse_name()
                self.skip_seps()
                continue
            if self._at_item_start():
                nodes = self.parse_item_or_use()
                for node in nodes:
                    if isinstance(node, ast.Use):
                        uses.append(node)
                    else:
                        items.append(node)
            else:
                # 精简写法：允许顶层语句（隐式入口，无需 package / fn main）
                items.append(self.parse_stmt())  # type: ignore[arg-type]
            self.skip_seps()
        return ast.Program(
            package=package,
            uses=uses,
            items=items,
            filename=self.filename,
            line=1,
            col=1,
        )

    def parse_repl(self) -> list[ast.Node]:
        nodes: list[ast.Node] = []
        while True:
            self.skip_seps()
            if self.at_eof():
                break
            if self.at_kw("package"):
                self.error("REPL 中不支持 package 声明")
            if self._at_item_start():
                nodes.extend(self.parse_item_or_use())
            else:
                nodes.append(self.parse_stmt())
            self.skip_seps()
        return nodes

    def _at_item_start(self) -> bool:
        t = self.tok
        if self.flow and t.kind == OP and t.text == "\\":
            return True
        if t.kind == KEYWORD:
            if t.text == "@":
                # `@unsafe { ... }` 是表达式/语句，不是项
                n1 = self.peek_sig(1)
                n2 = self.peek_sig(2)
                if n1.text == "unsafe" and n2.kind == PUNCT_KIND and n2.text == "{":
                    return False
                return True
            if t.text == "comptime":
                return self.peek_sig(1).text in ("fn", "irq")
            return t.text in {
                "pub", "priv", "prot", "fn", "let", "var", "type", "class",
                "trait", "impl", "mod", "static", "extern", "macro", "attr",
                "section", "export", "irq", "packed", "use",
            }
        return False

    # ------------------------------------------------------------------
    # 项
    # ------------------------------------------------------------------
    def parse_item_or_use(self) -> list[ast.Item]:
        if self.at_kw("use"):
            return list(self.parse_use())
        return [self.parse_item()]

    def parse_item(self) -> ast.Item:
        t0 = self.tok
        line, col = t0.line, t0.col
        attrs: list[str] = []
        while self.at_kw("@"):
            attrs.append(self.parse_attr())
            self.skip_nl()
        vis = "priv"
        while self.tok.kind == KEYWORD and self.tok.text in _VIS_KEYWORDS:
            vis = self.tok.text
            self.advance()
            self.skip_nl()
            while self.at_kw("@"):
                attrs.append(self.parse_attr())
                self.skip_nl()
        packed = False
        if self.at_kw("packed"):
            packed = True
            self.advance()
            self.skip_nl()
        t = self.tok
        if "asm" in attrs and t.kind in (STRING,):
            self.advance()
            self.skip_nl()
            if self.at_punct("("):
                depth = 1
                self.advance()
                while depth > 0 and not self.at_eof():
                    if self.at_punct("("): depth += 1
                    elif self.at_punct(")"): depth -= 1
                    self.advance()
            return ast.NopItem(line=line, col=col)
        if "static" in attrs and t.kind in (IDENT, RAW_IDENT):
            return self.parse_static_binding(attrs, line, col)
        if self.flow and t.kind == OP and t.text == "\\":
            fn = self.parse_fn_flow()
            fn.vis = vis
            fn.attrs = attrs
            fn.line, fn.col = line, col
            return fn
        if t.kind == KEYWORD:
            kw = t.text
            if kw in ("fn", "comptime", "irq"):
                fn = self.parse_fn(vis=vis, attrs=attrs)
                fn.line, fn.col = line, col
                return fn
            if kw == "let" or kw == "var":
                return self.parse_let_item(vis, attrs, line, col)
            if kw == "type":
                return self.parse_type_decl(vis, attrs, packed, line, col)
            if kw == "class":
                return self.parse_class_decl(vis, attrs, line, col)
            if kw == "trait":
                return self.parse_trait_decl(vis, attrs, line, col)
            if kw == "impl":
                return self.parse_impl_decl(vis, attrs, line, col)
            if kw == "mod":
                return self.parse_mod_decl(vis, attrs, line, col)
            if kw == "static":
                return self.parse_static_decl(vis, attrs, line, col)
            if kw == "extern":
                return self.parse_extern_decl(vis, attrs, line, col)
            if kw == "macro":
                return self.parse_macro_decl(vis, attrs, line, col)
            if kw == "attr":
                return self.parse_attr_decl(vis, attrs, line, col)
            if kw == "section":
                return self.parse_section_block(vis, attrs, line, col)
            if kw == "export":
                return self.parse_export_decl(vis, attrs, line, col)
        self.error(f"期望项声明，得到 {t.text!r}", t)

    # -- 属性 ----------------------------------------------------------
    def parse_attr(self) -> str:
        self.expect_kw("@")
        t = self.tok
        if t.kind not in (IDENT, RAW_IDENT, KEYWORD) or (
            t.kind == KEYWORD and t.text in ("@", "->", "=>", "|>")
        ):
            self.error("属性名缺失", t)
        name = t.text
        self.advance()
        if self.at_punct("("):
            self.advance()
            toks = []
            depth = 1
            while depth > 0 and not self.at_eof():
                t = self.tok
                if t.kind == PUNCT_KIND and t.text in "({[":
                    depth += 1
                    toks.append(t)
                    self.advance()
                elif t.kind == PUNCT_KIND and t.text in ")}]":
                    depth -= 1
                    if depth == 0:
                        self.advance()
                        break
                    toks.append(t)
                    self.advance()
                else:
                    toks.append(t)
                    self.advance()
            if depth != 0:
                self.error(f"属性 @{name} 的参数未闭合")
            return f"{name}({_join_tokens(toks)})"
        if self.at_punct("{"):
            body = self._collect_raw_braces()
            return f"{name}{{{body}}}"
        return name

    # -- let/var 顶层 --------------------------------------------------
    def parse_let_item(self, vis, attrs, line, col) -> ast.LetItem:
        mutable = self.tok.text == "var"
        self.advance()
        self.skip_nl()
        name = self.parse_binding_name()
        ty = None
        value = None
        if self.at_punct(":"):
            self.advance()
            ty = self.parse_type()
        if self.at_sym("="):
            self.advance()
            self.skip_nl()
            value = self.parse_expr()
        return ast.LetItem(
            name=name, type=ty, value=value, mutable=mutable,
            vis=vis, attrs=attrs, line=line, col=col,
        )

    # -- fn ------------------------------------------------------------
    def parse_fn(self, vis="priv", attrs=None, is_static=False) -> ast.FnDecl:
        attrs = attrs or []
        t0 = self.tok
        line, col = t0.line, t0.col
        is_comptime = is_irq = False
        while self.tok.kind == KEYWORD and self.tok.text in ("comptime", "irq"):
            if self.tok.text == "comptime":
                is_comptime = True
            else:
                is_irq = True
            self.advance()
        self.expect_kw("fn")
        self.skip_nl()
        name = self.parse_name()
        generics = []
        if self.at_punct("["):
            generics = self.parse_generic_names()
        while self.at_kw("where"):
            self.parse_where_clause()
        self.skip_nl()
        params = self.parse_params()
        ret = None
        while True:
            self.skip_nl()
            if self.at_kw("where"):
                self.parse_where_clause()
                continue
            if self.at_sym("->"):
                self.advance()
                self.skip_nl()
                ret = self.parse_type()
                continue
            break
        at_addr = None
        if self.at_kw("at"):
            self.advance()
            self.skip_nl()
            at_addr = self.parse_expr()
        body = None
        if self.at_punct("{"):
            body = self.parse_block()
        elif self.at_sym("=>"):
            self.advance()
            self.skip_nl()
            body = self.parse_expr()
        elif self.at_sym("="):
            # 精简写法：fn add(a, b) = a + b
            self.advance()
            self.skip_nl()
            body = self.parse_expr()
        elif self.at_punct(":"):
            # 精简写法：fn new(name): self.name = name
            t = self.tok
            self.advance()
            self.skip_nl()
            stmt = self.parse_stmt()
            body = ast.Block(stmts=[stmt], line=t.line, col=t.col)
        if self.at_kw("at"):
            self.advance()
            self.skip_nl()
            at_addr = self.parse_expr()
        return ast.FnDecl(
            name=name,
            params=params,
            generics=generics,
            ret=ret,
            body=body,
            is_comptime=is_comptime,
            is_irq=is_irq,
            is_unsafe=("unsafe" in attrs),
            is_static=is_static,
            is_new=(name == "new"),
            is_drop=(name == "drop"),
            vis=vis,
            attrs=attrs,
            at_addr=at_addr,
            line=line,
            col=col,
        )

    def parse_generic_names(self) -> list[str]:
        self.expect_punct("[")
        names: list[str] = []
        self.skip_nl()
        while not self.at_punct("]"):
            names.append(self.parse_name())
            # 宽容：`[T: Draw]` 形式的内联约束
            if self.at_punct(":"):
                self.advance()
                self.parse_type()
                while self.at_sym("+"):
                    self.advance()
                    self.parse_type()
            self.skip_nl()
            if self.at_punct(","):
                self.advance()
                self.skip_nl()
                continue
            break
        self.expect_punct("]")
        return names

    def parse_where_clause(self) -> None:
        self.expect_kw("where")
        self.skip_nl()
        while True:
            if (
                self.at_eof()
                or self.at_punct("{")
                or self.at_sym("=>")
                or self.at_sym("->")
                or self.at_kw("at")
            ):
                break
            # 约束：type ":" type {"+" type} {"," ...}
            try:
                self.parse_type()
            except DsSyntaxError:
                break
            if not self.at_punct(":"):
                break
            self.advance()
            self.skip_nl()
            self.parse_type()
            while self.at_sym("+"):
                self.advance()
                self.skip_nl()
                self.parse_type()
            if self.at_punct(","):
                self.advance()
                self.skip_nl()
                continue
            break

    def parse_params(self) -> list[ast.Param]:
        self.expect_punct("(")
        params: list[ast.Param] = []
        self.skip_nl()
        while not self.at_punct(")"):
            if self.at_eof():
                self.error("参数表未闭合（缺少 ')'）")
            t = self.tok
            line, col = t.line, t.col
            by_ref = False
            mutable = False
            if self.at_kw("ref"):
                by_ref = True
                self.advance()
            if self.at_kw("mut"):
                mutable = True
                self.advance()
            t = self.tok
            if t.kind in (IDENT, RAW_IDENT, KEYWORD, BLANK):
                name = t.text
                self.advance()
            else:
                self.error(f"期望参数名，得到 {t.text!r}", t)
            ty = None
            default = None
            if self.at_punct(":"):
                self.advance()
                ty = self.parse_type()
            if self.at_sym("="):
                self.advance()
                self.skip_nl()
                default = self.parse_expr()
            params.append(
                ast.Param(
                    name=name, type=ty, default=default,
                    mutable=mutable, by_ref=by_ref, line=line, col=col,
                )
            )
            self.skip_nl()
            if self.at_punct(","):
                self.advance()
                self.skip_nl()
                continue
            if self.at_punct(")"):
                break
        self.expect_punct(")")
        return params

    # -- type ----------------------------------------------------------
    def parse_type_decl(self, vis, attrs, packed, line, col) -> ast.TypeDecl:
        self.expect_kw("type")
        self.skip_nl()
        name = self.parse_name()
        generics = []
        if self.at_punct("["):
            generics = self.parse_generic_names()
        while self.at_kw("where"):
            self.parse_where_clause()
        self.skip_nl()
        if self.at_sym("="):
            self.advance()
            self.skip_nl()
            alias = self.parse_type()
            return ast.TypeDecl(
                name=name, generics=generics, fields=None, alias=alias,
                packed=packed, vis=vis, attrs=attrs, line=line, col=col,
            )
        if self.at_punct("{"):
            fields = self.parse_field_block()
            return ast.TypeDecl(
                name=name, generics=generics, fields=fields, alias=None,
                packed=packed, vis=vis, attrs=attrs, line=line, col=col,
            )
        self.error("type 声明需要 '{' 字段块或 '= 类型'")

    def parse_field_block(self) -> list[ast.FieldDecl]:
        self.expect_punct("{")
        fields: list[ast.FieldDecl] = []
        while True:
            self.skip_member_seps()
            if self.at_punct("}") or self.at_eof():
                break
            t = self.tok
            line, col = t.line, t.col
            if t.kind == KEYWORD and t.text in _VIS_KEYWORDS:
                self.advance()
                self.skip_nl()
            name = self.parse_name()
            self.expect_punct(":")
            self.skip_nl()
            ty = self.parse_type()
            default = None
            if self.at_sym("="):
                self.advance()
                self.skip_nl()
                default = self.parse_expr()
            fields.append(
                ast.FieldDecl(name=name, type=ty, default=default, line=line, col=col)
            )
        self.expect_punct("}")
        return fields

    # -- class / trait / impl -----------------------------------------
    def parse_class_decl(self, vis, attrs, line, col) -> ast.ClassDecl:
        self.expect_kw("class")
        self.skip_nl()
        name = self.parse_name()
        generics = []
        if self.at_punct("["):
            generics = self.parse_generic_names()
        extends = None
        if self.at_kw("extends"):
            self.advance()
            self.skip_nl()
            extends = self.parse_type()
        if not generics and self.at_punct("["):
            generics = self.parse_generic_names()
        while self.at_kw("where"):
            self.parse_where_clause()
        self.skip_nl()
        fields, methods = self.parse_members(allow_fields=True)
        return ast.ClassDecl(
            name=name, extends=extends, generics=generics,
            fields=fields, methods=methods,
            vis=vis, attrs=attrs, line=line, col=col,
        )

    def parse_trait_decl(self, vis, attrs, line, col) -> ast.TraitDecl:
        self.expect_kw("trait")
        self.skip_nl()
        name = self.parse_name()
        generics = []
        if self.at_punct("["):
            generics = self.parse_generic_names()
        while self.at_kw("where"):
            self.parse_where_clause()
        self.skip_nl()
        _, methods = self.parse_members(allow_fields=False)
        return ast.TraitDecl(
            name=name, generics=generics, methods=methods,
            vis=vis, attrs=attrs, line=line, col=col,
        )

    def parse_impl_decl(self, vis, attrs, line, col) -> ast.ImplDecl:
        self.expect_kw("impl")
        self.skip_nl()
        first = self.parse_type()
        trait = None
        ty = first
        if self.at_kw("for"):
            self.advance()
            self.skip_nl()
            trait = _type_label(first)
            ty = self.parse_type()
        while self.at_kw("where"):
            self.parse_where_clause()
        self.skip_nl()
        _, methods = self.parse_members(allow_fields=False)
        decl = ast.ImplDecl(
            trait=trait, type=ty, methods=methods,
            vis=vis, attrs=attrs, line=line, col=col,
        )
        if "unsafe" in attrs:
            try:
                decl.is_unsafe = True  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover
                pass
        return decl

    def parse_members(self, allow_fields: bool):
        self.expect_punct("{")
        fields: list[ast.FieldDecl] = []
        methods: list[ast.FnDecl] = []
        while True:
            self.skip_member_seps()
            if self.at_punct("}") or self.at_eof():
                break
            attrs: list[str] = []
            while self.at_kw("@"):
                attrs.append(self.parse_attr())
                self.skip_nl()
            vis = "priv"
            while self.tok.kind == KEYWORD and self.tok.text in _VIS_KEYWORDS:
                vis = self.tok.text
                self.advance()
                self.skip_nl()
                while self.at_kw("@"):
                    attrs.append(self.parse_attr())
                    self.skip_nl()
            is_static = False
            if self.at_kw("static"):
                is_static = True
                self.advance()
                self.skip_nl()
            t = self.tok
            if (
                self.at_kw("fn")
                or self.at_kw("comptime")
                or self.at_kw("irq")
            ):
                methods.append(self.parse_fn(vis=vis, attrs=attrs, is_static=is_static))
                continue
            if (
                not is_static
                and t.kind == KEYWORD
                and t.text in ("new", "drop")
                and self._next_is_punct("(")
            ):
                methods.append(self.parse_bare_method(vis, attrs))
                continue
            if allow_fields and not is_static:
                line, col = t.line, t.col
                name = self.parse_name()
                self.expect_punct(":")
                self.skip_nl()
                ty = self.parse_type()
                default = None
                if self.at_sym("="):
                    self.advance()
                    self.skip_nl()
                    default = self.parse_expr()
                fields.append(
                    ast.FieldDecl(name=name, type=ty, default=default, line=line, col=col)
                )
                continue
            self.error(f"期望成员声明，得到 {t.text!r}", t)
        self.expect_punct("}")
        return fields, methods

    def parse_bare_method(self, vis, attrs) -> ast.FnDecl:
        t = self.tok
        line, col = t.line, t.col
        name = t.text
        self.advance()
        params = self.parse_params()
        ret = None
        while True:
            self.skip_nl()
            if self.at_kw("where"):
                self.parse_where_clause()
                continue
            if self.at_sym("->"):
                self.advance()
                self.skip_nl()
                ret = self.parse_type()
                continue
            break
        body = None
        if self.at_punct("{"):
            body = self.parse_block()
        elif self.at_sym("=>"):
            self.advance()
            self.skip_nl()
            body = self.parse_expr()
        return ast.FnDecl(
            name=name, params=params, ret=ret, body=body,
            is_new=(name == "new"), is_drop=(name == "drop"),
            vis=vis, attrs=attrs, line=line, col=col,
        )

    # -- mod / static / extern ----------------------------------------
    def parse_mod_decl(self, vis, attrs, line, col) -> ast.ModDecl:
        self.expect_kw("mod")
        self.skip_nl()
        name = self.parse_name()
        self.skip_nl()
        items = None
        if self.at_punct("{"):
            self.advance()
            items = []
            while True:
                self.skip_seps()
                if self.at_punct("}") or self.at_eof():
                    break
                items.extend(self.parse_item_or_use())
                self.skip_seps()
            self.expect_punct("}")
        return ast.ModDecl(
            name=name, items=items, vis=vis, attrs=attrs, line=line, col=col
        )

    def parse_static_decl(self, vis, attrs, line, col) -> ast.StaticDecl:
        self.expect_kw("static")
        mutable = False
        if self.at_kw("mut"):
            mutable = True
            self.advance()
        self.skip_nl()
        name = self.parse_name()
        ty = None
        value = None
        if self.at_punct(":"):
            self.advance()
            self.skip_nl()
            ty = self.parse_type()
        if self.at_sym("="):
            self.advance()
            self.skip_nl()
            value = self.parse_expr()
        at_addr = None
        if self.at_kw("at"):
            self.advance()
            self.skip_nl()
            at_addr = self.parse_expr()
        return ast.StaticDecl(
            name=name, mutable=mutable, type=ty, value=value,
            at_addr=at_addr, vis=vis, attrs=attrs, line=line, col=col,
        )

    def parse_static_binding(self, attrs, line, col) -> ast.StaticDecl:
        name = self.parse_name()
        ty = None
        value = None
        if self.at_punct(":"):
            self.advance(); self.skip_nl(); ty = self.parse_type()
        if self.at_sym("="):
            self.advance(); self.skip_nl(); value = self.parse_expr()
        return ast.StaticDecl(name=name, mutable=False, type=ty, value=value,
                              at_addr=value, attrs=attrs, line=line, col=col)

    def parse_extern_decl(self, vis, attrs, line, col) -> ast.ExternDecl:
        self.expect_kw("extern")
        self.skip_nl()
        t = self.tok
        if t.kind == STRING:
            abi = t.text
            self.advance()
        elif t.kind in (IDENT, RAW_IDENT):
            abi = t.text
            self.advance()
        else:
            self.error("extern 后需要 ABI 字符串", t)
        self.skip_nl()
        if self.at_kw("fn") or self.at_kw("comptime") or self.at_kw("irq"):
            fn = self.parse_fn(vis=vis, attrs=attrs)
            return ast.ExternDecl(
                abi=abi, name=fn.name, params=fn.params, ret=fn.ret,
                members=None, vis=vis, attrs=attrs, line=line, col=col,
            )
        if self.at_punct("{"):
            self.advance()
            members: list[ast.ExternDecl] = []
            while True:
                self.skip_seps()
                if self.at_punct("}") or self.at_eof():
                    break
                while self.at_kw("@"):
                    self.parse_attr()
                    self.skip_nl()
                fn = self.parse_fn(vis=vis, attrs=[])
                members.append(
                    ast.ExternDecl(
                        abi=abi, name=fn.name, params=fn.params, ret=fn.ret,
                        members=None, line=fn.line, col=fn.col,
                    )
                )
                self.skip_seps()
            self.expect_punct("}")
            return ast.ExternDecl(
                abi=abi, name=None, params=[], ret=None,
                members=members, vis=vis, attrs=attrs, line=line, col=col,
            )
        self.error("extern 后需要 fn 声明或 '{' 块")

    # -- macro / attr / section / export ------------------------------
    def parse_macro_decl(self, vis, attrs, line, col) -> ast.MacroDecl:
        self.expect_kw("macro")
        self.skip_nl()
        name = self.parse_name()
        self.expect_punct("(")
        params: list[ast.MacroParam] = []
        self.skip_nl()
        while not self.at_punct(")"):
            pname = self.parse_name()
            self.expect_punct(":")
            self.skip_nl()
            kind = self.parse_name()
            params.append(ast.MacroParam(name=pname, kind=kind))
            self.skip_nl()
            if self.at_punct(","):
                self.advance()
                self.skip_nl()
                continue
            break
        self.expect_punct(")")
        self.skip_nl()
        body = self.parse_macro_body()
        return ast.MacroDecl(
            name=name, params=params, body=body,
            vis=vis, attrs=attrs, line=line, col=col,
        )

    def parse_macro_body(self) -> ast.Block:
        save = self.i
        try:
            return self.parse_block()
        except DsSyntaxError:
            self.i = save
        t = self.tok
        line, col = t.line, t.col
        text = self._collect_raw_braces()
        block = ast.Block(stmts=[], line=line, col=col)
        try:
            block.raw = text  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - dataclass 允许动态属性
            pass
        return block

    def parse_attr_decl(self, vis, attrs, line, col) -> ast.AttrDecl:
        self.expect_kw("attr")
        self.skip_nl()
        name = self.parse_name()
        self.expect_punct("(")
        self.skip_nl()
        if self.tok.kind in (IDENT, RAW_IDENT, KEYWORD) and self.tok.text == "target":
            self.advance()
        else:
            self.error("attr 声明需要 'target: 种类'")
        self.expect_punct(":")
        self.skip_nl()
        target = self.parse_name()
        self.expect_punct(")")
        self.skip_nl()
        fields = self.parse_field_block()
        return ast.AttrDecl(
            name=name, target=target, fields=fields,
            vis=vis, attrs=attrs, line=line, col=col,
        )

    def parse_section_block(self, vis, attrs, line, col) -> ast.SectionBlock:
        self.expect_kw("section")
        self.skip_nl()
        t = self.tok
        if t.kind != STRING:
            self.error("section 后需要字符串段名", t)
        name = t.text
        self.advance()
        self.skip_nl()
        self.expect_punct("{")
        items: list[ast.Item] = []
        while True:
            self.skip_seps()
            if self.at_punct("}") or self.at_eof():
                break
            items.extend(self.parse_item_or_use())
            self.skip_seps()
        self.expect_punct("}")
        return ast.SectionBlock(
            name=name, items=items, vis=vis, attrs=attrs, line=line, col=col
        )

    def parse_export_decl(self, vis, attrs, line, col) -> ast.ExportDecl:
        self.expect_kw("export")
        self.skip_nl()
        names: list[str] = []
        if self.at_punct("{"):
            self.advance()
            self.skip_nl()
            while not self.at_punct("}"):
                names.append(self.parse_dotted_name())
                self.skip_nl()
                if self.at_punct(","):
                    self.advance()
                    self.skip_nl()
                    continue
                break
            self.expect_punct("}")
        else:
            while True:
                names.append(self.parse_dotted_name())
                self.skip_nl()
                if self.at_punct(","):
                    self.advance()
                    self.skip_nl()
                    continue
                break
        return ast.ExportDecl(
            names=names, vis=vis, attrs=attrs, line=line, col=col
        )

    # -- use ------------------------------------------------------------
    def parse_use(self) -> list[ast.Use]:
        self.expect_kw("use")
        self.skip_nl()
        uses: list[ast.Use] = []
        while True:
            t = self.tok
            line, col = t.line, t.col
            parts = [self.parse_name()]
            alias = None
            names = None
            while self.at_op("."):
                self.advance()
                if self.at_punct("{"):
                    self.advance()
                    names = []
                    self.skip_nl()
                    while not self.at_punct("}"):
                        nm = self.parse_name()
                        if self.at_kw("as"):
                            self.advance()
                            alias_name = self.parse_name()
                            nm = f"{nm} as {alias_name}"
                        names.append(nm)
                        self.skip_nl()
                        if self.at_punct(","):
                            self.advance()
                            self.skip_nl()
                            continue
                        break
                    self.expect_punct("}")
                    break
                parts.append(self.parse_name())
            if self.at_kw("as"):
                self.advance()
                self.skip_nl()
                alias = self.parse_name()
            uses.append(
                ast.Use(parts=parts, alias=alias, names=names, line=line, col=col)
            )
            self.skip_nl()
            if self.at_punct(","):
                self.advance()
                self.skip_nl()
                continue
            break
        return uses

    def parse_dotted_name(self) -> str:
        parts = [self.parse_name()]
        while self.at_op("."):
            self.advance()
            self.skip_nl()
            parts.append(self.parse_name())
        return ".".join(parts)

    # ------------------------------------------------------------------
    # 语句
    # ------------------------------------------------------------------
    def parse_body(self) -> ast.Block:
        """精简写法：`{...}` 块，或 `:` 后单条语句（Python 风格）。"""
        if self.flow:
            return self.parse_flow_body()
        if self.at_punct("{"):
            return self.parse_block()
        if self.at_punct(":"):
            t = self.tok
            self.advance()
            self.skip_nl()
            stmt = self.parse_stmt()
            return ast.Block(stmts=[stmt], line=t.line, col=t.col)
        # 精简写法：省略冒号，直接单条语句（如 `if c: a else b` 的 else 分支）
        t = self.tok
        stmt = self.parse_stmt()
        return ast.Block(stmts=[stmt], line=t.line, col=t.col)

    def _atom_start(self) -> bool:
        t = self.tok
        if self.flow and t.kind == OP and t.text == "?":
            return True
        if t.kind in (INT, FLOAT, STRING, FSTRING, BYTES):
            return True
        if t.kind in (IDENT, RAW_IDENT):
            return True
        if t.kind == PUNCT_KIND and t.text in ("(", "["):
            return True
        return False

    def parse_flow_body(self) -> ast.Block:
        """Flow 写法：语句块以 '.' 结束；也兼容 `{...}` / `:单语句`。"""
        if self.at_punct("{"):
            return self.parse_block()
        if self.at_punct(":"):
            t = self.tok
            self.advance()
            self.skip_nl()
            return ast.Block(stmts=[self.parse_stmt()], line=t.line, col=t.col)
        if self.tok.kind != NEWLINE:
            t = self.tok
            return ast.Block(stmts=[self.parse_stmt()], line=t.line, col=t.col)
        t = self.tok
        self.skip_seps()
        stmts = []
        while not self.at_eof():
            if self.tok.kind == OP and self.tok.text == ".":
                self.advance()
                return ast.Block(stmts=stmts, line=t.line, col=t.col)
            # `else` 属于外层 if：它本身可以结束 then 块
            if self.at_kw("else"):
                return ast.Block(stmts=stmts, line=t.line, col=t.col)
            stmts.append(self.parse_stmt())
            self.skip_seps()
        self.error("Flow 语句块缺少 '.' 终止符", t)
        return ast.Block(stmts=stmts, line=t.line, col=t.col)

    def parse_flow_if(self, as_stmt: bool = False) -> ast.Stmt:
        t = self.tok
        self.advance()
        cond = self.parse_expr()
        then_block = self.parse_flow_body()
        else_ = None
        if self.at_punct(";"):
            # 精简替代：`?c: a; b` 用 `;` 代替 `else`
            self.advance()
            else_ = self.parse_flow_body()
        else:
            self.skip_seps()
            if self.at_kw("else"):
                self.advance()
                look = self.tok if self.tok.kind != NEWLINE else self.peek_sig(1)
                if look.kind == OP and look.text == "?":
                    self.skip_nl()
                    else_ = self.parse_flow_if()   # else-if，无需额外块终止符
                else:
                    else_ = self.parse_flow_body()
        node = ast.IfExpr(cond=cond, then_block=then_block, else_=else_, line=t.line, col=t.col)
        if as_stmt:
            return ast.ExprStmt(expr=node, line=t.line, col=t.col)
        return node

    def parse_fn_flow(self) -> ast.FnDecl:
        t = self.tok
        self.advance()  # '\'
        name = self.parse_name()
        params: list[ast.Param] = []
        while True:
            tk = self.tok
            if tk.kind in (NEWLINE, EOF):
                break
            if tk.kind == KEYWORD or (tk.kind == OP):
                break
            if tk.kind not in (IDENT, RAW_IDENT):
                break
            pname = self.parse_name()
            ptype = None
            if self.at_punct(":"):
                self.advance()
                ptype = self.parse_type()
            params.append(ast.Param(name=pname, type=ptype, line=tk.line, col=tk.col))
        ret = None
        if self.at_sym("->"):
            self.advance()
            ret = self.parse_type()
        body = None
        if self.at_sym("="):
            self.advance()
            self.skip_nl()
            body = self.parse_expr()
        elif self.at_punct(":"):
            self.advance()
            self.skip_nl()
            body = ast.Block(stmts=[self.parse_stmt()], line=t.line, col=t.col)
        else:
            body = self.parse_flow_body()
        return ast.FnDecl(
            name=name, params=params, generics=[], ret=ret, body=body,
            vis="priv", attrs=[], line=t.line, col=t.col,
        )

    def parse_block(self) -> ast.Block:
        t = self.tok
        line, col = t.line, t.col
        self.expect_punct("{")
        stmts: list[ast.Stmt] = []
        while True:
            self.skip_seps()
            if self.at_punct("}") or self.at_eof():
                break
            stmts.append(self.parse_stmt())
            self.skip_seps()
        self.expect_punct("}")
        return ast.Block(stmts=stmts, line=line, col=col)

    def parse_stmt(self) -> ast.Stmt:
        t = self.tok
        line, col = t.line, t.col
        if self.at_kw("@") and self.peek_sig(1).text == "asm":
            self.advance(); self.advance()
            self.skip_nl()
            if self.tok.kind == STRING:
                self.advance()
            elif self.at_punct("("):
                depth = 1; self.advance()
                while depth > 0 and not self.at_eof():
                    if self.at_punct("("): depth += 1
                    elif self.at_punct(")"): depth -= 1
                    self.advance()
            return ast.ExprStmt(expr=ast.Lit(value=None, line=line, col=col), line=line, col=col)
        if self.flow and t.kind == OP and t.text == "?":
            return self.parse_flow_if(as_stmt=True)
        if self.flow and t.kind == OP and t.text == "^":
            self.advance()
            value = None
            if not (
                self.tok.kind in (NEWLINE, EOF)
                or (self.tok.kind == OP and self.tok.text == ".")
                or (self.tok.kind == PUNCT_KIND and self.tok.text == "}")
            ):
                value = self.parse_expr()
            return ast.ReturnStmt(value=value, line=line, col=col)
        if self.at_kw("let") or self.at_kw("var"):
            return self.parse_let_stmt()
        if self.at_kw("while"):
            self.advance()
            self.skip_nl()
            self.block_guard += 1
            try:
                cond = self.parse_expr()
            finally:
                self.block_guard -= 1
            body = self.parse_body()
            return ast.WhileStmt(cond=cond, body=body, line=line, col=col)
        if self.at_kw("loop"):
            self.advance()
            body = self.parse_body()
            return ast.LoopStmt(body=body, line=line, col=col)
        if self.at_kw("for"):
            stmt = self.parse_for()
            stmt.line, stmt.col = line, col
            return stmt
        if self.at_kw("break"):
            self.advance()
            value = None
            if not self._stmt_end():
                value = self.parse_expr()
            return ast.BreakStmt(value=value, line=line, col=col)
        if self.at_kw("continue"):
            self.advance()
            return ast.ContinueStmt(line=line, col=col)
        if self.at_kw("return"):
            self.advance()
            value = None
            if not self._stmt_end():
                value = self.parse_expr()
            return ast.ReturnStmt(value=value, line=line, col=col)
        if self.at_kw("goto"):
            self.advance()
            self.skip_nl()
            name = self.parse_name()
            return ast.GotoStmt(name=name, line=line, col=col)
        if self.at_kw("send"):
            self.advance()
            self.skip_nl()
            ch = self.parse_expr()
            self.expect_punct(",")
            self.skip_nl()
            value = self.parse_expr()
            return ast.SendStmt(ch=ch, value=value, line=line, col=col)
        if self.at_kw("assert"):
            self.advance()
            self.skip_nl()
            cond = self.parse_expr()
            msg = None
            if self.at_punct(","):
                self.advance()
                self.skip_nl()
                msg = self.parse_expr()
            return ast.AssertStmt(cond=cond, msg=msg, line=line, col=col)
        if self.at_kw("comptime"):
            nxt = self.peek_sig(1)
            if nxt.text in ("if", "for") or (
                nxt.kind == PUNCT_KIND and nxt.text == "{"
            ):
                self.advance()
                self.skip_nl()
                if self.at_kw("if"):
                    inner = self.parse_if()
                elif self.at_kw("for"):
                    inner = self.parse_for()
                else:
                    blk = self.parse_block()
                    inner = ast.BlockExpr(block=blk, line=line, col=col)
                return ast.ComptimeStmt(inner=inner, line=line, col=col)
            # 其它情况按 "comptime 表达式" 语句处理
            expr = self.parse_expr()
            return ast.ExprStmt(expr=expr, line=line, col=col)
        if self.at_punct("{"):
            if self._looks_like_map():
                expr = self.parse_expr()
                return ast.ExprStmt(expr=expr, line=line, col=col)
            blk = self.parse_block()
            return blk
        # 标签：语句起始 IDENT 后紧跟 ':'
        if (
            t.kind in (IDENT, RAW_IDENT)
            and self._next_is_punct(":")
        ):
            self.advance()
            self.advance()
            return ast.LabelStmt(name=t.text, line=line, col=col)
        # 表达式语句 / 赋值语句
        expr = self.parse_expr()
        if self.tok.kind == OP and self.tok.text in _COMPOUND:
            op = self.tok.text
            self.advance()
            self.skip_nl()
            value = self.parse_expr()
            return ast.AssignStmt(target=expr, value=value, op=op, line=line, col=col)
        if self.at_sym("="):
            self.advance()
            self.skip_nl()
            value = self.parse_expr()
            # 右结合：`a = b = c`
            while self.at_sym("="):
                self.advance()
                self.skip_nl()
                inner = self.parse_expr()
                value = ast.AssignStmt(target=value, value=inner, line=line, col=col)
            return ast.AssignStmt(target=expr, value=value, line=line, col=col)
        return ast.ExprStmt(expr=expr, line=line, col=col)

    def _stmt_end(self) -> bool:
        t = self.tok
        if t.kind in (NEWLINE, EOF):
            return True
        if t.kind == OP and t.text == ".":
            return True
        if t.kind == PUNCT_KIND and t.text in (";", "}", ",", ")"):
            return True
        return False

    def parse_for(self) -> ast.ForStmt:
        t = self.tok
        line, col = t.line, t.col
        self.expect_kw("for")
        self.skip_nl()
        pattern = self.parse_pattern()
        self.expect_kw("in")
        self.skip_nl()
        self.block_guard += 1
        try:
            iterable = self.parse_expr()
        finally:
            self.block_guard -= 1
        body = self.parse_body()
        return ast.ForStmt(
            pattern=pattern, iterable=iterable, body=body, line=line, col=col
        )

    def parse_let_stmt(self) -> ast.LetStmt:
        t = self.tok
        line, col = t.line, t.col
        mutable = t.text == "var"
        self.advance()
        self.skip_nl()
        name = ""
        pattern = None
        if self.tok.kind == BLANK:
            name = "_"
            self.advance()
        else:
            pat = self.parse_pattern()
            if isinstance(pat, ast.BindPat) and pat.sub is None:
                name = pat.name
            else:
                pattern = pat
        ty = None
        if self.at_punct(":"):
            self.advance()
            self.skip_nl()
            ty = self.parse_type()
        value = None
        if self.at_sym("="):
            self.advance()
            self.skip_nl()
            value = self.parse_expr()
        return ast.LetStmt(
            name=name, pattern=pattern, type=ty, value=value,
            mutable=mutable, line=line, col=col,
        )

    # ------------------------------------------------------------------
    # 模式
    # ------------------------------------------------------------------
    def parse_pattern(self) -> ast.Pattern:
        first = self.parse_pattern_atom()
        if not self.at_sym("|"):
            return first
        alts = [first]
        while self.at_sym("|"):
            self.advance()
            self.skip_nl()
            alts.append(self.parse_pattern_atom())
        return ast.OrPat(alts=alts, line=first.line, col=first.col)

    def parse_pattern_atom(self) -> ast.Pattern:
        t = self.tok
        line, col = t.line, t.col
        if t.kind == BLANK:
            self.advance()
            return ast.WildcardPat(line=line, col=col)
        if t.kind in (INT, FLOAT, STRING, BYTES):
            self.advance()
            return ast.LitPat(value=t.text, line=line, col=col)
        if t.kind == PUNCT_KIND:
            if t.text == "[":
                return self.parse_array_pattern()
            if t.text == "{":
                return self.parse_map_pattern()
            if t.text == "(":
                self.advance()
                self.skip_nl()
                pat = self.parse_pattern()
                self.skip_nl()
                self.expect_punct(")")
                return pat
        if t.kind in (IDENT, RAW_IDENT):
            name = t.text
            self.advance()
            if name == "true":
                return ast.LitPat(value=True, line=line, col=col)
            if name == "false":
                return ast.LitPat(value=False, line=line, col=col)
            if self.at_punct("("):
                args = self.parse_pattern_args()
                return ast.CtorPat(name=name, args=args, line=line, col=col)
            if self.at_kw("@"):
                self.advance()
                self.skip_nl()
                sub = self.parse_pattern_atom()
                return ast.BindPat(name=name, sub=sub, line=line, col=col)
            if name == "none":
                return ast.CtorPat(name="none", args=[], line=line, col=col)
            return ast.BindPat(name=name, line=line, col=col)
        self.error(f"期望模式，得到 {t.text!r}", t)

    def parse_pattern_args(self) -> list[ast.Pattern]:
        self.expect_punct("(")
        args: list[ast.Pattern] = []
        self.skip_nl()
        while not self.at_punct(")"):
            args.append(self.parse_pattern())
            self.skip_nl()
            if self.at_punct(","):
                self.advance()
                self.skip_nl()
                continue
            if self.at_punct(")"):
                break
            continue
        self.expect_punct(")")
        return args

    def parse_array_pattern(self) -> ast.ArrayPat:
        t = self.tok
        line, col = t.line, t.col
        self.expect_punct("[")
        items: list[ast.Pattern] = []
        self.skip_nl()
        while not self.at_punct("]"):
            if self.at_eof():
                self.error("数组模式未闭合")
            items.append(self.parse_pattern())
            self.skip_nl()
            if self.at_punct(","):
                self.advance()
                self.skip_nl()
                continue
            if self.at_punct("]"):
                break
            continue
        self.expect_punct("]")
        return ast.ArrayPat(items=items, line=line, col=col)

    def parse_map_pattern(self) -> ast.MapPat:
        t = self.tok
        line, col = t.line, t.col
        self.expect_punct("{")
        pairs: list[tuple[str, ast.Pattern]] = []
        self.skip_nl()
        while not self.at_punct("}"):
            key = self.parse_name()
            self.expect_punct(":")
            self.skip_nl()
            pairs.append((key, self.parse_pattern()))
            self.skip_nl()
            if self.at_punct(","):
                self.advance()
                self.skip_nl()
                continue
            if self.at_punct("}"):
                break
            continue
        self.expect_punct("}")
        return ast.MapPat(pairs=pairs, line=line, col=col)

    # ------------------------------------------------------------------
    # 类型
    # ------------------------------------------------------------------
    def parse_type(self) -> ast.TypeExpr:
        self.skip_nl()
        t = self.tok
        line, col = t.line, t.col
        if t.kind == OP and t.text == "*":
            # Cut 指针类型 *T：base 类型系统用 PtrType 承载
            self.advance()
            self.skip_nl()
            return ast.PtrType(inner=self.parse_type(), line=line, col=col)
        if t.kind == BLANK:
            self.advance()
            return ast.InferredType(line=line, col=col)
        if t.kind == PUNCT_KIND:
            if t.text == "(":
                self.advance()
                self.skip_nl()
                if self.at_punct(")"):
                    self.advance()
                    return ast.UnitType(line=line, col=col)
                inner = self.parse_type()
                self.skip_nl()
                self.expect_punct(")")
                return inner
            if t.text == "[":
                return self.parse_bracket_type()
        if t.kind == OP and t.text == "!":
            self.advance()
            return ast.TypeName(name="!", line=line, col=col)
        if t.kind == KEYWORD:
            kw = t.text
            if kw in ("ref", "ptr"):
                kw_tok = self.tok
                self.advance()
                self.skip_nl()
                mutable = False
                if self.at_kw("mut"):
                    mutable = True
                    self.advance()
                    self.skip_nl()
                inner = None
                # `ptr[T]` / `ref[T]`（方括号紧贴关键字）是泛型实参形式；
                # `ref [i32]`（有空白）则是"指向切片"的 T。
                if self._bracket_adjacent(kw_tok):
                    self.advance()  # '['
                    self.skip_nl()
                    inner = self.parse_type()
                    self.skip_nl()
                    self.expect_punct("]")
                else:
                    inner = self.parse_type()
                cls = ast.RefType if kw == "ref" else ast.PtrType
                return cls(inner=inner, mutable=mutable, line=line, col=col)
            if kw == "volatile":
                self.advance()
                self.skip_nl()
                return ast.VolatileType(inner=self.parse_type(), line=line, col=col)
            if kw == "dyn":
                self.advance()
                self.skip_nl()
                return ast.DynType(inner=self.parse_type(), line=line, col=col)
            if kw == "raw":
                self.advance()
                return ast.RawType(line=line, col=col)
            if kw == "fn":
                self.advance()
                self.skip_nl()
                self.expect_punct("(")
                params: list[ast.TypeExpr] = []
                self.skip_nl()
                while not self.at_punct(")"):
                    params.append(self.parse_type())
                    self.skip_nl()
                    if self.at_punct(","):
                        self.advance()
                        self.skip_nl()
                        continue
                    if self.at_punct(")"):
                        break
                self.expect_punct(")")
                ret = None
                if self.at_sym("->"):
                    self.advance()
                    self.skip_nl()
                    ret = self.parse_type()
                return ast.FnType(params=params, ret=ret, line=line, col=col)
            if kw == "opt":
                self.advance()
                self.skip_nl()
                self.expect_punct("[")
                inner = self.parse_type()
                self.skip_nl()
                self.expect_punct("]")
                return ast.OptType(inner=inner, line=line, col=col)
            if kw == "res":
                self.advance()
                self.skip_nl()
                self.expect_punct("[")
                ok = self.parse_type()
                err = None
                self.skip_nl()
                if self.at_punct(","):
                    self.advance()
                    self.skip_nl()
                    err = self.parse_type()
                self.skip_nl()
                self.expect_punct("]")
                return ast.ResType(ok=ok, err=err, line=line, col=col)
            if kw in ("rc", "arc", "gc", "chan", "mutex", "task", "thread"):
                self.advance()
                inner = None
                size = None
                self.skip_nl()
                if self.at_punct("["):
                    self.advance()
                    self.skip_nl()
                    inner = self.parse_type()
                    self.skip_nl()
                    if self.at_punct(";"):
                        self.advance()
                        self.skip_nl()
                        if self.tok.kind == INT:
                            size = self.tok.text
                            self.advance()
                        else:
                            size = self.parse_expr()
                        self.skip_nl()
                    self.expect_punct("]")
                return ast.BoxType(kind=kw, inner=inner, size=size, line=line, col=col)
            # 其它关键字（例如 self）按类型名处理
            self.advance()
            node = ast.TypeName(name=kw, line=line, col=col)
            if self.at_punct("["):
                node.args = self.parse_type_args()
            return node
        if t.kind in (IDENT, RAW_IDENT):
            self.advance()
            if t.text == "task" and self.at_punct("["):
                inner = None
                self.advance()
                self.skip_nl()
                inner = self.parse_type()
                self.skip_nl()
                self.expect_punct("]")
                return ast.BoxType(kind="task", inner=inner, line=line, col=col)
            node = ast.TypeName(name=t.text, line=line, col=col)
            if self.at_punct("["):
                node.args = self.parse_type_args()
            return node
        self.error(f"期望类型，得到 {t.text!r}", t)

    def parse_type_args(self) -> list:
        self.expect_punct("[")
        args: list = []
        self.skip_nl()
        if self.at_punct("]"):
            self.advance()
            return args
        while True:
            self.skip_nl()
            t = self.tok
            if t.kind in (INT, FLOAT, STRING, BYTES):
                self.advance()
                args.append(ast.Lit(value=t.text, line=t.line, col=t.col))
            else:
                save = self.i
                parsed_as_type = False
                try:
                    ty = self.parse_type()
                    self.skip_nl()
                    if self.at_punct(",") or self.at_punct("]"):
                        args.append(ty)
                        parsed_as_type = True
                except DsSyntaxError:
                    pass
                if not parsed_as_type:
                    self.i = save
                    args.append(self.parse_expr())
            self.skip_nl()
            if self.at_punct(","):
                self.advance()
                self.skip_nl()
                continue
            break
        self.expect_punct("]")
        return args

    def parse_bracket_type(self) -> ast.TypeExpr:
        t = self.tok
        line, col = t.line, t.col
        self.expect_punct("[")
        self.skip_nl()
        if self.at_punct("]"):
            # []T 切片前缀
            self.advance()
            self.skip_nl()
            inner = self.parse_type()
            return ast.SliceType(elem=inner, line=line, col=col)
        elem = self.parse_type()
        self.skip_nl()
        if self.at_punct(";"):
            self.advance()
            self.skip_nl()
            if self.tok.kind == INT:
                size = self.tok.text
                self.advance()
            else:
                size = self.parse_expr()
            self.skip_nl()
            self.expect_punct("]")
            return ast.ArrayType(elem=elem, size=size, line=line, col=col)
        if self.at_punct(","):
            # `[T, U, ...]`：作为泛型实参序列承载在 TypeName 上
            args = [elem]
            while self.at_punct(","):
                self.advance()
                self.skip_nl()
                args.append(self.parse_type())
                self.skip_nl()
            self.expect_punct("]")
            return ast.TypeName(name="", args=args, line=line, col=col)
        self.expect_punct("]")
        return ast.SliceType(elem=elem, line=line, col=col)

    # ------------------------------------------------------------------
    # 表达式
    # ------------------------------------------------------------------
    def parse_expr(self, min_prec: int = 1) -> ast.Expr:
        left = self.parse_unary()
        last_nonassoc = None
        while True:
            t = self.tok
            if t.kind == NEWLINE:
                break
            if t.kind not in (OP, KEYWORD):
                break
            op = t.text
            prec = _PREC.get(op)
            if prec is None or prec < min_prec:
                break
            if op in _NONASSOC and last_nonassoc == prec:
                self.error(f"运算符 {op} 不可链式使用", t)
            self.advance()
            self.skip_nl()
            line, col = t.line, t.col
            if op == "as":
                ty = self.parse_type()
                left = ast.Cast(expr=left, type=ty, line=line, col=col)
                last_nonassoc = None
                continue
            if op == "is":
                target = self.parse_is_target()
                left = ast.IsTest(expr=left, target=target, line=line, col=col)
            elif op == "in":
                right = self.parse_expr(prec + 1)
                left = ast.InTest(item=left, container=right, line=line, col=col)
            else:
                right = self.parse_expr(prec + 1)
                left = ast.Binary(op=op, left=left, right=right, line=line, col=col)
            last_nonassoc = prec if op in _NONASSOC else None
        return left

    def parse_is_target(self):
        t = self.tok
        if t.kind in (IDENT, RAW_IDENT):
            nxt = self.peek_sig(1)
            if nxt.kind == PUNCT_KIND and nxt.text == "(":
                return self.parse_pattern()
        return self.parse_type()

    def parse_unary(self) -> ast.Expr:
        t = self.tok
        line, col = t.line, t.col
        if t.kind == OP:
            if t.text in ("-", "!", "~"):
                self.advance()
                self.skip_nl()
                return ast.Unary(op=t.text, expr=self.parse_unary(), line=line, col=col)
            if t.text == "&":
                self.advance()
                mutable = False
                if self.at_kw("mut"):
                    mutable = True
                    self.advance()
                self.skip_nl()
                return ast.AddrOf(
                    expr=self.parse_unary(), mutable=mutable, line=line, col=col
                )
            if t.text == "*":
                self.advance()
                self.skip_nl()
                return ast.Deref(expr=self.parse_unary(), line=line, col=col)
        if t.kind == KEYWORD:
            kw = t.text
            if kw == "try":
                self.advance()
                self.skip_nl()
                if self.at_punct("{"):
                    return self.parse_try_catch(line, col)
                return ast.TryExpr(expr=self.parse_unary(), line=line, col=col)
            if kw == "recv":
                self.advance()
                self.skip_nl()
                return ast.RecvExpr(ch=self.parse_unary(), line=line, col=col)
            if kw == "wait":
                self.advance()
                self.skip_nl()
                return ast.WaitExpr(handle=self.parse_unary(), line=line, col=col)
            if kw == "sizeof":
                return self.parse_sizeof_like(ast.SizeofExpr)
            if kw == "alignof":
                return self.parse_sizeof_like(ast.AlignofExpr)
            if kw == "typeinfo":
                return self.parse_sizeof_like(ast.TypeinfoExpr)
            if kw == "comptime":
                return self.parse_comptime_expr()
            if kw == "panic":
                self.advance()
                self.skip_nl()
                operand = self.parse_unary()
                return ast.Call(
                    fn=ast.Var(name="panic", line=line, col=col),
                    args=[operand], line=line, col=col,
                )
        expr = self.parse_postfix()
        if self.flow:
            # 并置调用：p "hi" / add x y / f (x+1)
            while self._atom_start():
                args = []
                while self._atom_start():
                    args.append(self.parse_postfix())
                expr = ast.Call(fn=expr, args=args, line=t.line, col=t.col)
        return expr

    def parse_sizeof_like(self, cls):
        t = self.tok
        line, col = t.line, t.col
        self.advance()
        self.skip_nl()
        self.expect_punct("(")
        self.skip_nl()
        if self.at_punct(")"):
            self.error(f"{t.text} 的参数不能为空")
        save = self.i
        try:
            ty = self.parse_type()
            self.skip_nl()
            if not self.at_punct(")"):
                raise DsSyntaxError(
                    "不是类型", self.filename, self.tok.line, self.tok.col
                )
            self.advance()
            return cls(target=ty, line=line, col=col)
        except DsSyntaxError:
            self.i = save
        expr = self.parse_expr()
        self.skip_nl()
        self.expect_punct(")")
        return cls(target=expr, line=line, col=col)

    def parse_comptime_expr(self) -> ast.ComptimeExpr:
        t = self.tok
        line, col = t.line, t.col
        self.expect_kw("comptime")
        self.skip_nl()
        if self.at_kw("if"):
            return ast.ComptimeExpr(inner=self.parse_if(), line=line, col=col)
        if self.at_punct("{"):
            blk = self.parse_block()
            return ast.ComptimeExpr(
                inner=ast.BlockExpr(block=blk, line=line, col=col),
                line=line, col=col,
            )
        if self.at_kw("for"):
            self.error("comptime for 只能作为语句使用")
        return ast.ComptimeExpr(inner=self.parse_unary(), line=line, col=col)

    def parse_postfix(self) -> ast.Expr:
        node = self.parse_primary()
        while True:
            t = self.tok
            if t.kind == NEWLINE:
                break
            if t.kind == PUNCT_KIND and t.text == "(":
                args, kwargs = self.parse_call_args()
                node = ast.Call(
                    fn=node, args=args, kwargs=kwargs, line=node.line, col=node.col
                )
                continue
            if t.kind == PUNCT_KIND and t.text == "[" and self._adjacent_prev():
                # `expr[` 才是索引/切片；`[1 2] [3 4]` 中的方括号属于下一个数组元素
                self.advance()
                self.skip_nl()
                lo = None
                if not self.at_punct(":"):
                    lo = self.parse_expr()
                    self.skip_nl()
                if self.at_punct(":"):
                    self.advance()
                    self.skip_nl()
                    hi = None
                    if not self.at_punct("]"):
                        hi = self.parse_expr()
                        self.skip_nl()
                    self.expect_punct("]")
                    node = ast.SliceExpr(
                        obj=node, lo=lo, hi=hi, line=node.line, col=node.col
                    )
                else:
                    self.expect_punct("]")
                    node = ast.Index(
                        obj=node, index=lo, line=node.line, col=node.col
                    )
                continue
            if t.kind == OP and t.text == ".":
                self.advance()
                self.skip_nl()
                nt = self.tok
                if nt.kind not in (IDENT, RAW_IDENT, KEYWORD):
                    self.error(f"'.' 后期望名字，得到 {nt.text!r}", nt)
                name = nt.text
                self.advance()
                if (
                    name == "new"
                    and isinstance(node, (ast.Var, ast.Path))
                    and self.at_punct("(")
                ):
                    type_name = (
                        node.name if isinstance(node, ast.Var) else ".".join(node.parts)
                    )
                    args, kwargs = self.parse_call_args()
                    node = ast.NewExpr(
                        type_name=type_name, args=args, kwargs=kwargs,
                        line=node.line, col=node.col,
                    )
                else:
                    node = ast.AttrExpr(
                        obj=node, name=name, line=node.line, col=node.col
                    )
                continue
            break
        return node

    def parse_call_args(self):
        self.expect_punct("(")
        args: list[ast.Expr] = []
        kwargs: list[tuple[str, ast.Expr]] = []
        self.skip_nl()
        while not self.at_punct(")"):
            if self.at_eof():
                self.error("调用参数未闭合（缺少 ')'）")
            t = self.tok
            if t.kind in (IDENT, RAW_IDENT) and self._next_is_punct(":"):
                name = t.text
                self.advance()
                self.advance()
                self.skip_nl()
                kwargs.append((name, self.parse_expr()))
            else:
                args.append(self.parse_expr())
            self.skip_nl()
            if self.at_punct(","):
                self.advance()
                self.skip_nl()
                continue
            if self.at_punct(")"):
                break
        self.expect_punct(")")
        return args, kwargs

    def parse_primary(self) -> ast.Expr:
        t = self.tok
        line, col = t.line, t.col
        if self.flow and t.kind == OP and t.text == "?":
            return self.parse_flow_if()
        if t.kind in (INT, FLOAT, STRING, BYTES):
            self.advance()
            return ast.Lit(value=t.text, line=line, col=col)
        if t.kind == FSTRING:
            self.advance()
            return self.parse_fstring(t)
        if t.kind == BLANK:
            self.advance()
            return ast.Var(name="_", line=line, col=col)
        if t.kind == PUNCT_KIND:
            if t.text == "[":
                return self.parse_array_lit()
            if t.text == "{":
                if self.block_guard > 0:
                    self.error("条件/迭代表达式后应直接跟块，不能把 '{' 当作表达式")
                return self.parse_brace_expr()
            if t.text == "(":
                self.advance()
                self.skip_nl()
                expr = self.parse_expr()
                self.skip_nl()
                self.expect_punct(")")
                return expr
        if t.kind == KEYWORD:
            kw = t.text
            if kw == "@":
                return self.parse_unsafe_block()
            if kw in ("self", "super"):
                self.advance()
                return ast.Var(name=kw, line=line, col=col)
            if kw == "recover":
                self.advance()
                return ast.Var(name="recover", line=line, col=col)
            if kw == "if":
                return self.parse_if()
            if kw == "loop":
                self.advance()
                self.skip_nl()
                return ast.LoopExpr(body=self.parse_body(), line=line, col=col)
            if kw == "match":
                return self.parse_match()
            if kw == "spawn":
                self.advance()
                self.skip_nl()
                if self.at_punct("{"):
                    body = self.parse_block()
                else:
                    body = self.parse_expr()
                return ast.SpawnExpr(body=body, line=line, col=col)
            if kw == "go":
                self.advance()
                self.skip_nl()
                return ast.GoExpr(call=self.parse_expr(), line=line, col=col)
            if kw in ("thread", "mutex", "rc", "arc", "gc"):
                self.advance()
                self.skip_nl()
                self.expect_punct("(")
                self.skip_nl()
                arg = self.parse_expr()
                self.skip_nl()
                self.expect_punct(")")
                return ast.Call(
                    fn=ast.Var(name=kw, line=line, col=col),
                    args=[arg], line=line, col=col,
                )
            if kw == "chan":
                self.advance()
                self.skip_nl()
                if self.at_punct("["):
                    self.advance()
                    self.skip_nl()
                    self.parse_type()
                    self.skip_nl()
                    self.expect_punct("]")
                cap: ast.Expr = ast.Lit(value=0, line=line, col=col)
                self.skip_nl()
                if self.at_punct("("):
                    self.advance()
                    self.skip_nl()
                    if not self.at_punct(")"):
                        cap = self.parse_expr()
                        self.skip_nl()
                    self.expect_punct(")")
                return ast.Call(
                    fn=ast.Var(name="chan", line=line, col=col),
                    args=[cap], line=line, col=col,
                )
            if kw == "alloc":
                self.advance()
                self.skip_nl()
                self.expect_punct("(")
                self.skip_nl()
                a = self.parse_expr()
                self.skip_nl()
                if self.at_punct(","):
                    self.advance(); self.skip_nl()
                    b = self.parse_expr()
                else:
                    b = ast.Lit(value=1, line=line, col=col)
                self.skip_nl()
                self.expect_punct(")")
                return ast.Call(
                    fn=ast.Var(name="alloc", line=line, col=col),
                    args=[a, b], line=line, col=col,
                )
            if kw == "free":
                self.advance()
                self.skip_nl()
                arg = self.parse_unary()
                return ast.Call(
                    fn=ast.Var(name="free", line=line, col=col),
                    args=[arg], line=line, col=col,
                )
            if kw == "asm":
                return self.parse_asm()
            if kw == "fn":
                return self.parse_fn_lit()
            if kw == "new":
                self.advance()
                self.skip_nl()
                args, kwargs = self.parse_call_args()
                return ast.NewExpr(
                    type_name="", args=args, kwargs=kwargs, line=line, col=col
                )
        if t.kind in (IDENT, RAW_IDENT):
            name = t.text
            self.advance()
            if name == "true":
                return ast.Lit(value=True, line=line, col=col)
            if name == "false":
                return ast.Lit(value=False, line=line, col=col)
            return ast.Var(name=name, line=line, col=col)
        self.error(f"期望表达式，得到 {t.text!r}", t)

    def parse_unsafe_block(self) -> ast.UnsafeBlock:
        t = self.tok
        line, col = t.line, t.col
        self.expect_kw("@")
        self.skip_nl()
        nt = self.tok
        if nt.text != "unsafe":
            self.error("表达式位置的 '@' 只支持 @unsafe { ... }", nt)
        self.advance()
        self.skip_nl()
        if not self.at_punct("{"):
            self.error("@unsafe 后需要块")
        blk = self.parse_block()
        return ast.UnsafeBlock(block=blk, line=line, col=col)

    def parse_fstring(self, tok) -> ast.Expr:
        raw = tok.text
        parts: list = []
        buf: list[str] = []

        def flush() -> None:
            if not buf:
                return
            seg = "".join(buf)
            buf.clear()
            try:
                parts.append(_lexer._decode_string(
                    '"' + seg + '"', self.filename, tok.line, tok.col))
            except Exception:
                parts.append(seg)

        i = 0
        while i < len(raw):
            ch = raw[i]
            if ch == "{" and i + 1 < len(raw) and raw[i + 1] == "{":
                buf.append("{")
                i += 2
                continue
            if ch == "}" and i + 1 < len(raw) and raw[i + 1] == "}":
                buf.append("}")
                i += 2
                continue
            if ch == "{":
                j = raw.find("}", i + 1)
                if j < 0:
                    self.error("f-string 插值未闭合", tok)
                expr_src = raw[i + 1:j].strip()
                if not expr_src:
                    self.error("f-string 插值不能为空", tok)
                flush()
                parts.append(Parser(expr_src, self.filename).parse_expr())
                i = j + 1
                continue
            buf.append(ch)
            i += 1
        flush()
        return ast.FString(parts=parts, line=tok.line, col=tok.col)

    def parse_fn_lit(self) -> ast.FnLit:
        t = self.tok
        line, col = t.line, t.col
        self.expect_kw("fn")
        self.skip_nl()
        params = self.parse_params()
        ret = None
        while True:
            self.skip_nl()
            if self.at_sym("->"):
                self.advance()
                self.skip_nl()
                ret = self.parse_type()
                continue
            break
        if not self.at_sym("=>"):
            self.error("匿名函数需要 '=>' 表达式体")
        self.advance()
        self.skip_nl()
        body = self.parse_expr()
        return ast.FnLit(params=params, ret=ret, body=body, line=line, col=col)

    def parse_asm(self) -> ast.AsmExpr:
        t = self.tok
        line, col = t.line, t.col
        self.expect_kw("asm")
        self.skip_nl()
        if self.tok.kind == STRING:
            text = self.tok.text
            self.advance()
            return ast.AsmExpr(text=text, line=line, col=col)
        if self.at_punct("{"):
            text = self._collect_raw_braces()
            return ast.AsmExpr(text=text, line=line, col=col)
        self.error("asm 后需要字符串或 '{' 操作数块")

    def parse_array_lit(self) -> ast.ArrayLit:
        t = self.tok
        line, col = t.line, t.col
        self.expect_punct("[")
        items: list[ast.Expr] = []
        self.skip_nl()
        while not self.at_punct("]"):
            if self.at_eof():
                self.error("数组字面量未闭合")
            items.append(self.parse_expr())
            self.skip_nl()
            if self.at_punct(","):
                self.advance()
                self.skip_nl()
                continue
            if self.at_punct("]"):
                break
        self.expect_punct("]")
        return ast.ArrayLit(items=items, line=line, col=col)

    def _looks_like_map(self) -> bool:
        if not self.at_punct("{"):
            return False
        j = self._sig_index(self.i + 1)
        t = self.toks[j]
        if t.kind == PUNCT_KIND and t.text == ":":
            return True  # {:} 空映射
        if t.kind in (IDENT, RAW_IDENT, STRING, INT, FLOAT, BYTES):
            j2 = self._sig_index(j + 1)
            t2 = self.toks[j2]
            return t2.kind == PUNCT_KIND and t2.text == ":"
        return False

    def parse_brace_expr(self) -> ast.Expr:
        if self._looks_like_map():
            return self.parse_map_lit()
        t = self.tok
        line, col = t.line, t.col
        blk = self.parse_block()
        return ast.BlockExpr(block=blk, line=line, col=col)

    def parse_map_lit(self) -> ast.MapLit:
        t = self.tok
        line, col = t.line, t.col
        self.expect_punct("{")
        pairs: list[tuple[ast.Expr, ast.Expr]] = []
        self.skip_nl()
        if self.at_punct(":"):
            self.advance()
            self.skip_nl()
            self.expect_punct("}")
            return ast.MapLit(pairs=[], line=line, col=col)
        while not self.at_punct("}"):
            if self.at_eof():
                self.error("映射字面量未闭合")
            key = self.parse_expr()
            self.skip_nl()
            self.expect_punct(":")
            self.skip_nl()
            value = self.parse_expr()
            pairs.append((key, value))
            self.skip_nl()
            if self.at_punct(","):
                self.advance()
                self.skip_nl()
                continue
            if self.at_punct("}"):
                break
        self.expect_punct("}")
        return ast.MapLit(pairs=pairs, line=line, col=col)

    def parse_if(self) -> ast.IfExpr:
        t = self.tok
        line, col = t.line, t.col
        self.expect_kw("if")
        self.skip_nl()
        self.block_guard += 1
        try:
            cond = self.parse_expr()
        finally:
            self.block_guard -= 1
        self.skip_nl()
        then_block = self.parse_body()
        else_ = None
        self.skip_nl()
        if self.at_kw("else"):
            self.advance()
            self.skip_nl()
            if self.at_kw("if"):
                else_ = self.parse_if()
            else:
                else_ = self.parse_body()
        return ast.IfExpr(
            cond=cond, then_block=then_block, else_=else_, line=line, col=col
        )

    def parse_match(self) -> ast.MatchExpr:
        t = self.tok
        line, col = t.line, t.col
        self.expect_kw("match")
        self.skip_nl()
        self.block_guard += 1
        try:
            subject = self.parse_expr()
        finally:
            self.block_guard -= 1
        self.skip_nl()
        self.expect_punct("{")
        arms: list[ast.MatchArm] = []
        while True:
            self.skip_member_seps()
            if self.at_punct("}") or self.at_eof():
                break
            at = self.tok
            arm_line, arm_col = at.line, at.col
            pattern = self.parse_pattern()
            self.skip_nl()
            guard = None
            if self.at_kw("when"):
                self.advance()
                self.skip_nl()
                guard = self.parse_expr()
            self.skip_nl()
            if not self.at_sym("=>"):
                self.error("match 分支需要 '=>'")
            self.advance()
            self.skip_nl()
            body = self.parse_arm_body()
            arms.append(
                ast.MatchArm(
                    pattern=pattern, guard=guard, body=body,
                    line=arm_line, col=arm_col,
                )
            )
            self.skip_member_seps()
        self.expect_punct("}")
        return ast.MatchExpr(subject=subject, arms=arms, line=line, col=col)

    def parse_arm_body(self):
        if self.at_punct("{"):
            if self._looks_like_map():
                return self.parse_expr()
            return self.parse_block()
        t = self.tok
        if t.kind == KEYWORD and t.text in _STMT_ONLY_START:
            return self.parse_stmt()
        expr = self.parse_expr()
        if self.at_sym("="):
            line, col = t.line, t.col
            self.advance()
            self.skip_nl()
            value = self.parse_expr()
            return ast.AssignStmt(target=expr, value=value, line=line, col=col)
        return expr

    def parse_try_catch(self, line, col) -> ast.TryCatch:
        blk = self.parse_block()
        catches: list[ast.CatchArm] = []
        self.skip_nl()
        while self.at_kw("catch"):
            ct = self.tok
            self.advance()
            self.skip_nl()
            kind = "error"
            name = None
            if self.at_kw("panic"):
                kind = "panic"
                self.advance()
                self.skip_nl()
                if self.tok.kind in (IDENT, RAW_IDENT):
                    name = self.tok.text
                    self.advance()
            else:
                if self.tok.kind in (IDENT, RAW_IDENT):
                    name = self.tok.text
                    self.advance()
            self.skip_nl()
            if not self.at_punct("{"):
                self.error("catch 后需要块")
            catch_block = self.parse_block()
            catches.append(
                ast.CatchArm(
                    kind=kind, name=name, block=catch_block,
                    line=ct.line, col=ct.col,
                )
            )
            self.skip_nl()
        if not catches:
            self.error("try 块后至少需要一个 catch", self.tok)
        return ast.TryCatch(
            block=blk, catches=catches, line=line, col=col
        )

    # ------------------------------------------------------------------
    # 原始 token 收集
    # ------------------------------------------------------------------
    def _collect_raw_braces(self) -> str:
        self.expect_punct("{")
        depth = 1
        toks = []
        while depth > 0 and not self.at_eof():
            t = self.tok
            if t.kind == PUNCT_KIND and t.text == "{":
                depth += 1
                toks.append(t)
                self.advance()
            elif t.kind == PUNCT_KIND and t.text == "}":
                depth -= 1
                if depth == 0:
                    self.advance()
                    break
                toks.append(t)
                self.advance()
            else:
                toks.append(t)
                self.advance()
        return _join_tokens(toks)


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------
def parse_program(src: str, filename: str = "<source>") -> ast.Program:
    """把完整源文件解析为 ``ast.Program``。"""
    return Parser(src, filename).parse_program()


def parse_repl(src: str, filename: str = "<repl>") -> list[ast.Node]:
    """把 REPL 输入解析为顶层项与语句的混合列表。"""
    return Parser(src, filename).parse_repl()
