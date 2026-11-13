# -*- coding: utf-8 -*-
"""``dsv01.parser`` 单元测试（unittest，仅标准库）。

覆盖任务要求的全部主题：
优先级/结合性（含 ``|>``、``as``、位运算层级）、容器与 ``{``/``{:}`` 消歧、
``if`` 条件不吃块、``match`` + ``when`` + ``|`` 模式、``try``/``catch``/``catch panic``、
class/extends/new/drop、trait/impl、type 字段默认值、macro/attr/section/extern/static、
模式解构与 ``is``、``&``/``*``（AddrOf/Deref）、命名实参，以及 4 个示例文件。
"""

import glob
import os
import unittest

from dsv01 import ast
from dsv01.lexer import DsSyntaxError
from dsv01.parser import Parser, parse_program, parse_repl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------
def program(src: str, filename: str = "<test>") -> ast.Program:
    return parse_program(src, filename)


def block_of(src: str) -> ast.Block:
    """把一段语句包进函数体，返回函数体块。"""
    prog = program("fn __test__() {\n" + src + "\n}\n")
    fn = prog.items[0]
    assert isinstance(fn, ast.FnDecl)
    return fn.body


def stmt(src: str) -> ast.Stmt:
    return block_of(src).stmts[0]


def value_of(src: str) -> ast.Expr:
    s = stmt("let __value = " + src)
    assert isinstance(s, ast.LetStmt), f"期望 LetStmt，得到 {type(s).__name__}"
    return s.value


def type_of(src: str) -> ast.TypeExpr:
    s = stmt("let __value: " + src + " = z")
    assert isinstance(s, ast.LetStmt), f"期望 LetStmt，得到 {type(s).__name__}"
    return s.type


def items_of(src: str):
    return program(src).items


def item_of(src: str, cls=ast.FnDecl):
    for item in items_of(src):
        if isinstance(item, cls):
            return item
    raise AssertionError(f"没找到 {cls.__name__}")


# ---------------------------------------------------------------------------
# 1. 优先级与结合性
# ---------------------------------------------------------------------------
class TestPrecedence(unittest.TestCase):
    def test_multiplicative_over_additive(self):
        e = value_of("1 + 2 * 3")
        self.assertIsInstance(e, ast.Binary)
        self.assertEqual(e.op, "+")
        self.assertEqual(e.left.value, 1)
        self.assertIsInstance(e.right, ast.Binary)
        self.assertEqual(e.right.op, "*")

    def test_additive_left_assoc(self):
        e = value_of("1 - 2 - 3")
        self.assertEqual(e.op, "-")
        self.assertIsInstance(e.left, ast.Binary)
        self.assertEqual(e.left.op, "-")
        self.assertEqual(e.right.value, 3)

    def test_shift_between_additive_and_compare(self):
        # (a + b) << c < d
        e = value_of("a + b << c < d")
        self.assertEqual(e.op, "<")
        self.assertIsInstance(e.left, ast.Binary)
        self.assertEqual(e.left.op, "<<")
        self.assertEqual(e.left.left.op, "+")

    def test_bitwise_levels(self):
        # a | (b ^ (c & d))
        e = value_of("a | b ^ c & d")
        self.assertEqual(e.op, "|")
        self.assertEqual(e.right.op, "^")
        self.assertEqual(e.right.right.op, "&")

    def test_equality_binds_tighter_than_bitand_per_spec(self):
        # 规范 §2.2：& 位于 == 之下 -> (a == b) & c
        e = value_of("a == b & c")
        self.assertEqual(e.op, "&")
        self.assertEqual(e.left.op, "==")
        e2 = value_of("a & b == c")
        self.assertEqual(e2.op, "&")
        self.assertEqual(e2.right.op, "==")

    def test_logical_levels(self):
        e = value_of("a && b || c && d")
        self.assertEqual(e.op, "||")
        self.assertEqual(e.left.op, "&&")
        self.assertEqual(e.right.op, "&&")

    def test_pipeline_left_assoc_and_lowest(self):
        e = value_of("a |> f |> g")
        self.assertEqual(e.op, "|>")
        self.assertIsInstance(e.left, ast.Binary)
        self.assertEqual(e.left.op, "|>")
        self.assertEqual(e.left.left.name, "a")
        # |> 低于 ||
        e2 = value_of("a || b |> f")
        self.assertEqual(e2.op, "|>")
        self.assertEqual(e2.left.op, "||")

    def test_as_binds_above_multiplicative(self):
        # a * (b as u32)
        e = value_of("a * b as u32")
        self.assertEqual(e.op, "*")
        self.assertIsInstance(e.right, ast.Cast)
        self.assertEqual(e.right.type.name, "u32")

    def test_as_chain(self):
        e = value_of("x as u32 as u64")
        self.assertIsInstance(e, ast.Cast)
        self.assertEqual(e.type.name, "u64")
        self.assertIsInstance(e.expr, ast.Cast)
        self.assertEqual(e.expr.type.name, "u32")

    def test_unary_tighter_than_binary(self):
        e = value_of("-a * b")
        self.assertEqual(e.op, "*")
        self.assertEqual(e.left.op, "-")
        self.assertIsInstance(e.left, ast.Unary)

    def test_comparison_non_assoc_raises(self):
        with self.assertRaises(DsSyntaxError):
            value_of("1 < 2 < 3")

    def test_deref_reads_as_postfix(self):
        # `*p.field` == `*(p.field)`
        e = value_of("*p.field")
        self.assertIsInstance(e, ast.Deref)
        self.assertIsInstance(e.expr, ast.AttrExpr)
        self.assertEqual(e.expr.name, "field")


# ---------------------------------------------------------------------------
# 2. 字面量、主表达式、调用
# ---------------------------------------------------------------------------
class TestPrimary(unittest.TestCase):
    def test_int_literals(self):
        self.assertEqual(value_of("42").value, 42)
        self.assertEqual(value_of("0x10").value, 16)
        self.assertEqual(value_of("1_000_000").value, 1000000)
        self.assertEqual(value_of("0b1010").value, 10)

    def test_float_string_bytes_bool(self):
        self.assertAlmostEqual(value_of("1.5").value, 1.5)
        self.assertEqual(value_of('"hi"').value, "hi")
        self.assertEqual(value_of('b"ab"').value, b"ab")
        self.assertIs(value_of("true").value, True)
        self.assertIs(value_of("false").value, False)

    def test_vars_and_raw_ident(self):
        self.assertEqual(value_of("foo").name, "foo")
        self.assertEqual(value_of("`free`").name, "free")
        self.assertEqual(value_of("self").name, "self")
        self.assertEqual(value_of("super").name, "super")

    def test_call_attr_index_slice(self):
        call = value_of("a.b(1)")
        self.assertIsInstance(call, ast.Call)
        self.assertIsInstance(call.fn, ast.AttrExpr)
        idx = value_of("xs[0]")
        self.assertIsInstance(idx, ast.Index)
        sl = value_of("xs[1:3]")
        self.assertIsInstance(sl, ast.SliceExpr)
        self.assertEqual(sl.lo.value, 1)
        self.assertEqual(sl.hi.value, 3)
        lo = value_of("xs[:2]")
        self.assertIsNone(lo.lo)
        hi = value_of("xs[1:]")
        self.assertIsNone(hi.hi)

    def test_named_arguments(self):
        call = value_of("f(x: 1, y: 2)")
        self.assertEqual(call.args, [])
        self.assertEqual([k for k, _ in call.kwargs], ["x", "y"])
        mixed = value_of("f(1, y: 2)")
        self.assertEqual(len(mixed.args), 1)
        self.assertEqual([k for k, _ in mixed.kwargs], ["y"])
        # 值类型构造同样走 Call(kwargs)
        ctor = value_of("Point(x: 1, y: 2)")
        self.assertIsInstance(ctor, ast.Call)
        self.assertEqual(ctor.fn.name, "Point")
        self.assertEqual([k for k, _ in ctor.kwargs], ["x", "y"])

    def test_type_dot_new(self):
        e = value_of("Buffer.new(16)")
        self.assertIsInstance(e, ast.NewExpr)
        self.assertEqual(e.type_name, "Buffer")
        self.assertEqual(len(e.args), 1)
        kw = value_of("Point.new(x: 1)")
        self.assertIsInstance(kw, ast.NewExpr)
        self.assertEqual([k for k, _ in kw.kwargs], ["x"])

    def test_grouping(self):
        e = value_of("(1 + 2) * 3")
        self.assertEqual(e.op, "*")
        self.assertEqual(e.left.op, "+")

    def test_index_then_attr(self):
        e = value_of("xs[0].field")
        self.assertIsInstance(e, ast.AttrExpr)
        self.assertIsInstance(e.obj, ast.Index)


# ---------------------------------------------------------------------------
# 3. 数组 / 映射 / 块 的消歧
# ---------------------------------------------------------------------------
class TestContainers(unittest.TestCase):
    def test_array_whitespace_and_comma(self):
        e = value_of("[1 2, 3]")
        self.assertIsInstance(e, ast.ArrayLit)
        self.assertEqual([i.value for i in e.items], [1, 2, 3])

    def test_array_nested_and_empty(self):
        nested = value_of("[[1 2] [3 4]]")
        self.assertEqual(len(nested.items), 2)
        self.assertIsInstance(nested.items[0], ast.ArrayLit)
        self.assertEqual(value_of("[]").items, [])

    def test_array_element_expression(self):
        e = value_of("[1 + 2 3]")
        self.assertEqual(len(e.items), 2)
        self.assertIsInstance(e.items[0], ast.Binary)

    def test_map_literal(self):
        e = value_of("{a: 1, b: 2}")
        self.assertIsInstance(e, ast.MapLit)
        self.assertEqual(len(e.pairs), 2)
        self.assertEqual(e.pairs[0][0].name, "a")
        self.assertEqual(e.pairs[1][1].value, 2)

    def test_map_string_key(self):
        e = value_of('{"k": 1}')
        self.assertIsInstance(e, ast.MapLit)
        self.assertEqual(e.pairs[0][0].value, "k")

    def test_empty_map_is_colon(self):
        e = value_of("{:}")
        self.assertIsInstance(e, ast.MapLit)
        self.assertEqual(e.pairs, [])

    def test_empty_brace_is_block(self):
        e = value_of("{}")
        self.assertIsInstance(e, ast.BlockExpr)
        self.assertEqual(e.block.stmts, [])

    def test_brace_block_expression(self):
        e = value_of("{ let x = 1\n x }")
        self.assertIsInstance(e, ast.BlockExpr)
        self.assertEqual(len(e.block.stmts), 2)
        self.assertIsInstance(e.block.stmts[0], ast.LetStmt)

    def test_map_newline_separated(self):
        e = value_of("{\n a: 1\n b: 2\n}")
        self.assertIsInstance(e, ast.MapLit)
        self.assertEqual(len(e.pairs), 2)

    def test_block_statement(self):
        s = stmt("{ let q = 1 }")
        self.assertIsInstance(s, ast.Block)
        self.assertIsInstance(s.stmts[0], ast.LetStmt)

    def test_map_as_statement(self):
        s = stmt("{a: 1}")
        self.assertIsInstance(s, ast.ExprStmt)
        self.assertIsInstance(s.expr, ast.MapLit)


# ---------------------------------------------------------------------------
# 4. if / match / try
# ---------------------------------------------------------------------------
class TestControl(unittest.TestCase):
    def test_if_condition_does_not_eat_block(self):
        e = value_of("if x { y }")
        self.assertIsInstance(e, ast.IfExpr)
        self.assertIsInstance(e.cond, ast.Var)
        self.assertEqual(e.cond.name, "x")
        self.assertEqual(len(e.then_block.stmts), 1)
        self.assertIsNone(e.else_)

    def test_if_else_if_else(self):
        e = value_of("if x > 0 { 1 } else if y { 2 } else { 3 }")
        self.assertEqual(e.cond.op, ">")
        self.assertIsInstance(e.else_, ast.IfExpr)
        self.assertIsInstance(e.else_.else_, ast.Block)

    def test_if_condition_has_call(self):
        e = value_of("if ok(x) { 1 }")
        self.assertIsInstance(e.cond, ast.Call)
        self.assertEqual(len(e.then_block.stmts), 1)

    def test_match_or_pattern_and_when(self):
        e = value_of('match x { 1 | 2 => "a", n when n > 0 => "b", _ => "c" }')
        self.assertIsInstance(e, ast.MatchExpr)
        self.assertEqual(len(e.arms), 3)
        first = e.arms[0]
        self.assertIsInstance(first.pattern, ast.OrPat)
        self.assertEqual(len(first.pattern.alts), 2)
        second = e.arms[1]
        self.assertIsInstance(second.pattern, ast.BindPat)
        self.assertEqual(second.pattern.name, "n")
        self.assertIsNotNone(second.guard)
        self.assertEqual(second.guard.op, ">")
        self.assertIsInstance(e.arms[2].pattern, ast.WildcardPat)

    def test_match_arm_block_and_assign(self):
        e = value_of('match o { some(v) => { 1 } }')
        self.assertIsInstance(e.arms[0].pattern, ast.CtorPat)
        self.assertIsInstance(e.arms[0].body, ast.Block)
        # 分支体允许赋值（concurrency.ds 写法）
        e2 = value_of("match o { some(v) => sum = sum + v }")
        self.assertIsInstance(e2.arms[0].body, ast.AssignStmt)

    def test_match_destructuring_patterns(self):
        cases = {
            "match v { some(x) => x }": ast.CtorPat,
            "match v { Point(a, b) => a }": ast.CtorPat,
            "match v { [x y] => x }": ast.ArrayPat,
            "match v { {k: val} => val }": ast.MapPat,
            "match v { n @ some(q) => q }": ast.BindPat,
        }
        for src, cls in cases.items():
            e = value_of(src)
            self.assertIsInstance(e.arms[0].pattern, cls, src)

    def test_match_bind_subpattern(self):
        e = value_of("match v { n @ some(q) => q }")
        pat = e.arms[0].pattern
        self.assertEqual(pat.name, "n")
        self.assertIsInstance(pat.sub, ast.CtorPat)
        self.assertEqual(pat.sub.name, "some")

    def test_match_literal_and_none_pattern(self):
        e = value_of('match v { 42 => 1, "s" => 2, true => 3, none => 4 }')
        self.assertIsInstance(e.arms[0].pattern, ast.LitPat)
        self.assertEqual(e.arms[0].pattern.value, 42)
        self.assertIsInstance(e.arms[2].pattern, ast.LitPat)
        self.assertIs(e.arms[2].pattern.value, True)
        self.assertIsInstance(e.arms[3].pattern, ast.CtorPat)
        self.assertEqual(e.arms[3].pattern.name, "none")

    def test_try_expression(self):
        e = value_of("try f()")
        self.assertIsInstance(e, ast.TryExpr)
        self.assertIsInstance(e.expr, ast.Call)

    def test_try_catch_error(self):
        e = value_of("try { f() } catch e { g(e) }")
        self.assertIsInstance(e, ast.TryCatch)
        self.assertIsInstance(e.block, ast.Block)
        self.assertEqual(len(e.catches), 1)
        arm = e.catches[0]
        self.assertEqual(arm.kind, "error")
        self.assertEqual(arm.name, "e")
        self.assertIsInstance(arm.block, ast.Block)

    def test_try_catch_panic(self):
        e = value_of('try { panic "boom" } catch panic { recover }')
        self.assertIsInstance(e, ast.TryCatch)
        arm = e.catches[0]
        self.assertEqual(arm.kind, "panic")
        self.assertIsNone(arm.name)
        # catch panic p 可命名载荷
        e2 = value_of("try { f() } catch panic p { recover }")
        self.assertEqual(e2.catches[0].kind, "panic")
        self.assertEqual(e2.catches[0].name, "p")

    def test_try_catch_multiple_arms(self):
        e = value_of(
            "try { f() } catch e { 1 } catch panic { 2 }"
        )
        self.assertEqual([c.kind for c in e.catches], ["error", "panic"])

    def test_assert_statement(self):
        s = stmt('assert x == 1, "bad"')
        self.assertIsInstance(s, ast.AssertStmt)
        self.assertEqual(s.cond.op, "==")
        self.assertEqual(s.msg.value, "bad")
        s2 = stmt("assert x")
        self.assertIsNone(s2.msg)


# ---------------------------------------------------------------------------
# 5. 语句
# ---------------------------------------------------------------------------
class TestStatements(unittest.TestCase):
    def test_while_loop_for(self):
        self.assertIsInstance(stmt("while x < 3 { }"), ast.WhileStmt)
        self.assertIsInstance(stmt("loop { break }"), ast.LoopStmt)
        f = stmt("for x in xs { }")
        self.assertIsInstance(f, ast.ForStmt)
        self.assertIsInstance(f.pattern, ast.BindPat)

    def test_for_wildcard_and_iterable(self):
        f = stmt("for _ in [1 2 3] { }")
        self.assertIsInstance(f.pattern, ast.WildcardPat)
        self.assertIsInstance(f.iterable, ast.ArrayLit)

    def test_break_continue_return(self):
        b = stmt("break 1")
        self.assertIsInstance(b, ast.BreakStmt)
        self.assertEqual(b.value.value, 1)
        self.assertIsNone(stmt("break").value)
        self.assertIsInstance(stmt("continue"), ast.ContinueStmt)
        r = stmt("return x + 1")
        self.assertIsInstance(r, ast.ReturnStmt)
        self.assertEqual(r.value.op, "+")
        self.assertIsNone(stmt("return").value)

    def test_goto_and_label(self):
        g = stmt("goto again")
        self.assertIsInstance(g, ast.GotoStmt)
        self.assertEqual(g.name, "again")
        lab = stmt("again:")
        self.assertIsInstance(lab, ast.LabelStmt)
        self.assertEqual(lab.name, "again")

    def test_send_statement(self):
        s = stmt("send ch, 42")
        self.assertIsInstance(s, ast.SendStmt)
        self.assertEqual(s.ch.name, "ch")
        self.assertEqual(s.value.value, 42)

    def test_assignment_forms(self):
        a = stmt("a = 1")
        self.assertIsInstance(a, ast.AssignStmt)
        self.assertIsInstance(a.target, ast.Var)
        deref = stmt("*p = 1")
        self.assertIsInstance(deref.target, ast.Deref)
        field = stmt("a.b = 2")
        self.assertIsInstance(field.target, ast.AttrExpr)
        index = stmt("xs[0] = 3")
        self.assertIsInstance(index.target, ast.Index)
        discard = stmt("_ = f()")
        self.assertIsInstance(discard, ast.AssignStmt)
        self.assertEqual(discard.target.name, "_")

    def test_expr_statement(self):
        s = stmt("f()")
        self.assertIsInstance(s, ast.ExprStmt)
        self.assertIsInstance(s.expr, ast.Call)

    def test_comptime_statement_forms(self):
        c1 = stmt("comptime { let x = 1 }")
        self.assertIsInstance(c1, ast.ComptimeStmt)
        self.assertIsInstance(c1.inner, ast.BlockExpr)
        c2 = stmt("comptime if true { 1 }")
        self.assertIsInstance(c2.inner, ast.IfExpr)
        c3 = stmt("comptime for x in xs { }")
        self.assertIsInstance(c3.inner, ast.ForStmt)

    def test_label_not_confused_with_expr(self):
        s = stmt("value = 1")
        self.assertIsInstance(s, ast.AssignStmt)
        self.assertIsInstance(s.target, ast.Var)


# ---------------------------------------------------------------------------
# 6. 类型
# ---------------------------------------------------------------------------
class TestTypes(unittest.TestCase):
    def test_named_and_pointer_ref(self):
        self.assertEqual(type_of("i32").name, "i32")
        p = type_of("ptr[u32]")
        self.assertIsInstance(p, ast.PtrType)
        self.assertEqual(p.inner.name, "u32")
        pm = type_of("ptr mut u8")
        self.assertIsInstance(pm, ast.PtrType)
        self.assertTrue(pm.mutable)
        r = type_of("ref Buffer")
        self.assertIsInstance(r, ast.RefType)
        self.assertFalse(r.mutable)
        rm = type_of("ref mut Buffer")
        self.assertTrue(rm.mutable)
        # `ref [i32]`（有空白）应视为指向切片
        rs = type_of("ref [i32]")
        self.assertIsInstance(rs.inner, ast.SliceType)

    def test_slice_and_array(self):
        s = type_of("[u8]")
        self.assertIsInstance(s, ast.SliceType)
        self.assertEqual(s.elem.name, "u8")
        s2 = type_of("[]u8")
        self.assertIsInstance(s2, ast.SliceType)
        a = type_of("[u8; 4]")
        self.assertIsInstance(a, ast.ArrayType)
        self.assertEqual(a.size, 4)

    def test_opt_res_box_dyn_volatile(self):
        o = type_of("opt[rc[Node]]")
        self.assertIsInstance(o, ast.OptType)
        self.assertIsInstance(o.inner, ast.BoxType)
        self.assertEqual(o.inner.kind, "rc")
        r = type_of("res[i32, error]")
        self.assertIsInstance(r, ast.ResType)
        self.assertEqual(r.ok.name, "i32")
        self.assertEqual(r.err.name, "error")
        b = type_of("chan[i32]")
        self.assertIsInstance(b, ast.BoxType)
        self.assertEqual(b.kind, "chan")
        d = type_of("dyn Draw")
        self.assertIsInstance(d, ast.DynType)
        v = type_of("volatile ptr[u32]")
        self.assertIsInstance(v, ast.VolatileType)
        self.assertIsInstance(v.inner, ast.PtrType)
        self.assertIsInstance(type_of("task[i32]"), ast.BoxType)

    def test_fn_type(self):
        f = type_of("fn(i32, str) -> i32")
        self.assertIsInstance(f, ast.FnType)
        self.assertEqual(len(f.params), 2)
        self.assertEqual(f.ret.name, "i32")

    def test_raw_inferred_unit(self):
        self.assertIsInstance(type_of("raw"), ast.RawType)
        self.assertIsInstance(type_of("_"), ast.InferredType)
        self.assertIsInstance(type_of("()"), ast.UnitType)

    def test_generic_args(self):
        t = type_of("Vec[u8, i32]")
        self.assertIsInstance(t, ast.TypeName)
        self.assertEqual(t.name, "Vec")
        self.assertEqual(len(t.args), 2)


# ---------------------------------------------------------------------------
# 7. 模式与 is
# ---------------------------------------------------------------------------
class TestPatternsAndIs(unittest.TestCase):
    def test_is_type(self):
        e = value_of("x is i32")
        self.assertIsInstance(e, ast.IsTest)
        self.assertIsInstance(e.target, ast.TypeName)
        self.assertEqual(e.target.name, "i32")
        self.assertEqual(e.expr.name, "x")

    def test_is_constructor_pattern(self):
        e = value_of("p is Circle(c)")
        self.assertIsInstance(e, ast.IsTest)
        self.assertIsInstance(e.target, ast.CtorPat)
        self.assertEqual(e.target.name, "Circle")
        self.assertIsInstance(e.target.args[0], ast.BindPat)
        self.assertEqual(e.target.args[0].name, "c")

    def test_array_map_patterns(self):
        arr = value_of("match v { [a b] => a }").arms[0].pattern
        self.assertIsInstance(arr, ast.ArrayPat)
        self.assertEqual([p.name for p in arr.items], ["a", "b"])
        mp = value_of("match v { {k: val} => val }").arms[0].pattern
        self.assertIsInstance(mp, ast.MapPat)
        self.assertEqual(mp.pairs[0][0], "k")
        self.assertIsInstance(mp.pairs[0][1], ast.BindPat)

    def test_literal_wildcard_or(self):
        e = value_of("match v { 1 | 2 | 3 => 0, _ => 1 }")
        pat = e.arms[0].pattern
        self.assertIsInstance(pat, ast.OrPat)
        self.assertEqual(len(pat.alts), 3)
        self.assertIsInstance(e.arms[1].pattern, ast.WildcardPat)


# ---------------------------------------------------------------------------
# 8. & / * 与特殊构造表达式
# ---------------------------------------------------------------------------
class TestAddressAndSpecial(unittest.TestCase):
    def test_addr_of(self):
        e = value_of("&x")
        self.assertIsInstance(e, ast.AddrOf)
        self.assertFalse(e.mutable)
        self.assertIsInstance(e.expr, ast.Var)
        em = value_of("&mut x")
        self.assertIsInstance(em, ast.AddrOf)
        self.assertTrue(em.mutable)

    def test_deref(self):
        e = value_of("*p")
        self.assertIsInstance(e, ast.Deref)
        self.assertEqual(e.expr.name, "p")
        # 语句层与表达式层
        s = stmt("let first = *p")
        self.assertIsInstance(s.value, ast.Deref)

    def test_spawn_go_thread_chan(self):
        sp = value_of("spawn { f() }")
        self.assertIsInstance(sp, ast.SpawnExpr)
        self.assertIsInstance(sp.body, ast.Block)
        sp2 = value_of("spawn f()")
        self.assertIsInstance(sp2.body, ast.Call)
        go = value_of("go f()")
        self.assertIsInstance(go, ast.GoExpr)
        th = value_of("thread(worker)")
        self.assertIsInstance(th, ast.Call)
        self.assertEqual(th.fn.name, "thread")
        ch = value_of("chan[i32](8)")
        self.assertIsInstance(ch, ast.Call)
        self.assertEqual(ch.fn.name, "chan")
        self.assertEqual(ch.args[0].value, 8)
        ch0 = value_of("chan[i32]")
        self.assertEqual(ch0.args[0].value, 0)
        ch1 = value_of("chan[i32]()")
        self.assertEqual(ch1.args[0].value, 0)

    def test_memory_builtins(self):
        for name in ("mutex", "rc", "arc", "gc"):
            e = value_of(f"{name}(x)")
            self.assertIsInstance(e, ast.Call)
            self.assertEqual(e.fn.name, name)
        alloc = value_of("alloc(8, 4)")
        self.assertEqual(alloc.fn.name, "alloc")
        self.assertEqual(len(alloc.args), 2)
        free = value_of("free p")
        self.assertEqual(free.fn.name, "free")
        self.assertEqual(free.args[0].name, "p")

    def test_recv_wait(self):
        self.assertIsInstance(value_of("recv ch"), ast.RecvExpr)
        self.assertIsInstance(value_of("wait t"), ast.WaitExpr)

    def test_sizeof_alignof_typeinfo(self):
        sz = value_of("sizeof(FrameHeader)")
        self.assertIsInstance(sz, ast.SizeofExpr)
        self.assertIsInstance(sz.target, ast.TypeName)
        # 先尝试类型、失败后按表达式
        sz2 = value_of("sizeof(x + 1)")
        self.assertIsInstance(sz2.target, ast.Binary)
        al = value_of("alignof(u8)")
        self.assertIsInstance(al, ast.AlignofExpr)
        ti = value_of("typeinfo(Vec2)")
        self.assertIsInstance(ti, ast.TypeinfoExpr)

    def test_comptime_expression(self):
        e = value_of("comptime typeinfo(Vec2)")
        self.assertIsInstance(e, ast.ComptimeExpr)
        self.assertIsInstance(e.inner, ast.TypeinfoExpr)
        b = value_of("comptime { 1 }")
        self.assertIsInstance(b, ast.ComptimeExpr)
        self.assertIsInstance(b.inner, ast.BlockExpr)

    def test_asm(self):
        a = value_of('asm "nop"')
        self.assertIsInstance(a, ast.AsmExpr)
        self.assertEqual(a.text, "nop")
        b = value_of('asm { "nop", out(x) }')
        self.assertIsInstance(b, ast.AsmExpr)
        self.assertIn("nop", b.text)

    def test_fn_literal(self):
        f = value_of("fn (x: i32) -> i32 => x + 1")
        self.assertIsInstance(f, ast.FnLit)
        self.assertEqual(len(f.params), 1)
        self.assertEqual(f.ret.name, "i32")
        self.assertEqual(f.body.op, "+")

    def test_unsafe_block(self):
        e = value_of("@unsafe { 1 }")
        self.assertIsInstance(e, ast.UnsafeBlock)
        self.assertEqual(len(e.block.stmts), 1)
        s = stmt("@unsafe { let x = 1 }")
        self.assertIsInstance(s, ast.ExprStmt)
        self.assertIsInstance(s.expr, ast.UnsafeBlock)

    def test_panic_and_recover(self):
        e = value_of('panic "boom"')
        self.assertIsInstance(e, ast.Call)
        self.assertEqual(e.fn.name, "panic")
        self.assertEqual(value_of("recover").name, "recover")


# ---------------------------------------------------------------------------
# 9. 声明（项）
# ---------------------------------------------------------------------------
class TestDeclarations(unittest.TestCase):
    def test_package_uses_filename(self):
        prog = program(
            "package app\n"
            "use a.b.c as x\n"
            "use a.b.{c, d as e}, q.r\n"
            "fn main() {}\n",
            "app.ds",
        )
        self.assertEqual(prog.package, "app")
        self.assertEqual(prog.filename, "app.ds")
        self.assertEqual(len(prog.uses), 3)
        self.assertEqual(prog.uses[0].parts, ["a", "b", "c"])
        self.assertEqual(prog.uses[0].alias, "x")
        self.assertIsNone(prog.uses[0].names)
        group = prog.uses[1]
        self.assertEqual(group.parts, ["a", "b"])
        self.assertEqual(group.names[0], "c")
        self.assertEqual(len(group.names), 2)
        self.assertEqual(prog.uses[2].parts, ["q", "r"])

    def test_visibility_and_attrs(self):
        prog = program(
            "@no_mangle\n"
            "@entry\n"
            "pub fn f() {}\n"
            "priv fn g() {}\n"
            "prot fn h() {}\n"
            "fn i() {}\n"
        )
        vis = [i.vis for i in prog.items]
        self.assertEqual(vis, ["pub", "priv", "prot", "priv"])
        self.assertEqual(prog.items[0].attrs, ["no_mangle", "entry"])

    def test_attr_args_and_unsafe(self):
        prog = program(
            '@doc(text: "hello")\n'
            "@unsafe\n"
            "fn f() {}\n"
        )
        fn = prog.items[0]
        self.assertEqual(fn.attrs[0], 'doc(text: "hello")')
        self.assertIn("unsafe", fn.attrs)
        self.assertTrue(fn.is_unsafe)
        # impl 上的 @unsafe 也记录（ImplDecl 无正式字段，动态标记）
        impl_prog = program("@unsafe impl X { fn a(self) {} }")
        self.assertTrue(getattr(impl_prog.items[0], "is_unsafe", False))

    def test_fn_generics_where_ret_expr_body(self):
        fn = item_of(
            "fn show[T, U](x: T) -> opt[i32] where T: Draw + Clone => x\n"
        )
        self.assertEqual(fn.generics, ["T", "U"])
        self.assertIsInstance(fn.ret, ast.OptType)
        self.assertIsInstance(fn.body, ast.Var)

    def test_fn_params(self):
        fn = item_of(
            "fn m(ref self, mut x: f32, y: i32 = 2, _) {}\n"
        )
        self.assertEqual([p.name for p in fn.params], ["self", "x", "y", "_"])
        self.assertTrue(fn.params[0].by_ref)
        self.assertTrue(fn.params[1].mutable)
        self.assertIsInstance(fn.params[1].type, ast.TypeName)
        self.assertEqual(fn.params[2].default.value, 2)

    def test_fn_new_drop_flags(self):
        prog = program(
            "class C {\n"
            "  fn new() {}\n"
            "  drop(self) {}\n"
            "  static fn make() -> C { C.new() }\n"
            "}\n"
        )
        cls = prog.items[0]
        methods = {m.name: m for m in cls.methods}
        self.assertTrue(methods["new"].is_new)
        self.assertTrue(methods["drop"].is_drop)
        self.assertTrue(methods["make"].is_static)

    def test_fn_at_addr_before_and_after_body(self):
        prog = program(
            "fn reset() at 0x100 { }\n"
            "fn other() { } at 0x200\n"
        )
        self.assertEqual(prog.items[0].at_addr.value, 0x100)
        self.assertEqual(prog.items[1].at_addr.value, 0x200)

    def test_comptime_and_irq_fn(self):
        prog = program(
            "comptime fn c() {}\n"
            "irq fn i() {}\n"
        )
        self.assertTrue(prog.items[0].is_comptime)
        self.assertTrue(prog.items[1].is_irq)

    def test_type_fields_defaults_and_packed(self):
        prog = program(
            "packed type Point { x: f32 = 1.0, y: f32 }\n"
            "type Alias = Point\n"
        )
        t = prog.items[0]
        self.assertTrue(t.packed)
        self.assertEqual([f.name for f in t.fields], ["x", "y"])
        self.assertAlmostEqual(t.fields[0].default.value, 1.0)
        alias = prog.items[1]
        self.assertIsNone(alias.fields)
        self.assertIsInstance(alias.alias, ast.TypeName)

    def test_class_extends_fields_methods(self):
        prog = program(
            "class Circle extends Shape {\n"
            "  pub radius: f32\n"
            "  fn new(r: f32) {}\n"
            "  drop(self) {}\n"
            "  fn area(self) -> f32 { 1.0 }\n"
            "}\n"
        )
        cls = prog.items[0]
        self.assertIsInstance(cls, ast.ClassDecl)
        self.assertEqual(cls.name, "Circle")
        self.assertIsInstance(cls.extends, ast.TypeName)
        self.assertEqual(cls.extends.name, "Shape")
        self.assertEqual([f.name for f in cls.fields], ["radius"])
        methods = {m.name: m for m in cls.methods}
        self.assertTrue(methods["new"].is_new)
        self.assertTrue(methods["drop"].is_drop)
        self.assertIsInstance(methods["area"].body, ast.Block)

    def test_trait_signature_and_default(self):
        prog = program(
            "trait Draw {\n"
            "  fn draw(ref self) -> str\n"
            "  fn name(self) -> str { \"x\" }\n"
            "}\n"
        )
        tr = prog.items[0]
        self.assertIsInstance(tr, ast.TraitDecl)
        methods = {m.name: m for m in tr.methods}
        self.assertIsNone(methods["draw"].body)
        self.assertIsInstance(methods["name"].body, ast.Block)

    def test_impl_trait_and_inherent(self):
        prog = program(
            "impl Draw for Point { fn draw(ref self) -> str { \"p\" } }\n"
            "impl Point { fn len(self) -> f32 { 1.0 } }\n"
        )
        impl_trait = prog.items[0]
        self.assertIsInstance(impl_trait, ast.ImplDecl)
        self.assertEqual(impl_trait.trait, "Draw")
        self.assertEqual(impl_trait.type.name, "Point")
        self.assertEqual(impl_trait.methods[0].name, "draw")
        impl_inherent = prog.items[1]
        self.assertIsNone(impl_inherent.trait)
        self.assertEqual(impl_inherent.type.name, "Point")

    def test_mod_inline_and_external(self):
        prog = program(
            "mod geo { pub fn f() {} }\n"
            "mod ext\n"
        )
        inline = prog.items[0]
        self.assertIsInstance(inline, ast.ModDecl)
        self.assertIsNotNone(inline.items)
        self.assertIsInstance(inline.items[0], ast.FnDecl)
        ext = prog.items[1]
        self.assertIsNone(ext.items)

    def test_static_mut_and_at(self):
        prog = program(
            "static mut COUNTER: u32 = 0\n"
            "static BASE: u32 = 1 at 0x100\n"
        )
        counter = prog.items[0]
        self.assertIsInstance(counter, ast.StaticDecl)
        self.assertTrue(counter.mutable)
        self.assertIsInstance(counter.type, ast.TypeName)
        self.assertEqual(counter.value.value, 0)
        base = prog.items[1]
        self.assertFalse(base.mutable)
        self.assertEqual(base.at_addr.value, 0x100)

    def test_extern_single(self):
        prog = program('extern "C" fn puts(s: str) -> i32\n')
        ext = prog.items[0]
        self.assertIsInstance(ext, ast.ExternDecl)
        self.assertEqual(ext.abi, "C")
        self.assertEqual(ext.name, "puts")
        self.assertEqual(ext.params[0].name, "s")
        self.assertEqual(ext.ret.name, "i32")
        self.assertIsNone(ext.members)

    def test_extern_block(self):
        prog = program(
            'extern "C" {\n'
            "  fn a()\n"
            "  fn b(x: i32) -> i32\n"
            "}\n"
        )
        ext = prog.items[0]
        self.assertIsInstance(ext, ast.ExternDecl)
        self.assertIsNotNone(ext.members)
        self.assertEqual([m.name for m in ext.members], ["a", "b"])
        self.assertEqual(ext.members[1].ret.name, "i32")

    def test_macro_params_and_body(self):
        prog = program(
            "macro unless(c: expr, t: type, p: pat, s: stmt, b: block, i: ident, l: lit) "
            "{ if !c { b } }\n"
        )
        m = prog.items[0]
        self.assertIsInstance(m, ast.MacroDecl)
        self.assertEqual(
            [p.kind for p in m.params],
            ["expr", "type", "pat", "stmt", "block", "ident", "lit"],
        )
        self.assertIsInstance(m.body, ast.Block)
        self.assertTrue(m.body.stmts)

    def test_macro_concise_template(self):
        # 0.1c 精简写法：`if !c b` 现在解析为「if + 单语句体」，宏模板更自然
        prog = program("macro odd(c: expr) { if !c b }\nfn g() {}\n")
        m = prog.items[0]
        self.assertIsInstance(m, ast.MacroDecl)
        self.assertIsInstance(m.body, ast.Block)
        self.assertTrue(m.body.stmts)
        self.assertIsInstance(m.body.stmts[0], ast.ExprStmt)
        self.assertIsInstance(m.body.stmts[0].expr, ast.IfExpr)

    def test_attr_decl(self):
        prog = program("attr doc(target: fn) { text: str }\n")
        a = prog.items[0]
        self.assertIsInstance(a, ast.AttrDecl)
        self.assertEqual(a.name, "doc")
        self.assertEqual(a.target, "fn")
        self.assertEqual([f.name for f in a.fields], ["text"])
        self.assertIsInstance(a.fields[0].type, ast.TypeName)

    def test_section_block(self):
        prog = program('section ".boot" { @entry fn reset() {} }\n')
        sec = prog.items[0]
        self.assertIsInstance(sec, ast.SectionBlock)
        self.assertEqual(sec.name, ".boot")
        self.assertIsInstance(sec.items[0], ast.FnDecl)
        self.assertEqual(sec.items[0].attrs, ["entry"])

    def test_export(self):
        prog = program("export a, b.c, d\nexport { x, y.z }\n")
        first = prog.items[0]
        self.assertIsInstance(first, ast.ExportDecl)
        self.assertEqual(first.names, ["a", "b.c", "d"])
        second = prog.items[1]
        self.assertEqual(second.names, ["x", "y.z"])

    def test_top_level_let_var_are_items(self):
        prog = program("let A = 1\nvar B: u32 = 2\n")
        self.assertIsInstance(prog.items[0], ast.LetItem)
        self.assertFalse(prog.items[0].mutable)
        self.assertIsInstance(prog.items[1], ast.LetItem)
        self.assertTrue(prog.items[1].mutable)
        self.assertEqual(prog.items[1].type.name, "u32")

    def test_block_let_is_statement(self):
        s = stmt("let x = 1")
        self.assertIsInstance(s, ast.LetStmt)
        self.assertEqual(s.name, "x")


# ---------------------------------------------------------------------------
# 10. 示例文件（验收 4/4）
# ---------------------------------------------------------------------------
class TestExamples(unittest.TestCase):
    def test_all_examples_parse(self):
        paths = sorted(glob.glob(os.path.join(ROOT, "examples", "*.ds")))
        self.assertEqual(len(paths), 4, f"examples 应为 4 个，实际 {paths}")
        packages = {}
        for path in paths:
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
            prog = parse_program(src, os.path.basename(path))
            self.assertIsInstance(prog, ast.Program)
            self.assertTrue(prog.items, f"{path} 没有解析出任何项")
            packages[os.path.basename(path)] = prog.package
        self.assertEqual(
            packages,
            {
                "bare.ds": "firmware",
                "concurrency.ds": "concurrency",
                "memory.ds": "memory",
                "tour.ds": "tour",
            },
        )

    def test_tour_structure(self):
        path = os.path.join(ROOT, "examples", "tour.ds")
        prog = program(open(path, encoding="utf-8").read(), "tour.ds")
        self.assertEqual(len(prog.uses), 1)
        classes = [i for i in prog.items if isinstance(i, ast.ClassDecl)]
        self.assertEqual([c.name for c in classes], ["Shape", "Circle"])
        circle = classes[1]
        self.assertEqual(circle.extends.name, "Shape")
        traits = [i for i in prog.items if isinstance(i, ast.TraitDecl)]
        self.assertEqual(traits[0].name, "Draw")
        impls = [i for i in prog.items if isinstance(i, ast.ImplDecl)]
        self.assertEqual(impls[0].trait, "Draw")
        macros = [i for i in prog.items if isinstance(i, ast.MacroDecl)]
        self.assertEqual(macros[0].name, "unless")
        externs = [i for i in prog.items if isinstance(i, ast.ExternDecl)]
        self.assertEqual(externs[0].name, "host_log")


# ---------------------------------------------------------------------------
# 11. 错误
# ---------------------------------------------------------------------------
class TestErrors(unittest.TestCase):
    def test_missing_brace(self):
        with self.assertRaises(DsSyntaxError):
            program("fn f() {")

    def test_missing_expression(self):
        with self.assertRaises(DsSyntaxError):
            program("fn f() { let x = }\n")

    def test_try_block_requires_catch(self):
        with self.assertRaises(DsSyntaxError):
            program("fn f() { try { 1 } }\n")

    def test_at_outside_supported_positions(self):
        with self.assertRaises(DsSyntaxError):
            program("@ { 1 }\n")

    def test_error_carries_position_and_filename(self):
        with self.assertRaises(DsSyntaxError) as ctx:
            program("fn f() {\n  let x =\n}\n", "bad.ds")
        err = ctx.exception
        self.assertEqual(err.filename, "bad.ds")
        self.assertGreater(err.line, 0)
        self.assertGreater(err.col, 0)
        self.assertTrue(err.msg)


# ---------------------------------------------------------------------------
# 12. 接口
# ---------------------------------------------------------------------------
class TestInterfaces(unittest.TestCase):
    def test_parse_program_returns_program(self):
        prog = parse_program("fn f() {}", "x.ds")
        self.assertIsInstance(prog, ast.Program)
        self.assertEqual(prog.filename, "x.ds")

    def test_parse_repl_mixed_nodes(self):
        nodes = parse_repl("use a.b\nlet x = 1\nx + 1\nif x { x }\n")
        self.assertIsInstance(nodes, list)
        self.assertIsInstance(nodes[0], ast.Use)
        self.assertIsInstance(nodes[1], ast.LetItem)
        self.assertIsInstance(nodes[2], ast.ExprStmt)
        self.assertIsInstance(nodes[3], ast.ExprStmt)
        self.assertIsInstance(nodes[3].expr, ast.IfExpr)

    def test_parse_repl_statements(self):
        nodes = parse_repl("foo()\nwhile x { }\n")
        self.assertIsInstance(nodes[0], ast.ExprStmt)
        self.assertIsInstance(nodes[1], ast.WhileStmt)

    def test_parser_class_is_usable(self):
        p = Parser("fn f() {}", "<x>")
        prog = p.parse_program()
        self.assertIsInstance(prog, ast.Program)
        self.assertEqual(len(prog.items), 1)

    def test_empty_source(self):
        prog = parse_program("")
        self.assertEqual(prog.items, [])
        self.assertEqual(prog.uses, [])
        self.assertIsNone(prog.package)
        self.assertEqual(parse_repl(""), [])


if __name__ == "__main__":
    unittest.main()
