"""Batch 3 控制流/作用域回归。"""
import unittest
from dsv01.interp import Interpreter


def run(src):
    it = Interpreter()
    return it.run_source(src)


class TestControl(unittest.TestCase):
    def test_loop_expression(self):
        run("let x = loop { break 42 }\np(x)\n")

    def test_shadowing(self):
        run("let x = 1\nfn f() { let x = 2; p(x) }\nf()\np(x)\n")


if __name__ == "__main__":
    unittest.main()
