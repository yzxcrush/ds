#!/usr/bin/env python3
"""生成可直接 dd 到磁盘/写盘的 x86_64 裸机镜像。

路径：BIOS MBR -> 实模式加载 stage2 -> 保护模式 -> PAE/长模式 -> COM1 输出。
无 C、无汇编器、无链接器；全部字节由 Python 生成。
"""
from __future__ import annotations
import hashlib
import pathlib
import struct

HERE = pathlib.Path(__file__).resolve().parent
STAGE2_ADDR = 0x8000
GDT_OFF = 0x200
GDTR_OFF = 0x228
LOAD_SECTORS = 8


class Asm:
    def __init__(self):
        self.b = bytearray()

    def emit(self, data: bytes) -> int:
        p = len(self.b)
        self.b += data
        return p

    def u16(self, v: int) -> bytes:
        return struct.pack("<H", v & 0xFFFF)

    def u32(self, v: int) -> bytes:
        return struct.pack("<I", v & 0xFFFFFFFF)


def stage2() -> bytes:
    a = Asm()
    # 16-bit entry
    a.emit(b"\xfa")                          # cli
    a.emit(b"\x31\xc0")                      # xor ax,ax
    a.emit(b"\x8e\xd8")                      # mov ds,ax
    a.emit(b"\x8e\xc0")                      # mov es,ax
    a.emit(b"\x8e\xd0")                      # mov ss,ax
    a.emit(b"\xbc\x00\x7c")                  # mov sp,0x7c00
    # A20 fast gate
    a.emit(b"\xe4\x92")                      # in al,0x92
    a.emit(b"\x0c\x02")                      # or al,2
    a.emit(b"\xe6\x92")                      # out 0x92,al
    # lgdt [0x8120]
    a.emit(b"\x0f\x01\x16" + a.u16(STAGE2_ADDR + GDTR_OFF))
    # enter protected mode
    a.emit(b"\x0f\x20\xc0")                  # mov eax,cr0
    a.emit(b"\x0c\x01")                      # or al,1
    a.emit(b"\x0f\x22\xc0")                  # mov cr0,eax
    # far jump 0x08:pm32 (66 EA off32 sel16)
    pm32_off = len(a.b) + 8
    a.emit(b"\x66\xea" + a.u32(STAGE2_ADDR + pm32_off) + a.u16(0x08))
    # --- 32-bit protected mode ---
    assert len(a.b) == pm32_off, (len(a.b), pm32_off)
    a.emit(b"\x66\xb8\x10\x00")              # mov ax,0x10
    a.emit(b"\x8e\xd8")                      # mov ds,ax
    a.emit(b"\x8e\xc0")                      # mov es,ax
    a.emit(b"\x8e\xd0")                      # mov ss,ax
    a.emit(b"\xbc\x00\x00\x07\x00")          # mov esp,0x70000
    # zero page tables 0x9000..0xbfff
    a.emit(b"\x31\xc0")                      # xor eax,eax
    a.emit(b"\xbf\x00\x90\x00\x00")          # mov edi,0x9000
    a.emit(b"\xb9\x00\x0c\x00\x00")          # mov ecx,0xc00
    a.emit(b"\xf3\xab")                      # rep stosd
    # PML4[0]=0xa003
    a.emit(b"\xc7\x05" + a.u32(0x9000) + a.u32(0xa003))
    # PDPT[0]=0xb003
    a.emit(b"\xc7\x05" + a.u32(0xa000) + a.u32(0xb003))
    # PD[0]=0x83 (2MiB page)
    a.emit(b"\xc7\x05" + a.u32(0xb000) + a.u32(0x83))
    # CR3
    a.emit(b"\xb8" + a.u32(0x9000))          # mov eax,0x9000
    a.emit(b"\x0f\x22\xd8")                  # mov cr3,eax
    # CR4.PAE
    a.emit(b"\x0f\x20\xe0")                  # mov eax,cr4
    a.emit(b"\x0d" + a.u32(0x20))            # or eax,0x20
    a.emit(b"\x0f\x22\xe0")                  # mov cr4,eax
    # EFER.LME
    a.emit(b"\xb9" + a.u32(0xC0000080))      # mov ecx,0xc0000080
    a.emit(b"\x0f\x32")                      # rdmsr
    a.emit(b"\x0d" + a.u32(0x100))           # or eax,0x100
    a.emit(b"\x0f\x30")                      # wrmsr
    # CR0.PG|PE
    a.emit(b"\x0f\x20\xc0")                  # mov eax,cr0
    a.emit(b"\x0d" + a.u32(0x80000001))      # or eax,0x80000001
    a.emit(b"\x0f\x22\xc0")                  # mov cr0,eax
    # far jump 0x18:lm64 (32-bit EA)
    lm64_off = len(a.b) + 7
    a.emit(b"\xea" + a.u32(STAGE2_ADDR + lm64_off) + a.u16(0x18))
    # --- 64-bit long mode ---
    assert len(a.b) == lm64_off, (len(a.b), lm64_off)
    a.emit(b"\x66\xb8\x10\x00")              # mov ax,0x10
    a.emit(b"\x8e\xd8")                      # mov ds,ax
    a.emit(b"\x8e\xc0")                      # mov es,ax
    a.emit(b"\x8e\xd0")                      # mov ss,ax
    a.emit(b"\x48\xbc" + struct.pack("<Q", 0x70000))  # mov rsp,0x70000
    # serial output helper inline
    msg = b"DsOS booted.\r\n"
    for ch in msg:
        a.emit(b"\x66\xba\xf8\x03")          # mov dx,0x3f8
        a.emit(b"\xb0" + bytes([ch]))        # mov al,ch
        a.emit(b"\xee")                      # out dx,al
    a.emit(b"\xfa")                          # cli
    a.emit(b"\xf4")                          # hlt
    a.emit(b"\xeb\xfd")                      # jmp $
    # GDT at GDT_OFF
    assert len(a.b) <= GDT_OFF, len(a.b)
    a.b += b"\x00" * (GDT_OFF - len(a.b))
    gdt = [
        0x0000000000000000,
        0x00CF9A000000FFFF,  # 32-bit code
        0x00CF92000000FFFF,  # data
        0x00AF9A000000FFFF,  # 64-bit code
        0x00AF92000000FFFF,  # 64-bit data
    ]
    for g in gdt:
        a.b += struct.pack("<Q", g)
    assert len(a.b) == GDTR_OFF
    a.b += struct.pack("<HI", 5 * 8 - 1, STAGE2_ADDR + GDT_OFF)
    return bytes(a.b)


def boot_sector() -> bytes:
    b = bytearray()
    b += b"\xfa"                       # cli
    b += b"\x31\xc0"                   # xor ax,ax
    b += b"\x8e\xd8"                   # mov ds,ax
    b += b"\x8e\xc0"                   # mov es,ax
    b += b"\x8e\xd0"                   # mov ss,ax
    b += b"\xbc\x00\x7c"               # mov sp,0x7c00
    b += b"\xfb"                       # sti
    b += b"\x88\x16\xf0\x7d"           # mov [0x7df0],dl
    b += b"\xb8\x08\x02"               # mov ax,0x0208 (read 8 sectors)
    b += b"\xb9\x02\x00"               # mov cx,0x0002 (cyl0, sector2)
    b += b"\xba\x00\x00"               # mov dx,0x0000
    b += b"\x8a\x16\xf0\x7d"           # mov dl,[0x7df0]
    b += b"\xbb\x00\x80"               # mov bx,0x8000
    b += b"\xcd\x13"                   # int 13h
    b += b"\x72\x05"                   # jc fail (+5, skip far jmp)
    b += b"\xea\x00\x80\x00\x00"       # jmp 0x0000:0x8000
    b += b"\xf4\xeb\xfd"               # fail: hlt; jmp fail
    assert len(b) <= 510
    b += b"\x00" * (510 - len(b)) + b"\x55\xaa"
    return bytes(b)


def simple_bios_sector() -> bytes:
    """512B 兜底：BIOS 引导扇区，直接 COM1 输出，不依赖 stage2。"""
    msg = b"DsOS booted.\r\n\x00"
    b = bytearray()
    b += b"\xba\xf8\x03"              # mov dx,0x3f8
    b += b"\xbe" + struct.pack("<H", 0x7C00 + 17)
    b += b"\xac"                        # lodsb
    b += b"\x84\xc0"                    # test al,al
    b += b"\x74\x03"                    # jz +3
    b += b"\xee"                        # out dx,al
    b += b"\xeb\xf8"                    # jmp -8
    b += b"\xf4\xeb\xfd"                # hlt; jmp
    assert len(b) == 17, len(b)
    b += msg
    b += b"\x00" * (510 - len(b)) + b"\x55\xaa"
    return bytes(b)


def main() -> None:
    st2 = stage2()
    assert len(st2) <= LOAD_SECTORS * 512, len(st2)
    st2_padded = st2 + b"\x00" * (LOAD_SECTORS * 512 - len(st2))
    img = boot_sector() + st2_padded
    # 1.44 MiB raw image，便于 dd / QEMU
    img += b"\x00" * (1440 * 1024 - len(img))
    out = HERE / "dsos-x86_64.img"
    out.write_bytes(img)
    bios = simple_bios_sector()
    (HERE / "dsos-bios.img").write_bytes(bios)
    print(f"✓ {out} ({len(img)} bytes)")
    print("sha256:", hashlib.sha256(img).hexdigest())
    print("boot signature:", img[510:512].hex())
    print("stage2 bytes:", len(st2))
    print("bios sha256:", hashlib.sha256(bios).hexdigest())


if __name__ == "__main__":
    main()
