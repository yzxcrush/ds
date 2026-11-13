# Ds v0.1 AI 数据集统计

| 数据 | 条数 | 用途 |
|---|---|---|
| `ds_sft.jsonl` | 32 | 指令微调（system + user + assistant，含 ```ds 代码） |
| `ds_corpus.jsonl` | 10 | 语料 / RAG（语言卡、关键词、语法、语义、FAQ） |
| `ds_bench.jsonl` | 19 | 评测（prompt + 参考 stdout，覆盖核心特性） |

- 系统提示词：`ai/system_prompt.txt`
- 生成脚本：`tools/make_datasets.py`（bench 预期输出由参考驱动实跑生成，保证可复现）
- 许可证：规范 CC-BY-4.0；代码与数据 MIT
