# Ds/Cut 裸机子语言规范（v0.1）

> **定位**：Cut 是 Ds 三层架构的**最底层裸机子语言**，用于启动代码、异常向量、最底层驱动。
> **铁律**：`Ds/Cut ⊂ Ds ⊂ Ds+`；Cut 代码必须能在 `--app` / `--plus` 下 100% 编译通过。
> **独立语义锚点**：无隐式任何东西；每条指令/生命周期/调用目标编译期可知；硬件即地址。

## 0. 规格冲突与修正（先读）

本任务原文有 4 处与铁律/事实冲突，本规范按「不违反铁律」修正：

| # | 原文 | 冲突 | 修正 |
|---|---|---|---|
| C1 | 标题「15 个关键字」，正文列到 16 个（含 `@irq`） | 数量自相矛盾 | 冻结 **16 个 token**：12 个标识符关键字 + `*` + `@static/@asm/@irq` 三个属性形式；若要严格 15，则删 `@irq`（不推荐） |
| C2 | 关键字写作 `如果/对于/返回` | Ds base 使用 `if/for/return`；中文关键字会让 Cut ⊄ Ds | **规范语法用英文** `if/else/while/for/return`；中文只是文档别名，不作为词法 |
| C3 | `@static/@asm/@irq` 是 Cut 关键字 | 它们是 Ds+ 的 `@` 令牌；直接作为新关键字会破坏 Ds 77 冻结 | 定义为 Ds 既有 `static/asm/irq` 的**属性拼写**，不是新关键字；Ds `--app` 必须接受这三种属性形式 |
| C4 | 「Zero 2 W + ARM Thumb + .uf2」 | Zero 2 W 是 **Cortex-A53 / AArch64**，不是 Thumb/Cortex-M，也不走 .uf2 | 双后端：**RP2350（Cortex-M33）→ Thumb/.uf2**；**Zero 2 W（Cortex-A53）→ AArch64/kernel8.img**。启动/链接脚本分别提供 |
| C5 | 「编译器内置汇编器或静态链接 LLVM-MC」 | 原型阶段自建完整汇编器成本过高 | v0.1 原型输出 `.s`，可选用系统 `clang --target=thumbv8m...` 汇编为 `.o`；自举汇编器列入路线图 |
| C6 | Zero 2 W 需要 64 位地址/寄存器 | Cut 冻结类型只有 u8/u16/u32/i32；u64 会破坏 16 token | **Cut v0.1 只覆盖 32 位 MCU（RP2350）**；Zero 2 W 的启动/上下文切换用**纯 @asm**参考，AArch64 的类型化后端放 v0.2（或把 u64 作为 Ds+ 类型，而非 Cut 关键字） |

## 1. 三层模式与层错误

| 模式 | 允许 | 拒绝 |
|---|---|---|
| `--cut` | Cut 16 token；Cut 子集语法 | 任何 Ds 关键字（`class/trait/match/gc/...`）→ `E_CUT_LAYER_DS`；任何 Ds+ `@raw/@mmap/@inb...` → `E_CUT_LAYER_PLUS` |
| `--app`（默认） | Cut 全部 + Ds base 77 关键字 | Ds+ `@` 令牌 → `E_CUT_LAYER_PLUS`（提示 `--plus`） |
| `--plus` | Cut + Ds + Ds+ | 无层错误；后端未实现的能力报 `E_CUT_UNSUPPORTED` |

错误格式（必须精确到行/列）：

```text
file.ds:12:5: error[E_CUT_LAYER_DS]: `class` 属于 Ds 层，请使用 --app 模式
file.ds:20:1: error[E_CUT_LAYER_PLUS]: `@raw` 属于 Ds+ 层，请使用 --plus 模式
```

## 2. 16 个冻结 token（语义 + 防换皮理由）

> 12 个标识符 + `*` + 3 个属性形式。`u8/u16/u32/i32/bool` 在 Ds 中是 prelude 类型，不是硬关键字。

| # | token | 一句话语义 | 防换皮理由（Ds 独有） |
|---|---|---|---|
| 1 | `let` | 栈上绑定，类型可推导或显式；无 move/copy 语义 | 值只有“栈槽 + 生命周期”，没有移动语义/析构歧义；汇编级就是一个 sp 偏移 |
| 2 | `fn` | 平面函数：无重载、无泛型、无虚表 | 每次调用目标在编译期唯一确定，生成直接 `bl`，不存在动态派发/单态化爆炸 |
| 3 | `if` | 条件分支，可跟 `else` | 条件必须是 `bool`；无隐式真值转换，分支在 IR 上就是比较+跳转 |
| 4 | `else` | if 的否定分支 | 与 if 同一跳转结构，不引入表达式二义性 |
| 5 | `while` | 条件循环 | 无迭代器/闭包/隐式分配；循环变量与退出条件显式，栈帧大小编译期固定 |
| 6 | `for` | 计数循环 `for i in start..end` | 只接受整数区间，编译为“初始化/比较/递增/跳转”四段，不生成迭代器对象 |
| 7 | `return` | 函数返回 | 单入口单出口可静态分析；无析构/异常展开，返回即 `bx lr` |
| 8 | `u8` | 8 位无符号整数 | 位宽=寄存器/内存宽度，无隐式提升；溢出行为显式（默认 wrap） |
| 9 | `u16` | 16 位无符号整数 | 同上；硬件寄存器映射按位宽直接选中，不做装箱 |
| 10 | `u32` | 32 位无符号整数 | 同上；地址/寄存器默认宽度，指针运算被禁止 |
| 11 | `i32` | 32 位有符号整数 | 仍无隐式转换；与 u32 混用必须显式 `as`（Cut v0.1 仅允许同宽/拓宽） |
| 12 | `bool` | 1 字节布尔（true/false） | 无“非零即真”；汇编层就是 0/1 比较结果 |
| 13 | `*` | 受限解引用/指针类型 `*T`：只能解引用已知地址/`@static`/`*T` 参数；**禁止指针算术** | 不是 C 指针：`p+1`、`p++` 直接编译错误；地址只能来自 `@static` 或硬件调用，编译器可枚举所有访存 |
| 14 | `@static` | `@static NAME: T = 地址常量`：把符号绑定到固定物理地址；`*NAME` 读写该地址；汇编层 `.equ NAME, ADDR` | 不是 C `static` 存储类：它产生的是**地址符号**；没有全局变量初始化/段放置的隐式行为 |
| 15 | `@asm` | 内联汇编块/纯汇编函数/文件级汇编；原样写入 `.s` | 一等公民，不是逃生舱；DSL 的调度/启动/上下文切换都直接写，不依赖外部 `.S` |
| 16 | `@irq` | 标记中断函数：自动现场保护 + 生成向量表条目 | 中断语义是语言级：编译器知道这是异常入口，生成 `push {lr}`/`pop {pc}`，不是普通函数加属性 |

### 2.1 标识符约束

Cut 代码里的用户标识符**不能与 Ds 关键字重名**（因为 Cut ⊂ Ds，Ds 会把它当关键字）。
例如上下文切换参数不能叫 `new`（Ds 的 `new` 关键字），请用 `next`；`in` 只作为 `for ... in` 的结构词。

### 2.2 中文别名（仅文档，不是词法）

`如果→if`、`否则→else`、`循环→while`、`对于→for`、`返回→return`、`函数→fn`。
**代码里必须写英文**，否则 Cut ⊄ Ds。

## 3. 语法

```ebnf
program      = { global_asm | static_decl | irq_attr? fn_decl } ;
global_asm   = "@asm" string [ ";" ] ;
static_decl  = "@static" IDENT ":" type "=" const_expr ";" ;
irq_attr     = "@irq" [ "(" INT ")" ] ;
fn_decl      = irq_attr? "fn" IDENT "(" [ param { "," param } ] ")"
               [ "->" type ] block ;
param        = IDENT ":" type ;
type         = "u8" | "u16" | "u32" | "i32" | "bool" | "*" type ;
block        = "{" { stmt } "}" ;
stmt         = let | assign | if | while | for | return | asm_stmt | expr_stmt ;
let          = "let" IDENT [ ":" type ] "=" expr ";" ;
assign       = lvalue "=" expr ";" ;
lvalue       = IDENT | "*" expr ;
if           = "if" expr block [ "else" ( block | if ) ] ;
while        = "while" expr block ;
for          = "for" IDENT "in" expr ".." expr block ;
return       = "return" [ expr ] ";" ;
asm_stmt     = "@asm" string asm_args? [ ";" ] ;
asm_args     = [ "," "in" "(" REG ")" expr ]* [ "," "out" "(" REG ")" IDENT ]* ;
expr         = logic ;  (* + - * / % & | ^ << >> == != < > <= >= && || ! ~ 一元 - 调用 解引用 *)
```

**禁止**（编译器必须拒绝，错误码 `E_CUT_FORBIDDEN`）：
堆分配、浮点、struct/class/trait/enum/match、闭包/lambda、异常/panic、字符串表达式（仅 @asm 字符串）、模块系统、并发、指针算术、任何 Ds/Ds+ 关键字、浮点字面量、全局可变变量（`@static` 是地址符号，不是存储）。

## 4. @asm 完整语法（一等公民）

### 4.1 语句级
```ds
@asm "adds r0, r0, #1"
@asm("add r0, r0, r1", in("r0") a, in("r1") b, out("r0") r)
@asm "loop:"; @asm "adds r0, r0, #1"; @asm "b loop"
```
- 字符串原样写入 `.s`；编译器**不校验汇编语法**，由汇编器报错。
- 分号分隔多条；标签 `name:` 可定义/跳转。
- `in("rN") expr`：先把 expr 求值到指定寄存器；`out("rN") var`：汇编后把该寄存器写回变量。
- 可引用 Ds/Cut 符号：函数名、`@static` 地址、全局汇编标签。

### 4.2 纯汇编函数
整个函数体只有 `@asm` 语句时，**不生成 prologue/epilogue**，原样输出：

```ds
fn context_switch(old: *u32, new: *u32) {
    @asm "push {r4-r11, lr}"
    @asm "str sp, [r0]"
    @asm "ldr sp, [r1]"
    @asm "pop {r4-r11, pc}"
}
```

### 4.3 文件级汇编
函数外的 `@asm` 直接写入输出（用于启动/向量表/段声明）：

```ds
@asm ".section .vector_table,\"a\",%progbits"
@asm ".word 0x20040000"
@asm ".word reset_handler"
```

### 4.4 中断函数
```ds
@irq fn timer_irq() {
    *TICKS = *TICKS + 1;
}
```
编译器生成：`push {lr}` ... `pop {pc}`；在 `.vector_table` 中按声明顺序生成 `.word timer_irq`（可用 `--irq-vector-base` 指定编号；v0.2 支持显式 `@irq(n)`）。

## 5. 编译管线 / ABI / 栈帧

```text
源码 → 词法 → 语法 → AST → 层检查 → 语义检查 → 线性 IR → ARM Thumb 汇编 → clang/llvm-mc → .o → ld.lld → ELF → objcopy/UF2
```

- **层检查先于语法**：错误的层关键字必须报 `E_CUT_LAYER_*`，而不是“未知语法”。
- **栈帧表**：每个局部变量编译期分配固定 `sp` 偏移；函数帧大小 = 槽数×4 向上对齐 8。
- **AAPCS**：前 4 参数 r0–r3，返回值 r0；调用者保存 r0–r3/r12，被调者保存 r4–r11。
- **中断**：`push {lr}` / `pop {pc}`；不生成普通函数返回。
- **输出**：`.s` 文本；`--emit obj` 用 `clang --target=thumbv8m.main-none-eabi -c`（RP2350）或 `thumbv6m-none-eabi`（RP2040）。

## 6. Thumb 指令映射表（原型子集）

| Cut 构造 | Thumb 汇编 |
|---|---|
| `let x = N` | `movs r0, #N` / `ldr r0, =N`；`str r0, [sp,#off]` |
| `let p: *T = @static 地址` | `ldr r0, =ADDR`；存指针值 |
| `*p` | `ldr r0, [r0]` |
| `*p = e` | 求值 e → r0；求值 p → r1；`str r0, [r1]` |
| `a + b` | 求 a→r0，push；求 b→r0；pop r1；`adds r0, r1, r0` |
| `a - b` | `subs r0, r1, r0` |
| `a * b` | `muls r0, r1, r0` |
| `& \| ^ << >>` | `ands/ orrs/ eors/ lsls/ asrs` |
| `== != < > <= >=` | `cmp r1, r0`；`ite` 或 `movs r0,#0; ...`（原型用 `ite` 组合） |
| `&& \|\|` | 分支短路或 `ands/orrs`（原型非短路） |
| `if` | `cmp`/`beq`/`bne` + 标签 |
| `while` | 标签 + 条件跳转 + `b` |
| `for i in a..b` | i=a；`cmp i,b`；`bhs end`；body；`adds i,#1`；`b loop` |
| 调用 `f(a,b)` | 参数入 r0–r3；`bl f` |
| `@static N: *T = A` | `.equ N, A`；取地址 `ldr r0, =N` |
| `@irq fn` | `push {lr}` ... `pop {pc}`；`.word fn` |
| 纯 `@asm` 函数 | 原样输出，无 prologue/epilogue |
| `@asm "..."` | 原样输出（`;` 分隔多行） |

## 7. 防换皮验证（必须通过）

1. **指针算术**：`p + 1` / `p++` 必须 `E_CUT_PTR_ARITH`；C 指针可直接算术 → Cut 额外禁止，语义不同。
2. **无隐式转换**：`u8 + u32` 必须显式 `as`（Cut v0.1 仅允许 same-width 或 widen）；C 会隐式提升。
3. **无隐式分配/调用**：没有堆、没有虚表、没有闭包；每个 `bl` 目标编译期唯一。
4. **`@static` 不是 C static**：它只产生地址符号；不分配存储、不初始化段。
5. **`@asm` 不是逃生舱**：语言级启动/调度/上下文切换都用它，且可引用语言符号。
6. **C/Rust 翻译测试**：把一段 Cut 逐行翻译到 C/Rust，若 C/Rust 需要额外机制（禁止指针算术的检查、地址符号 `.equ`、纯汇编函数无 prologue、@irq 向量生成）才能等价 → Cut 不是换皮。

## 8. DsOS 中的层映射

- **Ring -1（Cut）**：启动、异常向量、GPIO/UART/定时器最底层。
- **Ring 0（Ds+）**：PMM/VMM/调度/中断分发/syscall/驱动框架。
- **Ring 3（Ds）**：用户程序，无 `@` 硬件关键字。
- 编译器层强制：`--cut` 只能 Ring -1；`--app` 不能写 `@raw/@mmap/@inb`；`--plus` 才可写内核。

## 9. 实现状态（v0.1 原型）

- `cut/cutc.py`：词法/语法/层检查/语义检查/Thumb 与 AArch64（纯 @asm 函数）代码生成；支持 Cut 16 token、@asm、@static、@irq、纯汇编函数、if/while/for。
- `cut/uf2.py`：RP2350 UF2 生成（family 0xE48BFF56）；`cut/test_build.sh` 实际完成 Thumb/AArch64 汇编、链接与 UF2。
- `dsoss/`：DSOSS 标准 manifest + 一致性检查器。
- 测试：`cut/tests/`（18 项）、`dsoss/tests/`；示例：`cut/examples/`。
- 未实现：AArch64 普通函数代码生成（仅纯 @asm）、寄存器分配/优化、UF2 之外的镜像格式、实机运行。
