# Batch 5 — 错误 / 并发 / 元编程 / ABI（冒烟）

## 已修

| 用例 | 原行为 | 修复 |
|---|---|---|
| 顶层 `let v = try f()` 且 `f` 返回 `err` | `internal error: TryPropagate(...)` | 顶层无 res 函数可传播，明确报 runtime error |
| `try/catch panic` | 正常 | 保持 |
| `assert` | 正常 | 保持 |
| `chan/send/recv` | 正常 | 保持 |
| `comptime/sizeof/typeinfo` | 正常 | 保持 |

## 驱动覆盖差异

| 能力 | Python | C | Android |
|---|---|---|---|
| `res/opt/try/catch` | ✅ | ❌ 核心子集 | ❌ |
| `spawn/go/thread/chan` | 部分 | ❌ | ❌ |
| `comptime/macro/typeinfo` | 部分 | ❌ | ❌ |
| `extern/ABI` | ✅ | ❌ | ❌ |

这些不是“语言语义 bug”，而是 C/Android 驱动尚未实现对应子系统。  
在 base 语义冻结前，不能把“Python 能跑”当成三端一致。

## 仍未完成

- `opt` 与 `try` 的组合语义：规范只规定 `try` 对 `res` 传播；`opt` 需要单独 `if some/none`，当前 `try opt` 明确报错，属于语义边界，不是 bug。
- 并发/元编程的跨端 conformance 尚未建立。
- 错误对象/ABI 的布局未定。

## 结论

Batch 5：**部分冻结**。已修的顶层 try 有回归；其余能力仍受 C/Android 子集限制，不能整体冻结。
