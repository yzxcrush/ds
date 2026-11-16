# Ds v0.1 — 新编程语言定义（全量关键词表）

[English](README.en.md) · [中文](README.md) · [落地页](https://yzxcrush.github.io/ds/)

[![CI](https://github.com/yzxcrush/ds/actions/workflows/spec-check.yml/badge.svg)](https://github.com/yzxcrush/ds/actions/workflows/spec-check.yml)
[![Android APK](https://img.shields.io/badge/Android-APK%20v0.1.4-2b5278)](https://github.com/yzxcrush/ds-compiler/releases/latest)

> **定义 + 可执行参考驱动**：本仓库给出 Ds v0.1 的完整定位、词法、**77 项全量关键词表**、运算符、字面量、注释、EBNF、语义契约与 `dscc` 编译驱动定义，并附带 **Python 参考驱动**（词法器 → 解析器 → 树遍历解释器）与 `ds` / `dscc` 终端命令。**不产出机器码**，语言规范本身仍是定义稿。

## 一键安装终端驱动

```sh
curl -fsSL https://raw.githubusercontent.com/yzxcrush/ds/main/install.sh | sh
```

安装后直接运行：

```sh
dscc hello.ds
```

脚本会从 GitHub 下载仓库到 `~/.ds/ds`，生成 `dscc` 命令（Termux 安装到 `$PREFIX/bin`），并自动尝试构建 C 驱动 `ds-c`。
完整脚本见 [`install.sh`](install.sh)。

## 地基工程规则

**先地基，后高楼。** Base 已验证部分已冻结；**Ds+ / Ds/Cut 不冻结**，可独立演进，但必须继承 base 修复并通过 conformance。

- 规则与验收：[docs/FOUNDATION.md](docs/FOUNDATION.md)
- 批次状态：[audit/batches.json](audit/batches.json) · [Batch 3](audit/BATCH3.md)
- 审计与 blocker：[docs/AUDIT-v0.1.md](docs/AUDIT-v0.1.md)
- 冻结状态：[spec/freeze.json](spec/freeze.json)

## Base 冻结状态

**语法表面已冻结候选，语义尚未冻结**。原因与门槛见 [docs/FREEZE.md](docs/FREEZE.md)：

```bash
python3 tools/freeze_check.py
```

- Base（`--app`）：77 关键字 + 语法表面冻结；只修 bug，不新增关键字
- Ds+（`--plus`）：软件方向扩展
- Ds/Cut（`--cut`）：硬件方向扩展

## Ds/Cut 裸机子语言 + DsOS

三层严格超集：**Cut ⊂ Ds ⊂ Ds+**。Cut 是冻结 16 token 的裸机子语言，用于启动/异常向量/最底层驱动：

```bash
python3 cut/cutc.py dsos/boot/rp2350_start.ds --cut --emit asm -o start.s
sh cut/test_build.sh          # clang 汇编 + ld.lld 链接冒烟
```

- 规范：[spec/DS-CUT.md](spec/DS-CUT.md) ｜ 编译器：[cut/README.md](cut/README.md)
- DsOS 架构：[docs/DSOS.md](docs/DSOS.md) ｜ 启动/上下文切换/链接脚本：[dsos/](dsos/)
- 双目标（已纠正原任务冲突）：**RP2350 → Thumb/.uf2**；**Zero 2 W → AArch64/kernel8.img**
- 后端：Thumb 全子集；AArch64 纯 `@asm`（启动/上下文切换）；`cut/uf2.py` 生成 RP2350 UF2
- **DSOSS**（DsOS Standard Specification）：标准/一致性检查 → [spec/DSOSS.md](spec/DSOSS.md) · [dsoss/](dsoss/)
- 层错误精确提示：`--cut` 用 Ds 关键字报 `E_CUT_LAYER_DS`；`--app` 用 Ds+ `@` 令牌报 `E_CUT_LAYER_PLUS`

## 包管理 dspm（原型）

包 = GitHub 仓库，版本 = git tag，源码即分发，无中心服务器：

```bash
./dspm install ds-hello
./dspm list
./dspm remove yzxcrush/ds-json
./dspm cache-clean
```

- `ds.toml` 声明包名/版本/exports/依赖/目标；lock 记录 tag+commit+tarball hash
- 深度优先装依赖、缓存优先可离线、不执行任何包内脚本、unsafe 包需确认
- **C 驱动已原生支持 `use`**：读取 `~/.ds/pkg` 安装布局，按 exports/targets 解析模块，缺失时提示 dspm install
- 规范、安全说明、其它后端 `use` 解析伪代码、Android 集成方案：[docs/DSPM.md](docs/DSPM.md)
- Ds+ 一页纸：[docs/DS-PLUS.md](docs/DS-PLUS.md) · [分支](https://github.com/yzxcrush/ds/tree/ds-plus) · [发布](https://github.com/yzxcrush/ds/releases/tag/ds-plus-v0.1.0)
- 示例包：[ds-hello（GitHub，可直接安装）](https://github.com/yzxcrush/ds-hello) · [examples/packages/ds-hello](examples/packages/ds-hello)
- 包索引：[yzxcrush/ds-packages](https://github.com/yzxcrush/ds-packages)

## 为什么是 Ds？

一套语言覆盖 **应用 / 系统 / 裸机**，三档写法把 AI 生成成本压到最低，且每一步都能被三套参考实现执行验证：

- **一套语义三种交付**：`--app` 应用、`--bare` 裸机、7 个交叉编译目标
- **双分支**：Ds（77 冻结）/ **Ds+**（严格超集，16 个 `@` 硬件/区域令牌，x86-64 子集后端）
- **能力密度**：77 硬关键字覆盖类型/内存/错误/并发/元编程/OOP/模式/裸机
- **Token 效率**：常见程序 经典 137 → 精简 82（-31%）→ Flow 69（**-49%**）
- **可预测**：显式内存五选一、确定性析构、错误分层、结构化并发、布局可控
- **包管理**：**dspm** 用 GitHub 当包仓库（无中心服务器），C 驱动原生 `use` 解析
- **AI 原生**：llms.txt + 语言卡 + 41 条 SFT + 25 项评测 + Python/C/App 三实现可对拍
- **不是换皮**：Flow（`\` 定义 + 并置调用 + `.` 结束块）不属于任何主流编译语言语法家族

完整阐述（含与 Python/Rust/Go/C++ 的客观对比与适用范围）：[docs/WHY-DS.md](docs/WHY-DS.md)

## 一键校验

```bash
cd ds-v0.1
python3 tools/ds_keywords.py build                     # 从规范文档生成 spec/keywords.json
python3 tools/ds_keywords.py check --json spec/keywords.json   # 覆盖/重复/类别/计数校验
python3 tools/dslex.py                                # 词法自检 + 示例扫描
python3 -m unittest tests.test_driver -v              # 驱动/语言特性/示例/CLI 测试
make -C c && sh c/run_tests.sh                        # C 驱动构建 + 与 Python 对拍
```

实测结果：

```
✓ 关键词覆盖：11/11 类，合计 77（标识符 73 + 符号 4）
✓ 运算符：26 个全部在表
✓ dscc：位置参数 + 7 个核心选项全部在表
✓ 字面量 9 种、注释 4 种全部在文
✓ 词法自检：20/20 通过（关键字 77、字面量 9、注释 4 类、错误路径）
✓ 示例词法检查通过（4 个文件，1010 + 410 + 303 + 299 个记号）
✓ 示例关键词覆盖：77/77
```

## 交付物

| 文件 | 内容 |
|---|---|
| [`c/`](c/) | **C 参考驱动**（核心子集）：经典/精简/Flow 写法，`make -C c` 构建，与 Python 对拍 |



| 文件 | 内容 |
|---|---|
| [spec/DS-v0.1.md](spec/DS-v0.1.md) | 规范主文档（定位/词法/关键词语义表/运算符优先级/字面量/注释/EBNF/语义契约/dscc） |
| [spec/keywords.json](spec/keywords.json) | 机器可读索引：77 项关键词的形式、语义、示例，含字母序索引 |
| [tools/ds_keywords.py](tools/ds_keywords.py) | 关键词表校验器 + 索引生成器（与文档双向一致性） |
| [tools/dslex.py](tools/dslex.py) | 参考词法器：可执行的词法定义 + 自检 + 示例扫描 |
| [dsv01/](dsv01/) | Python 参考驱动：词法器 + 解析器 + 树遍历解释器 + prelude |
| [dscc](dscc) / [ds](ds) | 终端命令：`dscc` 编译器风格、`ds` Python 风格（含 REPL） |
| [examples/tour.ds](examples/tour.ds) | 应用模式综合示例（覆盖 77 个关键字的大部分语法形态） |
| [examples/concurrency.ds](examples/concurrency.ds) | 并发：`spawn`/`go`/`thread`/`chan`/`send`/`recv`/`mutex`/`wait` |
| [examples/memory.ds](examples/memory.ds) | 内存：`alloc`/`free`/`rc`/`arc`/`ref`/`ptr`/`raw`/`gc`/`volatile` |
| [examples/bare.ds](examples/bare.ds) | 裸机：`section`/`at`/`irq`/`asm`/`packed`/`static mut`/`@unsafe` |

## 终端驱动（Python 参考实现）

`dsv01/` 是 Ds v0.1 的可执行参考驱动：**词法器 → 解析器（AST）→ 树遍历解释器**。无需安装即可直接运行：

```bash
cd ds-v0.1
./dscc examples/tour.ds --app          # 编译器风格：按规范选项执行
./ds   examples/tour.ds                # Python 风格：像 python script.py 一样
./ds -c 'package t
fn main() { println("hello from Ds") }'   # 类似 python -c

./ds                                   # 进入 REPL（:help / :quit / :load / :reset）
python3 -m dsv01 examples/tour.ds      # 模块方式运行
python3 -m dsv01                       # 模块方式 REPL
```

也可以安装成命令（`pip install -e .` → `dscc`、`ds` 全局可用）。

### 安装到终端（本机已完成）

本机已通过 pip 安装为全局命令（`$PREFIX/bin/ds`、`$PREFIX/bin/dscc`），任意目录可直接用：

```bash
ds --version                    # ds (Ds v0.1.0)
ds ~/1/ds-v0.1/examples/tour.ds
dscc ~/1/ds-v0.1/examples/concurrency.ds
```

源码更新后重装 / 卸载：

```bash
cd ~/1/ds-v0.1 && pip install --force-reinstall .
pip uninstall dsv01
```

### 可执行脚本（像 `.py` 一样直接运行）

```ds
#!/data/data/com.termux/files/usr/bin/ds
package hello

fn main() {
    println("hi")
}
```

```bash
chmod +x hello.ds && ./hello.ds
```

Termux 的 shebang 用上面的绝对路径（本机没有 `/usr/bin/env`）；Linux/macOS 写 `#!/usr/bin/env ds` 即可。首行 `#` 在 Ds 里是注释，因此 shebang 不参与词法。

### 快捷指令

| 命令 | 作用 |
|---|---|
| `启动ds` | 进入 Ds v0.1 交互终端（REPL） |
| `启动ds 文件.ds` | 直接运行脚本（等价 `ds 文件.ds`） |
| `dsrepl` | 英文别名，同样进入 REPL |

一键安装（驱动 + 快捷指令 + 命令）：

```bash
cd ~/1/ds-v0.1 && ./install.sh
```

`install.sh` 会 `pip install --force-reinstall .` 并把 `bin/启动ds`、`bin/dsrepl` 复制到 `$PREFIX/bin`。

### 驱动选项

| 选项 | 行为 |
|---|---|
| `dscc <file.ds>` / `ds <file.ds>` | 解释执行 `main`；退出码 0/1/2/3/4 与规范一致 |
| `--app` / `--bare` | 模式（互斥）；`--bare` 默认 `--gc none --rt minimal`，非法组合退 2 |
| `--target` / `--opt` / `--gc` / `--rt` | 接受并记录（参考驱动不产机器码；`--bare` 约束会校验） |
| `--emit tokens` | 打印词法记号表（`行:列 类型 文本`） |
| `--emit ast` | 打印解析后的 AST |
| `--check` | 仅解析检查 |
| `-o <path>` | 编译器兼容参数（参考驱动不写可执行文件，会提示忽略） |
| `-c "code"` | 直接执行一段源码（`ds` 命令） |
| `--repl` | 强制进入 REPL |
| `--version` / `-v` | 版本 / 打印运行配置 |

### Python API

```python
import dsv01

dsv01.run_source('package demo\nfn main() { println("hi") }')

interp = dsv01.Interpreter()
value = interp.run_file("examples/tour.ds")   # 返回 main 的返回值
```

### 已实现 vs 近似

- **已实现**：77 关键字词法；声明（`package/mod/use/fn/type/class/trait/impl/static/extern/macro/attr/section`）；控制流（`if/else/loop/while/for/break/continue/return/goto` 标签）；模式匹配（`match/when`/or 模式/`some/ok/err`/数组/映射/类型模式）；`opt/res` + `try/catch` + `panic/recover/assert`；`class` 单继承/`super.init`/`dyn` trait 对象/确定性 `drop`；`|>` 管道；`sizeof/alignof/typeinfo/comptime/attr`；`spawn/go/thread/chan/send/recv/mutex/wait`（Python 线程 + 条件变量）；`alloc/free/rc/arc/gc/ptr/raw/volatile`（bytearray/地址模拟）。
- **近似**：类型标注不做静态检查（动态类型 + 标注驱动 `is/sizeof/typeinfo`）；不做借用检查与 unsafe 强制；`comptime` 在求值时即时计算；`chan[T]()` 零容量按无界缓冲近似；`spawn` 作用域结束自动等待、`go` 为 daemon 线程；`ptr` 用 bytearray/地址模拟；`extern` 未链接（调用报错）。
- 这些近似只影响参考驱动的严格程度，不修改规范语义。

## 让其他 AI 学习 Ds

本仓库同时是 Ds 的「AI 学习包」：可检索、可执行、可评测。

| 物料 | 入口 |
|---|---|
| AI 检索入口（llms.txt 约定） | [llms.txt](llms.txt) |
| 一页纸语言卡（先读） | [ai/LANGUAGE_CARD.md](ai/LANGUAGE_CARD.md) |
| 全量上下文（约 120 KB） | [ai/llms-full.txt](ai/llms-full.txt) |
| 系统提示词 | [ai/system_prompt.txt](ai/system_prompt.txt) |
| Agent 操作约定 | [AGENTS.md](AGENTS.md) |
| 指令微调数据（32 条） | [datasets/ds_sft.jsonl](datasets/ds_sft.jsonl) |
| 语料（10 篇） | [datasets/ds_corpus.jsonl](datasets/ds_corpus.jsonl) |
| 评测集（19 任务） | [datasets/ds_bench.jsonl](datasets/ds_bench.jsonl) |
| 评测脚本 | [tools/ds_bench.py](tools/ds_bench.py) |

```bash
python3 tools/ds_bench.py --list
python3 tools/ds_bench.py --submissions 模型提交.jsonl --json result.json
```

详细投喂/微调/评测方式见 [ai/README.md](ai/README.md)。

## 精简写法（0.1c，省 token）

语义与 77 关键字完全不变，只把「写」变短，**AI 生成默认推荐**（旧写法仍合法、可混用）：

```ds
# 经典
package hello
fn main() {
    println("hello, Ds")
}
```

```ds
# 精简（同一程序）
println("hello, Ds")
```

| 规则 | 精简写法 |
|---|---|
| 无样板 | 不需要 `package`/`fn main`，顶层语句即入口 |
| 函数 | `fn add(a,b)=a+b` / `fn say(x): println(x)` |
| 单语句块 | `for i in 0..10: println(i)` / `if c: a else b` |
| 变量 | `x=1` 即不可变定义；可变用 `var`；`+= -= *= /= %=` 等 |
| 范围 | `0..10`（半开，等价 `range(0,10)`） |
| 插值 | `f"x={x} n={x+1}"` |
| 类型 | 全部可省略 |

实测常见程序平均省 **31%** token（hello 省 61%，错误处理省 45%）；`python3 tools/token_report.py` 可复跑。
完整规则：[spec/DS-CONCISE.md](spec/DS-CONCISE.md)。

## Flow 写法（结构性精简，非换皮）

在 0.1c 之上再加一档 **Flow**：函数 `\` 定义、参数空白分隔、调用靠并置、多语句块用 `.` 结束、
条件用 `?`、返回用 `^`——没有 `{}`、没有 `fn main`、没有逗号参数表。

```dsf
# examples/flow/hello.dsf
p "hello, Ds"
```

```dsf
# examples/flow/fib.dsf
\fib n = ?n<2: n; fib(n-1)+fib(n-2)
for i in 0..10: p f"fib({i})={fib(i)}"
```

| 场景 | 经典 | 0.1c | Flow | vs 经典 | vs 0.1c |
|---|---|---|---|---|---|
| hello world | 13 | 5 | 3 | -76% | -40% |
| 斐波那契 10 项 | 64 | 38 | 34 | -46% | -10% |
| 累加 + 调用 | 60 | 39 | 32 | -46% | -17% |
| **合计** | **137** | **82** | **69** | **-49%** | **-15%** |

识别方式：文件名 `.dsf`、文件以 `\` 开头、或首行 `#!flow`；普通 `.ds` 不受影响。
完整规则与「为什么不是换皮」：[spec/DS-FLOW.md](spec/DS-FLOW.md)。
示例：[examples/flow/](examples/flow/)。

## 全量关键词表（77 项速查）

| 类别 | 数 | 关键词 |
|---|---|---|
| 定义 | 9 | `fn` `let` `var` `type` `class` `trait` `impl` `mod` `package` |
| 控制 | 9 | `if` `else` `loop` `while` `for` `break` `continue` `return` `goto` |
| 管道 | 3 | `->` `=>` `\|>` |
| 错误 | 7 | `try` `catch` `panic` `recover` `assert` `res` `opt` |
| 模块 | 8 | `use` `as` `export` `pub` `priv` `prot` `static` `extern` |
| 并发 | 8 | `spawn` `go` `thread` `chan` `send` `recv` `mutex` `wait` |
| 内存 | 9 | `raw` `free` `alloc` `rc` `arc` `gc` `ptr` `ref` `mut` |
| 裸机 | 7 | `@` `asm` `volatile` `at` `irq` `section` `packed` |
| 元编程 | 4 | `comptime` `macro` `typeinfo` `attr` |
| OOP | 6 | `self` `super` `new` `drop` `extends` `dyn` |
| 模式 | 7 | `match` `when` `where` `in` `is` `sizeof` `alignof` |
| **合计** | **77** | **73 个标识符式 + 4 个符号式（`@` `->` `=>` `\|>`）** |

每个词的形式、语义、示例见 [spec/DS-v0.1.md` §1.3](spec/DS-v0.1.md)。

## 关键设计决策（消歧摘要）

1. **硬关键字冻结**：77 项全部为硬关键字，不可作标识符；对齐外部符号用反引号原始标识符 `` `free` ``。
2. **`{}` 是块，`{k:v}` 是映射**：空块 `{}`、空映射 `{:}`；因此 **0.1 不设结构体字面量**——值类型用 `名(字段: 值)` 构造，类用 `类.new(...)` 构造。
3. **泛型用 `[]`**：`Vec[T]`、`res[T, E]`、`[]u8`，避免 `<>` 与比较运算符冲突。
4. **三个箭头分工**：`->` 管类型（返回类型/函数类型），`=>` 管值（match 分支/单表达式函数体/匿名函数），`|>` 是表达式管道（左结合降糖）。
5. **错误三层**：`res`/`opt` + `try`/`catch` 处理可恢复错误；`panic`/`recover` 处理不可恢复错误；`assert` 只用于不变量。
6. **内存四选一**：栈/静态、`alloc`+`free`、`rc`/`arc`、`gc`；`ref` 是受检借用，`ptr`/`raw` 是只能在 `@unsafe` 中解引用的逃逸口。
7. **并发**：`spawn` 结构化（作用域结束自动 `wait`）、`go` 分离（须自同步）、`thread` 独占 OS 线程；共享可变状态只能经 `mutex`/`chan`。
8. **裸机**：`@` 属性前缀 + `asm`/`volatile`/`at`/`irq`/`section`/`packed`，配合 `@unsafe { }` 不安全块；`--bare` 下禁用 GC 与隐式分配。
9. **元编程四阶段**：`macro`（解析期语法）、`comptime`（编译期求值）、`typeinfo`（类型反射）、`attr`（自定义属性）。
10. **OOP**：`class` 单继承 + `extends`/`super` + `trait`/`impl`/`dyn`；确定性 `drop`。
11. **注释三种**：`#` 行、`//` 行、`#| ... |#` 可嵌套块；紧邻声明的块注释约定为文档注释。
12. **编译驱动**：`dscc input.ds -o out --app/--bare --target --opt --gc --rt`，模式互斥、默认矩阵与退出码见规范 §7。

## `dscc` 核心选项速查

| 选项 | 取值 | 默认 |
|---|---|---|
| `-o <path>` | 输出路径 | `a.out`（app）/ `<package>.elf`（bare） |
| `--app` | 应用模式 | 默认（与 `--bare` 互斥） |
| `--bare` | 裸机 no_std 模式 | 与 `--app` 二选一 |
| `--target <triple>` | 7 个 0.1 支持目标 | 宿主 |
| `--opt <0\|1\|2\|3\|s\|z>` | 优化级别 | `2` |
| `--gc <none\|rc\|arc\|tracing>` | GC 策略 | app: `tracing`；bare: `none` |
| `--rt <none\|minimal\|full>` | 运行时 | app: `full`；bare: `minimal` |

## 发布到 GitHub

仓库已配置好 SSH(443) + Deploy Key 的发布脚本，默认目标 `yzxcrush/ds-v0.1`：

```bash
bash tools/publish.sh                 # 推送到 yzxcrush/ds-v0.1
bash tools/publish.sh owner/repo      # 或指定其他仓库
```

前置条件（只需做一次）：

1. <https://github.com/new> 新建空仓库 `ds-v0.1`（**不要**初始化 README/License）；
2. 仓库 Settings → Deploy keys → 添加 `~/.ssh/ds_github.pub` 的内容并勾选 **Allow write access**；
3. 运行上面的脚本。`tools/publish.sh` 会先自检 key 与仓库可达性，失败时给出明确修复提示。

## 边界说明

- **规范是定义稿**；`dsv01/` 是参考驱动（解释执行），用于验证规范可执行、可演示，不产出机器码，也不做静态类型/借用检查。
- 驱动对部分语义做了近似（零容量通道、`comptime` 求值时机、`ptr` 内存模拟等），详见上文「已实现 vs 近似」；这些近似不修改规范语义。
- 规范中的示例构造（`math.sqrt`、`println` 等）来自 prelude/std，prelude 清单见规范 §1.4。
- 未来（0.2）可能升格为关键字的候选词：`struct` `enum` `const` `defer` `async` `await`；在 0.1 中它们仍是合法标识符。
