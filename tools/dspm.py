#!/usr/bin/env python3
"""dspm — Ds 包管理器原型（v0.1）。

包 = GitHub 仓库，版本 = git tag，源码即分发；无中心服务器。
用法见 docs/DSPM.md。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    tomllib = None

HOME = Path(os.environ.get("DSPM_HOME", "~/.ds")).expanduser()
PKG = HOME / "pkg"
CACHE = HOME / "cache"
LOCK = HOME / "dspm.lock"
BASE = os.environ.get("DSPM_GITHUB_BASE", "https://github.com").rstrip("/")
API = os.environ.get("DSPM_GITHUB_API", "https://api.github.com").rstrip("/")
TOKEN = os.environ.get("DSPM_TOKEN") or os.environ.get("GITHUB_TOKEN")
INDEX_URL = os.environ.get(
    "DSPM_INDEX_URL",
    "https://raw.githubusercontent.com/yzxcrush/ds-packages/main/index.json")
INDEX_CACHE = CACHE / "index.json"
UA = "dspm/0.1 (+https://github.com/yzxcrush/ds)"
REF_RE = re.compile(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)(?:@([A-Za-z0-9_.-]+))?$")
AT_RE = re.compile(r"@(asm|raw|inb|outb|inw|outw|inl|outl|rdmsr|wrmsr|rdcr|wrcr|mmap|mmio)\b")


def log(msg: str) -> None:
    print(msg)


def die(msg: str, code: int = 1):
    print(f"dspm: error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def parse_ref(ref: str) -> tuple[str, str, str]:
    m = REF_RE.match(ref.strip())
    if not m or ".." in ref:
        die(f"非法包引用 `{ref}`，期望 <user>/<repo>[@tag]")
    owner, repo, tag = m.group(1), m.group(2), m.group(3) or "latest"
    return owner, repo, tag


def load_lock() -> dict:
    if LOCK.exists():
        return json.loads(LOCK.read_text(encoding="utf-8"))
    return {"version": 1, "packages": {}}


def save_lock(lock: dict) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    if TOKEN and "api.github.com" in url:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def _is_online_base() -> bool:
    return BASE.startswith("https://github.com")


def _local_base_dir() -> Path | None:
    u = urlparse(BASE)
    return Path(u.path) if u.scheme == "file" else None


def latest_tag(owner: str, repo: str) -> str:
    local = _local_base_dir()
    if local is not None:
        tags_dir = local / owner / repo / "archive" / "refs" / "tags"
        tags = sorted(p.name[:-7] for p in tags_dir.glob("*.tar.gz")) if tags_dir.exists() else []
        if not tags:
            die(f"本地镜像没有 {owner}/{repo} 的 tag")
        return tags[-1]
    if not _is_online_base():
        die("离线模式无法解析 @latest；请显式指定 tag 或使用 --offline")
    for url in (f"{API}/repos/{owner}/{repo}/tags?per_page=1",
                f"{API}/repos/{owner}/{repo}/releases/latest"):
        try:
            data = json.loads(_get(url))
            if isinstance(data, list) and data:
                return data[0]["name"]
            if isinstance(data, dict) and data.get("tag_name"):
                return data["tag_name"]
        except Exception:
            continue
    die(f"无法解析 {owner}/{repo} 的最新 tag（GitHub API 失败）")


def commit_sha(owner: str, repo: str, tag: str) -> str | None:
    if not _is_online_base():
        return None
    try:
        return json.loads(_get(f"{API}/repos/{owner}/{repo}/commits/{tag}"))["sha"]
    except Exception:
        return None


def download(owner: str, repo: str, tag: str, offline: bool) -> tuple[Path, bool]:
    cached = CACHE / owner / f"{repo}@{tag}.tar.gz"
    if cached.exists():
        return cached, True
    if offline:
        die(f"{owner}/{repo}@{tag} 不在缓存中（离线模式）")
    cached.parent.mkdir(parents=True, exist_ok=True)
    tmp = cached.with_suffix(".part")
    urls = [f"{BASE}/{owner}/{repo}/archive/refs/tags/{tag}.tar.gz"]
    if "github.com" in BASE:
        urls += [
            f"https://codeload.github.com/{owner}/{repo}/tar.gz/refs/tags/{tag}",
            f"{API}/repos/{owner}/{repo}/tarball/{tag}",
        ]
    last = None
    for url in urls:
        for attempt in range(2):
            try:
                log(f"↓ {url}")
                headers = {"User-Agent": UA}
                if TOKEN and "api.github.com" in url:
                    headers["Authorization"] = f"Bearer {TOKEN}"
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                            timeout=120) as r, open(tmp, "wb") as f:
                    shutil.copyfileobj(r, f)
                with tarfile.open(tmp, "r:gz"):
                    pass  # 校验 tar
                tmp.replace(cached)
                return cached, False
            except Exception as exc:
                last = exc
                tmp.unlink(missing_ok=True)
                time.sleep(1)
    die(f"下载失败（已尝试 {len(urls)} 个端点）：{last}")


def fetch_index(offline: bool = False, refresh: bool = False) -> dict:
    """获取包索引（短名 → GitHub repo）。默认缓存优先，可离线。"""
    if INDEX_CACHE.exists() and not refresh:
        try:
            return json.loads(INDEX_CACHE.read_text(encoding="utf-8"))
        except Exception:
            pass
    if offline:
        die("离线模式需要本地索引缓存；先联网运行一次 `dspm index`")
    urls = [INDEX_URL]
    if INDEX_URL.startswith("https://raw.githubusercontent.com/") and "DSPM_INDEX_URL" not in os.environ:
        urls.append("https://cdn.jsdelivr.net/gh/yzxcrush/ds-packages@main/index.json")
    last = None
    for url in urls:
        for _ in range(2):
            try:
                data = json.loads(_get(url))
                INDEX_CACHE.parent.mkdir(parents=True, exist_ok=True)
                INDEX_CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8")
                return data
            except Exception as exc:
                last = exc
    if INDEX_CACHE.exists():
        return json.loads(INDEX_CACHE.read_text(encoding="utf-8"))
    die(f"获取包索引失败：{last}（{INDEX_URL}）")
    INDEX_CACHE.parent.mkdir(parents=True, exist_ok=True)
    INDEX_CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def _split_name_tag(ref: str) -> tuple[str, str | None]:
    if "@" in ref:
        name, tag = ref.split("@", 1)
        return name, tag or None
    return ref, None


def resolve_target(ref: str, offline: bool = False) -> tuple[str, str, str]:
    """解析安装目标：支持 `owner/repo[@tag]` 或索引短名 `pkg[@tag]`。"""
    if "/" in ref:
        return parse_ref(ref)
    name, tag = _split_name_tag(ref)
    idx = fetch_index(offline)
    entry = (idx.get("packages") or {}).get(name)
    if not entry:
        die(f"索引里没有包 `{name}`；用 `dspm search <关键词>` 查看，或直接安装 `owner/repo@tag`")
    repo = entry.get("repo", "")
    if "/" not in repo:
        die(f"索引项 `{name}` 的 repo 非法：{repo!r}")
    owner, repo_name = repo.split("/", 1)
    return owner, repo_name, tag or entry.get("latest") or "latest"


def _safe_extract(tar: tarfile.TarFile, dest: Path) -> int:
    dest = dest.resolve()
    for m in tar.getmembers():
        if m.issym() or m.islnk():
            die(f"拒绝符号链接/硬链接：{m.name}")
        target = (dest / m.name).resolve()
        if target != dest and not str(target).startswith(str(dest) + os.sep):
            die(f"压缩包路径越界：{m.name}")
    tar.extractall(dest)
    return len(tar.getmembers())


def _meta_get(meta: dict, *keys: str, default=None):
    for k in keys:
        if k in meta:
            return meta[k]
    return default


def read_meta(path: Path) -> dict:
    f = path / "ds.toml"
    if not f.exists():
        die(f"包缺少 ds.toml：{path}")
    if tomllib is None:
        die("需要 Python 3.11+（tomllib）读取 ds.toml")
    try:
        meta = tomllib.loads(f.read_text(encoding="utf-8"))
    except Exception as exc:
        die(f"ds.toml 解析失败：{exc}")
    if not meta.get("name") or not meta.get("version"):
        die("ds.toml 必须包含 name 和 version")
    meta.setdefault("exports", [])
    meta.setdefault("deps", [])
    meta.setdefault("targets", ["app"])
    meta["deps"] = _meta_get(meta, "deps", "DEPS", "依赖", default=[])
    return meta


def scan_sources(path: Path) -> tuple[list[Path], bool]:
    files = [p for p in path.rglob("*") if p.is_file() and p.suffix in (".ds", ".dsf")]
    unsafe = any(AT_RE.search(p.read_text(encoding="utf-8", errors="replace")) for p in files)
    return files, unsafe


def target_ok(meta: dict, target: str) -> bool:
    target = {"cut": "ds", "base": "ds"}.get(target, target)
    targets = set(meta.get("targets") or [])
    if target == "ds":
        return bool({"ds", "app", "bare"} & targets)
    return target in targets


def confirm(meta: dict, owner: str, repo: str, tag: str, files: list[Path],
            unsafe: bool, yes: bool) -> None:
    log(f"包：{meta['name']} {meta['version']}  ({owner}/{repo}@{tag})")
    log(f"作者：{_meta_get(meta, 'authors', 'author', default=owner)}")
    log(f"目标：{meta.get('targets')}  依赖：{len(meta.get('deps', []))}  文件：{len(files)}")
    if unsafe:
        log("⚠ 该包含 @asm/@raw 等 unsafe 能力（安装只解压，不执行任何脚本）")
    if yes or not unsafe:
        return
    if not sys.stdin.isatty():
        die("该包标记 unsafe，非交互安装需要 --yes；请先确认上面的包信息")
    if input("该包含 unsafe 能力，继续安装？[y/N] ").strip().lower() not in ("y", "yes"):
        die("已取消")


def install_ref(ref: str, opts, lock: dict, seen: set[str]) -> None:
    owner, repo, tag = resolve_target(ref, getattr(opts, "offline", False))
    key = f"{owner}/{repo}"
    if key in seen:
        log(f"↺ 跳过已处理的依赖 {key}")
        return
    seen.add(key)
    if tag == "latest":
        tag = latest_tag(owner, repo)
    dest = PKG / owner / f"{repo}@{tag}"
    meta = read_meta(dest) if dest.exists() and not opts.force else None
    if meta is not None:
        log(f"✓ 已安装 {key}@{tag}（本地缓存）")
        files, unsafe = scan_sources(dest)
    else:
        tarball, cached = download(owner, repo, tag, opts.offline)
        tmp = Path(tempfile.mkdtemp(prefix="dspm-", dir=str(HOME)))
        with tarfile.open(tarball, "r:gz") as tar:
            count = _safe_extract(tar, tmp)
        roots = [p for p in tmp.iterdir() if p.is_dir()]
        root = roots[0] if len(roots) == 1 else tmp
        meta = read_meta(root)
        if not target_ok(meta, opts.target):
            die(f"{key} 的 targets={meta.get('targets')} 不兼容 --target {opts.target}")
        files, unsafe = scan_sources(root)
        confirm(meta, owner, repo, tag, files, unsafe, opts.yes)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.move(str(root), str(dest))
        shutil.rmtree(tmp, ignore_errors=True)
        log(f"✓ 安装 {key}@{tag} → {dest}  ({count} 个文件{'，来自缓存' if cached else ''})")
    sha = commit_sha(owner, repo, tag)
    lock["packages"][key] = {
        "tag": tag, "commit": sha or "",
        "tarball_sha256": hashlib.sha256((CACHE / owner / f"{repo}@{tag}.tar.gz").read_bytes()).hexdigest()
        if (CACHE / owner / f"{repo}@{tag}.tar.gz").exists() else "",
        "path": str(dest.relative_to(HOME)), "targets": meta.get("targets", []),
        "unsafe": bool(unsafe), "deps": meta.get("deps", []), "name": meta.get("name"),
    }
    save_lock(lock)
    for dep in meta.get("deps", []):
        install_ref(dep, opts, lock, seen)


def cmd_install(args) -> int:
    lock = load_lock()
    seen: set[str] = set()
    install_ref(args.ref, args, lock, seen)
    save_lock(lock)
    log(f"完成：{len(seen)} 个包，lock：{LOCK}")
    return 0


def cmd_remove(args) -> int:
    lock = load_lock()
    if "/" in args.ref:
        owner, repo, _ = parse_ref(args.ref)
        targets = [f"{owner}/{repo}"]
    else:
        name, _ = _split_name_tag(args.ref)
        targets = [k for k, e in lock["packages"].items()
                   if k.endswith("/" + name) or e.get("name") == name]
        if not targets:
            owner, repo, _ = resolve_target(args.ref)
            targets = [f"{owner}/{repo}"]
    removed = []
    for key in list(lock["packages"]):
        if key in targets:
            rel = lock["packages"][key]["path"]
            shutil.rmtree(HOME / rel, ignore_errors=True)
            del lock["packages"][key]
            removed.append(key)
    if not removed:
        die(f"未安装 {args.ref}")
    save_lock(lock)
    log(f"✓ 已移除 {', '.join(removed)}")
    return 0


def cmd_list(args) -> int:
    lock = load_lock()
    pkgs = lock.get("packages", {})
    if not pkgs:
        log("（没有已安装的包）")
        return 0
    log(f"{'包':<28} {'tag':<12} {'commit':<10} {'unsafe':<7} path")
    for key, e in sorted(pkgs.items()):
        log(f"{key:<28} {e.get('tag',''):<12} {(e.get('commit') or '-')[:8]:<10} "
            f"{'yes' if e.get('unsafe') else 'no':<7} {e.get('path','')}")
    return 0


def cmd_update(args) -> int:
    lock = load_lock()
    targets = [k for k in lock.get("packages", {}) if not args.repo or args.repo in k]
    if not targets:
        log("没有可更新的包")
        return 0
    for key in targets:
        log(f"检查 {key} …")
        old = lock["packages"][key].get("path", "")
        install_ref(f"{key}@latest", args, lock, set())
        new = lock["packages"][key].get("path", "")
        if old and old != new:
            shutil.rmtree(HOME / old, ignore_errors=True)
    save_lock(lock)
    return 0


def cmd_search(args) -> int:
    idx = fetch_index(args.offline, refresh=args.refresh)
    q = args.query.lower()
    rows = []
    for name, e in sorted((idx.get("packages") or {}).items()):
        hay = f"{name} {e.get('summary', '')} {e.get('repo', '')}".lower()
        if not q or q in hay:
            rows.append((name, e.get("repo", ""), e.get("latest", ""), e.get("summary", "")))
    if args.json:
        print(json.dumps({"query": args.query, "packages": [
            {"name": n, "repo": r, "latest": t, "summary": s} for n, r, t, s in rows]},
            ensure_ascii=False, indent=2))
    else:
        for n, r, t, s in rows:
            print(f"{n:<24} {t:<10} {r:<32} {s}")
        if not rows:
            print("（无匹配包）")
    return 0


def cmd_index(args) -> int:
    idx = fetch_index(args.offline, refresh=args.refresh)
    pkgs = idx.get("packages") or {}
    if args.json:
        print(json.dumps(idx, ensure_ascii=False, indent=2))
    else:
        print(f"索引：{INDEX_URL}")
        print(f"缓存：{INDEX_CACHE}")
        print(f"包数：{len(pkgs)}")
        for n, e in sorted(pkgs.items()):
            print(f"  {n:<24} {e.get('latest', ''):<10} {e.get('repo', '')}")
    return 0


def cmd_cache_clean(args) -> int:
    if CACHE.exists():
        shutil.rmtree(CACHE)
        log(f"✓ 已清理缓存 {CACHE}")
    else:
        log("缓存已经是空的")
    return 0


def resolve_module(module: str, target: str = "ds") -> Path:
    lock = load_lock()
    for key, e in lock.get("packages", {}).items():
        pkgdir = HOME / e["path"]
        meta = read_meta(pkgdir)
        if module not in (meta.get("exports") or []):
            continue
        if not target_ok(meta, target):
            continue
        for cand in (pkgdir / "src" / f"{module}.ds", pkgdir / f"{module}.ds",
                     pkgdir / "src" / f"{module}.dsf"):
            if cand.exists():
                return cand
    die(f"找不到模块 `{module}`；请运行 `dspm install <user>/<repo>` 安装提供它的包")


def cmd_resolve(args) -> int:
    log(str(resolve_module(args.module, args.target)))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="dspm", description="Ds 包管理器（GitHub 包仓库，无中心服务器）")
    ap.add_argument("--version", action="version", version="dspm 0.1.0")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("install", aliases=["安装", "add"], help="安装 <user>/<repo>[@tag]")
    p.add_argument("ref")
    p.add_argument("--target", default="ds", choices=["ds", "cut", "base", "app", "bare", "plus"])
    p.add_argument("--yes", "-y", action="store_true")
    p.add_argument("--offline", action="store_true")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_install)

    p = sub.add_parser("remove", aliases=["移除", "uninstall", "rm"])
    p.add_argument("ref"); p.set_defaults(fn=cmd_remove)

    p = sub.add_parser("list", aliases=["列表", "ls"]); p.set_defaults(fn=cmd_list)

    p = sub.add_parser("update", aliases=["更新", "upgrade"])
    p.add_argument("repo", nargs="?"); p.add_argument("--yes", "-y", action="store_true")
    p.add_argument("--target", default="ds"); p.add_argument("--offline", action="store_true")
    p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_update)

    p = sub.add_parser("cache-clean", aliases=["缓存清理", "clean"])
    p.set_defaults(fn=cmd_cache_clean)

    p = sub.add_parser("search", aliases=["搜索", "find"], help="搜索包索引")
    p.add_argument("query", nargs="?", default=""); p.add_argument("--json", action="store_true")
    p.add_argument("--offline", action="store_true"); p.add_argument("--refresh", action="store_true")
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser("index", aliases=["索引"], help="查看/刷新包索引")
    p.add_argument("--json", action="store_true")
    p.add_argument("--offline", action="store_true"); p.add_argument("--refresh", action="store_true")
    p.set_defaults(fn=cmd_index)

    p = sub.add_parser("resolve", help="编译器用：解析模块路径")
    p.add_argument("module"); p.add_argument("--target", default="ds")
    p.set_defaults(fn=cmd_resolve)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
