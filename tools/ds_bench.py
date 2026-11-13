#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ds v0.1 评测脚本：跑模型提交的代码，与参考输出比对。

用法：
  python3 tools/ds_bench.py --list
  python3 tools/ds_bench.py --submissions sub.jsonl [--json result.json] [--strict]

submissions.jsonl 每行：{"id": "fib", "code": "package t\\nfn main(){...}"}
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dsv01.interp import Interpreter  # noqa: E402


def load_jsonl(path: Path) -> list[dict]:
    items = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{i}: JSON 错误：{exc}")
    return items


def main() -> int:
    ap = argparse.ArgumentParser(description="Ds v0.1 评测")
    ap.add_argument("--bench", default=str(ROOT / "datasets" / "ds_bench.jsonl"))
    ap.add_argument("--submissions", help="模型提交的 JSONL：{id, code}")
    ap.add_argument("--json", help="把结果写入该 JSON 文件")
    ap.add_argument("--list", action="store_true", help="列出评测任务")
    ap.add_argument("--strict", action="store_true", help="有失败时退出码 1")
    args = ap.parse_args()

    bench = {t["id"]: t for t in load_jsonl(Path(args.bench))}
    if args.list:
        for tid, t in bench.items():
            print(f"{tid:14s} {t['title']}\n  {t['prompt']}")
        return 0
    if not args.submissions:
        ap.print_help()
        return 2

    subs = load_jsonl(Path(args.submissions))
    results = []
    passed = 0
    for sub in subs:
        tid = sub.get("id")
        code = sub.get("code", "")
        task = bench.get(tid)
        if task is None:
            results.append({"id": tid, "pass": False, "reason": "未知任务 id"})
            continue
        out = io.StringIO()
        try:
            Interpreter(stdout=out).run_source(code, f"<submission:{tid}>")
            actual = out.getvalue()
            ok = actual.strip() == task["expected_stdout"].strip()
            detail = "" if ok else "输出不一致"
        except BaseException as exc:  # noqa: BLE001
            actual = out.getvalue()
            ok = False
            detail = f"运行错误：{type(exc).__name__}: {exc}"
        if ok:
            passed += 1
        results.append({"id": tid, "pass": ok, "detail": detail,
                        "expected": task["expected_stdout"], "actual": actual})
        print(("✓ " if ok else "✗ ") + f"{tid:14s} {task['title']}" +
              ("" if ok else f"  ({detail})"))
    total = len(subs)
    score = (passed / total * 100) if total else 0.0
    print(f"\n得分：{passed}/{total}（{score:.1f}%）")
    if args.json:
        Path(args.json).write_text(json.dumps({"score": score, "passed": passed,
                                               "total": total, "results": results},
                                              ensure_ascii=False, indent=2) + "\n",
                                   encoding="utf-8")
        print(f"结果已写入 {args.json}")
    return 0 if (passed == total or not args.strict) else 1


if __name__ == "__main__":
    sys.exit(main())
