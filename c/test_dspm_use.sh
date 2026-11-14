#!/bin/sh
# C 驱动 use/dspm 端到端测试：本地 file:// 镜像装包 → C 驱动解析 use → 执行
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
TMP=$(mktemp -d "${TMPDIR:-$HOME}/dspm-use-XXXXXX")
trap 'rm -rf "$TMP"' EXIT
GH="$TMP/github"
SRC="$TMP/src/ds-hello-v0.1.0"
mkdir -p "$SRC/src" "$GH/demo/ds-hello/archive/refs/tags"
cat > "$SRC/ds.toml" <<'TOMLEOF'
name = "ds-hello"
version = "0.1.0"
exports = ["hello"]
deps = []
targets = ["app", "bare"]
TOMLEOF
cat > "$SRC/src/hello.ds" <<'DSEOF'
pub fn hello(name: str) -> str { "hello, " + name }
DSEOF
tar -czf "$GH/demo/ds-hello/archive/refs/tags/v0.1.0.tar.gz" -C "$TMP/src" ds-hello-v0.1.0
DSPM_HOME="$TMP/home" DSPM_GITHUB_BASE="file://$GH" DSPM_GITHUB_API="http://127.0.0.1:9" \
  python3 tools/dspm.py install demo/ds-hello@v0.1.0 --yes >/dev/null
cat > "$TMP/main.ds" <<'DSEOF'
use hello
p(hello.hello("Ds"))
DSEOF
OUT=$(DSPM_HOME="$TMP/home" ./c/build/ds "$TMP/main.ds")
[ "$OUT" = "hello, Ds" ] || { echo "✗ 输出不符：$OUT" >&2; exit 1; }
cat > "$TMP/miss.ds" <<'DSEOF'
use nope
DSEOF
if DSPM_HOME="$TMP/home" ./c/build/ds "$TMP/miss.ds" 2>"$TMP/err" >/dev/null; then
    echo "✗ 缺失模块应报错" >&2; exit 1
fi
grep -q "dspm install" "$TMP/err" || { echo "✗ 缺少 dspm 安装提示" >&2; cat "$TMP/err" >&2; exit 1; }
echo "✓ C 驱动 use/dspm 集成测试通过"
