# Step 3 — ds-core 共享模块清单

> 目标：把「两边必须一致」的定义抽到 `ds-core`，把「各自实现」留在 base/plus。
> 规则：`ds-core` 不含分支特有实现；base 77 关键字与行为不变；版本同步。

## 1. 目录与归属

| 路径 | 归属 | 说明 | 谁可改 |
|---|---|---|---|
| `ds-core/plus.keywords.json` | **共享（plus 定义）** | Ds+ 16 个 @ 令牌的唯一事实源 | 只能新增 `@` 令牌；不改 base |
| `spec/keywords.json` | **共享（base 定义，现有）** | base 77 关键字唯一事实源（保持原位，不搬家） | 冻结，不改 |
| `ds-core/base.keywords.snapshot.json` | **共享（冻结快照）** | base 77 词表的只读快照，供 Step 4 校验 | 随 base 发版重新生成 |
| `ds-core/keywords.registry.json` | **生成物（共享）** | base + plus 合并注册表（93 项） | 只能由 `tools/build_registry.py` 生成 |
| `ds-core/tools/build_registry.py` | **共享工具** | 合并/校验注册表 | 双方共同评审 |
| `ds-core/version.json` | **共享** | 版本同步规则、三档写法、AST 共享约束 | 双方同步 bump |
| `ds-core/abi/abi.json` | **共享** | 默认布局、C ABI 选择器、目标三元组、plus 输出 | 改变 ABI 需双方评审 |
| `ds-core/ir/ir.schema.json` | **共享** | base IR 节点 + plus 增量节点（InlineAsm/Intrinsic/RegionAlloc...） | plus 只能**增量**加节点 |
| `ds-core/diagnostics/codes.json` | **共享** | 诊断码目录（stub/profile/target/unsafe/const/align/version） | 错误码只增不改 |
| `ds-core/README.md` | **共享文档** | 共享层职责与约束 | 双方共同维护 |
| `dsv01/` | base 专属 | Python 参考驱动（全量语义） | base 维护 |
| `c/` | base 专属 | C 参考驱动（核心子集） | base 维护 |
| `spec/DS-v0.1.md`、`DS-CONCISE.md`、`DS-FLOW.md` | base 专属 | base 规范（77 关键字/三档写法） | base 维护 |
| `ds-plus/`（编译器实现目录，待建） | plus 专属 | Ds+ 前端扩展、硬件降级、bare 后端 | plus 维护 |
| `ds-plus/tools/keyword_guard.py` | plus 专属（供 base 复用） | base 编译器的 stub 守卫 | plus 维护，base 调用 |
| `ds-plus/tests/test_step2_keywords.py`、`test_step3_core.py`、`test_step4_superset.py` | plus 专属 | Ds+ 契约测试 | plus 维护 |
| `ds-plus/examples/plus_keywords.ds` | plus 专属 | stub/语法示例 | plus 维护 |
| `tools/make_datasets.py`、`tools/build_ai_kit.py`、`datasets/`、`ai/` | **共享（AI 包）** | base 子集 + plus delta 数据；后续加 `ds_plus_*` | 双方评审 |

## 2. 变更规则

1. **base 冻结**：`spec/keywords.json` 的 77 词不可增删改；`ds-core/base.keywords.snapshot.json` 用于 Step 4 检测漂移。
2. **plus 只增 `@`**：`plus.keywords.json` 只能加/改 `@` 令牌；新增令牌必须同时更新：注册表、诊断码、AI 卡、Step 2 文档。
3. **生成物不入手改**：`keywords.registry.json` 由脚本生成；CI 检查 `--check` 一致性。
4. **IR 增量**：plus 节点只做增量；base 节点语义在 compat/bare 下保持一致。
5. **版本同步**：`version.json` 的 `version` 必须同时代表两分支；发布时一起 bump。
6. **ABI 保守**：默认 `repr(Ds)` 不变；C ABI 只经 `@repr(C)`/`@abi("C")` 显式开启。

## 3. 本步产物

- `ds-core/version.json`：0.1.0、surfaces=classic/concise/flow、ast=shared
- `ds-core/abi/abi.json`：7 目标、C ABI 选择器、plus 输出格式
- `ds-core/ir/ir.schema.json`：51 个 base 节点 + 6 个 plus 增量节点
- `ds-core/diagnostics/codes.json`：16 个 stub 子码 + 6 个公共 plus 码
- `ds-core/keywords.registry.json`：93 项（77 + 16）
- `ds-core/base.keywords.snapshot.json`：77 词冻结快照
- `ds-core/tools/build_registry.py`：生成/校验
- `ds-plus/tests/test_step3_core.py`：共享层契约测试

## 4. 下一步（Step 4）

超集校验规则与可执行检查器：S1–S13，CI 门禁；见 `STEP4-SUPERSET.md`。
