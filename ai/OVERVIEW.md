# Ds 与 DsOS：完整介绍（AI 学习版）

> 面向 AI 训练/检索/代码生成的总览文档。  
> 版本：Ds 0.1.0；Base 冻结标签 `ds-base-v1`；Ds+ / Ds/Cut 不冻结。  
> 规范：CC-BY-4.0；代码：MIT。

---

## 0. 先读这一段：Ds 是什么，不是什么

**Ds 是什么：**

> 一门静态类型、显式内存、可裸机运行、编译期可元编程的系统级编程语言。  
> 一套语义核心，三层扩展：`Ds/Cut ⊂ Ds Base ⊂ Ds+`。

**Ds 不是什么：**

- 不是“Python 换皮”：它有显式内存、错误分层、裸机层。
- 不是“C 换皮”：有类型化整数、确定性析构、结构化并发、模块边界。
- 不是已经完成的生产级编译器：Base 已冻结，但后端/标准库/生态仍在早期。
- 不是“没有 bug 的语言”：只承诺已验证部分冻结、错误边界清楚。
- 不是图形操作系统：DsOS 仍是启动/内核骨架阶段。

---

## 1. 设计目标

1. **一套语义，三种交付**  
   应用、系统、裸机共用类型/内存/错误/并发规则。

2. **显式优于隐式**  
   内存策略写在代码里：栈/静态、alloc+free、rc、arc、gc。  
   没有隐藏 GC、隐藏分配、隐藏异常展开。

3. **可预测**  
   显式布局、确定性析构、整数边界检查、层错误精确、ABI 可控。

4. **AI 原生**  
   77 个硬关键字、三种写法、llms.txt、语言卡、SFT/评测集；  
   小关键字集 + 可检查语义，降低 AI 幻觉空间。

5. **边界清楚**  
   Base 只修 bug；新能力进 Ds+ / Ds/Cut；不删除已有功能。

---

## 2. 三层结构

```text
Ds/Cut（--cut）  硬件：启动、中断、MMIO、上下文切换
    ⊂
Ds Base（--app） 稳定核心：77 关键字，标签 ds-base-v1
    ⊂
Ds+（--plus）    软件：Unicode、硬件令牌、区域内存、x86-64 子集
```

| 层 | 命令 | 状态 | 用途 |
|---|---|---|---|
| Ds Base | `--app` | 🔒 `ds-base-v1` | 应用/系统核心语义 |
| Ds+ | `--plus` | 🔓 不冻结 | 软件方向扩展 |
| Ds/Cut | `--cut` | 🔓 不冻结 | 裸机/硬件方向 |

**只加不减**：扩展不能删除 Base 关键字/语义，也不能反向修改 Base。

---

## 3. 三种写法

同一 AST，三种表面语法，token 成本不同。

### 3.1 经典写法

```ds
fn fib(n) {
    if n < 2 {
        return n
    }
    return fib(n - 1) + fib(n - 2)
}

for i in 0..10 {
    println(fib(i))
}
```

### 3.2 0.1c 精简写法

```ds
fn fib(n) = if n < 2 { n } else { fib(n - 1) + fib(n - 2) }
for i in 0..10 { p(fib(i)) }
```

### 3.3 Flow 写法

```ds
\fib(n) = if n < 2 { n } else { fib(n-1) + fib(n-2) }
for i in 0..10 { p(fib(i)) }
.
```

Flow 的特征：

- `\` 定义
- 并置调用
- `.` 结束块
- 不属于主流编译语言语法家族

---

## 4. 语言核心

### 4.1 词法与关键字

- **77 个硬关键字**，11 类：类型/值、控制流、函数、内存、错误、并发、OOP、模式、元编程、模块、裸机。
- 标识符：Base 仅 ASCII；Unicode/emoji 属 Ds+ / Android 扩展。
- 注释 4 种；字面量 9 种；运算符 26 个。
- 机器可读表：`spec/keywords.json`。

### 4.2 类型

基础类型：

```text
i8 i16 i32 i64 i128
u8 u16 u32 u64 u128
isize usize
f32 f64
bool str bytes unit never
```

复合类型：数组 `[T; N]`、元组、结构 `struct`、类 `class`、trait、opt/res、指针 `ptr[T]` / `*T`。

**B1 语义（Base 冻结）**：

- 类型化存储/参数/返回做范围检查；
- 溢出 panic，不静默截断；
- `as` 位级截断：`300 as u8 == 44`；
- 默认整数字面量 `i32`；
- 混合宽度必须显式 `as`；
- Cut 保留硬件 wrap。

### 4.3 内存五选一

```ds
let a = 42                       # 栈
let p = alloc(1024, 8)           # 手动 alloc/free
let r = rc(Box(1))               # 引用计数
let s = arc(Box(2))              # 原子引用计数
let g = gc(Box(3))               # GC
let q = ptr[u8](0x1000)          # 地址指针
```

规则：

- 每个值的生命期策略写在代码里；
- 确定性析构；
- 顶层 `try` 不得吞掉错误；
- `ref/ptr/raw` 有明确权限边界。

### 4.4 错误分层

- `opt[T]`：可缺失
- `res[T, E]`：可恢复错误
- `try/catch`：边界捕获
- `err`：错误值
- 顶层 `try` 若未处理会显式报错，不静默

### 4.5 并发

- `spawn` / `go` / `thread`
- `chan` / `send` / `recv`
- `mutex` / `wait`
- 结构化并发：作用域结束前回收子任务

### 4.6 元编程

- `comptime`
- `macro`
- `typeinfo`
- `attr`
- 编译期执行与类型反射，但必须可检查

### 4.7 unsafe 与硬件

```ds
@unsafe {
    let p = ptr[u8](0x1000)
    *p = 1
}
```

- `@unsafe` 是显式边界；
- Base 普通代码不允许静态地址解引用；
- Cut 负责真实硬件语义。

---

## 5. Ds/Cut：16 个冻结 token

Cut 不是“另一个 C”，而是 16 个 token 的裸机子语言：

| # | token | 语义 |
|---|---|---|
| 1 | `let` | 栈绑定 |
| 2 | `fn` | 平面函数，无重载/泛型/虚表 |
| 3 | `if` | 条件分支 |
| 4 | `else` | 否定分支 |
| 5 | `while` | 条件循环 |
| 6 | `for` | `for i in start..end` 计数循环 |
| 7 | `return` | 函数返回 |
| 8 | `u8` | 8 位无符号 |
| 9 | `u16` | 16 位无符号 |
| 10 | `u32` | 32 位无符号 |
| 11 | `i32` | 32 位有符号 |
| 12 | `bool` | 1 字节布尔，无隐式真值 |
| 13 | `*` | `*T` 指针；禁止指针算术 |
| 14 | `@static` | 地址符号；`*NAME` 读写固定地址 |
| 15 | `@asm` | 内联汇编/纯汇编函数 |
| 16 | `@irq` | 中断函数 + 向量表 |

Cut 规则：

- 禁止指针算术：`p+1` 直接编译错误；
- 地址只能来自 `@static` 或硬件调用；
- 溢出默认 wrap（硬件语义）；
- `u8/u16/u32/i32/bool` 是 prelude 类型，不是硬关键字。

---

## 6. 延伸项目

### 6.1 Ds+（软件方向）

分支 `ds-plus`，严格超集，新增 16 个 `@` 令牌：

- 硬件 12：`@asm @inb @outb @inw @outw @inl @outl @rdmsr @wrmsr @rdcr @wrcr @mmio`
- 区域 4：`@stack @static @raw @mmap`

能力：

- Unicode / emoji 标识符扩展
- 区域内存
- 硬件令牌
- x86-64 子集后端
- 61 项测试（截至当前）

状态：**不冻结**；P4 后端仍无字符串/GC/异常/并发/类/宏的完整代码生成。

### 6.2 Ds/Cut（硬件方向）

- Thumb 后端 + 启动/向量表/上下文切换
- AArch64 纯 `@asm` 启动参考
- UF2 生成（RP2350）
- 与 Base 兼容测试
- 23 项 Cut 测试（截至当前）

状态：**不冻结**；真实硬件验证仍有限。

### 6.3 dspm（包管理）

- 包 = GitHub 仓库
- 版本 = git tag
- 无中心服务器
- lock 记录 tag + commit + tarball hash
- 不执行包内脚本
- C 驱动原生 `use` 解析

### 6.4 DsOS（操作系统）

```text
Cut 启动/向量/上下文切换
    ↓
Ds+ 内核：PMM/VMM/调度/中断/syscall/驱动
    ↓
Ds 用户态：shell/用户程序
```

目标板：

- RP2350 / Pico 2：Thumb、无 MMU、UF2
- Zero 2 W：AArch64、kernel8

当前状态：

- 架构文档 + 启动/切换骨架
- Phase 1 源码：Multiboot、长模式、UART、alive/tick/echo/stats 设计
- **未经 QEMU 实跑验证**
- 没有完整内核/文件系统/网络/用户态
- 模块接口只预埋空实现

### 6.5 DSOSS（DsOS 标准）

- DsOS Standard Specification
- Boot/Kernel/Driver/User ABI
- manifest + conformance 检查器
- 实现可替换，标准负责可验证

### 6.6 Android 编译器

- 离线编辑器/编译器
- emoji/Unicode 标识符扩展
- Ds+ 虚拟硬件语法预览
- 96 项测试（v0.3.8）

### 6.7 AI 学习包

- `ai/LANGUAGE_CARD.md`：一页纸
- `ai/DS_AI_CARD.txt`：可直接粘贴
- `ai/llms-full.txt`：全量上下文
- `llms.txt`：检索入口
- `datasets/`：SFT、语料、评测
- `ai/system_prompt.txt`：系统提示词

---

## 7. 当前实现状态（必须按真话使用）

| 项目 | 状态 |
|---|---|
| Base 语法/词法 | ✅ 冻结 `ds-base-v1` |
| Base 整数 checked | ✅ 类型化存储/参数/返回检查 |
| Base ASCII 标识符 | ✅ 冻结 |
| Base AddrSymbol | ✅ `*@static` 必须 `@unsafe`/Cut |
| Python 驱动 | ✅ 216 项 |
| C 驱动 | ✅ 对拍 + 12 项严格性 |
| Ds+ | 🔓 61 项，未冻结 |
| Cut | 🔓 23 项，未冻结 |
| Android | ✅ 96 项，v0.3.8 |
| DsOS Phase 1 | ⚠️ 源码/镜像存在，未 QEMU 实跑 |
| 模块加载 | ❌ 空接口 |
| GUI | ❌ 未开始 |

---

## 8. AI 使用规则

### 应该做

- 生成代码前先确认目标层：Base / Ds+ / Cut。
- Base 只用 `--app` 语义；不要使用 `@raw/@mmap/@inb`。
- Cut 只用 16 token；不要用 Base 的 class/match/gc。
- 显式写 `as`；不要依赖隐式宽度转换。
- 错误用 `res/opt`，不要用异常控制流。
- 不假设未文档化 API 存在；先查规范/语言卡。
- 生成后跑 `dscc --check` / 对应测试。

### 不应该做

- 不要发明新关键字/新 `@` token。
- 不要把 Ds 说成“已兼容 Linux/POSIX”。
- 不要把 Android 虚拟硬件说成真实裸机验证。
- 不要声称 DsOS 已完整启动/已冻结。
- 不要用 `void*`、指针算术、裸 null。

---

## 9. 最小代码示例

### Base

```ds
fn fib(n) = if n < 2 { n } else { fib(n - 1) + fib(n - 2) }

fn main() {
    for i in 0..10 { p(fib(i)) }
}
```

### Ds/Cut

```ds
@static UART: *u32 = 0x10000000

fn putc(c: u8) {
    *UART = c
}

@irq fn tick() {
    *UART = 65
}
```

### Ds+ 硬件

```ds
@unsafe fn kernel() {
    @outb(0x3F8, 65)
    let key = @inb(0x60)
    @asm volatile("cli")
}
```

---

## 10. 路线图

| 阶段 | 目标 |
|---|---|
| P0 | Base 冻结 ✅ |
| P1 | Ds+ 语言完整度 |
| P2 | 真实后端 + C ABI |
| P3 | 标准库 + 工具链 + 包生态 |
| P4 | DsOS / 嵌入式实机 |
| P5 | 自举 + 生产采用 |
| P6 | 图形界面 / POSIX 子集（远期） |

“和 Linux 一样完整”属于 P5–P6，不是当前版本承诺。

---

## 11. 术语表

| 术语 | 含义 |
|---|---|
| Base | 77 关键字稳定核心 |
| Ds+ | 软件扩展超集 |
| Cut | 16 token 裸机子语言 |
| DSOSS | DsOS 标准 |
| dspm | GitHub 包管理器 |
| AddrSymbol | `@static` 地址符号 |
| checked | 类型边界检查，溢出报错 |
| wrap | 硬件宽度回绕 |

---

## 12. 入口链接

- 仓库：<https://github.com/yzxcrush/ds>
- 语言卡：`ai/LANGUAGE_CARD.md`
- 规范：`spec/DS-v0.1.md`
- Ds+：`docs/DS-PLUS.md`
- Cut：`spec/DS-CUT.md`
- DsOS：`docs/DSOS.md`
- DSOSS：`spec/DSOSS.md`
- Android：<https://github.com/yzxcrush/ds-compiler>
- 基础版发布：<https://github.com/yzxcrush/ds/releases/tag/ds-base-v1>

> 本文档是“可验证事实 + 明确边界”的介绍，不是营销材料。  
> 任何超出本文档状态的承诺，都应视为未实现。
