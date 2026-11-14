# Ds+ v0.1.0（预览）发布说明

> 分支：`ds-plus` ｜ 与 Ds v0.1.0 同步 ｜ base 77 关键字未改动

## 内容

- **P1 前端**：16 个 `@` 令牌；base 代码 AST 与 Ds 逐字段一致；三档写法共享 plus AST 特征。
- **P2 语义**：profile/unsafe/常量/对齐检查；compat 模拟执行（端口/MSR/CR/MMIO）。
- **P3 IR/ABI**：规范化 IR + 哈希；ABI 指纹；默认 `repr(Ds)` 不变。
- **P4 后端**：x86-64 子集代码生成 → ELF / raw binary。
- **P5 工具**：`dsplus` CLI、SFT、语言卡。
- **CI**：base 单测 + C 对拍 + 28+ 项 ds-plus 测试 + S1–S18 超集校验。

## 快速开始

```bash
dsplus check examples/p1_hardware.ds --profile bare
dsplus run <file> --profile bare
dsplus build <file> --raw -o kernel.bin
```

## 已知限制

见 `ROADMAP.md`：无字符串/GC/异常/并发/类/宏后端，无优化与链接脚本，无非 x86-64 后端；这些属于 v0.2+。
