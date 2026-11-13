# -*- coding: utf-8 -*-
"""Ds v0.1 参考驱动测试：语言特性 + 示例 + CLI/REPL。"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import dsv01  # noqa: E402
from dsv01 import Interpreter, UNIT  # noqa: E402
from dsv01 import builtins as bi  # noqa: E402
from dsv01.lexer import KEYWORDS, tokenize  # noqa: E402
from dsv01.parser import parse_repl  # noqa: E402


def run(src: str, **options):
    out = io.StringIO()
    interp = Interpreter(stdout=out, **options)
    value = interp.run_source(src, "<test>")
    return value, out.getvalue()


class TestLexerAndKeywords(unittest.TestCase):
    def test_keywords_match_spec_index(self):
        data = json.loads((ROOT / "spec" / "keywords.json").read_text(encoding="utf-8"))
        spec_words = {entry["word"] for entry in data["alphabetical"]}
        self.assertEqual(spec_words, set(KEYWORDS))
        self.assertEqual(len(KEYWORDS), 77)

    def test_tokenize_comments_and_literals(self):
        toks = tokenize('5 0xFF 0b1010 "s" b"raw" # c\n#| b |# _', "<t>")
        kinds = [t.kind for t in toks]
        self.assertIn("INT", kinds)
        self.assertIn("STRING", kinds)
        self.assertIn("BYTES", kinds)
        self.assertIn("BLANK", kinds)
        self.assertEqual(2, kinds.count("COMMENT"))

    def test_lex_error(self):
        from dsv01.lexer import DsSyntaxError
        with self.assertRaises(DsSyntaxError):
            tokenize('"未闭合', "<t>")


class TestBasics(unittest.TestCase):
    def test_arithmetic_and_precedence(self):
        value, _ = run("package t\nfn main() -> i32 { 1 + 2 * 3 - 4 / 2 }")
        self.assertEqual(5, value)

    def test_let_var_and_loops(self):
        src = """
package t
fn main() -> i32 {
    var total = 0
    for v in [1 2 3 4 5] {
        if v == 4 { continue }
        total = total + v
    }
    var i = 0
    while i < 3 { i = i + 1 }
    loop {
        i = i - 1
        if i <= 0 { break }
    }
    total + i
}
"""
        value, _ = run(src)
        self.assertEqual(11, value)

    def test_strings_arrays_maps(self):
        src = """
package t
fn main() -> i32 {
    let s = "ab" + "cd"
    let xs = [1 2 3]
    let m = {"a": 1, "b": 2}
    let empty = {:}
    if s == "abcd" && xs[1] == 2 && m["b"] == 2 && empty == empty { 1 } else { 0 }
}
"""
        value, _ = run(src)
        self.assertEqual(1, value)

    def test_functions_and_recursion(self):
        src = """
package t
fn fact(n: i32) -> i32 {
    if n <= 1 { 1 } else { n * fact(n - 1) }
}
fn main() -> i32 { fact(5) }
"""
        value, _ = run(src)
        self.assertEqual(120, value)

    def test_pipe_operator(self):
        src = """
package t
fn inc(x: i32) -> i32 { x + 1 }
fn dbl(x: i32) -> i32 { x * 2 }
fn main() -> i32 { 5 |> inc |> dbl }
"""
        value, _ = run(src)
        self.assertEqual(12, value)

    def test_goto_label(self):
        src = """
package t
fn main() -> i32 {
    var n = 0
again:
    n = n + 1
    if n < 3 { goto again }
    n
}
"""
        value, _ = run(src)
        self.assertEqual(3, value)


class TestErrorsAndPatterns(unittest.TestCase):
    def test_opt_and_match(self):
        src = """
package t
fn pick(o: opt[i32]) -> i32 {
    match o {
        some(v) when v > 0 => v,
        some(_) => 0,
        none => -1,
    }
}
fn main() -> i32 { pick(some(5)) + pick(none) }
"""
        value, _ = run(src)
        self.assertEqual(4, value)

    def test_res_try_and_catch(self):
        src = """
package t
fn div(a: i32, b: i32) -> res[i32, error] {
    if b == 0 { return err(error("zero")) }
    ok(a / b)
}
fn plus(a: i32, b: i32) -> res[i32, error] {
    let v = try div(a, b)
    ok(v + 1)
}
fn main() -> res[i32, error] {
    match plus(4, 2) {
        ok(v) => println("ok"),
        err(e) => println("err"),
    }
    plus(1, 0)
}
"""
        value, out = run(src)
        self.assertEqual("ok\n", out)
        self.assertFalse(value.ok)
        self.assertEqual("zero", value.value.message)

    def test_panic_recover_assert(self):
        src = """
package t
fn main() {
    try {
        panic "boom"
    } catch panic {
        println("recovered: " + recover)
    }
    assert 1 + 1 == 2, "math"
}
"""
        _, out = run(src)
        self.assertEqual("recovered: boom\n", out)

    def test_is_and_in(self):
        src = """
package t
fn main() -> i32 {
    var n = 1
    if "x" in ["x" "y"] { n = n + 1 }
    if n is i32 { n = n + 1 }
    n
}
"""
        value, _ = run(src)
        self.assertEqual(3, value)

    def test_array_and_map_patterns(self):
        src = """
package t
fn first(p: [i32]) -> i32 { match p { [a b] => a, _ => 0 } }
fn main() -> i32 { first([7 8]) }
"""
        value, _ = run(src)
        self.assertEqual(7, value)


class TestOop(unittest.TestCase):
    def test_class_inheritance_super_drop(self):
        src = """
package t
class Base {
    name: str
    fn new(name: str) { self.name = name }
    fn hello(self) -> str { "base " + self.name }
}
class Child extends Base {
    fn new(name: str) { super.init(name) }
    fn hello(self) -> str { "child " + self.name }
    drop(self) { println("drop " + self.name) }
}
fn main() {
    let c = Child.new("x")
    println(c.hello())
}
"""
        _, out = run(src)
        self.assertEqual("child x\ndrop x\n", out)

    def test_trait_impl_dyn(self):
        src = """
package t
trait Draw { fn draw(ref self) -> str }
type Circle { r: f32 }
impl Draw for Circle {
    fn draw(ref self) -> str { "circle" }
}
fn main() {
    let c = Circle(r: 1.0)
    println(c.draw())
    let d: dyn Draw = c as dyn Draw
    println(d.draw())
}
"""
        _, out = run(src)
        self.assertEqual("circle\ncircle\n", out)

    def test_type_default_constructor(self):
        src = """
package t
type Point { x: i32, y: i32 }
fn main() -> i32 {
    let p = Point(x: 3, y: 4)
    p.x * 10 + p.y
}
"""
        value, _ = run(src)
        self.assertEqual(34, value)


class TestMeta(unittest.TestCase):
    def test_sizeof_alignof_typeinfo(self):
        src = """
package t
type V { x: f32, y: f32 }
fn main() -> i32 {
    comptime { assert sizeof(V) == 8, "size" }
    let info = comptime typeinfo(V)
    if info.name == "V" && alignof(V) == 4 && sizeof(V) == 8 { 1 } else { 0 }
}
"""
        value, _ = run(src)
        self.assertEqual(1, value)

    def test_macro_expansion(self):
        src = """
package t
macro unless(c: expr, b: block) { if !c { b } }
fn main() {
    unless(false, { println("fired") })
}
"""
        _, out = run(src)
        self.assertEqual("fired\n", out)


class TestConcurrencyAndMemory(unittest.TestCase):
    def test_chan_go_spawn_wait(self):
        src = """
package t
fn worker(ch: chan[i32]) { send ch, 7 }
fn main() {
    let ch = chan[i32](4)
    go worker(ch)
    match recv ch {
        some(v) => println("chan got"),
        none => println("chan none"),
    }
    let t = spawn { 42 }
    match wait t {
        ok(v) => println("task ok"),
        err(e) => println("task err"),
    }
}
"""
        _, out = run(src)
        self.assertEqual("chan got\ntask ok\n", out)

    def test_mutex_and_thread(self):
        src = """
package t
fn job() { }
fn main() {
    let m = mutex(0)
    {
        let guard = m.lock()
        _ = guard
    }
    let t = thread(job)
    wait t
    println("done")
}
"""
        _, out = run(src)
        self.assertEqual("done\n", out)

    def test_alloc_ptr_free_rc_gc(self):
        src = """
package t
fn main() -> i32 {
    let p = alloc(4, 1)
    @unsafe { *p = 65 }
    let v = @unsafe { *(p + 0) }
    free(p)
    let r = rc(1)
    let g = gc(2)
    v
}
"""
        value, _ = run(src)
        self.assertEqual(65, value)


class TestExamples(unittest.TestCase):
    EXPECT = {
        "tour.ds": ["vec2", "circle", "contains", "signed total", "positive",
                    "ratio ok", "caught: division by zero", "Vec2", "unless fires",
                    "drop circle"],
        "concurrency.ds": ["task ok", "got value"],
        "memory.ds": ["byte read"],
        "bare.ds": [],
    }

    def test_examples_run(self):
        for name, expected in self.EXPECT.items():
            with self.subTest(example=name):
                out = io.StringIO()
                interp = Interpreter(stdout=out)
                interp.run_file(str(ROOT / "examples" / name))
                text = out.getvalue()
                for fragment in expected:
                    self.assertIn(fragment, text)


class TestCliAndRepl(unittest.TestCase):
    def _cmd(self, *args):
        return subprocess.run([str(ROOT / args[0]), *args[1:]], cwd=str(ROOT),
                              capture_output=True, text=True, timeout=120)

    def _python(self, *args):
        return subprocess.run([sys.executable, *args], cwd=str(ROOT),
                              capture_output=True, text=True, timeout=120)

    def test_dscc_runs_example(self):
        proc = self._cmd("dscc", "examples/tour.ds")
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertIn("vec2", proc.stdout)

    def test_ds_runs_example(self):
        proc = self._cmd("ds", "examples/concurrency.ds")
        self.assertEqual(0, proc.returncode, proc.stderr)

    def test_ds_code_flag(self):
        proc = self._cmd("ds", "-c", 'package t\nfn main() { println("hi") }')
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertIn("hi", proc.stdout)

    def test_dscc_emit_tokens_and_check(self):
        proc = self._cmd("dscc", "examples/bare.ds", "--emit", "tokens")
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertIn("KEYWORD", proc.stdout)
        proc = self._cmd("dscc", "examples/bare.ds", "--check")
        self.assertEqual(0, proc.returncode, proc.stderr)

    def test_bare_mode_conflict_exit_code(self):
        proc = self._cmd("dscc", "examples/bare.ds", "--bare", "--gc", "tracing")
        self.assertEqual(2, proc.returncode, proc.stderr)

    def test_module_entry(self):
        proc = self._python("-m", "dsv01", "-c", 'package t\nfn main() { println("mod") }')
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertIn("mod", proc.stdout)

    def test_python_api(self):
        value, out = run("package t\nfn main() -> i32 { 6 * 7 }")
        self.assertEqual(42, value)

    def test_repl_nodes(self):
        interp = Interpreter(stdout=io.StringIO())
        nodes = parse_repl("let x = 1\nx + 1")
        value = interp.run_repl_nodes(nodes)
        self.assertEqual(2, value)


if __name__ == "__main__":
    unittest.main(verbosity=2)
