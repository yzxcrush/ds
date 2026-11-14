# Step 5（P1）— Ds+ 前端实现

> 状态：**P1 语法超集（前端）已实现**；语义（P2）与 ABI/机器码（P3）待后续。
> 代码：`ds-plus/dsplus/frontend.py`、`ast_plus.py`；测试：`ds-plus/tests/test_step5_frontend.py`。

## 1. 设计：零重写复用 base parser

```
Ds+ 源码
  → 扫描 @ 令牌（16 个注册表项，跳过字符串/注释）
  → 重写为 base 可解析形式（占位调用 / 空白）
  → 复用 dsv01.parser（经典/0.1c/Flow 三档自动识别）
  → AST 变换：Call → Intrinsic/InlineAsm；区域记录 → RegionAnnotated
  → Ds+ AST（base AST + 4 个 plus 节点）
```

优点：

- **base 代码 100% 等价**：不含 16 个令牌时直接返回 `dsv01.parser.parse_program` 的 AST，逐字段一致（S14 断言）。
- **三档写法零重复**：表面语法仍由 base parser 处理；plus 节点与写法无关（S15 断言）。
- **属性兼容**：`@raw fn`、`@stack type` 这类 base 合法属性仍按属性解析，不被误判为区域（避免破坏严格超集）。

## 2. 支持的 P1 形式

### 硬件（12）

| 令牌 | P1 语法 | AST |
|---|---|---|
| `@asm` | `@asm("...")`、`@asm volatile("...")` | `InlineAsm(template, volatile)` |
| `@inb/@outb/@inw/@outw/@inl/@outl` | `@inb(port)`、`@outb(port, val)` | `Intrinsic("port_in/out", width)` |
| `@rdmsr/@wrmsr` | `@rdmsr(msr)`、`@wrmsr(msr, val)` | `Intrinsic("msr_read/write")` |
| `@rdcr/@wrcr` | `@rdcr(3)`、`@wrcr(3, val)` | `Intrinsic("cr_read/write")` |
| `@mmio` | `@mmio(addr, T)` | `Intrinsic("mmio", type_name=T)` |

### 区域（4）

`@stack/@static/@raw/@mmap` 只能标注 `let` / `var` / 隐式赋值（0.1c/Flow 的 `x = ...`）：

```ds
@stack var s: i32 = 42
@static var g: u64 = 0x1000
@raw var dma: ptr[u8] = malloc(4096)
@mmap var page: ptr[u8] = map_page(0xC0000000, 4096)
```

- 区域令牌在重写时替换为等长空白，AST 中产生 `RegionAnnotated(region, node)`；
- 未匹配到声明/赋值 → `E_DS_PLUS_REGION_TARGET`；
- 标注 `fn/type` 的 `@stack` 等按 base 属性解析（保持超集）。

## 3. 错误码（P1）

| 错误码 | 场景 |
|---|---|
| `E_DS_PLUS_ASM_FORM_P1` | `@asm` 带操作数/约束/命名参数（P2 实现） |
| `E_DS_PLUS_ARGS` | intrinsic 参数个数不匹配 |
| `E_DS_PLUS_REGION_TARGET` | 区域令牌没有落到 let/var/隐式赋值 |

## 4. 测试与门禁

- `ds-plus/tests/test_step5_frontend.py`：9 项（base AST 等价、16 令牌、三档一致、属性兼容、字符串/注释屏蔽、区域目标、错误码）。
- `superset_check.py` 新增 **S14/S15**；CI `ds-plus-check` 自动执行。
- 当前结果：S1–S15 全绿；ds-plus 测试 28 项全绿。

## 5. 已知限制（P1 → P2）

1. `@asm` 仅支持零操作数/volatile 字符串；C 风格操作数/约束/clobber 在 P2 解析并降级。
2. 前端只产生 AST；区域合法性（页对齐、静态初始化器常量）、unsafe 检查、profile 限制在类型检查（P2）。
3. 改写后错误行列基于重写文本，列号可能与原文有偏移；行号保持。
4. 全量 base corpus 的 AST 等价目前抽 4 个代表文件；P1.5 扩展到 `tests/` + `examples/` 全量。

## 6. 下一步（P2）

- 类型检查器：`@rdcr/@wrcr` 常量子集、`@static` 常量初始化、`@mmap` 页对齐、`@unsafe` 上下文、profile（bare/compat）限制；
- 解释/执行 plus intrinsic 的 compat 模拟（用于语义超集差分测试）；
- `@asm` 操作数形式与 clobber 降级。
