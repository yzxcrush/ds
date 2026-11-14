"""Step 4：Ds+ 严格超集校验器测试。"""
import json, pathlib, subprocess, sys, unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
CHECK = ROOT / "ds-plus" / "tools" / "superset_check.py"


class TestSuperset(unittest.TestCase):
    def test_static_checks_pass(self):
        r = subprocess.run([sys.executable, str(CHECK), "--json"],
                           capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        data = json.loads(r.stdout)
        self.assertTrue(data["ok"])
        ids = {c["id"] for c in data["checks"] if c["ok"]}
        for sid in ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11", "S12"):
            self.assertIn(sid, ids)

    def test_compile_mode(self):
        r = subprocess.run([sys.executable, str(CHECK), "--compile", "--json"],
                           capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        data = json.loads(r.stdout)
        self.assertIn("S13", {c["id"] for c in data["checks"] if c["ok"]})


if __name__ == "__main__":
    unittest.main()
