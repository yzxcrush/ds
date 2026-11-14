# Step 7（P3）— IR 与 ABI 指纹

> 代码：`ds-plus/dsplus/ir.py`；测试：`test_step7_p3_ir_abi.py`（6 项）。

## IR

- `module_ir(prog)`：AST → 去行列的规范化 JSON（`ir` 字段 = 节点类型）。
- plus 节点映射：
  - `Intrinsic` → `{"ir":"Intrinsic","name","token","width","args","type"}`
  - `InlineAsm` → `{"ir":"InlineAsm","template","volatile","inputs"}`
  - `RegionAnnotated` → `{"ir":"Region","region","node"}`
- `ir_hash(prog)`：对规范化 IR 做 SHA-256；**base 源码经 Ds / Ds+ 前端得到同一 hash**（S14/S17）。
- 位置信息不进入 IR，保证跨文件/跨写法稳定。

## ABI 指纹

`abi_fingerprint(target, layout)` 输出：
- 目标三元组与 ABI（sysv/aapcs64/eabi/ilp32/wasm）；
- 默认布局 `repr(Ds)`、C 布局 `repr(C)`、bare 外部 ABI = C；
- 指针宽度（32/64）与基础类型 size/align。

P3 超集结论：Ds+ 不改变 base 默认布局；C ABI 只经 `@repr(C)`/`@abi("C")` 显式开启；ABI 指纹与 Ds 一致（S17）。

## 限制

- IR 是**规范化 AST**，尚未做 SSA/控制流图/优化。
- 结构体布局计算尚未纳入指纹（当前覆盖基础类型/指针/目标）。
