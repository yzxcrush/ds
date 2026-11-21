#!/usr/bin/env python3
"""Create a sanitized Ds project backup zip on the phone.

Usage:
  python3 tools/make_backup.py --name DsBackup-DsOS-M1-20261121-1900 \
      --milestone "DsOS Phase1 QEMU alive" --out /sdcard/Download/DsBackups
"""
from __future__ import annotations
import argparse, hashlib, json, pathlib, re, shutil, subprocess, sys, zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
PHONE = pathlib.Path("/data/data/com.termux/files/home/storage/downloads")
DEFAULT_OUT = PHONE / "DsBackups"
IGNORE = {".tmp", "exports", "build", "dsv01.egg-info", "__pycache__", "dist", ".gradle", "app/build"}
TOKEN_RE = re.compile(rb"ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]+")


def ignore(_d, names):
    return [n for n in names if n in IGNORE or n.endswith(".pyc")]


def copytree(src: pathlib.Path, dst: pathlib.Path):
    if src.is_dir():
        shutil.copytree(src, dst, ignore=ignore, dirs_exist_ok=True)


def sanitize_text(p: pathlib.Path):
    try:
        b = p.read_bytes()
    except OSError:
        return
    nb = TOKEN_RE.sub(b"<REDACTED_GITHUB_TOKEN>", b)
    if nb != b:
        p.write_bytes(nb)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--milestone", required=True)
    ap.add_argument("--status", default="unverified", choices=["unverified", "verified"])
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()
    out = pathlib.Path(args.out); out.mkdir(parents=True, exist_ok=True)
    tmp = out / (args.name + ".tmpdir")
    if tmp.exists(): shutil.rmtree(tmp)
    for d in ("项目", "产物/对话记录", "产物/交接资料", "文档"): (tmp / d).mkdir(parents=True, exist_ok=True)
    # projects
    copytree(ROOT, tmp / "项目/ds-main")
    copytree(ROOT / ".tmp/ds-plus-wt", tmp / "项目/ds-plus")
    android = ROOT.parent / "ds-android"
    copytree(android, tmp / "项目/ds-android")
    # key artifacts
    for rel in ("dsos/images/x86_64/dsos-x86_64.img", "dsos/images/x86_64/dsos-bios.img",
                "dsos/phase1/kernel.bin", "dsos/toolchain/step2/examples/hello.bin",
                "dsos/toolchain/step4/examples/call.bin", "dsos/toolchain/step5/examples/branch.bin"):
        p = ROOT / rel
        if p.exists():
            (tmp / "产物" / p.name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, tmp / "产物" / p.name)
    # chat
    chat = ROOT / "exports/ds-chat-2026-11-21"
    for n in ("chat.md", "chat.jsonl", "manifest.json"):
        if (chat / n).exists(): shutil.copy2(chat / n, tmp / "产物/对话记录" / n)
    # handoff docs
    for n in ("HANDOFF.md", "NEXT_AI_PROMPT.md", "README.md"):
        p = ROOT / "exports/DsAIHandoff-2026-11-21" / n
        if p.exists(): shutil.copy2(p, tmp / "产物/交接资料" / n)
    # status
    (tmp / "BACKUP.md").write_text(
        f"# Ds 补充备份\n\n- 名称：{args.name}\n- 里程碑：{args.milestone}\n- 状态：{args.status}\n"
        f"- 生成：2026-11-21\n\n> 本包是 `交接` 的补充备份；未验证状态不得当作已验证。\n",
        encoding="utf-8")
    # sanitize all
    for p in tmp.rglob("*"):
        if p.is_file(): sanitize_text(p)
    # manifest
    files = [p for p in tmp.rglob("*") if p.is_file() and p.name != "MANIFEST.json"]
    ents=[]; total=0
    for p in sorted(files):
        b=p.read_bytes(); total+=len(b)
        ents.append({"path":str(p.relative_to(tmp)),"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest()})
    (tmp / "MANIFEST.json").write_text(json.dumps(
        {"name":args.name,"milestone":args.milestone,"status":args.status,
         "file_count":len(ents),"total_bytes":total,"files":ents},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    # zip
    zpath = out / (args.name + ".zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(tmp.rglob("*")):
            if p.is_file(): z.write(p, str(pathlib.Path(args.name) / p.relative_to(tmp)))
    # verify
    with zipfile.ZipFile(zpath) as z:
        assert z.testzip() is None
    # token scan
    hits=[]
    for p in tmp.rglob("*"):
        if p.is_file() and TOKEN_RE.search(p.read_bytes()): hits.append(str(p))
    shutil.rmtree(tmp)
    print(f"backup: {zpath}")
    print(f"files={len(ents)} bytes={zpath.stat().st_size} token_hits={len(hits)}")
    if hits:
        print("ERROR token hits:", hits[:5], file=sys.stderr); return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
