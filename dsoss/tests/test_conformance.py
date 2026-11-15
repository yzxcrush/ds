"""DSOSS manifest 检查测试。"""
import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("dsoss_check", ROOT / "dsoss" / "check_conformance.py")
mod = importlib.util.module_from_spec(spec)
sys.modules["dsoss_check"] = mod
spec.loader.exec_module(mod)


class TestConformance(unittest.TestCase):
    def test_examples_pass(self):
        self.assertEqual(mod.check(str(ROOT / "dsoss" / "dsoss.toml")), [])
        self.assertEqual(mod.check(str(ROOT / "dsoss" / "profiles" / "zero2w.toml")), [])

    def test_wrong_arch_fails(self):
        text = (ROOT / "dsoss" / "dsoss.toml").read_text(encoding="utf-8")
        text = text.replace('arch = "thumbv8m.main"', 'arch = "aarch64"')
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False, encoding="utf-8") as f:
            f.write(text); name = f.name
        errs = mod.check(name)
        self.assertTrue(any("kernel.arch" in e for e in errs), errs)

    def test_missing_syscall_fails(self):
        text = (ROOT / "dsoss" / "dsoss.toml").read_text(encoding="utf-8")
        text = text.replace("[[syscalls]]\nnumber = 2\nname = \"sys_exit\"\nargs = 1\n", "")
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False, encoding="utf-8") as f:
            f.write(text); name = f.name
        errs = mod.check(name)
        self.assertTrue(any("syscall 2" in e for e in errs), errs)


if __name__ == "__main__":
    unittest.main()
