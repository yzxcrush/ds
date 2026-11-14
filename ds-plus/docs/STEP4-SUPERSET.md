# Step 4 — Ds+ 严格超集校验规则

> 目标：证明「Ds 代码粘贴到 Ds+ 必须 100% 编译通过」，并把证明变成可执行门禁。
> 工具：`ds-plus/tools/superset_check.py`（静态 + `--compile` 冒烟）。

## 1. 检查项

| 编号 | 规则 | 实现 | 失败处理 |
|---|---|---|---|
| **S1** | 版本同步：Ds v0.x.x ↔ Ds+ v0.x.x | 比较 `version.json` / plus registry / base spec | 阻断发布 |
| **S2** | base 77 关键字冻结（不增/不删/不改名） | 比对 `spec/keywords.json` 与 `base.keywords.snapshot.json` | 阻断合并 |
| **S3** | 合并注册表可重现 | `build_registry.py --check` | 阻断 CI |
| **S4** | plus 令牌全部 `@` 前缀，且与 base 词表不相交 | 注册表检查 | 阻断 |
| **S5** | 合并注册表计数 = 77 + N | 注册表检查 | 阻断 |
| **S6** | 三档写法（classic/concise/flow）共享 AST | `version.json` surfaces/ast | 阻断 |
| **S7** | ABI 默认 `repr(Ds)` 不变，C ABI 显式 | `abi.json` | 阻断 |
| **S8** | IR 只允许增量节点 | `ir.schema.json` | 阻断 |
| **S9** | 诊断码完整、唯一 | `codes.json` + registry | 阻断 |
| **S10** | base 编译器 stub 守卫：plus 令牌全部被识别；base 代码无告警 | `keyword_guard.py` | 阻断 |
| **S11** | AI 学习包 base 子集一致 | `make_datasets.py --check` + `build_ai_kit.py --check` | 阻断 |
| **S12** | base 三档示例完整 | 文件存在性 | 阻断 |
| **S13** | base 编译器可编译 base 三档示例 | `--compile` 冒烟 | 阻断 |
| **S14** | P1 前端：base AST 等价 + 16 令牌注入 | `dsplus.frontend` | 阻断 |
| **S15** | P1 前端：三档写法 plus AST 特征一致 | `dsplus.frontend` | 阻断 |

## 2. 运行

```bash
python3 ds-plus/tools/superset_check.py --json
python3 ds-plus/tools/superset_check.py --compile
python3 -m unittest discover -s ds-plus/tests -v
```

## 3. CI 门禁（`.github/workflows/ds-plus-check.yml`）

分支 `ds-plus` 上每次 push / PR 必须通过：

1. base 全量单测（158 项）与 C 对拍；
2. `ds-plus/tests` 全部契约测试；
3. `build_registry.py --check`；
4. `superset_check.py --compile`；
5. AI 学习包一致性。

## 4. 语义级超集的阶段目标

静态检查只能证明「注册表/契约」不破坏超集；完整证明还需要：

| 阶段 | 证明方式 | 当前状态 |
|---|---|---|
| P0 结构与关键字 | S1–S12 | ✅ 本步完成 |
| P1 语法超集 | base 全部 `.ds/.dsf` 同时送 base 与 Ds+（compat）前端，比较 token→AST 摘要 | ✅ **前端已实现**（S14/S15）；全量 corpus 比对待扩 |
| P2 语义超集 | 同一输入两实现执行结果逐字节比对（复用 `c/run_tests.sh` 模式） | 待 Ds+ 运行时/后端 |
| P3 ABI 超集 | base 程序在 Ds+ 下产物的 ABI 指纹与 base 一致 | 待机器码后端 |

**规则**：P1–P3 任一未完成，Ds+ 不得标记为「严格超集已验证」，只能标记「结构契约通过」。

## 5. 失败处理

- S1–S2：禁止合并/发布；修正 base 冻结或版本。
- S3–S9：修正注册表/IR/诊断源文件后重新生成。
- S10：修正上下文消歧守卫或 plus 语法（不得改 base 语义）。
- S11–S13：修正 base 资产或编译器冒烟。
