#!/usr/bin/env python3
"""检查 Ds base 冻结状态与 77 关键字门槛。"""
from __future__ import annotations
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main() -> int:
    policy = json.loads((ROOT / "spec" / "freeze.json").read_text(encoding="utf-8"))
    spec = json.loads((ROOT / "spec" / "keywords.json").read_text(encoding="utf-8"))
    words = {e["word"] for e in spec["alphabetical"]}
    print(f"base version : {policy['base_version']}")
    print(f"status       : {policy['status']}")
    print(f"syntax frozen: {policy['syntax_frozen']}")
    print(f"semantics    : {policy['semantics_frozen']}")
    print(f"keywords     : {len(words)} / {policy['keywords']}")
    print("blockers     : " + ", ".join(b["id"] for b in policy["blockers"]))
    if len(words) != policy["keywords"]:
        print("ERROR: 关键字数量与冻结策略不一致", file=sys.stderr)
        return 1
    if "--require-semantic-freeze" in sys.argv and not policy["semantics_frozen"]:
        print("ERROR: 语义尚未冻结，仍有 blocker", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
