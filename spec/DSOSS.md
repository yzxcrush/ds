# DSOSS — DsOS Standard Specification（v0.1 初稿）

> **命名假设**：本文把 **DSOSS** 定义为 **DsOS Standard Specification**——不是又一个 OS 实现，
> 而是「任何声称兼容 DsOS 的内核」必须满足的标准/契约。若你原意是别的缩写，以你的定义为准。
> DsOS 是实现；DSOSS 是**标准**。实现可替换，标准负责可验证。

## 0. 为什么需要 DSOSS

DsOS 的内核会分叉（Zero 2 W / RP2350 / 未来板子）。如果只写一个实现：
- 没有“兼容 DsOS”的可验证含义；
- 驱动、syscall、启动协议会随实现漂移；
- 无法用测试证明“三层权限/ABI/中断契约”成立。

DSOSS 把 **启动协议、内核 ABI、驱动契约、用户态 ABI、工具链契约** 固化成版本化标准，
并用 `dsoss/check_conformance.py` 检查 manifest。

## 1. 一致性等级

| 等级 | 名称 | 要求 |
|---|---|---|
| C0 | Toolchain | Cut/Ds/Ds+ 编译器可用；层错误正确；产物可重现 |
| C1 | Boot | 通过板级启动协议，能把控制权交给内核并打印 boot banner |
| C2 | Kernel ABI | 实现 syscall 表、线程上下文、中断入口约定 |
| C3 | Driver | MMIO/IRQ 声明式绑定；ISR 不分配、不阻塞 |
| C4 | User ABI | Ds 用户程序可运行；无 `@` 令牌；syscall 返回约定 |

一个实现可声明 `conformance = ["C0","C1"]`；未实现的等级不得声明。

## 2. 板级 profile（v0.1 两个）

| profile | 架构 | 启动 | 镜像 | 指针 |
|---|---|---|---|---|
| `rp2350-m33` | Cortex-M33 / Thumb-2 | 向量表 + reset_handler | ELF → **UF2**（family 0xE48BFF56） | 32 |
| `zero2w-a53` | Cortex-A53 / AArch64 | GPU 固件加载到 0x80000，EL2→EL1 | ELF → **kernel8.img**（不是 UF2） | 64 |

## 3. Boot 契约

必须提供 manifest 字段：

```toml
[boot]
entry = "reset_handler"        # 或 _start
image_format = "uf2"           # rp2350: uf2；zero2w: kernel8
vector_base = 0x10000000       # rp2350；zero2w 用 vbar_el1
stack_top = 0x20082000
```

要求：
1. 入口前完成：栈设置、`.data` 复制、`.bss` 清零（或声明由固件完成）；
2. 向量表/异常向量地址必须与 `vector_base` 一致；
3. 启动后必须通过 `sys_write(1, "DsOS booting...\n", 18)` 输出（C1 验证）；
4. 不得依赖未在 manifest 声明的外部固件符号。

## 4. Kernel ABI

- 上下文切换：`context_switch(old_sp, new_sp)`；Thumb 保存 r4-r11/lr，AArch64 保存 x19-x30/d8-d15；
- 中断：Thumb `push {lr}`/`pop {pc}`，AArch64 用 EL1 向量；
- syscall：`svc #0`；号在 manifest `[[syscalls]]` 中声明，全局唯一；
- 指针宽度必须与 profile 一致（rp2350=32，zero2w=64）；
- 内核不得暴露 `@` 令牌给用户态（见 C4）。

v0.1 标准 syscall 表：

| 号 | 名称 | 参数 | 返回 |
|---|---|---|---|
| 1 | sys_write | fd, ptr, len | 写入字节数 |
| 2 | sys_exit | code | 不返回 |
| 3 | sys_yield | - | 0 |
| 4 | sys_alloc | pages | 虚拟地址或错误码 |

## 5. Driver 契约

- 设备通过 manifest `[[devices]]` 声明：`name`、`mmio_base`、`size`、`irq`；
- 驱动只能用 `@volatile`/`@mmap`（Ds+ 层）访问声明的区域；
- ISR 内禁止分配、禁止阻塞、禁止调用非 ISR-safe syscall；
- 每个设备必须有 `probe()`/`init()` 的成功/失败返回值。

## 6. User ABI

- 用户程序用 Ds（`--app`）编译，不能出现 `@` 硬件令牌；
- 只能通过 syscall 访问内核；返回约定：非负成功、负错误码；
- 栈由内核通过 `@stack` 分配；用户程序不得假设物理地址。

## 7. Toolchain 契约

```toml
[toolchain]
compiler = "cutc"
backend = "thumb"          # rp2350；zero2w=aarch64
cut_mode = "--cut"
reproducible = true
```

- 内核必须由 Cut/Ds+ 编译，不混 C；
- 启动/异常向量由 Cut `@asm` 写；
- 产物名/哈希写入 manifest `[artifact]`；
- 编译器必须支持 `--cut/--app/--plus` 的层错误（C0）。

## 8. Manifest（`dsoss.toml`）

```toml
[standard]
name = "DSOSS"
version = "0.1"

[board]
profile = "rp2350-m33"

[boot]
entry = "reset_handler"
image_format = "uf2"
vector_base = 0x10000000
stack_top = 0x20082000

[kernel]
arch = "thumbv8m.main"
pointer_bits = 32
page_size = 4096
syscall_max = 32

[toolchain]
compiler = "cutc"
backend = "thumb"
cut_mode = "--cut"
reproducible = true

[[syscalls]]
number = 1
name = "sys_write"
args = 3
```

## 9. 一致性验证

```bash
python3 dsoss/check_conformance.py dsoss/dsoss.toml
python3 dsoss/check_conformance.py dsoss/profiles/zero2w.toml
```

检查项：profile/arch/pointer_bits 一致；boot 格式匹配；syscall 号唯一且在范围内；toolchain 合法。
未通过时退出码 1。

## 10. 与 DsOS 的关系

- **DsOS**：参考实现（本仓库 `dsos/` 骨架；内核主体未实现）；
- **DSOSS**：标准；不绑定实现；
- 一个实现可以只通过 C0/C1；标准允许多个 profile 与未来扩展；
- 任何“DsOS 兼容”声明必须附 manifest + 通过检查器。

## 11. 未决/路线图

- C2–C4 的可执行 conformance suite（QEMU 两板）；
- SMP/内存屏障/缓存一致性条款；
- 安全启动/镜像签名；
- `@entry/@section/@volatile/@packed` 等 Ds+ 关键字落地后更新 Toolchain 契约；
- 若 DSOSS 原意不同，本文件重命名/改写。
