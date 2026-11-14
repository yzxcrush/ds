# Ds+（plus 分支）一页纸

> Ds+ 是 Ds 的**严格超集**：base 77 关键字与语义不变，新增 16 个 `@` 令牌。
> 分支 `ds-plus`；发布 `ds-plus-v0.1.0`；基础版 `main` 不受影响。

## 为什么有 Ds+

同一门语言里既要「应用/系统」的通用能力，又要「裸机/内核」的硬件能力。拆成双分支：

- **Ds（base）**：稳定、冻结 77 关键字，适合应用与教学。
- **Ds+（plus）**：在 base 之上加硬件/内存区域，不破坏 base 代码。

## 新增能力（16 个 @ 令牌）

**硬件 12**：`@asm @inb @outb @inw @outw @inl @outl @rdmsr @wrmsr @rdcr @wrcr @mmio`
**区域 4**：`@stack @static @raw @mmap`

```ds
@stack var s: i32 = 42
@static var g: u64 = 0x1000

@unsafe fn kernel() {
    @outb(0x3F8, 65)
    let key = @inb(0x60)
    let efer = @rdmsr(0xC0000080)
    @wrmsr(0xC0000080, efer | 0x100)
    let cr3 = @rdcr(3)
    @wrcr(3, cr3)
    let uart = @mmio(0x3F8, u8)
    @asm volatile("cli")
}
```

规则：硬件仅 `bare` profile；`@asm`/端口 IO/MSR/CR/`@raw`/`@mmap` 需要 `@unsafe`；
`@rdcr/@wrcr` 的 cr ∈ {0,2,3,4}；`@static` 初始化器必须常量；`@mmap` 字面量地址页对齐。

## 已实现（P0–P6）

| 阶段 | 内容 |
|---|---|
| P0 | ds-core：93 项注册表、ABI、IR、诊断码、版本冻结 |
| P1 | 前端：16 令牌解析；base AST 与 Ds 逐字段一致；三档写法一致 |
| P2 | 语义：profile/unsafe/常量/对齐；compat 模拟执行；`@asm` 输入操作数 |
| P3 | IR 规范化哈希 + ABI 指纹 |
| P4 | x86-64 子集后端：ELF / raw binary |
| P5 | `dsplus` CLI、SFT、语言卡 |
| P6 | v0.1.0 预览发布 |

验证：61 项 Ds+ 测试、S1–S18 超集校验、CI 绿。

## 工具

```bash
ds-plus/bin/dsplus check  file.ds --profile bare
ds-plus/bin/dsplus run    file.ds --profile bare
ds-plus/bin/dsplus build  file.ds --raw -o kernel.bin
ds-plus/bin/dsplus ir     file.ds --hash
```

## 限制

- P4 仅 x86-64 子集：无字符串/GC/异常/并发/类/宏后端、无优化/链接脚本、无 `@mmio` 代码生成。
- P2 是规则级检查，非完整类型推断/借用检查。
- 未合并进 `main`（双分支架构），base 保持纯 Ds。

## 入口

- 分支：<https://github.com/yzxcrush/ds/tree/ds-plus>
- 路线：<https://github.com/yzxcrush/ds/blob/ds-plus/ds-plus/ROADMAP.md>
- 发布：<https://github.com/yzxcrush/ds/releases/tag/ds-plus-v0.1.0>
