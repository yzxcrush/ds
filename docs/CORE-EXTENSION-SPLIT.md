# Ds Core / Extension Split（决定记录，2026-11）

> 用户决定：D1–D11 全 A，按最优解执行。
> 原则：**只加不减**；Base 保持简单可验证；难校验语义下沉 Ds+ / Ds/Cut。

## 1. 三层职责

```text
Ds Base（--app）
  简单、可验证、安全默认
  ├─ Ds+（--plus，软件方向）
  │    吸收软件复杂度：Unicode/emoji 标识符、高级类型、GC、并发、元编程
  └─ Ds/Cut（--cut，硬件方向）
       吸收硬件复杂度：固定宽度 wrap、AddrSymbol、MMIO、启动/中断
```

**只加不减**：

- 不删除 base 的关键字/语法/已有功能；
- base 保留 `@static`、`*T`、emoji 的**语法兼容入口**（能解析/`--check`）；
- 真正的复杂语义由扩展层实现，base 不承担无法验证的行为；
- Cut ⊂ Ds ⊂ Ds+ 不变。

## 2. 锁定决定

| ID | 决定 | 结果 |
|---|---|---|
| D1 | 整数溢出 | Base/Ds+ **checked**；Cut **wrap** |
| D2 | Unicode | Base **ASCII only**；emoji/Unicode 属 Ds+ / Android 扩展 |
| D3 | `@static` | `UART` 是地址值；`*UART` 仅 `@unsafe`/Cut 允许 |
| D4 | `as` 窄化 | 位级截断/wrap；`300 as u8 == 44` |
| D5 | 常量溢出 | 编译期错误 |
| D6 | 指针类型 | Base 规范 `ptr[T]`；Cut `*T`；互为别名 |
| D7 | C `@static` | 模拟地址读写，不崩溃 |
| D8 | `[expr; N]` | 0.1 不支持；用 `zeros(n)` |
| D9 | Base 冻结 | 只冻结已验证部分；B1/B2/B3 前不发 `ds-core-v1` |
| D10 | Ds+/Cut | **不冻结**，独立演进，必须继承 base 修复 |
| D11 | Ds+ checker | 强制继承 base checker，`E_DS_BASE` |

## 3. 难校验语义下沉表

| 难点 | Base | 扩展层 |
|---|---|---|
| 固定宽度 wrap | 不实现 wrap；只做 checked 范围/溢出 | Cut 实现硬件 wrap；Ds+ 默认 checked |
| Unicode/emoji 标识符 | 拒绝非 ASCII | Ds+ 实现 Unicode；Android 保留扩展 |
| AddrSymbol/MMIO | 地址值 + `@unsafe` 模拟 | Cut 生成 `.equ`/真实地址；C 扩展模拟 |
| 并发/GC/元编程 | 不新增 base 语义 | Ds+ 独立实现 |
| 中断/启动/汇编 | 只保留 `@asm` 兼容解析 | Cut 真实 codegen |
| 硬件 ABI | 不承诺 | Cut/Ds+ 定义 profile |

**结果**：Base 的 conformance 只验证简单核心；扩展层的复杂度不阻塞 base 冻结，但扩展必须通过 base conformance。

## 4. B1/B2/B3 验收

### B1（checked 整数）

- Base/Ds+：`u8 255 + 1` → overflow panic；`300 as u8 == 44`。
- Cut：`u8 255 + 1` → 0（硬件 wrap）。
- 三端 + Cut 后端同一向量表。

### B2（ASCII base）

- Base Python/C/Cut：非 ASCII 标识符报错。
- Ds+ / Android：emoji 扩展；NFC/安全规则只在扩展定义。
- base 不引入 Unicode 规范化负担。

### B3（AddrSymbol）

- Base：`@static UART: *u32 = ADDR` 解析；`UART` 是地址值；`*UART` 仅 `@unsafe`。
- Cut：`@static` 生成 `.equ`；`@asm` 可引用。
- C：模拟地址读写；普通 base 不崩溃。
- `p(UART)` 统一输出整数地址。

## 5. 执行顺序

1. 写 B1/B2/B3 的 spec + conformance 失败用例。
2. 先实现 Python base（checked 整数、ASCII、AddrSymbol）。
3. 同步 C、Android、Cut。
4. Ds+ 继承 base checker + Unicode 扩展。
5. 三端 + Cut 跑同一 conformance。
6. 只有 B1–B3 全绿，才考虑 `ds-core-v1`。

> Ds+ / Ds/Cut 从现在起不冻结；但每次修改必须跑 base conformance。
