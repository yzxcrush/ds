# -*- coding: utf-8 -*-
"""Ds 0.1c 精简写法的测试（保持旧写法兼容）。"""

from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dsv01 import Interpreter  # noqa: E402


def run(src: str) -> tuple[str, object]:
    out = io.StringIO()
    value = Interpreter(stdout=out).run_source(src)
    return out.getvalue(), value


class TestConcise(unittest.TestCase):
    def test_implicit_entry(self):
        out, _ = run('println("hi")\n')
        self.assertEqual("hi\n", out)

    def test_expression_fn(self):
        out, _ = run("fn add(a,b)=a+b\nprintln(add(2,3))\n")
        self.assertEqual("5\n", out)

    def test_colon_body_fn(self):
        out, _ = run("fn f(x): println(x)\nf(9)\n")
        self.assertEqual("9\n", out)

    def test_colon_if_else(self):
        out, _ = run('let m=if 3>2: "big" else "small"\nprintln(m)\n')
        self.assertEqual("big\n", out)

    def test_colon_loops_and_range(self):
        out, _ = run("var s=0\nfor i in 0..5: s+=i\nvar n=0\nwhile n<3: n+=1\nprintln(s)\nprintln(n)\n")
        self.assertEqual("10\n3\n", out)

    def test_compound_assign(self):
        out, _ = run("var x=10\nx-=3\nx*=2\nx/=7\nx%=2\nprintln(x)\n")
        self.assertEqual("0\n", out)

    def test_fstring(self):
        out, _ = run('let x=42\nprintln(f"x={x} y={x+1} {{lit}}")\n')
        self.assertEqual("x=42 y=43 {lit}\n", out)

    def test_implicit_let_is_immutable(self):
        from dsv01 import DsRuntimeError
        with self.assertRaises(DsRuntimeError):
            run("x=1\nx=2\n")

    def test_classic_still_works(self):
        out, _ = run('package t\nfn main() {\n    println("old")\n}\n')
        self.assertEqual("old\n", out)

    def test_top_level_skips_main(self):
        out, _ = run('fn main() { println("main") }\nprintln("top")\n')
        self.assertEqual("top\n", out)

    def test_arrays_maps_concise(self):
        out, _ = run('let xs=[1 2 3]\nxs[0]+=10\nlet m={"a":1}\nm["b"]=2\nprintln(xs)\nprintln(m)\n')
        self.assertEqual("[11 2 3]\n{a: 1, b: 2}\n", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
