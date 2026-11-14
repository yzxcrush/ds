# Ds v0.1 — a compact systems language for predictable code and AI generation

[![CI](https://github.com/yzxcrush/ds/actions/workflows/spec-check.yml/badge.svg)](https://github.com/yzxcrush/ds/actions/workflows/spec-check.yml)
[![Android APK](https://img.shields.io/badge/Android-APK-2b5278)](https://github.com/yzxcrush/ds-compiler/releases/latest)
[![Landing page](https://img.shields.io/badge/website-yzxcrush.github.io%2Fds-64b5ef)](https://yzxcrush.github.io/ds/)

**Ds** is a definition-first systems language: **77 hard keywords**, one semantics covering
**app / systems / bare-metal** targets, and **three interchangeable surface syntaxes** designed to
cut AI generation cost. It is not a re-skin of C/Java/Python/Rust/Go — its Flow syntax is built on
juxtaposition application and `.`-terminated blocks.

> 中文文档见 [README.md](README.md)；优势阐述见 [docs/WHY-DS.md](docs/WHY-DS.md)。

## Why Ds

| Strength | What it means |
|---|---|
| One language, three deliverables | `--app`, `--bare` (no OS/GC), 7 cross-compile targets incl. thumbv7em / riscv32 / wasm32 |
| Capability density | 77 keywords cover types, memory, errors, concurrency, metaprogramming, OOP, patterns, bare-metal |
| Token efficiency | classic 137 → concise 82 (−31%) → **Flow 69 (−49%)** on common programs |
| Predictability | static types, explicit memory (stack/alloc/rc/arc/gc), deterministic `drop`, layered errors, structured concurrency, layout control |
| AI-native | `llms.txt` + language card + 41 SFT rows + 25 benchmark tasks + auto-grader; three implementations cross-checked |
| Not a re-skin | Flow: `\` definitions, `p "hi"` juxtaposition calls, `.` block terminators |

## Three syntaxes, one AST

```ds
# classic
package hello
fn main() {
    println("hello, Ds")
}
```

```ds
# 0.1c concise (5 tokens)
println("hello, Ds")
```

```dsf
# Flow (3 tokens)
p "hello, Ds"
```

## Quick start

```bash
git clone https://github.com/yzxcrush/ds && cd ds
python3 -m unittest discover -s tests     # 158 tests
./dscc examples/tour.ds                   # classic
./dscc examples/concise/fib.ds            # concise
./dscc examples/flow/fib.dsf              # Flow
sh c/run_tests.sh                         # Python ↔ C differential tests
```

## AI learning kit

- [`llms.txt`](llms.txt) · [`ai/LANGUAGE_CARD.md`](ai/LANGUAGE_CARD.md) · [`ai/llms-full.txt`](ai/llms-full.txt)
- [`datasets/ds_sft.jsonl`](datasets/ds_sft.jsonl) · [`datasets/ds_bench.jsonl`](datasets/ds_bench.jsonl)
- grade generated code: `python3 tools/ds_bench.py --submissions sub.jsonl --json result.json`

## Android compiler

[Ds Compiler APK](https://github.com/yzxcrush/ds-compiler/releases/latest) — Telegram-style UI,
Pydroid-like editor/console, 0.1c + Flow kernel, fully offline.

## Status & scope

v0.1 is a **definition + reference implementations** (Python full sub-language, C core subset,
Android kernel). No package manager, standard library ecosystem, or production tooling yet.
See [docs/WHY-DS.md](docs/WHY-DS.md) for an honest comparison with Python/Rust/Go/C++ and when **not** to use Ds.

## License

Specs CC-BY-4.0, code MIT.
