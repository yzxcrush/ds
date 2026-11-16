"""Batch 5: top-level try propagation regression."""
import unittest
from dsv01.interp import Interpreter
from dsv01.builtins import DsRuntimeError


class TestErrors(unittest.TestCase):
    def test_try_at_top_level_has_clear_error(self):
        it = Interpreter()
        with self.assertRaises(DsRuntimeError):
            it.run_source('fn f() -> res[i32, error] { err(error("x")) }\n'
                          'let v = try f()\np(v)\n')


if __name__ == "__main__":
    unittest.main()
