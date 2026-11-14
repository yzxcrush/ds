#!/usr/bin/env python3
"""从 spec/keywords.json（base 77）+ ds-core/plus.keywords.json（plus 16）
生成 ds-core/keywords.registry.json。--check 只校验不写文件。"""
from __future__ import annotations
import argparse, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = ROOT / "spec" / "keywords.json"
PLUS = ROOT / "ds-core" / "plus.keywords.json"
OUT = ROOT / "ds-core" / "keywords.registry.json"


def build() -> dict:
    base = json.loads(BASE.read_text(encoding="utf-8"))
    plus = json.loads(PLUS.read_text(encoding="utf-8"))
    base_entries = [{"token": e["word"], "branch": "base", "kind": e["kind"],
                     "category": e["category"]} for e in base["alphabetical"]]
    plus_entries = [{"token": e["name"], "branch": "plus", "kind": "at-token",
                     "category": e["category"], "profiles": e["profiles"],
                     "requires_unsafe": e["requires_unsafe"]} for e in plus["keywords"]]
    entries = base_entries + plus_entries
    return {"version": "0.1.0", "base_count": len(base_entries),
            "plus_count": len(plus_entries), "total": len(entries), "entries": entries}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    built = build()
    text = json.dumps(built, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print("✗ keywords.registry.json 与源不一致，请运行 build_registry.py")
            return 1
        print(f"✓ registry 一致（base {built['base_count']} + plus {built['plus_count']} = {built['total']}）")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"✓ 生成 registry（{built['base_count']} + {built['plus_count']} = {built['total']}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
