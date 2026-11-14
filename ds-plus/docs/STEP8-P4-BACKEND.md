# Step 8（P4）— x86-64 子集后端

> 代码：`ds-plus/dsplus/codegen.py`；测试：`test_step8_p4_codegen.py`（7 项）。
> 构建：ELF（`cc`/`clang --target=x86_64-linux-gnu` + `ld.lld`）→ `objcopy -O binary` 得 raw。

## 支持子集

- 整数/布尔字面量、局部变量、赋值、return；
- 算术 `+ - * / % & | ^ << >>`、比较、`! ~ -`；
- `if`/`while`、用户函数调用（最多 6 参数，SysV 寄存器）；
- `@asm`（输入 `%0..%N` 替换）；
- `@inb/@outb/@inw/@outw/@inl/@outl`、`@rdmsr/@wrmsr`、`@rdcr/@wrcr`；
- `@stack`（普通栈槽）、`@static`（整数字面量 .data/.bss 简化版）。

## 入口

- 无 `main` 时把顶层语句合成 `main`；
- Linux 测试入口 `_start`：`call main; exit(main())`（syscall 60）；
- `--bare` 仅影响是否生成 `_start` 包装（当前裸机镜像为 raw binary，链接脚本/地址布局后续）。

## 验证

- 汇编断言：`outb %al, %dx`、`inb %dx, %al`、`rdmsr`、`movq %cr3` 等；
- ELF 头检查：`\x7fELF`、e_machine=62（x86-64）；
- raw binary 非空；
- x86_64 主机上运行 `main()=42` 校验退出码（CI）。

## 限制（P4 子集）

字符串/GC/异常/并发/类/宏、`@mmio` 代码生成、优化、链接脚本、非 x86-64 目标均未实现。
