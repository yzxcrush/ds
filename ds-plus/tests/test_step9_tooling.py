"""P5：CLI 与 AI 资产。"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
CLI = ROOT / "ds-plus" / "tools" / "dsplus_cli.py"
ENV = dict(os.environ, PYTHONPATH=f"{ROOT / 'ds-plus'}{os.pathsep}{ROOT}")


def run_cli(*args):
    return subprocess.run([sys.executable, str(CLI), *args],
                          capture_output=True, text=True, cwd=ROOT, env=ENV)


class TestCLI(unittest.TestCase):
    def test_version(self):
        r = run_cli("--version")
        self.assertEqual(r.returncode, 0)
        self.assertIn("0.1.0", r.stdout)

    def test_check_ok(self):
        f = ROOT / "ds-plus" / "examples" / "p1_hardware.ds"
        r = run_cli("check", str(f), "--profile", "bare")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_check_unsafe(self):
        with tempfile.TemporaryDirectory() as td:
            f = pathlib.Path(td) / "u.ds"
            f.write_text("fn f() { @inb(0x60) }\n", encoding="utf-8")
            r = run_cli("check", str(f), "--profile", "bare", "--json")
            self.assertEqual(r.returncode, 1)
            data = json.loads(r.stdout)
            self.assertIn("E_DS_PLUS_UNSAFE", {d["code"] for d in data["diagnostics"]})

    def test_run_sim(self):
        with tempfile.TemporaryDirectory() as td:
            f = pathlib.Path(td) / "s.ds"
            f.write_text('@unsafe fn main() { @outb(0x3F8, 65) p(@inb(0x3F8)) }\n',
                         encoding="utf-8")
            r = run_cli("run", str(f), "--profile", "bare")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout, "65\n")

    def test_ir_hash_and_abi(self):
        r = run_cli("ir", str(ROOT / "ds-plus" / "examples" / "p1_hardware.ds"), "--hash")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(len(r.stdout.strip()), 64)
        r = run_cli("abi", "--target", "x86_64-linux-gnu")
        data = json.loads(r.stdout)
        self.assertEqual(data["pointer"]["size"], 8)
        self.assertEqual(data["ds_default_layout"], "repr(Ds)")

    def test_build(self):
        with tempfile.TemporaryDirectory() as td:
            f = pathlib.Path(td) / "b.ds"
            f.write_text("fn main() -> i32 { return 42 }\n", encoding="utf-8")
            out = pathlib.Path(td) / "b.elf"
            r = run_cli("build", str(f), "-o", str(out), "--raw")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(out.read_bytes()[:4], b"\x7fELF")
            self.assertTrue((pathlib.Path(str(out) + ".bin")).exists())


class TestPlusAI(unittest.TestCase):
    def test_sft_shape(self):
        rows = [json.loads(l) for l in (ROOT / "ds-plus" / "datasets" / "ds_plus_sft.jsonl")
                .read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertGreaterEqual(len(rows), 8)
        for row in rows:
            self.assertEqual(row["messages"][0]["role"], "user")
            self.assertEqual(row["messages"][1]["role"], "assistant")
            self.assertTrue(row["messages"][0]["content"])

    def test_card(self):
        text = (ROOT / "ds-plus" / "ai" / "PLUS_CARD.md").read_text(encoding="utf-8")
        for token in ("@inb", "@stack", "dsplus build", "@unsafe"):
            self.assertIn(token, text)


if __name__ == "__main__":
    unittest.main()
