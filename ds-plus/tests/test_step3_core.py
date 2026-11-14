"""Step 3：ds-core 共享模块契约测试。"""
import json, pathlib, subprocess, sys, unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
CORE = ROOT / "ds-core"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


class TestCore(unittest.TestCase):
    def setUp(self):
        self.version = load(CORE / "version.json")
        self.plus = load(CORE / "plus.keywords.json")
        self.registry = load(CORE / "keywords.registry.json")
        self.base_snap = load(CORE / "base.keywords.snapshot.json")
        self.abi = load(CORE / "abi" / "abi.json")
        self.ir = load(CORE / "ir" / "ir.schema.json")
        self.codes = load(CORE / "diagnostics" / "codes.json")
        self.spec = load(ROOT / "spec" / "keywords.json")

    def test_version_sync(self):
        self.assertEqual(self.version["base_branch"], "main")
        self.assertEqual(self.version["plus_branch"], "ds-plus")
        self.assertEqual(self.version["version"], self.plus["version"])
        self.assertEqual(self.version["surfaces"], ["classic", "concise", "flow"])
        self.assertEqual(self.version["ast"], "shared")

    def test_base_snapshot_frozen(self):
        self.assertEqual(self.base_snap["count"], 77)
        self.assertEqual(sorted(e["word"] for e in self.spec["alphabetical"]),
                         sorted(self.base_snap["words"]))

    def test_registry_counts(self):
        self.assertEqual(self.registry["base_count"], 77)
        self.assertEqual(self.registry["plus_count"], 16)
        self.assertEqual(self.registry["total"], 93)
        base = [e for e in self.registry["entries"] if e["branch"] == "base"]
        plus = [e for e in self.registry["entries"] if e["branch"] == "plus"]
        self.assertEqual(len(base), 77)
        self.assertEqual(len(plus), 16)
        self.assertEqual({e["token"] for e in plus}, {e["name"] for e in self.plus["keywords"]})

    def test_build_registry_check(self):
        r = subprocess.run([sys.executable, str(CORE / "tools" / "build_registry.py"), "--check"],
                           capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_abi(self):
        self.assertEqual(self.abi["default_layout"], "repr(Ds)")
        self.assertEqual(self.abi["c_layout"], "repr(C)")
        self.assertEqual(self.abi["bare_extern_abi"], "C")
        triples = {t["triple"] for t in self.abi["build_targets"]}
        for t in ("x86_64-linux-gnu", "aarch64-linux-gnu", "thumbv7em-none-eabi", "riscv32-none-elf"):
            self.assertIn(t, triples)
        self.assertIn("raw-binary", self.abi["plus_outputs"])

    def test_ir_additive(self):
        self.assertIn("InlineAsm", {n["name"] for n in self.ir["plus_nodes"]})
        self.assertIn("RegionAlloc", {n["name"] for n in self.ir["plus_nodes"]})
        for base_node in ("Module", "FnDecl", "Block", "Alloc", "Call"):
            self.assertIn(base_node, self.ir["base_nodes"])
        self.assertTrue(self.ir["invariants"])

    def test_diagnostics_complete(self):
        codes = {c["code"] for c in self.codes["codes"]}
        for e in self.plus["keywords"]:
            self.assertIn(e["base_stub"]["code"], codes)
        for c in ("E_DS_PLUS_PROFILE", "E_DS_PLUS_TARGET", "E_DS_PLUS_UNSAFE",
                  "E_DS_PLUS_CONST", "E_DS_PLUS_ALIGN", "E_DS_PLUS_VERSION_MISMATCH"):
            self.assertIn(c, codes)
        self.assertEqual(len(codes), len(self.codes["codes"]))


if __name__ == "__main__":
    unittest.main()
