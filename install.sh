#!/bin/sh
# 在 Termux / Linux 上安装 Ds v0.1：Python 驱动 + 终端快捷指令
set -e
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$here"
pip install --force-reinstall --no-cache-dir .
prefix=${PREFIX:-/usr/local}
mkdir -p "$prefix/bin"
cp bin/启动ds bin/dsrepl "$prefix/bin/"
chmod +x "$prefix/bin/启动ds" "$prefix/bin/dsrepl"
echo "✓ 已安装：ds / dscc / 启动ds / dsrepl → $prefix/bin"
