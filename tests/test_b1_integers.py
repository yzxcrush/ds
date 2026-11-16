"""B1: base checked integer storage/params/returns; Cut wrap is separate."""
import unittest
from dsv01.interp import Interpreter
from dsv01.builtins import DsRuntimeError


def run(src):
    Interpreter().run_source(src)


class TestB1(unittest.TestCase):
    def test_u8_assignment_overflow_panics(self):
        with self.assertRaises(DsRuntimeError):
            run("var x: u8 = 255\nx = x + 1\np(x)\n")

    def test_u8_underflow_panics(self):
        with self.assertRaises(DsRuntimeError):
            run("var x: u8 = 0\nx = x - 1\np(x)\n")

    def test_u8_max_ok(self):
        run("var x: u8 = 254\nx = x + 1\np(x)\n")

    def test_param_range_checked(self):
        with self.assertRaises(DsRuntimeError):
            run("fn f(x: u8) { p(x) }\nf(300)\n")

    def test_return_range_checked(self):
        with self.assertRaises(DsRuntimeError):
            run("fn f() -> u8 { 300 }\np(f())\n")

    def test_explicit_cast_truncates(self):
        run("var x: u8 = 300 as u8\np(x)\n")


if __name__ == "__main__":
    unittest.main()
