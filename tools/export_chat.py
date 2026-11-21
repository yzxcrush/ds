#!/usr/bin/env python3
"""Export the current DSH session to readable Markdown + JSONL.

Usage:
  python3 tools/export_chat.py [--session session.v4.jsonl.zstd] [--out exports/ds-chat]

Reads the DSH session event log (zstd JSONL), exports:
  chat.md              readable user/assistant transcript
  chat.jsonl           user/assistant events only (with tool names)
  session.raw.jsonl    every session event, decompressed
  manifest.json        counts, timestamps, sha256
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import shutil
import sys
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))


def ts(ms: int | None) -> str:
    if not ms:
        return "-"
    return datetime.fromtimestamp(ms / 1000, TZ).strftime("%Y-%m-%d %H:%M:%S")


CONTEXT_PREFIXES = (
    "Current runtime context.",
    "Time sampled while preparing turn",
    "The approval policy changed",
    "Background subagent ",
    "Approval prompts are disabled",
)


def is_runtime_context(text: str) -> bool:
    t = text.lstrip()
    return any(t.startswith(p) for p in CONTEXT_PREFIXES)


def text_of(content: list) -> str:
    out = []
    for c in content or []:
        t = c.get("type")
        if t == "text" and c.get("text"):
            out.append(c["text"])
        elif t == "image":
            out.append("[图片]")
    return "\n\n".join(out).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default=os.environ.get("DSH_SESSION_FILE"))
    ap.add_argument("--out", default="exports/ds-chat")
    args = ap.parse_args()
    if not args.session:
        # Best-effort default: current session id under ~/.dsh/sessions/*/
        sid = os.environ.get("DSH_SESSION_ID", "")
        base = pathlib.Path(os.environ.get("DSH_HOME", pathlib.Path.home() / ".dsh")) / "sessions"
        hits = list(base.glob(f"**/{sid}/session.v4.jsonl.zstd")) if sid else []
        if not hits:
            print("error: pass --session path (session.v4.jsonl.zstd)", file=sys.stderr)
            return 2
        args.session = str(hits[0])
    src = pathlib.Path(args.session)
    raw = subprocess.run(["zstd", "-dc", str(src)], check=True, capture_output=True).stdout
    lines = raw.decode("utf-8", errors="replace").splitlines()
    events = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "session.raw.jsonl").write_bytes(raw)
    (out / "session.v4.jsonl.zstd").write_bytes(src.read_bytes())

    current_turn = 1
    messages = []
    for e in events:
        typ = e.get("type")
        if typ == "turn/start":
            current_turn = e.get("data", {}).get("turn", current_turn)
            continue
        if typ not in ("user/message", "assistant/message"):
            continue
        d = e.get("data", {})
        seq = e.get("seq")
        time_ms = e.get("time")
        if typ == "user/message":
            text = text_of(d.get("content", []))
            if not text or is_runtime_context(text):
                continue
            messages.append({
                "role": "user", "seq": seq, "time_ms": time_ms,
                "time": ts(time_ms), "turn": current_turn, "step": None,
                "text": text, "tools": [],
            })
        else:
            msg = d.get("message", {})
            text = text_of(msg.get("content", []))
            tools = [c.get("name", "?") for c in msg.get("content", []) if c.get("type") == "tool-call"]
            if not text:
                continue
            messages.append({
                "role": "assistant", "seq": seq, "time_ms": time_ms,
                "time": ts(time_ms), "turn": d.get("turn", current_turn),
                "step": d.get("step"), "text": text, "tools": tools,
            })

    # JSONL
    with (out / "chat.jsonl").open("w", encoding="utf-8") as f:
        for m in messages:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")

    # Markdown
    session_meta = next((e for e in events if e.get("type") == "session"), {})
    md = []
    md.append("# Ds / DsOS 对话记录")
    md.append("")
    md.append(f"- 导出时间：{datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S %Z')}")
    md.append(f"- Session：`{session_meta.get('id', '-')}`")
    md.append(f"- 工作目录：`{session_meta.get('cwd', '-')}`")
    md.append(f"- 消息数：user `{sum(1 for m in messages if m['role']=='user')}` / assistant `{sum(1 for m in messages if m['role']=='assistant')}`")
    md.append("- 已过滤 harness 注入的 runtime context / time sampled / approval 通知；原文保留在 `session.raw.jsonl`。")
    md.append(f"- 原始事件数：`{len(events)}`")
    md.append("")
    md.append("> 只导出 user / assistant 的可见文本；reasoning、tool 结果、system prompt 不进入正文，保留在 `session.raw.jsonl`。")
    md.append("")
    last_turn = None
    for m in messages:
        if m["turn"] != last_turn:
            last_turn = m["turn"]
            md += ["", f"## Turn {last_turn}", ""]
        who = "🧑 用户" if m["role"] == "user" else "🤖 助手"
        meta = f"`{m['time']}`"
        if m.get("step") is not None:
            meta += f" · step {m['step']}"
        if m["tools"]:
            meta += " · 工具: " + ", ".join(m["tools"])
        md += [f"### {who} · {meta}", "", m["text"] if m["text"] else "_（仅工具调用）_", ""]
    (out / "chat.md").write_text("\n".join(md).rstrip() + "\n", encoding="utf-8")

    manifest = {
        "session": session_meta.get("id"),
        "cwd": session_meta.get("cwd"),
        "exported_at": datetime.now(TZ).isoformat(),
        "events": len(events),
        "messages": len(messages),
        "user_messages": sum(1 for m in messages if m["role"] == "user"),
        "assistant_messages": sum(1 for m in messages if m["role"] == "assistant"),
        "files": {},
    }
    for name in ("chat.md", "chat.jsonl", "session.raw.jsonl", "session.v4.jsonl.zstd"):
        p = out / name
        manifest["files"][name] = {
            "bytes": p.stat().st_size,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"exported {out}")
    print(f"events={len(events)} messages={len(messages)}")
    for name, info in manifest["files"].items():
        print(f"  {name}: {info['bytes']} bytes {info['sha256'][:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
