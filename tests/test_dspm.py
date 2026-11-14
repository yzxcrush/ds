"""dspm 原型测试：用 file:// 本地镜像模拟 GitHub，无网络依赖。"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DSPM = ROOT / "tools" / "dspm.py"


class FakeGitHub:
    def __init__(self, root: pathlib.Path):
        self.root = root / "github"

    def add(self, owner: str, repo: str, tag: str, files: dict[str, str]):
        tgz = self.root / owner / repo / "archive" / "refs" / "tags" / f"{tag}.tar.gz"
        tgz.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as work:
            base = pathlib.Path(work)
            with tarfile.open(tgz, "w:gz") as tar:
                for rel, content in files.items():
                    p = base / rel
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(content, encoding="utf-8")
                    tar.add(p, arcname=f"{repo}-{tag}/{rel}")
        return tgz


def meta(name, version, exports=None, deps=None, targets=None):
    lines = [f'name = "{name}"', f'version = "{version}"']
    if exports is not None:
        lines.append("exports = [" + ", ".join(f'"{e}"' for e in exports) + "]")
    if deps is not None:
        lines.append("deps = [" + ", ".join(f'"{d}"' for d in deps) + "]")
    if targets is not None:
        lines.append("targets = [" + ", ".join(f'"{t}"' for t in targets) + "]")
    return "\n".join(lines) + "\n"


class TestDspm(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self.td.name)
        self.gh = FakeGitHub(self.tmp)
        self.home = self.tmp / "home"
        self.env = dict(os.environ, DSPM_HOME=str(self.home),
                        DSPM_GITHUB_BASE=f"file://{self.gh.root}",
                        DSPM_GITHUB_API="http://127.0.0.1:9")

    def tearDown(self):
        self.td.cleanup()

    def run_dspm(self, *args, stdin=None):
        return subprocess.run([sys.executable, str(DSPM), *args], capture_output=True,
                              text=True, cwd=ROOT, env=self.env, stdin=stdin,
                              timeout=60)

    def pkg(self, owner, repo, tag, exports=("a",), deps=None, targets=("app",),
            extra=None, unsafe=False):
        files = {"ds.toml": meta(repo, tag.lstrip("v"), exports=list(exports),
                                 deps=deps, targets=list(targets))}
        for e in exports:
            files[f"src/{e}.ds"] = f"package {repo}\n"
        if unsafe:
            files["src/u.ds"] = '@unsafe fn f() { @asm volatile("nop") }\n'
        if extra:
            files.update(extra)
        self.gh.add(owner, repo, tag, files)

    # ------------------------------------------------------------ 安装/lock
    def test_install_and_lock(self):
        self.pkg("fake", "a", "v1")
        r = self.run_dspm("install", "fake/a@v1", "--target", "ds")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        installed = self.home / "pkg" / "fake" / "a@v1" / "src" / "a.ds"
        self.assertTrue(installed.exists())
        lock = json.loads((self.home / "dspm.lock").read_text(encoding="utf-8"))
        e = lock["packages"]["fake/a"]
        self.assertEqual(e["tag"], "v1")
        self.assertEqual(len(e["tarball_sha256"]), 64)
        self.assertEqual(e["path"], "pkg/fake/a@v1")

    def test_latest_tag(self):
        self.pkg("fake", "a", "v1")
        self.pkg("fake", "a", "v2")
        r = self.run_dspm("install", "fake/a@latest")
        self.assertEqual(r.returncode, 0, r.stderr)
        lock = json.loads((self.home / "dspm.lock").read_text(encoding="utf-8"))
        self.assertEqual(lock["packages"]["fake/a"]["tag"], "v2")

    def test_deps_dfs(self):
        self.pkg("fake", "b", "v1")
        self.pkg("fake", "a", "v1", deps=["fake/b@v1"])
        r = self.run_dspm("install", "fake/a@v1", "--target", "ds")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for key in ("fake/a@v1", "fake/b@v1"):
            self.assertTrue((self.home / "pkg" / key / "src").exists(), key)
        lock = json.loads((self.home / "dspm.lock").read_text(encoding="utf-8"))
        self.assertEqual(set(lock["packages"]), {"fake/a", "fake/b"})

    def test_cache_offline(self):
        self.pkg("fake", "a", "v1")
        self.assertEqual(self.run_dspm("install", "fake/a@v1").returncode, 0)
        shutil.rmtree(self.home / "pkg" / "fake" / "a@v1")
        self.env["DSPM_GITHUB_BASE"] = "file:///nonexistent"
        r = self.run_dspm("install", "fake/a@v1", "--offline")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.home / "pkg" / "fake" / "a@v1" / "ds.toml").exists())

    def test_target_filter(self):
        self.pkg("fake", "pluspkg", "v1", targets=("plus",))
        r = self.run_dspm("install", "fake/pluspkg@v1", "--target", "ds")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("不兼容", r.stderr)
        r = self.run_dspm("install", "fake/pluspkg@v1", "--target", "plus")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_unsafe_confirmation(self):
        self.pkg("fake", "u", "v1", unsafe=True)
        r = self.run_dspm("install", "fake/u@v1", stdin=subprocess.DEVNULL)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--yes", r.stderr)
        r = self.run_dspm("install", "fake/u@v1", "--yes")
        self.assertEqual(r.returncode, 0, r.stderr)
        lock = json.loads((self.home / "dspm.lock").read_text(encoding="utf-8"))
        self.assertTrue(lock["packages"]["fake/u"]["unsafe"])

    def test_traversal_rejected(self):
        tgz = self.gh.root / "fake" / "evil" / "archive" / "refs" / "tags" / "v1.tar.gz"
        tgz.parent.mkdir(parents=True)
        with tarfile.open(tgz, "w:gz") as tar:
            p = self.tmp / "ds.toml"
            p.write_text(meta("evil", "1.0"), encoding="utf-8")
            tar.add(p, arcname="evil-v1/ds.toml")
            tar.add(p, arcname="../escape.txt")
        r = self.run_dspm("install", "fake/evil@v1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("越界", r.stderr)

    def test_list_remove_cache(self):
        self.pkg("fake", "a", "v1")
        self.assertEqual(self.run_dspm("install", "fake/a@v1").returncode, 0)
        r = self.run_dspm("list")
        self.assertEqual(r.returncode, 0)
        self.assertIn("fake/a", r.stdout)
        self.assertEqual(self.run_dspm("remove", "fake/a").returncode, 0)
        self.assertIn("没有已安装", self.run_dspm("list").stdout)
        self.assertEqual(self.run_dspm("cache-clean").returncode, 0)
        self.assertFalse((self.home / "cache").exists())

    def test_example_package(self):
        import tomllib
        root = ROOT / "examples" / "packages" / "ds-hello"
        meta = tomllib.loads((root / "ds.toml").read_text(encoding="utf-8"))
        self.assertEqual(meta["name"], "ds-hello")
        self.assertIn("hello", meta["exports"])
        self.assertTrue((root / "src" / "hello.ds").exists())

    def test_resolve_module(self):
        self.pkg("fake", "a", "v1", exports=("a",))
        self.assertEqual(self.run_dspm("install", "fake/a@v1").returncode, 0)
        r = self.run_dspm("resolve", "a", "--target", "ds")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.strip().endswith("a.ds"))
        r = self.run_dspm("resolve", "missing")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("dspm install", r.stderr)


if __name__ == "__main__":
    unittest.main()
