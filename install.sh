#!/bin/sh
# Ds v0.1 一键安装脚本（Termux / Linux / macOS）
# 用法:
#   curl -fsSL https://raw.githubusercontent.com/yzxcrush/ds/main/install.sh | sh
# 可选环境变量:
#   DS_REPO=yzxcrush/ds      仓库
#   DS_REF=main              分支/标签
#   DS_HOME=$HOME/.ds/ds     源码安装目录
#   DS_BIN=$PREFIX/bin       命令安装目录（默认 Termux 用 $PREFIX/bin，其它用 ~/.local/bin）
#   DS_WITH_C=0              跳过 C 驱动构建（默认自动尝试）
set -eu

REPO=${DS_REPO:-yzxcrush/ds}
REF=${DS_REF:-main}
DS_HOME=${DS_HOME:-$HOME/.ds/ds}

if [ -n "${DS_BIN:-}" ]; then
  BIN_DIR=$DS_BIN
elif [ -n "${PREFIX:-}" ] && [ -d "$PREFIX/bin" ]; then
  BIN_DIR=$PREFIX/bin
else
  BIN_DIR=$HOME/.local/bin
fi

say() { printf '%s\n' "$*"; }
die() { printf '错误: %s\n' "$*" >&2; exit 1; }

command -v tar >/dev/null 2>&1 || die "需要 tar"
if command -v curl >/dev/null 2>&1; then
  DL="curl"
elif command -v wget >/dev/null 2>&1; then
  DL="wget"
else
  die "需要 curl 或 wget"
fi

TMP=$(mktemp -d "${TMPDIR:-$HOME}/ds-install-XXXXXX") || die "无法创建临时目录"
trap 'rm -rf "$TMP"' EXIT INT TERM

download() {
  url=$1
  if [ "$DL" = curl ]; then
    curl -fL --retry 4 --retry-delay 2 --connect-timeout 15 --max-time 180 \
      -o "$TMP/ds.tar.gz" "$url"
  else
    wget -O "$TMP/ds.tar.gz" --tries=4 --timeout=30 "$url"
  fi
}

say "==> 下载 Ds 驱动: $REPO@$REF"
ok=0
for url in \
  "https://codeload.github.com/$REPO/tar.gz/refs/heads/$REF" \
  "https://github.com/$REPO/archive/refs/heads/$REF.tar.gz" \
  "https://api.github.com/repos/$REPO/tarball/$REF"
do
  say "    $url"
  if download "$url" && tar -tzf "$TMP/ds.tar.gz" >/dev/null 2>&1; then ok=1; break; fi
  rm -f "$TMP/ds.tar.gz"
done
[ "$ok" = 1 ] || die "下载失败（GitHub 网络不稳定，请重试或设置代理）"

say "==> 解压到 $DS_HOME"
mkdir -p "$TMP/unpack"
tar -xzf "$TMP/ds.tar.gz" -C "$TMP/unpack"
SRC=$(find "$TMP/unpack" -mindepth 1 -maxdepth 1 -type d | head -n 1)
[ -n "$SRC" ] && [ -f "$SRC/dscc" ] || die "压缩包结构异常"
rm -rf "$DS_HOME"
mkdir -p "$DS_HOME"
cp -R "$SRC"/. "$DS_HOME"/
chmod +x "$DS_HOME/dscc"

say "==> 安装 dscc 命令到 $BIN_DIR"
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/dscc" <<LAUNCH
#!/bin/sh
exec "$DS_HOME/dscc" "\$@"
LAUNCH
chmod +x "$BIN_DIR/dscc"

say "==> 冒烟测试"
printf 'p("ds-install-ok")\n' > "$TMP/ok.ds"
OUT=$("$DS_HOME/dscc" "$TMP/ok.ds" 2>&1) || die "dscc 运行失败: $OUT"
[ "$OUT" = "ds-install-ok" ] || die "dscc 输出异常: $OUT"

if [ "${DS_WITH_C:-1}" != "0" ] && command -v make >/dev/null 2>&1 && command -v cc >/dev/null 2>&1; then
  say "==> 构建 C 驱动"
  if make -C "$DS_HOME/c" >/dev/null 2>&1; then
    cat > "$BIN_DIR/ds-c" <<LAUNCH
#!/bin/sh
exec "$DS_HOME/c/build/ds" "\$@"
LAUNCH
    chmod +x "$BIN_DIR/ds-c"
    say "    C 驱动: $BIN_DIR/ds-c"
  else
    say "    C 驱动构建失败（不影响 Python 驱动）"
  fi
fi

say ""
say "✅ 安装完成"
say "   源码: $DS_HOME"
say "   命令: $BIN_DIR/dscc"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) say "⚠️  $BIN_DIR 不在 PATH，请加入：export PATH=\"$BIN_DIR:\$PATH\"" ;;
esac
say ""
say "试试:"
say "  dscc --help"
say "  printf 'p(\"hello, Ds\")\\n' > hello.ds && dscc hello.ds"
