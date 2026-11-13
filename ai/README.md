# 让别的 AI 学会 Ds v0.1

目标：让其他 AI（聊天模型、Agent、微调模型、RAG 系统）能**正确理解并生成 Ds 代码**。
这里不是一篇教程，而是一套「可直接投喂」的物料：**上下文包 + 训练数据 + 可执行验证 + 评测集**。

## 物料一览

| 层 | 文件 | 用途 |
|---|---|---|
| 上下文 | [`llms.txt`](../llms.txt) → [`ai/LANGUAGE_CARD.md`](LANGUAGE_CARD.md) → [`spec/DS-v0.1.md`](../spec/DS-v0.1.md) | 按 token 预算从浅到深投喂 |
| 上下文 | [`ai/llms-full.txt`](llms-full.txt) | 一次投喂全量（约 120 KB：卡+规范+示例输出+关键词 JSON） |
| 系统提示 | [`ai/system_prompt.txt`](system_prompt.txt) | 直接作为 system prompt |
| Agent | [`AGENTS.md`](../AGENTS.md) | 给编码 Agent 的操作约定（读什么、怎么验证） |
| 数据 | [`datasets/ds_sft.jsonl`](../datasets/ds_sft.jsonl) | 32 条 chat 格式指令微调数据 |
| 数据 | [`datasets/ds_corpus.jsonl`](../datasets/ds_corpus.jsonl) | 10 篇语料（语言卡/关键词/语法/语义/FAQ） |
| 评测 | [`datasets/ds_bench.jsonl`](../datasets/ds_bench.jsonl) | 19 个任务，含参考 stdout |
| 工具 | [`tools/ds_bench.py`](../tools/ds_bench.py) | 自动评分器 |
| 参考实现 | [`dsv01/`](../dsv01/) + [`ds`](../ds) / [`dscc`](../dscc) | 可执行的真值（生成代码后跑一遍） |

## 方式一：直接对话（最快）

把 `ai/system_prompt.txt` 作为 system prompt，把 `ai/LANGUAGE_CARD.md` 粘进上下文即可。
需要细节时再追加 `spec/DS-v0.1.md` 对应章节。示例开场：

```text
你是 Ds v0.1 专家。下面是语言卡（略）。请用 Ds 写一个 HTTP 风格的解析器。
```

## 方式二：RAG / 检索

把仓库 raw 文件挂到你的知识库：

```
https://raw.githubusercontent.com/yzxcrush/ds/main/llms.txt
https://raw.githubusercontent.com/yzxcrush/ds/main/ai/LANGUAGE_CARD.md
https://raw.githubusercontent.com/yzxcrush/ds/main/spec/DS-v0.1.md
https://raw.githubusercontent.com/yzxcrush/ds/main/spec/keywords.json
https://raw.githubusercontent.com/yzxcrush/ds/main/ai/llms-full.txt
```

推荐 chunk 方式：按 `spec/DS-v0.1.md` 的 `##` 章节、`ai/LANGUAGE_CARD.md` 的 `##` 章节、
`datasets/ds_corpus.jsonl` 的每行一篇。检索命中后把原文喂给模型，避免模型「回忆」出不存在的关键字。

## 方式三：微调 / 继续预训练

- 指令微调：`datasets/ds_sft.jsonl`（OpenAI/Anthropic 兼容的 `messages` 格式；也可直接转 HF TRL 的 chat 模板）。
- 语料继续预训练：`ai/llms-full.txt` + `datasets/ds_corpus.jsonl`。
- 建议：先做小规模 LoRA（例如 Qwen/Llama 系 7B 级），用 `ds_bench` 评测后再决定是否全参微调。
- 转换示例（Python）：

```python
import json
rows = [json.loads(l) for l in open("datasets/ds_sft.jsonl", encoding="utf-8")]
# rows[i]["messages"] -> 你的训练框架所需的 chat 格式
```

## 方式四：评测（判断 AI 到底学会没有）

让模型对 `datasets/ds_bench.jsonl` 的每个 `prompt` 生成完整 Ds 程序，保存为：

```json
{"id": "fib", "code": "package t\nfn main() { println(42) }"}
```

然后：

```bash
python3 tools/ds_bench.py --submissions submissions.jsonl --json result.json
```

评分器会用参考驱动真实执行，和参考 stdout 对比；也可以把 `--strict` 接进 CI。

## 方式五：工具化（Agent 边写边验证）

把参考驱动注册成 Agent 的工具，形成「生成 → 运行 → 修正」闭环：

| 工具 | 命令 | 说明 |
|---|---|---|
| `ds_check` | `./dscc 文件.ds --check` | 仅解析，返回语法错误与行列 |
| `ds_run` | `./dscc 文件.ds` | 解释执行，返回 stdout/错误 |
| `ds_tokens` | `./dscc 文件.ds --emit tokens` | 词法结果，便于排查 |

给 OpenAI 风格 function-calling 的 schema 示例：

```json
{"name":"ds_run","description":"运行 Ds v0.1 源码并返回 stdout","parameters":{"type":"object","properties":{"code":{"type":"string"}},"required":["code"]}}
```

也可以直接调用 Python API：`from dsv01 import run_source; run_source(code)`。

## 方式六：发布到公开渠道

1. **GitHub**（本仓库）：README、`llms.txt`、`AGENTS.md` 放在根目录，便于爬虫/Agent 发现。
2. **Hugging Face Dataset**（推荐，训练数据最容易被复用）：

```bash
pip install huggingface_hub
huggingface-cli login
huggingface-cli upload <你的账号>/ds-v0.1 datasets/ . --repo-type dataset
```

3. 把 `llms.txt` 挂到官网/文档站根路径（llms.txt 约定），让检索型 AI 自动发现。
4. 在模型卡/README 里声明：规范 CC-BY-4.0、代码 MIT，允许训练使用。

## 注意事项

- **0.1 是定义稿 + 参考驱动子集**：不要宣称 `class/match/try` 等在所有运行时都可用；以 `spec/DS-v0.1.md` 为准。
- 模型容易「编造关键字」：把 77 个关键字表当硬约束，生成后必须跑 `--check`/`ds_bench` 验证。
- 不要与其他语言语法混用（`struct`/`let mut`/`<>` 泛型/`->` 当 lambda 都是错的）。
