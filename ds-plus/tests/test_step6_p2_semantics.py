"""P2：语义检查 + compat 模拟执行。"""
import io
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ds-plus"))

from dsplus.checker import check_program, PROFILE_BARE, PROFILE_COMPAT  # noqa: E402
from dsplus.compat import run_compat  # noqa: E402
from dsplus.frontend import parse_program  # noqa: E402


def codes(src, profile):
    return {d.code for d in check_program(parse_program(src, "t.ds"), profile)}


class TestChecker(unittest.TestCase):
    def test_hw_only_bare(self):
        src = '@unsafe fn f() { @outb(0x20, 0x20) }\n'
        self.assertIn("E_DS_PLUS_PROFILE", codes(src, PROFILE_COMPAT))
        self.assertEqual(codes(src, PROFILE_BARE), set())

    def test_requires_unsafe(self):
        src = 'fn f() { @inb(0x60) }\n'
        self.assertIn("E_DS_PLUS_UNSAFE", codes(src, PROFILE_BARE))

    def test_unsafe_fn_attr_ok(self):
        src = '@unsafe fn f() { @inb(0x60) }\n'
        self.assertEqual(codes(src, PROFILE_BARE), set())

    def test_unsafe_block_ok(self):
        src = 'fn f() { @unsafe { @inb(0x60) } }\n'
        self.assertEqual(codes(src, PROFILE_BARE), set())

    def test_cr_const(self):
        src = '@unsafe fn f() { @rdcr(1) }\n'
        self.assertIn("E_DS_PLUS_CONST", codes(src, PROFILE_BARE))
        self.assertEqual(codes('@unsafe fn f() { @rdcr(3) }\n', PROFILE_BARE), set())

    def test_static_const(self):
        src = '@static var g: i32 = f()\n'
        self.assertIn("E_DS_PLUS_CONST", codes(src, PROFILE_COMPAT))
        self.assertEqual(codes('@static var g: i32 = 1 + 2\n', PROFILE_COMPAT), set())

    def test_mmap_align(self):
        src = '@unsafe fn f() { @mmap var p: ptr[u8] = map_page(0x1001, 4096) }\n'
        self.assertIn("E_DS_PLUS_ALIGN", codes(src, PROFILE_COMPAT))
        ok = '@unsafe fn f() { @mmap var p: ptr[u8] = map_page(0x1000, 4096) }\n'
        self.assertEqual(codes(ok, PROFILE_COMPAT), set())

    def test_raw_unsafe(self):
        src = '@raw var p: ptr[u8] = malloc(16)\n'
        self.assertIn("E_DS_PLUS_UNSAFE", codes(src, PROFILE_COMPAT))


class TestCompat(unittest.TestCase):
    SRC = '''@unsafe fn main() {
    @outb(0x3F8, 65)
    p(@inb(0x3F8))
    @wrmsr(0x10, 42)
    p(@rdmsr(0x10))
    @wrcr(3, 0x1000)
    p(@rdcr(3))
    let u = @mmio(0x3F8, u8)
    u[0] = 7
    p(u[0])
}
'''

    def test_hardware_simulation(self):
        result, machine, out = run_compat(self.SRC, "sim.ds")
        self.assertEqual(out, "65\n42\n4096\n7\n")
        self.assertEqual(machine.ports[0x3F8], 65)
        self.assertEqual(machine.msrs[0x10], 42)
        self.assertEqual(machine.crs[3], 0x1000)

    def test_regions_stripped(self):
        src = '@stack var s: i32 = 42\n@static var g: i32 = 7\np(s + g)\n'
        _, _, out = run_compat(src, "regions.ds")
        self.assertEqual(out, "49\n")

    def test_asm_inputs_noop(self):
        src = '@unsafe fn f() { @asm volatile("mov %0, %1", 1, 2) }\nf()\n'
        _, m, out = run_compat(src, "asm.ds")
        self.assertEqual(out, "")

    def test_base_semantics_equal(self):
        src = 'fn add(a: i32, b: i32) -> i32 { a + b }\nfn main() { p(add(2, 3)) }\n'
        from dsv01.parser import parse_program as bp
        from dsv01.interp import Interpreter
        out1 = io.StringIO()
        Interpreter(stdout=out1, filename="base.ds").run_program(bp(src, "base.ds"))
        _, _, out2 = run_compat(src, "plus.ds", profile=PROFILE_COMPAT)
        self.assertEqual(out1.getvalue(), out2)


if __name__ == "__main__":
    unittest.main()
