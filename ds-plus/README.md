# Ds+ 分支（重型版）

> 状态：**P1 前端已实现**（S14/S15 通过）；P2 语义/P3 ABI 与机器码后端待实现
> 版本绑定：Ds v0.x.x ↔ Ds+ v0.x.x
> 关系：Ds+ 是 Ds 的**严格超集**，不是独立语言；Ds 代码粘贴到 Ds+ 必须 100% 编译通过。

## 锁定决策（不可变更）

1. 双分支：Ds（基础版）/ Ds+（重型版）
2. Ds+ 是 Ds 的严格超集
3. 共享 `ds-core`：关键字表、ABI、IR 定义
4. 版本号同步：Ds v0.x.x ↔ Ds+ v0.x.x
5. 命名类比 C / C++
6. Ds 现有 **77 关键字冻结**
7. Ds+ 新增硬件关键字使用 `@` 前缀（`@raw` / `@asm` / `@inb` / `@outb` / `@rdmsr` 等）
8. Ds+ 解锁四区域内存：`@stack` / `@static` / `@raw` / `@mmap`
9. Ds+ 无 GC 模式，输出纯二进制 / ELF / 裸机镜像
10. 三档写法（经典 / 0.1c / Flow）共享同一 AST，行为逐字节一致，Ds+ 继承不变
11. 不省 token；人可以看不懂，AI 必须懂

## 目录

- `docs/STEP1-DIFF-MATRIX.md` — PYX→Ds+ 差异矩阵、机器翻译修正、裁决项
- `docs/STEP2-KEYWORDS.md` — 12 个硬件关键字 + 4 个区域标注（语义/PYX 对应/编译行为/base stub）
- `docs/STEP3-DS-CORE.md` — ds-core 共享模块归属与变更规则
- `docs/STEP4-SUPERSET.md` — S1–S15 超集校验规则、CI 门禁、P0–P3 证明阶段
- `docs/STEP5-FRONTEND-P1.md` — P1 前端设计、支持形式、错误码与限制
- 代码：`../ds-core/`（keywords/ABI/IR/diagnostics/version）、`tools/keyword_guard.py`、`tools/superset_check.py`
- 测试：`tests/test_step2_keywords.py`（10）、`test_step3_core.py`（7）、`test_step4_superset.py`（2）、`test_step5_frontend.py`（9）
- CI：`.github/workflows/ds-plus-check.yml`（base 单测 + C 对拍 + 契约 + 超集校验 + AI 包）

## 与 base 分支的关系

- `main`：Ds（base，冻结 77 关键字）
- `ds-plus`：Ds+ 设计与实现（本分支）
- 本分支只新增 `ds-plus/` 与后续 `ds-core/` 等目录；**不修改** `main` 上的 Ds 规范与关键字表。
