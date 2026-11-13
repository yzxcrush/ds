---
license: mit
language: ds
task_categories:
  - text-generation
  - text2text-generation
pretty_name: Ds v0.1 Language & Bench
size_categories:
  - n<1K
---

# Ds v0.1 — 语言学习与评测数据集

配合 <https://github.com/yzxcrush/ds> 使用。

## 文件

| 文件 | 行数 | 字段 |
|---|---|---|
| `ds_sft.jsonl` | 32 | `id`, `messages`（system/user/assistant，assistant 含 ```ds 代码） |
| `ds_corpus.jsonl` | 10 | `id`, `title`, `text`（语言卡/关键词/语法/语义/FAQ） |
| `ds_bench.jsonl` | 19 | `id`, `title`, `prompt`, `expected_stdout`, `difficulty` |

## 生成方式

```bash
python3 tools/make_datasets.py          # 重新生成（bench 预期输出由参考驱动实跑）
python3 tools/make_datasets.py --check  # CI 校验
```

## 评测

```bash
python3 tools/ds_bench.py --list
python3 tools/ds_bench.py --submissions submissions.jsonl --json result.json
```

## 许可

MIT（数据与代码）。语言规范文本为 CC-BY-4.0，见仓库 `spec/`。
