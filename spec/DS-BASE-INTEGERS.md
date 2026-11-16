# Ds Base 整数语义（B1，v1.0-frozen）

> 状态：**Base 已冻结**。Cut 的硬件 wrap 语义不在本文；Ds+ 默认继承 base。

## 1. 模型

Base 的 `u8/u16/u32/i8/i16/i32/u64/i64/isize/usize` 是**带范围的类型化存储**：

- 每个值在运行期是数学整数；
- 整数的宽度/符号在**绑定点**生效：`let/var`、赋值、函数实参、函数返回值、顶层绑定；
- 超出目标类型范围 → **panic**（checked），不静默截断；
- 显式 `as` 是位级转换：`300 as u8 == 44`（截断，不 panic）；
- 未标注整数字面量默认 `i32`；
- 混合宽度必须显式 `as`（checker 已强制）。

例：

```ds
var x: u8 = 255
x = x + 1        # runtime error: 256 不在 [0,255]

var y: u8 = 300 as u8
p(y)             # 44
```

## 2. 与 Cut 的分工

| 层 | 语义 |
|---|---|
| Base | 类型化存储 checked；算术表达式本身按数学整数求值，绑定边界检查 |
| Ds+ | 继承 base；不额外定义 wrap |
| Cut | 按目标宽度 **wrap**；硬件寄存器/内存语义 |

Base 不承诺“每条整数指令按 u8 宽度回绕”；它承诺的是**任何写入类型化位置的值都不会静默溢出**。Cut 才承诺硬件 wrap。

## 3. 已知边界

- `p(u8_value + 1)` 的中间表达式是数学整数；结果只有在写回类型化位置/返回/传参时才检查。
- 数组元素的类型化检查尚未覆盖（后续 base 版本）。
- Cut 后端/真实机器码的 wrap 测试属于 Cut conformance。

## 4. Conformance

- `tests/test_b1_integers.py`
- `c/test_strict.sh` 的 `b1_overflow.ds`
- `ds-android/tests/node_test.js` 的 `b1-*`
- 边界：0/max/max+1/min/min-1、参数、返回、`as`。

## 5. 冻结

- 标签：`ds-base-v1`
- Base 的已验证语义冻结；新增能力只能进 Ds+ / Cut。
- 不删除任何已有语法/功能。
