"""Batch 4: pointer type / static address smoke tests."""
import unittest
from dsv01.checker import check_program
from dsv01.parser import parse_program
from dsv01.interp import Interpreter


class TestPointer(unittest.TestCase):
    def test_cut_pointer_type_parses(self):
        check_program(parse_program(
            '@static UART: *u32 = 0x1000\np(*UART)\n', "p.ds"))

    def test_static_addr_deref(self):
        it = Interpreter()
        it.run_source('@static UART: u32 = 0x1000\np(*UART)\n')

    def test_pointer_type_alias(self):
        check_program(parse_program('let p: *u32 = 0x1000\n', "p.ds"))


if __name__ == "__main__":
    unittest.main()
