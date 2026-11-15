#!/bin/sh
# Cut 构建冒烟：Thumb（RP2350）+ AArch64（Zero 2 W）+ UF2
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
TMP=$(mktemp -d "${TMPDIR:-$HOME}/cut-build-XXXXXX")
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP"

python3 cut/cutc.py dsos/boot/rp2350_start.ds --cut --emit asm -o "$TMP/start.s" >/dev/null
python3 cut/cutc.py dsos/arch/context_switch_thumb.ds --cut --emit asm -o "$TMP/ctx.s" >/dev/null
python3 cut/cutc.py dsos/boot/zero2w_start.ds --cut --arch aarch64 --emit asm -o "$TMP/zero2w.s" >/dev/null
python3 cut/cutc.py dsos/arch/context_switch_aarch64.ds --cut --arch aarch64 --emit asm -o "$TMP/ctx64.s" >/dev/null

if command -v clang >/dev/null && command -v ld.lld >/dev/null; then
  clang --target=thumbv8m.main-none-eabi -c "$TMP/start.s" -o "$TMP/start.o"
  clang --target=thumbv8m.main-none-eabi -c "$TMP/ctx.s" -o "$TMP/ctx.o"
  ld.lld -T dsos/bsp/rp2350.ld -o "$TMP/dsos.elf" "$TMP/start.o"
  [ -s "$TMP/dsos.elf" ]
  echo "✓ RP2350 Thumb ELF ($(wc -c < "$TMP/dsos.elf") bytes)"

  clang --target=aarch64-none-elf -c "$TMP/zero2w.s" -o "$TMP/zero2w.o"
  clang --target=aarch64-none-elf -c "$TMP/ctx64.s" -o "$TMP/ctx64.o"
  cat > "$TMP/stubs.s" <<'ASM'
.text
.globl uart_init
uart_init:
  ret
.globl kernel_main
kernel_main:
  wfe
  b kernel_main
ASM
  clang --target=aarch64-none-elf -c "$TMP/stubs.s" -o "$TMP/stubs.o"
  ld.lld -T dsos/bsp/zero2w.ld -o "$TMP/zero2w.elf" "$TMP/zero2w.o" "$TMP/ctx64.o" "$TMP/stubs.o"
  [ -s "$TMP/zero2w.elf" ]
  echo "✓ Zero 2 W AArch64 ELF ($(wc -c < "$TMP/zero2w.elf") bytes)"

  if command -v llvm-objcopy >/dev/null; then
    llvm-objcopy -O binary "$TMP/dsos.elf" "$TMP/dsos.bin"
    python3 cut/uf2.py "$TMP/dsos.bin" "$TMP/dsos.uf2" >/dev/null
    [ -s "$TMP/dsos.uf2" ]
    echo "✓ RP2350 UF2 ($(wc -c < "$TMP/dsos.uf2") bytes)"
  fi
else
  echo "✓ Cut assembly generated (clang/ld.lld not found; skipped assemble/link)"
fi
