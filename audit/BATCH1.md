# Batch 1 — 词法 / 关键字 / 字面量 / 层边界

对 Python、C 两个终端驱动 + Android 内核做同一批用例；脚本：`audit/batch1_lexical.py`。

## 已确认并修复

| 用例 | 问题 | 修复 |
|---|---|---|
| `let if = 1` | Python 顶层 `let` 允许硬关键字作变量名；C 正确拒绝 | base 绑定名只接受 IDENT/RAW_IDENT；`fn new/drop` 例外 |
| `let _ = 1` | C 允许 `_` 作变量名；规范 §3.10 禁止 | C `parse_let` 拒绝 `_` |
| `p("\x41")` | C 字符串词法把 `\xNN` 多推进一步，误报“字符串含裸换行” | C 修正 `\x` 消耗长度 |
| `let a = 1\n + 2` | C 把换行前的 `+` 继续当二元运算；规范规定换行终止语句 | C `parse_postfix` 不再吞掉无后缀的换行 |
| `let x: u8 = -1` | Python/C/Android 都接受，因为负号不是字面量节点 | 三端做常量折叠 + 目标整数范围检查 |

## 确认不是语言 bug（驱动子集限制）

| 用例 | 说明 |
|---|---|
| `label:` / `goto` | C 驱动 v0.1 明确不支持；Python 参考实现支持。C 报清晰“不支持”，不是静默错编 |
| 中文/emoji 标识符 | base 规范仍是 ASCII；Android 是扩展，见 B2 |
| `p(“hello”)` | 全角引号不是 Ds 词法，报错正确 |
| `0...3` | 不是合法区间写法，报错正确 |

## 仍开放的 Batch 1 议题

- **Unicode 策略（B2）**：base 是否允许 Unicode 标识符，尚未决策。
- **NFC/NFD 与同形字**：如果未来允许 Unicode，必须定规范化与安全规则。
- **C 驱动 label/goto**：C 是核心子集，若要作为完整 base 对拍驱动，需要补齐。

## 结论

Batch 1 找到 5 个**真正的语言/词法 bug**，已全部修复并有回归。
C 的 label/goto 与换行差异已收敛；剩余 C 子集未实现项必须显式报错，不能静默。
