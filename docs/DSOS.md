# DsOS 架构初稿（v0.1）

> **定位**：用 Ds+ 编写的实验性 OS 内核，验证 Ds+ 硬件关键字能否覆盖“启动 → 中断 → 调度 → 用户态”。
> **状态**：架构 + 启动/上下文切换/链接脚本骨架；内核主体（PMM/VMM/调度/syscall）为路线图。
> **不混 C**：内核 Ds+，启动/异常向量 Ds/Cut（@asm），用户程序 Ds。

## 0. 先修正两个硬件事实

| 任务原文 | 事实 | 本设计 |
|---|---|---|
| Zero 2 W（Cortex-A53）用 ARM Thumb + .uf2 | Zero 2 W 是 **AArch64**，由 GPU 固件加载 `kernel8.img` 到 `0x80000`，**不用 UF2** | Zero 2 W 走 **AArch64 后端 + ELF/kernel8.img** |
| RP2350 用 ARM Thumb + .uf2 | RP2350 是 Cortex-M33（ARMv8-M），Thumb-2 + UF2 正确 | RP2350 走 **Thumb 后端 + ELF → UF2** |

因此 DsOS 是**双 BSP/双后端**：`thumbv8m.main`（RP2350）与 `aarch64`（Zero 2 W）。
`cut/cutc.py` 当前只实现 Thumb；AArch64 后端是 v0.2 路线图（启动代码已给出参考实现）。

## 1. 三层权限映射

| Ring | 语言层 | 模式 | 写什么 |
|---|---|---|---|
| Ring -1 | Ds/Cut | `--cut` | 启动代码、异常向量、GPIO/UART/定时器最底层、上下文切换 |
| Ring 0 | Ds+ | `--plus` | PMM/VMM、调度、中断分发、syscall、驱动框架 |
| Ring 3 | Ds | `--app` | 用户程序；没有 `@` 硬件关键字 |

编译器强制：
- `--app` 不能写 `@raw/@mmap/@inb...` → `E_CUT_LAYER_PLUS`；
- `--cut` 不能写 Ds 关键字（`class/gc/match/...`）→ `E_CUT_LAYER_DS`；
- 内核代码不能悄悄跑在用户层（层检查先于语法）。

## 2. 目标板与内存地图

### Zero 2 W（BCM2710A1，Cortex-A53 ×4，512MB）

```text
0x00000000 - 0x00080000   固件/ATAGS 保留
0x00080000 - 0x00200000   内核镜像 + 异常向量 + .text/.rodata
0x00200000 - 0x00400000   页表（L1/L2/L3，@mmap）
0x00400000 - 0x08000000   内核堆（@raw 管理，约 124MB）
0x08000000 - 0x20000000   用户进程空间（每进程 16MB 起）
0x20000000 - 0x3F000000   外设寄存器（UART/GPIO/定时器/GIC）
```

### RP2350（Cortex-M33，264KB SRAM）

```text
0x10000000 - 0x10400000   XIP Flash（内核 .text/.rodata，向量表在 0x10000000）
0x20000000 - 0x20040000   SRAM（.data/.bss/栈/堆；最坏 256KB）
0x40000000+               APB 外设（UART/GPIO/TIMER）
0xE0000000+               Cortex-M 系统控制（VTOR/NVIC/SysTick）
```

UF2：`objcopy -O binary` → `uf2conv.py`（RP2350 的 family id 0xE48BFF56）。
Zero 2 W：`kernel8.img` 直接由固件加载，不用 UF2。

## 3. 启动流程

### RP2350（Thumb）
1. Boot ROM 从 Flash 0x10000000 取向量表；
2. 栈顶 = 0x20082000；`reset_handler`：
   - 设置 VTOR = 0x10000000；
   - 从 Flash 复制 `.data` 到 SRAM；
   - 清零 `.bss`；
   - 初始化 UART/时钟/定时器；
   - `bl main` → 调度器。
3. `@irq` 函数生成向量表条目；`@asm` 负责上下文切换。

### Zero 2 W（AArch64）
1. GPU 固件加载 `kernel8.img` 到 0x80000；
2. `_start`（EL2 或 EL1，MMU off）：
   - 设置栈到 0x00200000；
   - 清零 `.bss`；
   - 设置 `VBAR_EL1` 到异常向量；
   - 初始化 UART（0x3F201000）；
   - 初始化 GIC/定时器；
   - `bl kernel_main`。
3. 异常向量使用 16 项 AArch64 向量表；`@irq` 在 Ds+ 层绑定。

## 4. 调度与并发

- 每线程一个 `@stack` 标记的内核栈/用户栈（`@stack` 在 Ds+ 层）；
- 上下文切换用 `@asm` 纯汇编函数（见 `dsos/arch/`）；
- 时间片由定时器中断（`@irq`）触发；
- 线程间通信：ring buffer + 自旋锁（v0.1 单核；SMP 后加原子/内存屏障）。

```ds
# 内核伪代码（Ds+）
@irq fn timer_irq() {
    ticks = ticks + 1
    schedule()
}
```

## 5. syscall 接口

用户态 Ds：

```ds
sys_write(1, "hello", 5)
```

编译器按目标生成：
- RP2350：`svc #0`（SVC 异常），内核 SVC handler 分发；
- Zero 2 W：`svc #0`（AArch64），异常向量 `VBAR_EL1 + 0x400` 分发。

syscall 表（v0.1）：

| 号 | 名称 | 参数 | 返回 |
|---|---|---|---|
| 1 | `sys_write` | fd, ptr, len | 写入字节数 |
| 2 | `sys_exit` | code | 不返回 |
| 3 | `sys_yield` | - | 0 |
| 4 | `sys_alloc` | pages | 虚拟地址 |

用户态不能直接 `@raw/@mmap/@asm`；只能 `sys_*`。

## 6. 文件结构

```text
DS-OS/
├── cut/                     # Ds/Cut 编译器 + 启动代码
├── dsos/
│   ├── boot/
│   │   ├── rp2350_start.ds   # Thumb 启动/向量（可编译）
│   │   └── zero2w_start.ds   # AArch64 启动（参考，AArch64 后端待实现）
│   ├── arch/
│   │   ├── context_switch_thumb.ds
│   │   └── context_switch_aarch64.ds
│   ├── bsp/
│   │   ├── rp2350.ld
│   │   └── zero2w.ld
│   ├── kernel/                # Ds+ 内核（路线图）
│   │   ├── main.ds+
│   │   ├── mm/pmm.ds+  mm/vmm.ds+
│   │   ├── sched/sched.ds+
│   │   ├── irq/handler.ds+
│   │   ├── drivers/uart.ds+
│   │   └── syscall.ds+
│   └── ds.toml
├── spec/DS-CUT.md
└── docs/DSOS.md
```

## 7. Ds+ 关键字在 DsOS 的用法

| 关键字 | 用途 | 层 |
|---|---|---|
| `@asm` | 启动、上下文切换、SVC 入口 | Cut/Ds+ |
| `@static` | 固定地址符号（UART/GPIO/VTOR） | Cut/Ds+ |
| `@irq` | 中断/SVC 入口，生成向量表 | Cut/Ds+ |
| `@raw` | 物理页帧、DMA 缓冲 | Ds+ |
| `@mmap` | 页表映射 | Ds+ |
| `@stack` | 内核栈/用户栈指定地址 | Ds+ |
| `@entry` | `_start` / syscall 入口（路线图） | Ds+ |
| `@section` | 段放置（向量表 0x10000000） | Ds+ |
| `@volatile` | 设备寄存器读写不优化 | Ds+ |
| `@packed` | 页表项/描述符紧凑布局 | Ds+ |

> 注：`@static/@asm/@irq` 在 Ds/Cut 中是既有 `static/asm/irq` 的属性拼写，不新增关键字；
> `@raw/@mmap/...` 才是 Ds+ 新令牌。这样满足 Cut ⊂ Ds ⊂ Ds+。

## 8. 防换皮验证（DSOS 视角）

1. 启动代码没有 C 的 `crt0`/链接脚本约定：`@asm` 直接写向量表 + `.equ` 地址符号，C 需要额外汇编/链接脚本才能等价；
2. 上下文切换是纯 `@asm` 函数，无 prologue/epilogue，C 需要内联汇编或外部 `.S`；
3. 中断函数由 `@irq` 生成 `push {lr}`/`pop {pc}` 和向量表条目，C 需要 `__attribute__((interrupt))` + 启动文件；
4. 用户态没有 `@` 令牌，内核对 `@raw/@mmap` 的独占由编译器层强制，C 无语言级 Ring 隔离；
5. `@static` 不是 C static：它只绑定地址符号，不分配存储。

## 9. 路线图

- M0：Cut 编译器 Thumb 子集（本仓库 v0.1 原型） ✅
- M1：RP2350 启动 → 串口输出 → 死循环（`boot/rp2350` + UART）
- M2：PMM/VMM（Ds+ `@raw/@mmap`）→ 页表 → 用户态
- M3：@irq 定时器 + 上下文切换 + 轮转调度
- M4：syscall + 用户程序 + DsOS shell
- M5：Zero 2 W AArch64 后端 + 多核启动
- M6：移植到 Pico 2 / Zero 2 W 实机

## 10. 风险与未决

- AArch64 后端、UF2/family id、GPU 固件启动细节未实现；
- Ds+ 的 `@mmap/@raw/@stack/@entry/@section/@volatile/@packed` 在现有 Ds+ 原型中尚未全部落地（P0–P6 已实现 16 令牌，其中不含 @entry/@section/@volatile/@packed 的新拼写，需要 v0.2 扩展）；
- 中断现场保护/浮点/多核缓存一致性未做；
- 无 MMU 的 RP2350 与有 MMU 的 Zero 2 W 需要两套内存管理路径。
