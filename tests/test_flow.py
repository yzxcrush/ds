# -*- coding: utf-8 -*-
"""Ds Flow 写法测试：`\\` 定义、并置调用、`.` 结束块。"""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dsv01.parser import Parser, parse_program  # noqa: E402
from dsv01 import Interpreter  # noqa: E402


def run_flow(src: str) -> str:
    out = io.StringIO()
    interp = Interpreter(stdout=out)
    interp.run_file(_write_temp(src))
    return out.getvalue()


def _write_temp(src: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".dsf")
    with open(fd, "w", encoding="utf-8") as fh:
        fh.write(src)
    return path


class TestFlow(unittest.TestCase):
    def test_hello_juxtaposition(self):
        self.assertEqual("hello, Ds\n", run_flow('p "hello, Ds"\n'))

    def test_function_and_multiarg_call(self):
        src = "\\add a b = a+b\nlet r=add 2 3\np r\n"
        self.assertEqual("5\n", run_flow(src))

    def test_dot_blocks_and_return(self):
        src = "\\fib n\n    ?n<2\n        ^n\n    else\n        ^fib(n-1)+fib(n-2)\n    .\n.\np fib(10)\n"
        self.assertEqual("55\n", run_flow(src))

    def test_loops_with_dot_blocks(self):
        src = "var s=0\nfor i in 1..6\n    s+=i\n.\nvar n=0\nwhile n<3\n    n+=1\n.\np s\np n\n"
        self.assertEqual("15\n3\n", run_flow(src))

    def test_inline_conditional_argument(self):
        src = 'p ?1<2: "y" else "n"\n'
        self.assertEqual("y\n", run_flow(src))

    def test_typed_params(self):
        src = "\\add a:i32 b:i32 -> i32 = a+b\nlet r=add 1 2\np r\n"
        self.assertEqual("3\n", run_flow(src))

    def test_plain_ds_files_unaffected(self):
        out = io.StringIO()
        Interpreter(stdout=out).run_source('println("classic")\n')
        self.assertEqual("classic\n", out.getvalue())

    def test_parser_autodetect(self):
        prog = parse_program("\\f n = n+1\n", "x.dsf")
        self.assertEqual("FnDecl", type(prog.items[0]).__name__)


if __name__ == "__main__":
    unittest.main(verbosity=2)
