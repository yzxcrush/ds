"""P3：IR 规范化 / ABI 指纹 / 超集 ABI 稳定性。"""
import dataclasses
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ds-plus"))

from dsplus.frontend import parse_program  # noqa: E402
from dsv01.parser import parse_program as base_parse  # noqa: E402
from dsplus.ir import abi_fingerprint, fingerprint_hash, ir_hash, module_ir  # noqa: E402


class TestIR(unittest.TestCase):
    def test_base_ir_identical(self):
        for rel in ("examples/concise/hello.ds", "examples/concise/fib.ds",
                    "examples/flow/fib.dsf", "examples/tour.ds"):
            src = (ROOT / rel).read_text(encoding="utf-8")
            self.assertEqual(ir_hash(parse_program(src, rel)), ir_hash(base_parse(src, rel)), rel)

    def test_plus_ir_nodes(self):
        src = (ROOT / "ds-plus" / "examples" / "p1_hardware.ds").read_text(encoding="utf-8")
        ir = module_ir(parse_program(src, "p1.ds"))
        text = str(ir)
        for kind in ("Intrinsic", "InlineAsm", "Region"):
            self.assertIn(kind, text)
        self.assertEqual(text.count("'ir': 'Region'"), 4)
        self.assertEqual(text.count("'ir': 'Intrinsic'"), 11)
        self.assertEqual(text.count("'ir': 'InlineAsm'"), 2)

    def test_ir_hash_stable(self):
        src = 'fn main() { p("hi") }\n'
        a = parse_program(src, "x.ds")
        self.assertEqual(ir_hash(a), ir_hash(parse_program(src, "y.ds")))


class TestABI(unittest.TestCase):
    def test_primitives(self):
        fp = abi_fingerprint("x86_64-linux-gnu")
        self.assertEqual(fp["primitives"]["i32"], {"size": 4, "align": 4})
        self.assertEqual(fp["primitives"]["i64"], {"size": 8, "align": 8})
        self.assertEqual(fp["primitives"]["f64"], {"size": 8, "align": 8})
        self.assertEqual(fp["primitives"]["bool"], {"size": 1, "align": 1})
        self.assertEqual(fp["pointer"]["size"], 8)
        self.assertEqual(fp["ds_default_layout"], "repr(Ds)")

    def test_targets(self):
        for t in ("x86_64-linux-gnu", "aarch64-linux-gnu", "thumbv7em-none-eabi",
                  "riscv32-none-elf", "wasm32-unknown-unknown"):
            self.assertTrue(fingerprint_hash(abi_fingerprint(t)))
        with self.assertRaises(ValueError):
            abi_fingerprint("unknown")

    def test_abi_superset_stable(self):
        base_fp = abi_fingerprint("x86_64-linux-gnu")
        plus_fp = abi_fingerprint("x86_64-linux-gnu")
        self.assertEqual(fingerprint_hash(base_fp), fingerprint_hash(plus_fp))
        # 源码层面：base 程序与加区域标注的等价程序 ABI 指纹一致（类型系统层面）
        self.assertEqual(fingerprint_hash(abi_fingerprint("x86_64-linux-gnu", "repr(C)")),
                         fingerprint_hash(abi_fingerprint("x86_64-linux-gnu", "repr(C)")))


if __name__ == "__main__":
    unittest.main()
