# Ds 四条并行方向

> 结论：**不冲突，但不能无组织地同时铺开。**  
> 共享一条脊梁：dscc 后端 + ABI + 运行时 + conformance；四条支线各自交付，按里程碑汇合。

## 0. 共享脊梁（所有方向共用）

```text
dscc 前端/检查器
  → 类型化 IR
  → x86_64 / ARM / Thumb 后端
  → ABI / 运行时
  → conformance + 备份
```

禁止四条线各自复制一套编译器/ABI。

## A. DsOS 最小可运行系统

- 目标：QEMU/实机启动、串口 Shell、定时器、页分配、调度、syscall、模块加载
- 先做：Phase1 实跑 → `dsos-phase1-v1` → Shell
- 依赖脊梁：x86_64 后端、ABI、运行时

## B. Ds 通用编译器

- 目标：`dscc kernel.ds --emit multiboot`、struct/数组/字符串、C ABI、自举
- 先做：把 `build.py` 能力迁入 dscc
- 依赖脊梁：IR、后端、ABI

## C. Ds/Cut 嵌入式与硬件

- 目标：RP2350/Pico 2、UART/GPIO/定时器/中断、UF2、AArch64
- 先做：UART + 定时器 + 真实板验证
- 依赖脊梁：Thumb/AArch64 codegen、Cut conformance

## D. AI 原生与工具链

- 目标：AI 生成→检查→评测、LSP、Android IDE、dspm 生态
- 先做：稳定语法 + 评测集 + 一键验证
- 依赖脊梁：检查器、诊断、AI kit

## 汇合点

| 里程碑 | A | B | C | D |
|---|---|---|---|---|
| M1 | Phase1 实跑 | Multiboot 后端 | UART 实机 | 评测集 |
| M2 | Shell | struct/数组 | 定时器/中断 | LSP |
| M3 | 模块加载 | C ABI | UF2 | Android IDE |
| M4 | 调度/syscall | 自举 | AArch64 | 包生态 |

每个里程碑完成 → 触发 `tools/make_backup.py` 生成补充包。
