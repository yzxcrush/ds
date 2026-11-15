"""cutc 原型测试：分层、语义、@asm、Thumb 代码生成。"""
import importlib.util
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("cutc", ROOT / "cut" / "cutc.py")
cutc = importlib.util.module_from_spec(spec)
sys.modules["cutc"] = cutc
spec.loader.exec_module(cutc)

UART = (ROOT / "cut" / "examples" / "uart_hello.ds").read_text(encoding="utf-8")
CTX = (ROOT / "cut" / "examples" / "context_switch.ds").read_text(encoding="utf-8")
START = (ROOT / "cut" / "examples" / "rp2350_start.ds").read_text(encoding="utf-8")


class TestLayer(unittest.TestCase):
    def test_cut_rejects_ds_keyword(self):
        with self.assertRaises(cutc.CutError) as cm:
            cutc.compile_source("class X {}\n", "x.ds", "cut")
        self.assertEqual(cm.exception.code, "E_CUT_LAYER_DS")
        self.assertIn("--app", cm.exception.msg)

    def test_cut_rejects_plus_token(self):
        with self.assertRaises(cutc.CutError) as cm:
            cutc.compile_source("@raw var p: *u32 = 0x1000\n", "x.ds", "cut")
        self.assertEqual(cm.exception.code, "E_CUT_LAYER_PLUS")
        self.assertIn("--plus", cm.exception.msg)

    def test_app_rejects_plus_token(self):
        with self.assertRaises(cutc.CutError) as cm:
            cutc.compile_source("@raw var p: *u32 = 0x1000\n", "x.ds", "app")
        self.assertEqual(cm.exception.code, "E_CUT_LAYER_PLUS")

    def test_cut_code_compiles_in_app_and_plus(self):
        for mode in ("app", "plus"):
            asm = cutc.compile_source(UART, "uart.ds", mode)
            self.assertIn("putc:", asm)
            self.assertIn(".equ UART0", asm)

    def test_layer_error_location(self):
        try:
            cutc.compile_source("let x = 1\nclass X {}\n", "x.ds", "cut")
        except cutc.CutError as exc:
            self.assertEqual(exc.line, 2)
            self.assertEqual(exc.code, "E_CUT_LAYER_DS")
        else:
            self.fail("应当报层错误")


class TestSemantics(unittest.TestCase):
    def test_ptr_arithmetic_rejected(self):
        src = "@static UART: u32 = 0x1000\nfn f() { let p = UART\n *p = 1\n p = p + 1 }\n"
        with self.assertRaises(cutc.CutError) as cm:
            cutc.compile_source(src, "p.ds", "cut")
        self.assertEqual(cm.exception.code, "E_CUT_PTR_ARITH")

    def test_deref_int_rejected(self):
        with self.assertRaises(cutc.CutError) as cm:
            cutc.compile_source("fn f() { *1 = 2 }\n", "d.ds", "cut")
        self.assertEqual(cm.exception.code, "E_CUT_DEREF")

    def test_static_requires_int(self):
        with self.assertRaises(cutc.CutError) as cm:
            cutc.compile_source("@static A: u32 = 1 + 2\n", "s.ds", "cut")
        self.assertEqual(cm.exception.code, "E_CUT_SYNTAX")

    def test_no_string_expr(self):
        with self.assertRaises(cutc.CutError):
            cutc.compile_source('fn f() { let s = "x" }\n', "s.ds", "cut")


class TestCodegen(unittest.TestCase):
    def test_irq_vector_and_prologue(self):
        asm = cutc.compile_source(UART, "uart.ds", "cut")
        self.assertIn("timer_irq:", asm)
        self.assertIn("push {lr}", asm)
        self.assertIn(".section .vector_table", asm)
        self.assertIn(".word timer_irq", asm)

    def test_pure_asm_no_prologue(self):
        asm = cutc.compile_source(CTX, "ctx.ds", "cut")
        self.assertIn("context_switch:", asm)
        self.assertIn("push {r4-r11, lr}", asm)
        self.assertNotIn("push {r4, lr}", asm)

    def test_global_asm_and_labels(self):
        asm = cutc.compile_source(START, "start.ds", "cut")
        self.assertIn("reset_handler:", asm)
        self.assertIn(".word 0x20082000", asm)

    def test_asm_constraints(self):
        src = 'fn f() { let a = 1\n let b = 0\n @asm("adds r0, r0, #1", in("r0") a, out("r0") b)\n return b }\n'
        asm = cutc.compile_source(src, "asm.ds", "cut")
        self.assertIn("mov r0, r0", asm)
        self.assertIn("adds r0, r0, #1", asm)

    def test_for_and_if(self):
        src = "fn f() -> u32 { let s = 0\n for i in 0..4 { s = s + i }\n if s > 2 { return 1 }\n return 0 }\n"
        asm = cutc.compile_source(src, "f.ds", "cut")
        self.assertIn(".Lfor_", asm)
        self.assertIn(".Lifend_", asm)

    @unittest.skipUnless(shutil.which("clang"), "需要 clang")
    def test_assemble_thumb(self):
        asm = cutc.compile_source(UART, "uart.ds", "cut")
        with tempfile.TemporaryDirectory() as td:
            sp = pathlib.Path(td) / "u.s"; op = pathlib.Path(td) / "u.o"
            sp.write_text(asm, encoding="utf-8")
            r = subprocess.run(["clang", "--target=thumbv8m.main-none-eabi", "-c",
                                "-o", str(op), str(sp)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertGreater(op.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
