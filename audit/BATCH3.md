# Batch 3 — 控制流 / 函数 / 作用域 / 求值顺序

差分脚本：`audit/batch3_control.py`（Python vs C；Android 用 Node 回归覆盖）。

## 已确认并修复

| 问题 | 影响 | 修复 |
|---|---|---|
| Python 不支持 `let x = loop { break 42 }` | 规范明确 `loop` 是表达式，Python 却只当语句 | 新增 `LoopExpr` AST/解析/求值 |
| C 的 `let` 会覆盖父作用域同名变量 | 函数内 `let x = 2` 改写了全局 `x`；违反词法作用域 | `env_def` 只查当前作用域，允许正确遮蔽 |

## 验证通过（Python/C 输出一致）

- 嵌套 `return`、循环内 `return`
- 嵌套 `break` / `continue`
- `loop` 表达式与 `break value`
- 短路 `&&` / `||`（副作用不执行）
- 函数实参/管道求值顺序：左→右
- 默认参数在调用时求值
- `if` 尾表达式
- 变量遮蔽
- `while false`

## 剩余差异（驱动子集，不是语言 bug）

- `for` 变量离开循环后未定义：两端都报未定义，只是错误文案不同。
- C 不支持函数类型/闭包语法：C 是核心子集，显式报错。

## 结论

Batch 3 冻结：Python/C/Android 的控制流、作用域、求值顺序已知用例一致。
