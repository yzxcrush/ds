"""Step 2：Ds+ 关键字注册表与 base stub 守卫测试。"""
import json
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
REG = json.loads((ROOT / "ds-core" / "plus.keywords.json").read_text(encoding="utf-8"))
BASE = json.loads((ROOT / "spec" / "keywords.json").read_text(encoding="utf-8"))
BASE_WORDS = {e["word"] for e in BASE["alphabetical"]}
ENTRIES = REG["keywords"]
BY_NAME = {e["name"]: e for e in ENTRIES}
GUARD = ROOT / "ds-plus" / "tools" / "keyword_guard.py"


class TestRegistry(unittest.TestCase):
    def test_base_77_frozen(self):
        self.assertEqual(BASE["totals"]["keywords"], 77)
        self.assertEqual(REG["base_keywords"], 77)

    def test_counts(self):
        hw = [e for e in ENTRIES if e["kind"] == "hardware"]
        rg = [e for e in ENTRIES if e["kind"] == "region"]
        self.assertEqual(len(hw), 12)
        self.assertEqual(len(rg), 4)
        self.assertEqual(REG["counts"]["new_at_tokens"], 16)

    def test_all_at_prefixed_and_unique(self):
        self.assertEqual(len(ENTRIES), len({e["name"] for e in ENTRIES}))
        for e in ENTRIES:
            self.assertTrue(e["name"].startswith("@"), e["name"])
            self.assertNotIn(e["name"], BASE_WORDS)

    def test_required_fields(self):
        need = {"name", "kind", "category", "pyx", "syntax", "semantics",
                "lowering", "profiles", "targets", "requires_unsafe", "base_stub"}
        for e in ENTRIES:
            self.assertTrue(need <= set(e), e["name"])
            stub = e["base_stub"]
            self.assertTrue(stub["code"].startswith("E_DS_PLUS_"), stub)
            self.assertIn(e["name"], stub["message"], stub)
            self.assertTrue(stub["base_alternative"])

    def test_stub_codes_unique(self):
        codes = [e["base_stub"]["code"] for e in ENTRIES]
        self.assertEqual(len(codes), len(set(codes)))

    def test_profiles(self):
        self.assertEqual(BY_NAME["@asm"]["profiles"], ["bare"])
        for region in ("@stack", "@static", "@raw", "@mmap"):
            self.assertEqual(BY_NAME[region]["profiles"], ["bare", "compat"])
        self.assertTrue(BY_NAME["@raw"]["requires_unsafe"])
        self.assertFalse(BY_NAME["@stack"]["requires_unsafe"])

    def test_not_adopted(self):
        adopted = {e["name"] for e in ENTRIES}
        for word in ("@trusted",):
            self.assertNotIn(word, adopted)


class TestGuard(unittest.TestCase):
    def run_guard(self, *args):
        return subprocess.run([sys.executable, str(GUARD), *args],
                              capture_output=True, text=True, cwd=ROOT)

    def test_plus_example_detected(self):
        sample = ROOT / "ds-plus" / "examples" / "plus_keywords.ds"
        r = self.run_guard("--json", str(sample))
        self.assertEqual(r.returncode, 2, r.stderr)
        data = json.loads(r.stdout)
        names = {h["name"] for h in data["hits"]}
        self.assertEqual(len(names), 16, names)
        self.assertIn("@asm", names)
        self.assertIn("@mmap", names)

    def test_base_code_clean(self):
        r = self.run_guard(str(ROOT / "examples" / "concise" / "hello.ds"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_all_mode(self):
        r = self.run_guard("--all", "--json", str(ROOT / "ds-plus" / "examples" / "plus_keywords.ds"))
        self.assertEqual(r.returncode, 2)
        self.assertGreaterEqual(len(json.loads(r.stdout)["hits"]), 16)


if __name__ == "__main__":
    unittest.main()
