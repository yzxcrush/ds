#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""组装 AI 学习包：ai/llms-full.txt + 数据校验 + 统计。

用法：python3 tools/build_ai_kit.py [--check]
--check 只校验当前文件是否与生成结果一致（CI 用）。
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dsv01.interp import Interpreter  # noqa: E402


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def run_example(path: Path) -> str:
    out = io.StringIO()
    Interpreter(stdout=out).run_file(str(path))
    return out.getvalue()


def build() -> str:
    card = read("ai/LANGUAGE_CARD.md")
    concise = read("spec/DS-CONCISE.md")
    flow = read("spec/DS-FLOW.md")
    why = read("docs/WHY-DS.md")
    plus = read("docs/DS-PLUS.md")
    dspm = read("docs/DSPM.md")
    spec = read("spec/DS-v0.1.md")
    llms = read("llms.txt")
    keywords = read("spec/keywords.json")
    agents = read("ai/AGENTS.md")
    system = read("ai/system_prompt.txt")

    parts = [
        "# Ds v0.1 — AI 完整学习包（llms-full）",
        "",
        "> 由 `tools/build_ai_kit.py` 从语言卡、规范、示例与数据集自动汇编。",
        "",
        "## 0. llms.txt 索引",
        "",
        llms,
        "",
        "## 1. 系统提示词（可直接粘贴给模型）",
        "",
        "```text",
        system,
        "```",
        "",
        "## 2. 精简写法（0.1c，AI 默认推荐）",
        "",
        concise,
        "",
        "## 2b. Flow 写法（结构性最省 token）",
        "",
        flow,
        "",
        "## 2a. 为什么是 Ds（优势与边界）",
        "",
        why,
        "",
        "## 2d. Ds+（plus 分支）",
        "",
        plus,
        "",
        "## 2e. dspm 包管理",
        "",
        dspm,
        "",
        "## 2c. Language Card",
        "",
        card,
        "",
        "## 3. 完整规范",
        "",
        spec,
        "",
        "## 4. 完整示例与真实输出",
        "",
    ]
    for f in sorted((ROOT / "examples").glob("*.ds")):
        try:
            output = run_example(f)
        except Exception as exc:  # noqa: BLE001
            output = f"<运行失败：{exc}>"
        parts += [
            f"### `examples/{f.name}`",
            "",
            "```ds",
            f.read_text(encoding="utf-8").rstrip(),
            "```",
            "",
            "输出：",
            "",
            "```text",
            output.rstrip(),
            "```",
            "",
        ]

    stats = (ROOT / "datasets" / "STATS.md").read_text(encoding="utf-8")
    parts += [
        "## 5. 机器可读关键词表（spec/keywords.json）",
        "",
        "```json",
        keywords.rstrip(),
        "```",
        "",
        "## 6. 数据集统计",
        "",
        stats,
        "",
        "## 7. 给 Agent 的操作说明",
        "",
        agents,
    ]
    return "\n".join(parts) + "\n"


def validate_datasets() -> list[str]:
    problems: list[str] = []
    for name, need in [("ds_sft.jsonl", "messages"), ("ds_corpus.jsonl", "text"), ("ds_bench.jsonl", "expected_stdout")]:
        p = ROOT / "datasets" / name
        if not p.exists():
            problems.append(f"缺少 datasets/{name}")
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                problems.append(f"datasets/{name}:{i} JSON 错误 {exc}")
                continue
            if need not in obj:
                problems.append(f"datasets/{name}:{i} 缺少字段 {need}")
    return problems


def main() -> int:
    check = "--check" in sys.argv
    out_path = ROOT / "ai" / "llms-full.txt"
    text = build()
    if check:
        problems = validate_datasets()
        if not out_path.exists() or out_path.read_text(encoding="utf-8") != text:
            problems.append("ai/llms-full.txt 过期（运行 python3 tools/build_ai_kit.py）")
        if problems:
            print("✗ AI 学习包校验失败：", file=sys.stderr)
            for p in problems:
                print("  - " + p, file=sys.stderr)
            return 1
        print("✓ AI 学习包一致（llms-full + 3 个数据集）")
        return 0
    out_path.write_text(text, encoding="utf-8")
    size = len(text.encode("utf-8"))
    print(f"✓ 生成 ai/llms-full.txt（{size} 字节）")
    for p in validate_datasets():
        print("  ⚠ " + p, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
