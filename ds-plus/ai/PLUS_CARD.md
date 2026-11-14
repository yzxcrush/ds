# Ds+ 语言卡（v0.1.0，P1–P4 预览）

> Ds+ = Ds 的严格超集。base 77 关键字不变；新增 16 个 `@` 令牌。
> 三档写法（classic / 0.1c / Flow）共享同一 AST；Ds+ 只扩展后端与语义。

## 新增令牌

**硬件 12**：`@asm @inb @outb @inw @outw @inl @outl @rdmsr @wrmsr @rdcr @wrcr @mmio`
**区域 4**：`@stack @static @raw @mmap`

## 语法

```ds
@stack var s: i32 = 42
@static var g: u64 = 0x1000
@raw var dma: ptr[u8] = malloc(4096)
@mmap var page: ptr[u8] = map_page(0xC0000000, 4096)

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

## 规则

- 硬件令牌仅 `bare` profile；`@mmio`/4 区域两种 profile 可用。
- `@asm`/端口 IO/MSR/CR/`@raw`/`@mmap` 必须在 `@unsafe` 上下文。
- `@rdcr/@wrcr` 的 cr ∈ {0,2,3,4} 且为编译期常量。
- `@static` 初始化器必须是编译期常量；`@mmap` 地址（字面量）必须 4096 对齐。
- 区域只能标注 `let/var`/隐式赋值；`@raw fn` 等仍按 Ds 属性解析。

## 工具

```bash
dsplus check file.ds --profile bare
dsplus run file.ds --profile bare        # compat 模拟执行（端口/MSR/CR/MMIO）
dsplus ir file.ds --hash
dsplus abi
dsplus build file.ds --bare --raw -o kernel.bin
```

## 当前限制（P4）

- 代码生成仅 x86-64 子集：整数/布尔、算术、let/var、if/while、函数调用、@asm/端口 IO/MSR/CR/区域；字符串/GC/@mmio 代码生成、优化、ELF 链接脚本未做。
- `@asm` 操作数只有 `%0..%N` 输入替换，无输出/clobber 约束。
- compat 模拟只覆盖端口/MSR/CR/MMIO 的语义，不模拟中断/页表。
