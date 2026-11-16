"""Cut 代码生成回归：tail expression 不能被默认返回值覆盖。"""
import importlib.util
import sys
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("cutc", ROOT / "cut" / "cutc.py")
cutc = importlib.util.module_from_spec(spec)
sys.modules["cutc"] = cutc
spec.loader.exec_module(cutc)


class TestCutCodegen(unittest.TestCase):
    def test_tail_expression_preserved(self):
        asm = cutc.compile_source(
            "fn add(a: u32, b: u32) -> u32 { a + b }\n", "add.ds", "cut")
        # 默认 movs 只能在函数体前；尾表达式之后直接进入 ret 标签
        body = asm.split("add:", 1)[1].split(".Lret_", 1)[0]
        self.assertIn("adds r0, r0, r1", body)
        self.assertLess(body.index("movs r0, #0"), body.index("adds r0, r0, r1"))

    def test_irq_vector_and_pure_asm(self):
        src = ("@irq fn tick() { }\n"
               "fn ctx(old: *u32, nxt: *u32) { @asm \"pop {r4-r11, pc}\" }\n")
        asm = cutc.compile_source(src, "irq.ds", "cut")
        self.assertIn(".word tick", asm)
        ctx = asm.split("ctx:", 1)[1]
        self.assertIn("pop {r4-r11, pc}", ctx)
        self.assertNotIn("push {r4, lr}", ctx.split("pop")[0])


if __name__ == "__main__":
    unittest.main()
