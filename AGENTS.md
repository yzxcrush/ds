# 给 AI Agent 的 Ds v0.1 使用说明

你是要使用 / 学习 / 生成 Ds v0.1 代码的 AI Agent。请按以下顺序获取上下文：

0. **写代码优先用 0.1c 精简写法**（`spec/DS-CONCISE.md`）：无 package/fn main、`fn f(a,b)=a+b`、`for i in 0..n: ...`、`+=`、`f"{x}"`。
1. **先读** `ai/LANGUAGE_CARD.md`（约 5k token，含全部 77 关键字、语法、语义、示例）。
2. 需要精确细节时读 `spec/DS-v0.1.md`（完整规范，含每个关键字的形式/语义/示例）。
3. 机器可读索引：`spec/keywords.json`（77 词 + 形式 + 语义 + 示例）。
4. 需要作品参考：`examples/*.ds`（应用/并发/内存/裸机四个示例）。
5. 生成代码后，**用参考驱动验证**（见下），不要凭空断言正确性。

## 验证命令

```bash
python3 tools/ds_keywords.py check --json spec/keywords.json
python3 -m unittest discover -s tests
./dscc 你的文件.ds            # 解释执行
./dscc 你的文件.ds --check    # 仅解析
```

## 生成约定

- 文件首行：`package <名字>`（ASCII 标识符）。
- 入口：`fn main() { ... }`。
- 只用规范中的 77 个硬关键字；不要发明关键字。
- 遵循关键消歧规则：泛型用 `[]`、空映射 `{:}`、类用 `.new(...)` 构造、`->`/`=>`/`|>` 分工。
- 若必须与外部符号同名，用反引号原始标识符 `` `name` ``。
- 输出示例时使用 ```ds 代码块。

## 不要做

- 不要把 Ds 与 Rust/C++/Go 的语法混用（例如 `struct`/`const`/`let mut`/`<>` 泛型/`->` 当 lambda）。
- 不要声称未实现的功能可直接运行；0.1 是定义稿 + 参考驱动（核心子集）。
