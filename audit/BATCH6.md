# Batch 6 — 三端 conformance 与 base 部分冻结

日期：2026-11-16

## 本轮验收命令

```bash
python3 tools/ds_keywords.py check --json spec/keywords.json
python3 -m unittest discover -s tests
sh c/run_tests.sh
sh c/test_strict.sh
PYTHONPATH=cut:. python3 -m unittest discover -s cut/tests
python3 tools/freeze_check.py
```

## 结果

| 检查 | 结果 |
|---|---|
| 77 关键字 | ✅ 77/77 |
| Python 参考驱动 | ✅ 206 项 |
| C 驱动对拍 | ✅ core/concise/functions/flow/control_scope |
| C 严格性 | ✅ 10 项 |
| Cut 编译器 | ✅ 21 项 |
| Cut → base `--check` | ✅ |
| AI 学习包 | ✅ llms-full + 3 数据集 |

## 冻结范围（本轮）

**冻结**：

- 77 关键字、语法表面（Batch 1）
- 词法/关键字/字面量/换行
- 控制流/作用域/求值顺序（Batch 3）
- 已验证子项：字面量范围、数组同构、if 分支、64 位位运算、移位边界、`*T` 指针类型、顶层 try 错误

**不冻结**：

- B1 固定宽度整数/溢出
- B2 Unicode/emoji 跨端策略
- B3 AddrSymbol（C 指针运行期）
- C/Android 的 res/opt/try/catch、并发、元编程、ABI
- Batch 2/4/5 整体

因此标签只能是 **base-partial-freeze**，不是 `ds-core-v1`。

## Ds+ / Cut

- **Ds+ 不冻结**：同步 base checker（`E_DS_BASE`）和 base 修复，继续独立演进。
- **Ds/Cut 不冻结**：同步 `*T`、`@irq(5) irq fn` 和 base 兼容测试，继续独立演进。
