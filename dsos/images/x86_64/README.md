# DsOS 裸机镜像（x86_64 legacy BIOS）

> **直接可烧录**：把 `.img` 写入 U 盘/磁盘即可从 legacy BIOS 启动。  
> 启动路径：BIOS MBR → 实模式 stage2 → 保护模式 → PAE 长模式 → COM1 输出。

## 1. 产物

| 文件 | 大小 | 说明 |
|---|---|---|
| `dsos-x86_64.img` | 1.44 MiB | 完整镜像：MBR + stage2 + 长模式代码 |
| `dsos-bios.img` | 512 B | 兜底引导扇区，直接 COM1 输出 |
| `gen_boot.py` | — | 纯 Python 生成器，无 C/汇编器/链接器 |

SHA256：

```text
dsos-x86_64.img  e6240e26c532df874a131384b299fafbe1ed24ccfc47bbf33d4d2a5b035eeaf2
dsos-bios.img    870cd07c744fd8dfeed5f31350502c7ceff651b996bde338e2ee1352d8263e85
```

## 2. 预期输出

串口（COM1，115200 8N1）输出：

```text
DsOS booted.
```

## 3. QEMU 先验证（强烈建议）

```bash
qemu-system-x86_64 \
  -drive format=raw,file=dsos/images/x86_64/dsos-x86_64.img,if=floppy \
  -serial stdio -display none
```

兜底镜像：

```bash
qemu-system-x86_64 \
  -drive format=raw,file=dsos/images/x86_64/dsos-bios.img,if=floppy \
  -serial stdio -display none
```

期望串口打印 `DsOS booted.`。

## 4. 烧录到 U 盘 / 磁盘

> **危险操作：`dd` 会覆盖目标设备全部数据。先确认设备名，不要写错盘。**

```bash
lsblk
# 假设 U 盘是 /dev/sdX（不要带数字分区，如 /dev/sdX1）
sudo dd if=dsos/images/x86_64/dsos-x86_64.img of=/dev/sdX \
  bs=4M conv=fsync status=progress
sync
```

然后：

1. 目标机 BIOS 开启 **Legacy/CSM** 启动；
2. 选择 U 盘启动；
3. 串口接 COM1（或 USB-TTL）看输出；
4. 预期 `DsOS booted.`。

UEFI-only、Secure Boot 开启的机器不会直接启动这个 legacy 镜像。

## 5. 启动流程

```text
BIOS 0x7C00
  └─ MBR: 读 8 个扇区到 0x8000
      └─ stage2: A20 → GDT → CR0.PE
          └─ 32-bit: 页表 0x9000/0xA000/0xB000 → CR3 → CR4.PAE → EFER.LME → CR0.PG
              └─ 64-bit: COM1 输出 → cli → hlt
```

没有使用 C、汇编器、链接器、libc；所有字节由 `gen_boot.py` 直接生成。

## 6. 重新生成

```bash
cd dsos/images/x86_64
python3 gen_boot.py
sha256sum dsos-x86_64.img dsos-bios.img
```

## 7. 当前边界

- 这是 **最小裸机镜像**：验证 MBR/长模式/串口，不含 DsOS 内核、页分配器、中断、调度。
- 未在本机执行 QEMU（本机 aarch64 Termux 无 `qemu-system-x86_64`）；已做镜像结构/签名/地址静态校验。  
  **烧录前请先在 QEMU 或可丢弃 U 盘上验证。**
- UEFI 启动、GPT、图形输出、键盘输入不在本阶段。

## 8. 层标注

| 项 | 值 |
|---|---|
| 层 | Ds-（Cut/裸机边界） |
| 入口 | BIOS MBR，LBA 0 |
| 依赖 | x86_64 CPU、legacy BIOS、COM1 |
| 生成器 | `gen_boot.py` |
