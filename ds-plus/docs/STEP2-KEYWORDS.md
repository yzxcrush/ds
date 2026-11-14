# Step 2 — Ds+ 新增关键字清单（12 硬件 + 4 区域标注）

> 分支：`ds-plus` ｜ 版本：Ds+ v0.1.0 ↔ Ds v0.1.0 ｜ base 77 关键字未改动
> 机器可读注册表：`ds-core/plus.keywords.json`
> base stub 守卫：`ds-plus/tools/keyword_guard.py`

## 0. 计数口径（必须先说清楚）

- **12 个硬件关键字**（决策 7）：`@asm`、6 个端口 IO、2 个 MSR、`@mmio`、2 个控制寄存器。
- **4 个内存区域标注**（决策 8）：`@stack`、`@static`、`@raw`、`@mmap`。
- 合计 **16 个新 @ 令牌**。

为什么不是「总数严格 12」：4 区域 + 完整 8/16/32 位端口 IO + MSR + CR + MMIO + `@asm` 的并集是 16；若压到 12，必须砍掉 6 个方向中的至少 4 个（例如去掉 32 位端口 IO 和 CR），会直接削弱内核能力。因此采用 **12 硬件 + 4 区域标注** 的口径：硬件关键字满足「约 10–12」，区域是决策 8 的独立令牌。

若你后续要求严格 12 总数，最小损失方案是：删 `@rdcr/@wrcr`（用 `@asm` 表达）与 `@inl/@outl`（32 位端口 IO 退化为两次 16 位或 `@asm`），得 10 硬件 + 4 区域 = 14，仍大于 12；进一步删 `@mmio` 与 `@inw/@outw` 才能到 12。**本步按 12+4 执行。**

## 1. 硬件关键字（12 个，全部 `@` 前缀）

| 名称 | 类别 | 语义 | PYX 原草图对应 | 编译行为 / 降级 | base 中的 stub 报错 |
|---|---|---|---|---|---|
| @asm | 汇编 | 内联汇编语句/表达式：把模板与操作数下发给目标后端；volatile 禁止重排与删除；操作数约束沿用 C/LLVM 约定。 | asm / ASM Volatile（一等公民） | IR::InlineAsm { template, inputs, outputs, clobbers, volatile } -> 目标汇编/LLVM inline asm | E_DS_PLUS_ASM：用 Ds 的 asm 语句（需放在 @unsafe 块内）；Ds+ 的 @asm 额外支持操作数/约束/clobber/volatile。 |
| @inb | 端口 IO | 从 x86 I/O 端口读 1 字节；等价 in al, dx。 | inb（8 位端口读） | IR::Intrinsic{ name: "port_in", width: 8, port } -> x86 `in` 指令 | E_DS_PLUS_INB：用 Ds 的 asm 写 `in al, dx`（需 @unsafe），或 extern C 封装。 |
| @outb | 端口 IO | 向 x86 I/O 端口写 1 字节；等价 out dx, al。 | outb（8 位端口写） | IR::Intrinsic{ name: "port_out", width: 8, port, value } | E_DS_PLUS_OUTB：用 Ds 的 asm 写 `out dx, al`（需 @unsafe），或 extern C 封装。 |
| @inw | 端口 IO | 从 x86 I/O 端口读 2 字节；等价 in ax, dx。 | inw（16 位端口读） | IR::Intrinsic{ name: "port_in", width: 16, port } | E_DS_PLUS_INW：用 Ds 的 asm 写 16 位 in（需 @unsafe）。 |
| @outw | 端口 IO | 向 x86 I/O 端口写 2 字节；等价 out dx, ax。 | outw（16 位端口写） | IR::Intrinsic{ name: "port_out", width: 16, port, value } | E_DS_PLUS_OUTW：用 Ds 的 asm 写 16 位 out（需 @unsafe）。 |
| @inl | 端口 IO | 从 x86 I/O 端口读 4 字节；等价 in eax, dx。 | inl（32 位端口读） | IR::Intrinsic{ name: "port_in", width: 32, port } | E_DS_PLUS_INL：用 Ds 的 asm 写 32 位 in（需 @unsafe）。 |
| @outl | 端口 IO | 向 x86 I/O 端口写 4 字节；等价 out dx, eax。 | outl（32 位端口写） | IR::Intrinsic{ name: "port_out", width: 32, port, value } | E_DS_PLUS_OUTL：用 Ds 的 asm 写 32 位 out（需 @unsafe）。 |
| @rdmsr | 系统寄存器 | 读模型特定寄存器（MSR），返回 64 位值；等价 rdmsr，特权级。 | rdmsr | IR::Intrinsic{ name: "msr_read", msr } | E_DS_PLUS_RDMSR：用 Ds 的 asm 写 rdmsr（需 @unsafe）。 |
| @wrmsr | 系统寄存器 | 写模型特定寄存器（MSR）；等价 wrmsr，特权级。 | wrmsr | IR::Intrinsic{ name: "msr_write", msr, value } | E_DS_PLUS_WRMSR：用 Ds 的 asm 写 wrmsr（需 @unsafe）。 |
| @mmio | MMIO | 返回带 volatile 语义的 MMIO 指针；每次读写都不得被优化掉/合并；可用于任意目标。 | @mmio（内存映射 IO） | IR::Intrinsic{ name: "mmio", addr, T } -> 生成 volatile load/store | E_DS_PLUS_MMIO：用 Ds 的 `volatile ptr[T]`（配合 @at/裸地址）表达。 |
| @rdcr | 系统寄存器 | 读控制寄存器；cr 必须是编译期常量；特权级。 | CR0/CR2/CR3/CR4 读取 | IR::Intrinsic{ name: "cr_read", cr } | E_DS_PLUS_RDCR：用 Ds 的 asm 写 mov crN（需 @unsafe）。 |
| @wrcr | 系统寄存器 | 写控制寄存器；cr 必须是编译期常量；特权级。 | CR0/CR2/CR3/CR4 写入 | IR::Intrinsic{ name: "cr_write", cr, value } | E_DS_PLUS_WRCR：用 Ds 的 asm 写 mov crN（需 @unsafe）。 |

## 2. 内存区域标注（4 个）

| 名称 | 语义 | PYX 原草图对应 | 编译行为 / 降级 | base 中的 stub 报错 |
|---|---|---|---|---|
| @stack | 显式栈放置：变量分配在当前栈帧，零运行时开销；默认局部变量已如此，显式标注用于可读性与自文档。 | @stack | IR::Alloc { region: Stack } | E_DS_PLUS_STACK：去掉 @stack 即可：Ds 局部变量默认在栈上。 |
| @static | 静态区放置：分配在 .data/.bss，地址固定；初始化器必须是编译期常量；生命周期=程序。 | @static | IR::Global { region: Static, init } | E_DS_PLUS_STATIC：用模块级 var/let + @section(".data") 或 @at(addr) 近似，或用 Ds+。 |
| @raw | 裸内存区域：手动管理，无 GC、无隐藏分配；分配/释放走 Ds 的 alloc/free；bare profile 不提供内置分配器，链接时提供 ds_raw_alloc/ds_raw_free。 | @raw | IR::Alloc { region: Raw, allocator: "user" } | E_DS_PLUS_RAW：用 Ds 的 raw 指针 + alloc/free 手动管理（无区域保证）。 |
| @mmap | 页映射区域：页对齐、按页管理；映射函数由 OS 或用户代码提供（bare 下由内核实现）；未经映射访问是 UB。 | @mmap | IR::Alloc { region: Map, hook: "map_page" } | E_DS_PLUS_MMAP：调用 extern C 的 mmap/map_page（需目标 OS 或用户代码）。 |

## 3. `@` 双角色消歧规则（决策 ②A）

Ds 的 `@` 是属性前缀；Ds+ 的 `@` 令牌必须**上下文识别**，否则破坏严格超集：

1. 词法层：`@` + 标识符产生 `AT_NAME` 候选，不直接定为关键字。
2. 语法层按上下文重分类：
   - 硬件：`AT_NAME` 后接 `(`、`{`，或 `volatile` 后接 `(` → Ds+ 硬件关键字；
   - 区域：`AT_NAME` 后接 `let` / `var` / `fn` / `type` / `const` / 另一个 `@` → Ds+ 区域标注；
   - 其他情况（出现在 item 前、类型前、函数前的属性位置）→ 按 Ds 属性解析。
3. 属性名空间中 `raw/asm/stack/...` 不设为保留；因此形如 `@raw fn f()` 的 Ds 属性代码仍按属性解析（可编译），满足 100% 超集。

守卫工具实现了同样的上下文过滤（`--all` 可关闭过滤做调试）。

## 4. Profile 语义（锁定决策 ①A 的落地）

| profile | 开关 | base 语义 | Ds+ 新增能力 | GC / 运行时 |
|---|---|---|---|---|
| `compat` | 默认（继承 Ds） | 100% 保留：app/GC/异常/反射/OOP/三档写法 | 允许使用区域标注（`@stack/@static/@raw/@mmap`）与 `@mmio` | 保留 Ds 运行时与 GC |
| `bare` | `--bare --gc none --rt none` | Ds 的 bare 子集语义 | 全部 12 硬件关键字 + 4 区域；输出 raw/ELF/bare image | **无 GC、无语言运行时** |

- 严格超集校验永远在 `compat` 下跑 Ds 全量测试；`bare` 只用于 Ds+ 裸机交付。
- `@asm/@inb/.../@rdcr` 仅 `bare`；`@mmio` 与 4 区域在两种 profile 都可用（区域在 compat 下映射到普通栈/静态/手动内存）。

## 5. 三档写法示例（同一 AST）

经典：

```ds
@stack var s: i32 = 42
@static var g: u64 = 0x1000
@raw var dma: ptr[u8] = alloc(4096)
@mmap var page: ptr[u8] = map_page(0xC0000000, 4096)

fn kernel() {
    @outb(0x20, 0x20)
    let key = @inb(0x60)
    @asm volatile("cli")
}
```

0.1c：

```ds
@stack s = 42
@static g = 0x1000
@outb(0x20, 0x20)
p @inb(0x60)
```

Flow：

```dsf
\init
    @static g = 0
    @outb(0x20, 0x20)
    p @inb(0x60)
.
```

三档写法只影响表面语法；`@` 令牌的语义、降级、错误码完全一致。

## 6. 编译行为与错误码

| 错误码 | 触发条件 | 行为 |
|---|---|---|
| `E_DS_PLUS_*`（各关键字独立子码，见 §1/§2） | base 编译器遇到注册表令牌 | 拒绝编译并提示 base 替代写法 |
| `E_DS_PLUS_PROFILE` | `bare` 限制的硬件令牌出现在 `compat` | 提示改用 `--bare` 或 Ds `asm` |
| `E_DS_PLUS_TARGET` | 端口 IO/MSR/CR 用在非 x86 目标 | 提示目标不支持 |
| `E_DS_PLUS_UNSAFE` | 需要 `@unsafe` 的令牌出现在安全上下文 | 提示包 `@unsafe`（`@asm/@inb/.../@raw/@mmap`） |
| `E_DS_PLUS_CONST` | `@rdcr/@wrcr` 的 `cr` 不是编译期常量、`@static` 初始化器非常量 | 拒绝 |
| `E_DS_PLUS_ALIGN` | `@mmap` 地址/长度未页对齐 | 拒绝（可配置页大小） |

## 7. 明确不采纳的 PYX 关键字

`struct`、`union`、`enum`、`alias`、`function`、`zero`、`@trusted`（决策 ⑥）：

- `struct/alias` 用 Ds `type`；`union` 用 `@repr(C)+type+comptime`；`enum` 用 `type`+常量；`zero` 用 `0`；
- `@trusted` 与 Ds 的 `@unsafe` 显式边界冲突，不引入；
- 并发原语 `atomic/lock/futex` 不占本轮名额（决策 ④A，0.2 再议）。

## 8. 代码与文档同步产物

| 文件 | 作用 |
|---|---|
| `ds-core/plus.keywords.json` | 16 个令牌的机器可读注册表（registry） |
| `ds-core/README.md` | ds-core 共享职责与约束 |
| `ds-plus/tools/keyword_guard.py` | base 编译器用的 stub 守卫（上下文过滤 / `--all` / `--json`） |
| `ds-plus/tests/test_step2_keywords.py` | 注册表 + 守卫测试 |
| `ds-plus/examples/plus_keywords.ds` | 触发全部 16 个 stub 的示例 |

运行：

```bash
python3 -m unittest ds-plus.tests.test_step2_keywords -v
python3 ds-plus/tools/keyword_guard.py ds-plus/examples/plus_keywords.ds
```

## 9. 下一步（Step 3）

`ds-core` 共享模块拆分：关键字表、ABI 常量、IR 节点、诊断码、三档 AST 的公共定义；base 与 plus 各自保留的实现边界；为 Step 4 超集校验准备 harness。
