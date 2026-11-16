# Ds v0.1 语言审计报告（2026-11）

> 范围：`spec/` 规范、Python 驱动 `dsv01/`、C 驱动 `c/ds.c`、Android JS 内核 `ds-android`、Cut/Ds+ 层声明。
> 方法：规范对照 + 三端差分执行 + 非法程序回归 + Emoji/Ds+ 压力测试。
> 结论：**修掉 7 类可复现冲突；仍有 5 项会在 OS/内核阶段变成隐患，已列为 blocker。**

## 1. 已修复（有回归测试）

| # | 问题 | 影响 | 修复 |
|---|---|---|---|
| F1 | JS 的 `& \| ^ << >> ~` 默认 32 位，Python/C 是 64 位/无限精度 | `1 << 31` 在 Android 得 `-2147483648`，Python/C 得 `2147483648`；位掩码/寄存器代码跨端不一致 | JS 改用 BigInt 做 64 位语义；补 `~0 == -1`、`1<<31` 回归 |
| F2 | C 驱动不识别 base 的 `@irq` / `@static var` / `@asm` | 同一段 Ds/Cut 代码 Python 能跑、C 报 “无法解析 @” | C 解析器增加 `parse_at_item` / `parse_static_binding` / `@asm` no-op |
| F3 | Python 不识别 Cut 的 `@asm`、`@static NAME: T = ADDR` | `Cut ⊂ Ds` 的声明在 base 驱动上不成立 | 增加 `NopItem` 与 `parse_static_binding`；base 可解析 Cut 属性形式 |
| F4 | 数组字面量允许 `[1, "x"]` | 违反规范“元素类型必须一致、无隐式提升”；后续 ABI/布局不可预测 | Python/C/JS 检查器统一拒绝异构数组 |
| F5 | `if` 表达式分支类型可不同：`if c { 1 } else { "s" }` | 表达式类型不确定，编译期无法定布局/宽度 | 三端检查器拒绝不一致分支（整数字面量可按目标整数类型归一） |
| F6 | C 的移位量没有边界检查 | 与 Python/JS 的 0..63 规则不一致；C 未定义行为 | C 运行期对 `<0` 或 `>=64` 报错 |
| F7 | Cut 的 `@static/@asm/@irq` 在 base 层没有落点 | “Cut 代码在 Ds --app 100% 编译”只在 cutc 成立 | base Python/C 接受属性拼写；Cut 片段可 `--check` |

回归命令：

```bash
python3 -m unittest discover -s tests          # 193+ 项
sh c/run_tests.sh && sh c/test_strict.sh      # 对拍 + 8 项非法
cd ds-android && node tests/node_test.js      # 89 项
```

## 2. 未修复的 blocker（写 OS 前必须解决）

### B1. 整数宽度/溢出没有运行期语义（最高优先级）

规范说字面量默认 `i32`，类型有 `u8/u16/u32/i32/...`，但：

- Python 驱动是任意精度整数；
- C 驱动内部统一 `int64_t`；
- Android JS 是 IEEE-754 `Number`；
- 三端都**不按声明宽度回绕/饱和**，也不检查溢出。

例子：`let x: u8 = 255; x = x + 1` 在三种驱动里都得到 `256`，而不是 `u8` 的 `0`。

**风险**：寄存器宽度、页表项、CRC、协议字段、中断计数在 OS 里会悄悄越界；跨端结果不同。
**建议**：在 IR 层给每个值附宽度与 signedness；明确规定 `wrap`（默认）或 `checked`（`--overflow=panic`）；增加 `u8/u16/u32/i32` 边界测试。目前只能算“带类型标注的动态语言”，不是可依赖的固定宽度语言。

### B2. Unicode/emoji 标识符是 Android-only 扩展

- Android JS：允许 `let 🌱 = 1`、`let 🇨🇳 = 2`、ZWJ/肤色/变体选择符；
- Python/C/规范：标识符仍为 ASCII `[A-Za-z_][A-Za-z0-9_]*`；
- 因此同一份带 emoji 标识符的代码无法跨端编译。

**建议**：要么把 Unicode 标识符写进 base 规范并实现 Python/C（C 需 UTF-8 解码 + 类别表），要么明确它是 Android 编辑器扩展，OS/内核代码禁止使用。当前按后者处理，但需要在规范里标注，避免 AI 误以为 base 支持。

### B3. Cut `@static` 的“地址符号”与 Ds `static` 的“静态存储”语义不同

Cut 的 `@static UART0: u32 = 0x1000` 表示“绑定到物理地址的符号”；base Ds 的 `static` 是模块级存储。
目前 base Python/C 能**解析并通过 `--check`**，但运行期 `*UART0` 仍按普通整数解引用（Python 报错；C 行为未定义）。
**建议**：在 AST/IR 中引入明确的 `AddrSymbol` 类型，base 层只允许在 `@unsafe` 中解引用；Cut 层生成地址常量；不要用普通 `let` 模拟。

### B4. Android 的 Ds+ 是“虚拟硬件”，不是可执行裸机

- `@inb/@outb/@mmio/@mmap` 是进程内模拟；
- `@asm` 只解析、不执行机器码；
- `@irq` 不接真实中断向量；
- Android WebView 没有 MMIO/端口权限，这是平台边界，不是 bug。
**建议**：OS 的 Ds+ 代码必须由真正的 AArch64/Thumb 后端编译；Android 只能作为语法/逻辑预览，不能作为内核验证环境。

### B5. 值级数组重复 `[0; N]` 不存在

规范里的 `[T; N]` 是**类型**；值位置没有 `[0; N]` 展开语法。用户写 `let g = [0; 800]` 会报语法错误。
**建议**：明确写入规范“0.1 无值级重复字面量”，或增加 `[expr; count]` 并规定 count 必须是编译期常量；在加入前用 `zeros(n)` 辅助函数。

## 3. 其他观察（非 blocker）

- **Cut ⊂ Ds 的边界**已从“完全没实现”提升到“可解析/可 `--check`”，但 `@static` 运行语义仍未统一（见 B3）。
- **Ds+ 的 16 个 `@` 令牌**与 Cut 的 `@irq` 存在命名层重叠；目前靠“属性拼写”解释，建议在文档中给出一张唯一归属表。
- **`@asm` 参数约束**在 Android 只做跳过；不要用它验证寄存器分配。
- **执行步数上限** Android 50M、Python/C 无统一限制；这不是语言语义，但会导致“同一程序在 App 超限、终端能跑”。建议把资源限制做成显式 API/选项。
- **Map 迭代顺序**目前实现相关；OS 代码不要依赖。
- **`@static` 初始化器常量性**在 base 驱动未强制；Cut/Ds+ 应在检查器里强制常量。

## 4. 建议的下一步（按优先级）

1. 固定宽度语义 + 溢出策略（B1）——这是 OS 的地基。
2. 明确 Unicode 策略并同步 Python/C 或禁止（B2）。
3. 把 `AddrSymbol` 纳入 AST/IR，统一 Cut `@static` 与 base `static`（B3）。
4. 用真实后端（Thumb/AArch64）替换 Android 虚拟 Ds+ 做内核验证（B4）。
5. 增加跨驱动差分 fuzz：同一批表达式在 Python/C/JS 上比较结果与错误码。

> 本报告不是“语言已经安全”的证明；它只说明当前可复现的冲突已被缩到可管理范围。OS 阶段请以 B1–B3 为前置条件。
