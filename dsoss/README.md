# DSOSS — DsOS Standard Specification

DSOSS 是 **DsOS 的标准/契约**，不是 OS 实现；用于让不同 DsOS 内核可验证地声称兼容。

- 标准全文：[spec/DSOSS.md](../spec/DSOSS.md)
- 一致性检查：

```bash
python3 dsoss/check_conformance.py dsoss/dsoss.toml
python3 dsoss/check_conformance.py dsoss/profiles/zero2w.toml
```

- 两个 profile：`rp2350-m33`（Thumb/UF2/32 位）、`zero2w-a53`（AArch64/kernel8/64 位）
- manifest 包含 standard/board/boot/kernel/toolchain/syscalls；检查器校验 profile 与字段一致性。
