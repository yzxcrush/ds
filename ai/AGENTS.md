# 给 AI Agent 的 Ds v0.1 使用说明

你是要使用 / 学习 / 生成 Ds v0.1 代码的 AI Agent。请按以下顺序获取上下文：

0. **写代码优先用 0.1c 精简写法；要极限省 token 用 Flow（`.dsf`：\ 定义/并置调用/. 结束块）**（`spec/DS-CONCISE.md`）。
   注意：base 只有 77 关键字；Ds+ 是 `ds-plus` 分支的严格超集，新增 16 个 `@` 令牌，默认不要混用。
1. **先读** `ai/LANGUAGE_CARD.md`（约 5k token，含全部 77 关键字、语法、语义、示例）。
2. 需要精确细节时读 `spec/DS-v0.1.md`（完整规范）；Ds+ 读 `docs/DS-PLUS.md`；包管理读 `docs/DSPM.md`。
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

- 经典写法文件首行 `package <名字>`（ASCII 标识符）、入口 `fn main()`；0.1c 可省略两者（顶层语句即入口）。
- 只用规范中的 77 个硬关键字；不要发明关键字。
- 遵循关键消歧规则：泛型用 `[]`、空映射 `{:}`、类用 `.new(...)` 构造、`->`/`=>`/`|>` 分工。
- 若必须与外部符号同名，用反引号原始标识符 `` `name` ``。
- 输出示例时使用 ```ds 代码块。


## Ds+（plus 分支）与 dspm

- **Ds+ 不是 base**：base `main` 只有 77 关键字；Ds+（`ds-plus` 分支）是严格超集，新增 16 个 `@` 令牌。
  回答 base 问题时不要用 `@inb/@asm/@stack` 等；回答 Ds+ 问题时才可用，并遵守 profile/unsafe/常量/对齐规则。
- Ds+ 文档在主仓库 `docs/DS-PLUS.md`；分支内有 `ds-plus/ROADMAP.md`、`ds-plus/docs/`。
- 包管理 dspm：包 = GitHub 仓库，版本 = tag；命令 `./dspm install <user>/<repo>[@tag]`、`list`、`remove`、`update`、`cache-clean`。
- 编译器 `use <module>` 解析到 `~/.ds/pkg`；C 驱动已原生支持，调用 `模块名.函数名`；缺失时提示 `dspm install <user>/<repo>`。
- dspm 不执行包脚本；`@asm/@raw` 包标 unsafe，安装需确认（`--yes` 非交互）。

验证命令补充：

```bash
python3 -m unittest tests.test_dspm -v
sh c/test_dspm_use.sh
ds-plus/bin/dsplus check <file> --profile bare
```

## 不要做

- 不要把 Ds 与 Rust/C++/Go 的语法混用（例如 `struct`/`const`/`let mut`/`<>` 泛型/`->` 当 lambda）。
- 不要声称未实现的功能可直接运行；base 是定义稿 + 参考驱动（核心子集），Ds+ 后端仅 x86-64 子集。
- 不要把 base 与 Ds+ 的能力混写（例如在 base 代码里用 `@inb`）。
