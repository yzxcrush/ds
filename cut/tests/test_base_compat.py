"""Cut 与 base 的交叉兼容：Cut 代码必须能过 base --check。"""
import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("cutc", ROOT / "cut" / "cutc.py")
cutc = importlib.util.module_from_spec(spec)
sys.modules["cutc"] = cutc
spec.loader.exec_module(cutc)

sys.path.insert(0, str(ROOT))
from dsv01.parser import parse_program  # noqa: E402
from dsv01.checker import check_program  # noqa: E402

CUT = """@static UART: *u32 = 0x1000
@irq(5) irq fn tick() { }
fn f() { @asm "nop" }
"""


class TestCutBaseCompat(unittest.TestCase):
    def test_cut_compiles_with_cutc(self):
        asm = cutc.compile_source(CUT, "compat.ds", "app")
        self.assertIn(".equ UART", asm)
        self.assertIn("tick:", asm)

    def test_cut_parses_in_base(self):
        prog = parse_program(CUT, "compat.ds")
        check_program(prog)

    def test_cut_pointer_type(self):
        asm = cutc.compile_source("@static P: *u32 = 0x2000\n", "p.ds", "cut")
        self.assertIn(".equ P", asm)


if __name__ == "__main__":
    unittest.main()
