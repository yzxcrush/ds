#!/bin/sh
# Cut 构建冒烟：Thumb 汇编 + 链接 RP2350 启动
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
TMP=$(mktemp -d "${TMPDIR:-$HOME}/cut-build-XXXXXX")
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP"
python3 cut/cutc.py dsos/boot/rp2350_start.ds --cut --emit asm -o "$TMP/start.s" >/dev/null
python3 cut/cutc.py dsos/arch/context_switch_thumb.ds --cut --emit asm -o "$TMP/ctx.s" >/dev/null
if command -v clang >/dev/null && command -v ld.lld >/dev/null; then
  clang --target=thumbv8m.main-none-eabi -c "$TMP/start.s" -o "$TMP/start.o"
  clang --target=thumbv8m.main-none-eabi -c "$TMP/ctx.s" -o "$TMP/ctx.o"
  ld.lld -T dsos/bsp/rp2350.ld -o "$TMP/dsos.elf" "$TMP/start.o"
  [ -s "$TMP/dsos.elf" ]
  echo "✓ Cut bootstrap assembled + linked ($(wc -c < "$TMP/dsos.elf") bytes)"
else
  echo "✓ Cut assembly generated (clang/ld.lld not found; skipped assemble/link)"
fi
