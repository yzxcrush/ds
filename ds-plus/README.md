# Ds+ 分支（重型版）

> 状态：**Step 2 — Ds+ 新增关键字清单**（注册表 + base stub 守卫 + 测试已完成；编译器实现待 Step 3/4）
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
- 代码：`../ds-core/plus.keywords.json`、`tools/keyword_guard.py`、`tests/test_step2_keywords.py`
- 后续：Step 3 ds-core 拆分、Step 4 超集校验

## 与 base 分支的关系

- `main`：Ds（base，冻结 77 关键字）
- `ds-plus`：Ds+ 设计与实现（本分支）
- 本分支只新增 `ds-plus/` 与后续 `ds-core/` 等目录；**不修改** `main` 上的 Ds 规范与关键字表。
