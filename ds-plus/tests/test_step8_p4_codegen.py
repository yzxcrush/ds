"""P4：x86-64 子集代码生成（汇编检查 + ELF/raw 构建；x86_64 主机上执行）。"""
import pathlib
import platform
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ds-plus"))

from dsplus.codegen import CodegenError, generate_source, build  # noqa: E402


class TestAsm(unittest.TestCase):
    def test_port_io_asm(self):
        src = '@unsafe fn main() -> i32 { @outb(0x3F8, 65) return @inb(0x3F8) }\n'
        asm = generate_source(src, "p.ds")
        self.assertIn("outb %al, %dx", asm)
        self.assertIn("inb %dx, %al", asm)
        self.assertIn("movw $1016, %dx", asm)

    def test_msr_cr_asm(self):
        src = ('@unsafe fn main() -> i32 { @wrmsr(0x10, 42) let v = @rdmsr(0x10) '
               'let cur = @rdcr(3) @wrcr(3, v) return 0 }\n')
        asm = generate_source(src, "p.ds")
        for needle in ("rdmsr", "wrmsr", "movq %cr3", "movq %rax, %cr3"):
            self.assertIn(needle, asm)

    def test_asm_inputs(self):
        src = '@unsafe fn f() { @asm volatile("mov %0, %1", 1, 2) }\n'
        asm = generate_source(src, "a.ds")
        self.assertIn("mov %r10, %r11", asm)

    def test_unsupported_mmio(self):
        with self.assertRaises(CodegenError) as cm:
            generate_source('@unsafe fn f() { let u = @mmio(0x3F8, u8) }\n', "m.ds")
        self.assertEqual(cm.exception.code, "E_DS_PLUS_CODEGEN")


class TestBuild(unittest.TestCase):
    SRC = "fn add(a: i32, b: i32) -> i32 { a + b }\nfn main() -> i32 { return add(20, 22) }\n"

    def test_elf_and_raw(self):
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td) / "a.out"
            info = build(self.SRC, str(out), raw=True)
            data = out.read_bytes()
            self.assertEqual(data[:4], b"\x7fELF")
            self.assertEqual(int.from_bytes(data[18:20], "little"), 62)  # x86-64
            self.assertGreater(pathlib.Path(info["raw"]).stat().st_size, 0)

    @unittest.skipUnless(platform.machine() in ("x86_64", "AMD64"), "需要 x86-64 主机执行")
    def test_run_exit_code(self):
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td) / "a.out"
            build(self.SRC, str(out))
            r = subprocess.run([str(out)])
            self.assertEqual(r.returncode, 42)

    def test_while_loop(self):
        src = "fn main() -> i32 { var n = 0 while n < 5 { n = n + 1 } return n }\n"
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td) / "loop.out"
            build(src, str(out), raw=True)
            self.assertEqual(out.read_bytes()[:4], b"\x7fELF")


if __name__ == "__main__":
    unittest.main()
