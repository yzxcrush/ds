# Ds 地基工程规则（Foundation First）

> 原则：**先地基，后高楼。**
> Ds Base 未通过语义冻结门槛前，不向 Ds+ / Ds/Cut 增加新能力，也不把 base 的未定义行为带进扩展层。

## 1. “地基牢固”的可验证定义

不承诺“零 bug”（任何语言都无法证明），而是承诺以下 5 条：

| 编号 | 地基条件 | 当前 |
|---|---|---|
| D1 | 77 关键字/语法表面冻结，不再新增 | ✅ 已冻结候选 |
| D2 | 语义核心有正式规范，不依赖实现巧合 | ❌ 待补 integer/AddrSymbol |
| D3 | Python/C/Android 三端对同一合法/非法程序结论一致 | ⚠️ 已修 7 类，仍有余项 |
| D4 | 无已知 critical/high blocker | ❌ B1/B2/B3 |
| D5 | Ds+ / Cut 通过 base conformance 才能扩展 | ⏳ 未启动扩展 |

**结论：Base 已完成完整冻结（`ds-base-v1`）；Cut wrap / Ds+ 扩展保持不冻结。**

## 2. 扩展准入规则（硬规则）

```text
Base 已验证部分已冻结（partial-freeze）
    ↓
Ds+ / Ds/Cut 不冻结，可继续独立演进
但必须继承 base 修复，并通过 base conformance
    ↓
base 未验证的 B1/B2/B3 继续修，仍不发布 ds-core-v1
```

任何扩展 PR 必须满足：

1. 不改 base 语义；
2. base conformance 全绿；
3. 扩展层只新增、不覆盖 base 行为；
4. 新增能力在扩展层有自己的版本号；
5. 不允许用扩展层“绕过”base 的未定义行为。

## 3. 地基施工顺序

### P0 语义核心（必须先做）

1. **B1 固定宽度整数**
   - 明确 `u8/u16/u32/i32/...` 的宽度、符号、溢出策略；
   - base 是 checked 还是 wrap，必须写死；
   - 三端一致；
   - 边界测试：0、max、max+1、min-1、负数、除零、移位。

2. **B3 AddrSymbol**
   - Cut `@static` 变成 AST/IR 的地址符号；
   - base `static` 是存储，二者不再共用 `let`；
   - 指针解引用只允许在 `@unsafe`/Cut 层；
   - 运行期语义可检查（不允许“能 --check 但运行报错”）。

3. **B2 Unicode 策略**
   - 决策：base 允许 Unicode 标识符，或明确 Android-only 扩展；
   - 若允许：Python/C/Android 同步；
   - 若不允许：Android 编辑器加提示，OS/内核禁用。

### P1 地基验收

- 三端差分测试：同一表达式/程序/错误码；
- 负面测试：类型、宽度、数组、if、return、@ 层；
- conformance 报告入库；
- `python3 tools/freeze_check.py --require-semantic-freeze` 通过；
- 打 `ds-core-v1`。

### P2 才允许扩展

- Ds+：软件方向（GC/类/并发/元编程）；
- Ds/Cut：硬件方向（启动/中断/MMIO/裸机）；
- 两者都必须通过 base conformance。

## 4. 当前不该做的事

- ❌ 现在给 Ds+ 加新关键字/新语义
- ❌ 现在给 Cut 加新硬件原语
- ❌ 现在宣传“base 无 bug”
- ❌ 现在把 Android 虚拟 Ds+ 当成内核验证环境

## 5. 当前证据

- 已修 7 类跨端冲突（见 `docs/AUDIT-v0.1.md`）
- Python 197 项、Android 89 项、C 对拍 + 8 项严格性全绿
- 但 B1/B2/B3 仍未解决
- 冻结状态：`spec/freeze.json` → `semantics_frozen: false`

## 6. 下一步

**只做 B1**：整数宽度与溢出语义。  
B1 完成并通过三端边界测试后，才进入 B3，之后 B2，最后 `ds-core-v1`。

> 在此之前，Ds+ 和 Ds/Cut 保持现状；不扩展，是对未来 DsOS 最负责的做法。
