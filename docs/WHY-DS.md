# 为什么是 Ds？

> **一句话**：Ds 用 77 个关键字把「应用 / 系统 / 裸机」三种交付物收进同一套语义，
> 用三档写法把 AI 生成成本压到最低，并且每一步都能被三套参考实现执行验证。
> 它不是 Python 的替代品，也不是 C/Rust/Go 的换皮，而是「可预测系统编程 + AI 生成」这一交叉点的语言设计。

<p align="center">
  <b>77</b> 硬关键字 · <b>3</b> 档写法 · <b>3</b> 套参考实现 · <b>7</b> 个编译目标 · <b>1</b> 套语义
</p>

---

## 0. TL;DR

| 维度 | Ds 的答案 |
|---|---|
| 一套语言三种交付 | `--app` 应用、`--bare` 裸机、交叉编译 7 个目标 |
| 能力密度 | 77 个关键字覆盖类型/内存/错误/并发/元编程/OOP/模式/裸机；Ds+ 再加 16 个硬件/区域令牌 |
| Token 效率 | 常见程序：经典 137 → 精简 82（-31%）→ Flow 69（**-49%**）token |
| 双分支 | Ds（77 冻结）/ Ds+（严格超集，裸机硬件与四区域内存） |
| 包管理 | dspm：GitHub 即包仓库，无中心服务器；C 驱动原生 `use` 解析 |
| 可预测 | 静态类型、显式内存五选一、确定性析构、错误分层、结构化并发、布局可控 |
| 可验证 | 三套实现 + 逐用例对拍 + AI 评测集（25 任务，自动执行比对） |
| 可学习 | `llms.txt` / 语言卡 / 130 KB 全量上下文 / 41 条 SFT / 评测脚本 |
| 不是换皮 | Flow 写法：`\` 定义 + 并置调用 + `.` 结束块，结构独立于 C/Java/Python |

---

## 1. 优势一：一套语言，三种交付物

大多数项目要在「Python 写应用 + C 写驱动 + Rust 写系统」之间反复做边界重写。Ds 把三种场景收进同一套语义：

| 交付物 | 命令 | 运行时特征 |
|---|---|---|
| 应用/服务 | `dscc app.ds --app` | OS 运行时、线程池、可选 GC、panic 展开 |
| 裸机固件 | `dscc main.ds --bare --target thumbv7em-none-eabi` | 无 OS、无 GC、无隐式分配、显式分配器 |
| 库/模块 | `package` + `mod` + `use` + `export` | 包级可见性、跨包 API 表 |
| WASM | `--target wasm32-unknown-unknown` | 浏览器/边缘运行 |

0.1 支持的 7 个目标：`x86_64-linux-gnu`、`aarch64-linux-gnu`、`aarch64-linux-android`、
`thumbv7em-none-eabi`、`riscv32-none-elf`、`wasm32-unknown-unknown`、`x86_64-none`。

**价值**：同一套类型、错误、内存、并发规则，从服务器一路用到中断服务例程，不需要三套心智模型。

---

## 2. 优势二：能力密度（77 关键字的矩阵，而不是拼装层）

| 能力 | Ds 关键字 | 对比：通常要怎么做 |
|---|---|---|
| 定义/数据 | `fn let var type class trait impl mod package` | Python 用 class/装饰器；C 用 struct+函数指针；Rust 用 struct/enum/trait |
| 内存 | `alloc free rc arc gc ptr ref raw mut` | Python 只有 GC；C 只有 malloc/free；Rust 用所有权+unsafe |
| 错误 | `try catch panic recover assert res opt` | Python 异常；C 返回码；Rust `Result/Option` 但无 panic 捕获块 |
| 并发 | `spawn go thread chan send recv mutex wait` | Python 三套库；Go 只有 goroutine/channel；Rust 需 crate |
| 裸机 | `@ asm volatile at irq section packed` | C 用宏/链接脚本；Rust 用 `no_std`+`unsafe`+crate |
| 元编程 | `comptime macro typeinfo attr` | Python 运行时反射/元类；C 宏；Rust 过程宏 |
| 模式 | `match when where in is sizeof alignof` | Python 3.10 match；C 无；Rust 模式匹配 |
| 管道/分支 | `-> => \|>` | 各语言用不同语法或库 |

**价值**：能力是语言一级公民（可发现、可诊断、可文档化），而不是「标准库 + 预处理器 + FFI 拼出来」。
77 个关键字换来的是**可枚举的能力清单**：AI 和人都能在一个表里看完全部能力。

---

## 3. 优势三：Token 效率（为 AI 生成而优化）

同一门语言提供三档写法，语义完全相同、可混用：

| 写法 | 特征 | 适用 |
|---|---|---|
| 经典 | `package` / `fn main` / `{}` / 类型标注 | 团队协作、对外 API、教学阅读 |
| 0.1c 精简 | 隐式入口、`fn f(a,b)=a+b`、`:` 单语句体、`a..b`、f-string、`+=` | 日常与 AI 默认 |
| Flow | `\` 定义、空白参数、并置调用、`.` 结束块、`?`/`^`/`;` | 极限省 token、结构独特 |

同一程序的三种写法：

```ds
# 经典（13 token）
package hello
fn main() {
    println("hello, Ds")
}
```

```ds
# 0.1c（5 token）
println("hello, Ds")
```

```dsf
# Flow（3 token）
p "hello, Ds"
```

实测（`python3 tools/token_report.py`）：

| 场景 | 经典 | 0.1c | Flow | vs 经典 | vs 0.1c |
|---|---|---|---|---|---|
| hello world | 13 | 5 | 3 | **-76%** | -40% |
| 斐波那契 10 项 | 64 | 38 | 34 | **-46%** | -10% |
| 累加 + 调用 | 60 | 39 | 32 | **-46%** | -17% |
| **合计** | **137** | **82** | **69** | **-49%** | **-15%** |

**价值**：更少的 token 意味着更低的训练/推理成本、更少的上下文占用、更低的复制粘贴错误率。
并且这不是"缩写黑话"——三档写法编译到同一棵 AST，行为逐字节一致。

---

## 4. 优势四：可预测性（系统语言的核心）

- **静态类型，无隐式转换**：混合类型必须 `as` 显式转换，避免运行期惊喜。
- **内存五选一**：栈/静态、`alloc`+`free`、`rc[T]`、`arc[T]`、`gc[T]`；每个值的生命期策略写在代码里。
- **确定性析构**：离开作用域/引用计数归零即调用 `drop`；不依赖 GC 时机。
- **错误三层**：可恢复 `res`/`opt` + `try`/`catch`；不可恢复 `panic`/`recover`；不变量 `assert`。
  `--bare` 下 `panic` 恒 abort（无展开运行时）。
- **结构化并发**：`spawn` 绑作用域自动 `wait` 并传播错误；`go` 是唯一分离口；共享可变状态只能经 `mutex`/`chan`。
- **布局可控**：`sizeof`/`alignof` 编译期常量、`packed`、`@repr(C)`、`@at` 固定地址、`section` 段放置。
- **unsafe 显式**：指针解引用/asm/`static mut`/volatile 必须在 `@unsafe` 块内。

**价值**：延迟可推理、内存可审计、并发边界可静态化——这些是系统级代码最贵的属性。

---

## 5. 优势五：裸机优先（不是事后补的 `no_std`）

```ds
package firmware

section ".boot" {
    @entry
    fn reset_handler() at 0x0000_0000 {
        init()
        loop { @unsafe { asm "wfi" } }
    }
}

@irq(5)
irq fn timer_tick() { }

fn read_reg(addr: usize) -> u32 {
    @unsafe {
        let p = addr as volatile ptr[u32]
        *p
    }
}
```

从语言层直接提供：入口/中断向量、段与地址放置、易失访问、内联汇编、紧凑布局、分配器注册。
**价值**：同一门语言写应用和固件；中断服务例程与普通函数在同一套类型系统里。

---

## 6. 优势六：AI 原生——可学习、可执行、可评测的闭环

很多语言的「AI 支持」只是把文档喂给模型；Ds 提供的是闭环：

| 层 | 物料 |
|---|---|
| 检索 | [`llms.txt`](../llms.txt)、[`ai/LANGUAGE_CARD.md`](../ai/LANGUAGE_CARD.md)、[`ai/llms-full.txt`](../ai/llms-full.txt)（约 130 KB） |
| 训练 | [`datasets/ds_sft.jsonl`](../datasets/ds_sft.jsonl)（41 条指令）、[`ds_corpus.jsonl`](../datasets/ds_corpus.jsonl)（10 篇语料） |
| 评测 | [`datasets/ds_bench.jsonl`](../datasets/ds_bench.jsonl)（25 个任务，含参考 stdout）、[`tools/ds_bench.py`](../tools/ds_bench.py) 自动执行比对 |
| 真值 | 三套参考实现：Python（全量）、C（核心子集）、Android 内核；`c/run_tests.sh` 与 Python 逐用例对拍 |
| 约束 | 77 关键字表 + CI 校验（关键词/词法/测试/AI 包/对拍） |

**价值**：模型生成代码后可以立刻执行、比对、打分；「编造关键字/语法」会被 `--check` 与 bench 立刻发现。
这比单纯的提示词工程可靠得多。

---

## 7. 优势七：不是任何编译语言的换皮

Ds 保留 77 个可读关键字（可发现性），但**结构**是独立的：

- **Flow 写法**把函数定义写成 `\name a b = expr`，调用靠**并置**（`p "hi"`、`add 2 3`），
  多语句块用**单独一行 `.`** 结束，条件 `?`、返回 `^`、`else` 可缩写为 `;`。
- 没有花括号、没有 `fn main`、没有逗号参数表、没有分号语句分隔。
- 函数应用 + 结束符 + 前缀 sigil 这一组合，不属于 C/Java/Python/Rust/Go 中任何一种的语法家族。

三档写法共享同一套语义与 AST：**写法可换，语义不换**。这既避免了"为了省 token 再造一门语言"的分裂，
也避免了"只是把关键字改名"的换皮。

---

## 7b. 优势八：Ds+ 严格超集（裸机能力不污染 base）

- base 77 关键字冻结；Ds+ 只新增 16 个 `@` 令牌（12 硬件 + 4 区域），**Ds 代码 100% 通过**。
- 双 profile：`compat` 保留全部 base 语义；`bare` 无 GC/无语言运行时，输出 ELF/raw binary。
- P0–P6 已实现：ds-core 共享、前端、语义检查、compat 模拟执行、IR/ABI、x86-64 子集后端、CLI、发布。
- 验证：61 项 Ds+ 测试 + S1–S18 超集校验 + CI；base 分支完全不受影响。

## 7c. 优势九：dspm——生态冷启动不买服务器

- 包 = GitHub 仓库，版本 = git tag，源码即分发；无中心 registry。
- 短名像 pip：`dspm install ds-hello`（默认索引在 yzxcrush/ds-packages，索引本身只是 GitHub 上的 JSON）。
- `install/remove/list/update/cache-clean`；深度优先依赖、缓存优先可离线、lock 记录 tag/commit/hash。
- 安全：不执行包脚本、拒绝路径越界/符号链接、`@asm/@raw` 标 unsafe 并确认。
- **C 驱动已原生集成 `use`**：扫描 `~/.ds/pkg`，按 exports/targets 解析，`hello.hello("Ds")` 可直接执行；缺失时提示 `dspm install`。
- 示例包 `examples/packages/ds-hello`；后续可移植 Kotlin（Android）。

## 8. 客观对比（不吹不黑）

| 维度 | Python | Rust | Go | C/C++ | Ds（0.1） |
|---|---|---|---|---|---|
| 类型 | 动态 | 静态 | 静态 | 静态 | 静态、无隐式转换 |
| 内存 | GC | 所有权+借用 | GC | 手动 | 五选一（栈/alloc/rc/arc/gc）+ ref/ptr |
| 析构确定性 | 否 | 是 | 否 | 手动 | **是** |
| 错误模型 | 异常 | Result/panic | error 值 | 返回码 | res/opt + try/catch + panic/recover |
| 并发 | 库 | 库/async | goroutine | pthread | 关键字级 spawn/go/chan/mutex |
| 裸机 | 否 | 需 no_std | 否 | 是 | **语言级 `--bare`** |
| 元编程 | 运行时 | 过程宏 | 有限 | 宏 | comptime/macro/typeinfo/attr |
| AI token 效率 | 中 | 中 | 中 | 低 | **高（三档写法）** |
| 生态/工具链 | 极强 | 强 | 强 | 极强 | **几乎为零（0.1 定义稿）** |
| 成熟度 | 生产级 | 生产级 | 生产级 | 生产级 | **研究/教学/原型** |

> Ds 不假装在生态、性能、工具链上追上这些语言。它的优势是**设计空间**：能力密度、token 效率、可预测性、
> 以及"同一套语义覆盖应用+裸机"的组合。

---

## 9. 什么时候该用 Ds / 什么时候别用

**适合**
- 语言设计/编译器教学：77 关键字 + 三套实现 + 对拍，是很好的实验床。
- 需要"一套语法从应用写到裸机"的原型（教学板、实验固件、DSL 外壳）。
- AI 代码生成管线：token 敏感、需要自动验证、需要可评测的基准。
- 研究"语法结构对模型生成质量的影响"：同语义三档写法天然是对照组。

**不适合**
- 生产服务/高并发业务系统（没有生态、包管理、成熟运行时）。
- 需要成熟库、性能基准、团队现有 Rust/C++ 资产的场景。
- 要求长期维护与商业支持的项目。

---

## 10. 现状与路线图

| 实现 | 状态 |
|---|---|
| 规范 `spec/` | 0.1 定义稿 + 0.1c/Flow 写法档 |
| Python 参考驱动 `dsv01/` | 全量语义子集（含 class/match/opt/res/try/并发/内存/元编程） |
| C 驱动 `c/` | 核心子集（经典/精简/Flow），与 Python 逐用例对拍；原生 `use` + dspm 包解析 |
| 包管理 dspm | install/remove/list/update/cache-clean/resolve；10 项离线测试；示例包 ds-hello |
| Ds+ `ds-plus` | 严格超集；16 个 `@` 令牌；P0–P6；61 项测试 + S1–S18；x86-64 子集后端 |
| Android App | 内核 0.2.0（0.1c + Flow），GitHub Actions 出 APK；包管理为集成方案 |
| AI 学习包 | llms.txt + 语言卡 + 数据 + 评测器 + Ds+/dspm 上下文，CI 校验 |

路线图（0.2）：Python/Android 接 `use` 与 lock → C 驱动补全 class/match/opt/res → Ds+ 非 x86 后端/优化 → App 包管理实装。

---

## 11. 快速开始

```bash
# 语言仓库
git clone https://github.com/yzxcrush/ds && cd ds
python3 -m unittest discover -s tests        # 158 项测试
./dscc examples/tour.ds                      # 经典
./dscc examples/concise/fib.ds               # 0.1c
./dscc examples/flow/fib.dsf                 # Flow
sh c/run_tests.sh                            # Python/C 对拍
./dspm install <user>/<repo>@v0.1.0          # dspm 包管理（GitHub 包仓库）
sh c/test_dspm_use.sh                        # C 驱动 use/dspm 端到端
# Ds+：git clone -b ds-plus …；见 docs/DS-PLUS.md

# Android 编译器
https://github.com/yzxcrush/ds-compiler/releases/latest
```

## 12. 链接

- 语言仓库：<https://github.com/yzxcrush/ds>
- Android App：<https://github.com/yzxcrush/ds-compiler>
- 规范：<https://github.com/yzxcrush/ds/blob/main/spec/DS-v0.1.md>
- AI 入口：<https://raw.githubusercontent.com/yzxcrush/ds/main/llms.txt>
- 评测：<https://github.com/yzxcrush/ds/blob/main/datasets/ds_bench.jsonl>
- 包管理：<https://github.com/yzxcrush/ds/blob/main/docs/DSPM.md>
- Ds+：<https://github.com/yzxcrush/ds/blob/main/docs/DS-PLUS.md> · [分支](https://github.com/yzxcrush/ds/tree/ds-plus) · [发布](https://github.com/yzxcrush/ds/releases/tag/ds-plus-v0.1.0)

---

## English TL;DR

**Ds** is a compact systems language (77 hard keywords) designed for *predictable systems programming* and
*AI code generation*. It ships three interchangeable surface syntaxes over one AST — classic (C/Java-like),
concise (boilerplate-free), and **Flow** (juxtaposition application, `.`-terminated blocks, `\` sigils) —
cutting token usage by **~49%** vs the classic form on common programs. One language covers `--app`,
`--bare` bare-metal (7 targets), explicit memory (alloc/rc/arc/gc), deterministic drops, layered errors,
structured concurrency, compile-time metaprogramming, and layout control. It is **not** a re-skin:
its Flow structural syntax belongs to no mainstream compiled-language family. The repo ships a complete
AI learning kit (`llms.txt`, language card, SFT/corpus/bench datasets, auto-grader) and three reference
implementations (Python, C, Android) with differential tests. Status: definition-first (v0.1) — great as a
design/teaching/prototyping language; **no ecosystem yet**, so not a production replacement for
Python/Rust/Go/C++.
