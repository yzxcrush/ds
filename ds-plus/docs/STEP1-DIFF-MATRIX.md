# Step 1 — PYX → Ds+ 差异矩阵

> 输入：PYX v0.1 草图（18 节，含机器翻译损坏）
> 输出：按「维度 | Ds(base) | Ds+(plus) | PYX 原草图 | 备注」逐项比对，并给出机器翻译修正与需设计师裁决的分歧。
> 约束：Ds+ 严格超集；Ds 77 关键字冻结；三档写法同一 AST。

## 0. 结论摘要

1. PYX 与 Ds 的冲突主要是**语言哲学级**：无运行时/无 GC/无异常/无反射/无 OOP/无属性系统 vs Ds 的完整通用语义。
2. 由于 Ds+ 必须严格超集，PYX 中「删除式」的设计（无 GC、无异常、无反射、无 OOP）**不能进入 Ds+ 的语言级语义**；只能作为 Ds+ 的 **no-GC/bare profile（模式）** 或 **不采纳**。
3. PYX 中可增量吸收的价值：**四区域内存标注、硬件 IO/汇编/系统寄存器关键字、raw binary/裸机镜像输出、C ABI 互操作意图、无锁原语与原子操作**（后两者需名额裁决）。
4. PYX 的 `struct/union/enum/alias/function/zero/@trusted` 等与 Ds 的 77 关键字冻结冲突，落入「不采纳/替代实现」。
5. 草图存在多处机器翻译错译与规则-示例不一致（见 §3），必须先规范化才能作为 Ds+ 的设计输入。

## 1. 差异矩阵

| 维度 | Ds(base) | Ds+(plus) | PYX 原草图 | 备注 |
|---|---|---|---|---|
| 定位/分支 | 通用系统语言：`--app` 应用 + `--bare` 裸机；77 硬关键字；定义稿 + Python/C/Android 参考实现 | Ds 的严格超集；在 base 之上增加硬件/区域能力；提供 no-GC bare profile；base 语义（含 app/GC/异常/反射/OOP）必须保留 | 纯裸机语言：无 VM/运行时/GC/反射/异常/标准库；只有裸机与系统编程 | 严格超集 ⇒ PYX 的「删除式」设计只能作为模式或不采纳（见 §4-①） |
| 关键字 | **77 冻结**：定义 9 / 控制 9 / 管道 3 / 错误 7 / 模块 8 / 并发 8 / 内存 9 / 裸机 7 / 元编程 4 / OOP 6 / 模式 7；`@` 为属性前缀 | `ds-core` 冻结 77 + 新增 `@` 前缀硬件/区域关键字（约 10–12 硬件 + 4 区域，见 Step 2）；总表 = 77 + N；`@` 出现双角色，需要上下文消歧 | 自称 48 关键字（草表实际约 45，含重复/错译）；含 `struct/union/enum/alias/function/zero/@trusted` | PYX 的 `struct/union/enum/alias/function/zero` 不引入（与 77 冻结冲突）；`@trusted` 不拟引入（与 `@unsafe` 边界冲突） |
| 内存模型 | 栈/静态 + `alloc/free` + `rc[T]`/`arc[T]`/`gc[T]` + `ref` 借用 + `ptr`/`raw` + `@unsafe` | 继承全部 base 语义；**新增**四区域显式标注 `@stack`/`@static`/`@raw`/`@mmap`；no-GC bare profile 下 `gc[T]` 不可用（base 兼容 profile 下仍可用） | 恰好 4 区域 `@stack/@static/@raw/@mmap`；无 GC、无 reference、无隐藏分配 | PYX「无 reference」应修正为「无 GC 引用」；`@raw` 在 PYX 既是区域又是分配方式，Ds+ 用同一关键字承载（语义见 Step 2） |
| 错误 | `res`/`opt` + `try`/`catch` + `panic`/`recover` + `assert` | 继承 base（超集）；bare profile 下 `panic` 语义保持 Ds（默认展开；`--rt none` 可 abort） | 无异常（草图未定义错误模型；示例用返回值/裸指针） | PYX「无异常」不能作为 Ds+ 语言级删除；建议只作为 bare profile 的策略选择 |
| 并发 | 关键字级 `spawn`（结构化）/`go`（分离）/`thread`/`chan`/`send`/`recv`/`mutex`/`wait` | 继承 base；PYX 的无锁原语作为**增量**：`@atomic_*`/`@fence`/`@cas` 等（名额与 Step 2 待裁） | `atomic/lock/unlock/fence/mfence/futex`；自旋锁手写；无结构化任务概念 | PYX 的 `futex_wait` 是 OS 系统调用封装，不是语言运行时；原子/锁关键字是否有价值需裁决（§4-④） |
| IO / 硬件 | `asm`（需 `@unsafe`）、`volatile`、`@at`/`@section`/`@irq`、MMIO 用 `volatile ptr[u32]`；无端口 IO/MSR 内建 | 新增 `@asm`（带操作数/volatile）、`@inb/@outb/@inw/@outw/@inl/@outl`、`@rdmsr/@wrmsr`、`@mmio`（候选） | `asm` 一等公民（含 `ASM Volatile` 操作数）；`inb/outb/inw/outw/inl/outl`；`rdmsr/wrmsr`；`@mmio`；`CR0/CR3` 直接读写 | PYX 示例把汇编助记符直接写进 Flow（`MOV/HLT`），Ds+ 必须包在 `@asm` 内；`CR0/CR3` 建议用 `@rdcr/@wrcr`（候选）或 `@asm` 表达 |
| ABI | 默认 `repr(Ds)`；`@repr(C)` 显式 C 布局；`extern "C"`；0.1 目标无 Windows/macOS | 继承 Ds 默认 ABI（字节级一致是超集要求）；新增 C ABI 显式保证；bare 目标可默认 C ABI（待裁） | SysV AMD64（Linux/macOS）/ Microsoft x64（Windows）默认 C ABI，1:1 调用 C | PYX「默认 C ABI」与 Ds 默认布局冲突；超集不能改 base 默认，建议 `@abi("C")` 或 `@repr(C)` 显式开启（§4-③） |
| 输出格式 | `dscc --app` / `--bare`；ELF/可执行；7 目标；无 raw 启动扇区 | 继承全部 base 输出；**新增** raw binary / ELF32/64 / bare image（`--raw`）；可扩展 i686/PE/Mach-O（待裁） | raw binary、ELF32/64、PE、Mach-O、WASM；512 字节启动扇区（0xAA55、`$` 位置计数器） | PYX「无 VM」却输出 WASM 自相矛盾；Ds+ 不应宣称无 VM 的同时把 wasm 当 bare 输出（§3-③） |
| AI 学习包适配 | `llms.txt` + 语言卡 + 77 关键词索引 + 41 SFT + 25 bench + 三实现；版本 0.1 | **同一 ds-core 数据 + Ds+ delta**：base 子集评测（必须全过）+ plus 增量评测；llms 入口标注分支；数据版本与代码版本同步 | 无（仅规范草图） | 双分支必须做「base subset + plus delta」，避免模型混淆两套关键字；llms.txt 要分 `main`/`ds-plus` 两个入口 |
| 类型系统 | 静态类型；`type/class/trait`；无隐式数值转换；泛型 `[]` | 继承不变（超集）；**不引入** `struct/union/enum/alias/function` 关键字；C 布局用 `@repr(C)`/`@packed` | `struct/union/enum/alias` 关键字；`void`、`ptr<T>/*T`；C ABI 布局 | PYX 的 `void` 对应 Ds `unit`；`ptr<T>` 对应 `ptr[T]`/`*T`；union 语义可用 `@repr(C)+type+comptime` 表达（不新增关键字） |
| 元编程/OOP | `comptime/macro/typeinfo/attr`；`class/trait/impl/dyn/self/super/new/drop` | 继承不变；no-GC profile 下 `typeinfo` 运行期保留受 `--rt` 影响 | 无反射、无 OOP、无标准库 | PYX 的删除式设计不能进入 Ds+ 语言级；只影响 bare profile 的可用子集 |
| 工具链/编译 | `dscc` 定义 + 参考解释器（Python 全量 / C 核心 / Android 内核）；无机器码后端 | 共享 `ds-core` 前端与 IR；plus 增加硬件后端与 `--raw`/bare 镜像；最终机器码后端列入路线图 | tokenizer→parser→静态类型检查→LLVM IR/asm→NASM/ld（无 libc）；自举编译器路线 | Ds+ 不能只靠解释器实现「无运行时」承诺；需在 ds-core IR 上扩展真实代码生成（后续步骤） |
| AI token 度量 | 实测：经典 137 → 0.1c 82（−31%）→ Flow 69（−49%），基准是 Ds 自身 | 继承三档写法与度量；plus 新增关键字必须同时提供三档写法示例 | 自称相对 C 省 72%（基准/口径未给出） | 两者基准不同（Ds vs Ds；PYX vs C），不可直接比较；Ds+ 应发布自己的基准与脚本 |

## 2. 锁定决策 ↔ 矩阵自检

| 锁定项 | 矩阵落点 | 状态 |
|---|---|---|
| 1 双分支 | §1「定位/分支」 | ✅ |
| 2 严格超集 | 各维度均标注「继承全部 base 语义」；§4-① 指出无 GC 的张力 | ✅（需裁决口径） |
| 3 共享 ds-core | §1 工具链/关键词/AI 行；Step 3 详列 | ✅ |
| 4 版本同步 | §1 AI 行、README | ✅ |
| 5 C/C++ 类比 | 命名 Ds / Ds+；base 分支不动 | ✅ |
| 6 77 冻结 | §1 关键字行；不采纳 PYX 的 struct/union/enum/alias/function/zero | ✅ |
| 7 @ 前缀新关键字 | §1 关键字/IO 行；§4-② 消歧方案 | ✅（需裁决） |
| 8 四区域 | §1 内存行 | ✅ |
| 9 无 GC 模式 + raw/ELF/bare | §1 内存/输出行；§4-①③ | ✅（需裁决口径） |
| 10 三档写法同 AST | §1 定位/工具链行；Ds+ 只扩展后端，不新增表面语法 | ✅ |
| 11 不省 token | 本文件与后续步骤按完整展开写 | ✅ |

## 3. PYX 草图的机器翻译错误与内部矛盾（修正）

| # | 草图原文 | 实际含义 | 修正/处理 |
|---|---|---|---|
| 3.1 | `退役` | `ret` | 修正为汇编写法；Ds+ 若写汇编必须包在 `@asm`/`asm` |
| 3.2 | `环线` / `环形：HLT;JMP环线` | `loop` / `loop: hlt; jmp loop` | 同上 |
| 3.3 | `性传播疾病` | `sti`（开中断） | 同上 |
| 3.4 | `时刻表 ctx` / `时刻表` | `schedule ctx` | 修正为函数调用 |
| 3.5 | `呼号打印` | `call print` | 修正 |
| 3.6 | `特别推荐` | `esp`（栈指针） | 修正 |
| 3.7 | `印刷` / `普沙` / `波帕` | `print` / `pusha` / `popa` | 修正 |
| 3.8 | `利特与idt_ptr` | `lidt [idt_ptr]` | 修正 |
| 3.9 | `虚空` / `原始覆盖层` / `别名` | `void` / `union` overlay / `alias` | 类型关键字名修正；Ds+ 不新增这些关键字 |
| 3.10 | `36/48 关键字`（正文写 48，用户消息写 36/48） | 草表实际唯一条目约 45，且含重复（`fence/mfence`）与错译 | 以规范化英文表为准；Ds+ 只取「4 区域 + 10–12 @ 硬件」，其余不采纳 |
| 3.11 | 规则 `\name =` vs 示例 `\name:`；`.=`/`!=`/`?=`/`|=` 在示例中未出现 | 草图规则与示例不一致 | Ds+ **不引入**这些未落地符号；直接继承 Ds Flow：`\` 定义、`=` 表达式体、`^` 返回、`?` if、`.` 结束块 |
| 3.12 | 「没有引用」 | 应为「没有 GC 引用」；指针仍然存在 | 修正表述；Ds+ 保留 `ref` 借用与 `ptr` |
| 3.13 | 「没有运行时」但提供 `futex`/调度器/`libc` 子集 | 应为「没有语言运行时；OS 服务由用户代码/系统调用提供」 | 修正表述；Ds+ 的 no-runtime 指 no-GC/no-language-runtime，不排斥 OS |
| 3.14 | 「没有 VM」但输出 WASM | WASM 需要宿主 VM/运行时 | 修正：Ds+ bare profile 不输出 WASM；WASM 仍属 Ds base 目标 |
| 3.15 | Flow 示例把 `MOV/HLT/CLI` 等汇编指令直接写进高层代码（无 `asm` 包裹） | 汇编需要显式标记 | Ds+ 必须 `@asm { ... }` 或在 `asm` 语句内；否则解析失败 |

## 4. 需要设计师裁决的分歧（含推荐）

### ① 「Ds+ 无 GC 模式」与「严格超集」的张力（最高优先级）

- 冲突：若 Ds+ **语言级**删除 GC/异常/反射/OOP，则包含 `gc[T]`/`try`/`class` 的 Ds 代码无法在 Ds+ 编译，违反决策 2。
- 推荐解释（A）：**「无 GC」是 Ds+ 的 bare profile**；Ds+ 仍有 compatibility profile 完整支持 base 语义。这样 base 代码 100% 通过，且 Ds+ 能在 bare 模式下满足「无 GC/无运行时」。
- 备选（B）：Ds+ 只做 no-GC 子集，拒绝 base 的 GC 代码 —— **直接违反决策 2**，不建议。
- 请选 A / B（推荐 A）。

### ② `@` 的双角色消歧

- 冲突：Ds 中 `@` 是属性前缀（`@inline`/`@unsafe`/`@section`）；Ds+ 要把 `@raw`/`@inb` 等作为关键字。若简单把 `@name` 一律当关键字，Ds 代码里以 `@raw` 作属性的写法会失效（理论上违反超集）。
- 推荐（A）：**上下文关键字**——`@` 后的名字若属于硬件/区域集合，且**后续语法符合硬件用法**（如 `@inb(port)`、`@raw :=`、`@mmap(...)`、`@asm { }`、`@rdmsr(...)`），则识别为硬件关键字；否则按属性解析。
- 备选（B）：在 ds-core 把 `raw/asm/inb/...` 列为属性保留名，要求 Ds 代码迁移——违反决策 2，不建议。
- 请选 A / B（推荐 A）。

### ③ ABI 默认值

- 冲突：PYX 默认 C ABI；Ds 默认 `repr(Ds)`。超集要求 Ds 代码行为字节一致，不能把 Ds+ 默认改成 C。
- 推荐（A）：保留 Ds 默认；新增 `@abi("C")`（或复用 `@repr(C)`）显式开启；Ds+ bare 目标可**默认** C ABI（因为 base 在 bare 下也多为 C 交互）。
- 备选（B）：Ds+ 全局默认 C ABI —— 改变 base 布局，违反超集。
- 请选 A / B（推荐 A）。

### ④ 无锁原语（atomic/lock/fence/futex）是否进本轮 Ds+ 关键字名额

- PYX 有 `atomic/lock/unlock/fence/mfence/futex`；但本轮锁定是「约 10–12 个硬件关键字」，名额主要给 IO/汇编/区域。
- 推荐（A）：本轮只做 4 区域 + 10–12 硬件 IO/asm；无锁原语用 `@asm`/现有 `mutex` 过渡，0.2 再增 `@atomic`/`@fence`/`@cas` 系列（单独版本同步）。
- 备选（B）：挤进本轮名额（需砍掉端口 IO 宽度关键字）。
- 请选 A / B（推荐 A）。

### ⑤ 输出/目标扩展范围

- PYX：i686 启动扇区、PE、Mach-O、WASM。
- 推荐（A）：Ds+ v0.x 先做 `--raw` + bare image（x86_64/ARM/RISC-V 现有目标），i686/16 位实模式、PE/Mach-O、WASM 后续；`--raw` 只对 `--bare` 生效。
- 备选（B）：一次覆盖 i686/PE/Mach-O（成本高，且 PE/Mach-O 与 Ds 目标列表不一致）。
- 请选 A / B（推荐 A）。

### ⑥ 是否引入 PYX 的 `struct/union/enum/alias/function/zero/@trusted`

- 决策 6 冻结 77 ⇒ **不引入**。替代：`type` 表达 struct/alias；union 用 `@repr(C)`+`type`/`comptime`；enum 用 `type`+常量；`zero` 用 `0`；`@trusted` 不引入（保留 `@unsafe` 显式边界）。
- 请确认「不引入」（推荐），或指出必须保留的个别关键字及理由。

## 5. Step 1 交付物与下一步

- 本文件：`ds-plus/docs/STEP1-DIFF-MATRIX.md`（在 `ds-plus` 分支）
- 分支：`ds-plus`（base `main` 未改动，77 关键字未动）
- 下一步（Step 2）：Ds+ 新增关键字清单（10–12 个 `@` 前缀）——名称、语义、PYX 对应原文、编译行为、base stub 报错信息
- Step 3：`ds-core` 共享模块清单（文件/定义归属）
- Step 4：超集校验规则（Ds+ 编译器必须执行的检查项）
