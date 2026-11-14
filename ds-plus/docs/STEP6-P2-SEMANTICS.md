# Step 6（P2）— 语义检查与 compat 模拟

> 代码：`ds-plus/dsplus/checker.py`、`compat.py`；测试：`test_step6_p2_semantics.py`（12 项）。

## 检查项

| 错误码 | 规则 |
|---|---|
| `E_DS_PLUS_PROFILE` | 硬件令牌（@asm/端口/MSR/CR）只允许 `--bare`；@mmio 与区域两种 profile 可用 |
| `E_DS_PLUS_UNSAFE` | @asm/@inb.../@rdmsr.../@raw/@mmap 必须在 `@unsafe` 函数或 `@unsafe {}` 块中 |
| `E_DS_PLUS_CONST` | @rdcr/@wrcr 的 cr ∈ {0,2,3,4} 且为常量；@static 初始化器必须常量 |
| `E_DS_PLUS_ALIGN` | @mmap 字面量地址必须 4096 对齐（@mmio 不要求） |

## compat 模拟

`run_compat()` 把 plus AST 降级为 base AST：
- 区域标注剥离；
- 硬件 intrinsic → `__dsplus_*` 原生函数（端口字典 / MSR 字典 / CR 字典 / MMIO 数组）；
- `@asm` → base `AsmExpr`（no-op）。

从而在 **不写新解释器** 的前提下，对 Ds+ 程序做语义执行/差分测试。示例：

```ds
@unsafe fn main() {
    @outb(0x3F8, 65)
    p(@inb(0x3F8))     # 65
    @wrmsr(0x10, 42)
    p(@rdmsr(0x10))    # 42
    @wrcr(3, 0x1000)
    p(@rdcr(3))        # 4096
    let u = @mmio(0x3F8, u8)
    u[0] = 7
    p(u[0])            # 7
}
```

## 已知限制

- 模拟不覆盖中断/页表/DMA；硬件语义仅用于差分测试。
- 类型检查是**规则级**（profile/unsafe/常量/对齐/参数个数），完整类型推断与借用检查未做。
- `@asm` 输出/clobber 约束未实现（只有输入 `%0..%N`）。
