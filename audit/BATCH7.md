# Batch 7 — B1/B2/B3 收尾（部分）

## B2 base 侧：冻结

- 决策：Base 只允许 ASCII 标识符；emoji/Unicode 属 Ds+/Android 扩展。
- Python/C 对 `变量`、`🌱` 均报错。
- Android 仍保留 emoji 扩展（不属于 base）。
- 结论：**B2 base 侧冻结**；Ds+ 的 Unicode 扩展另立版本。

## B3 base 侧：基本语义

- 新增 `AddrSymbol`：`@static` 不再用普通 `Ptr` 模拟。
- `p(UART)` 输出整数地址。
- `*UART` 在普通 base 检查时报错，必须在 `@unsafe` 或 Cut 中。
- `@unsafe { p(*UART) }` 通过。
- Python base 运行期地址读写为安全模拟（读 0，写 no-op）。
- C 运行期仍不支持指针：按“难校验部分下沉 Cut”处理；C 的 `--check` 通过，运行 `*` 显式报错。
- Cut 负责真实 `.equ`/MMIO codegen。

状态：**B3 base 语法/检查冻结；C 运行期与真实 MMIO 归 Cut，未整体冻结。**

## B1：未完成

- 仍未实现固定宽度 checked 整数；`u8 255+1` 仍是 256。
- 按 D1：Base/Ds+ checked，Cut wrap；Cut 侧 wrap 已有硬件 codegen 基础，Base checked 仍需 typed IR。

## 当前动作

- B2 base 侧、B3 base 检查侧可视为冻结子项。
- B1 仍是唯一阻止 `ds-core-v1` 的 critical blocker。
- Ds+/Cut 不冻结；同步 base 修复后继续独立演进。
