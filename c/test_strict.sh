#!/bin/sh
# C 驱动严格性回归：明显非法必须在执行前报错
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
[ -x c/build/ds ] || make -C c -s
TMP=$(mktemp -d "${TMPDIR:-$HOME}/ds-strict-XXXXXX")
trap 'rm -rf "$TMP"' EXIT
cat > "$TMP/ret.ds" <<'DS'
fn f() -> i32 { "x" }
p(f())
DS
cat > "$TMP/miss.ds" <<'DS'
fn f() -> i32 { }
p(f())
DS
cat > "$TMP/annot.ds" <<'DS'
let x: i32 = "s"
p(x)
DS
cat > "$TMP/topret.ds" <<'DS'
return 1
DS
for f in ret miss annot topret; do
  if c/build/ds "$TMP/$f.ds" >"$TMP/out" 2>"$TMP/err"; then
    echo "✗ $f 应失败却成功：$(cat "$TMP/out")" >&2; exit 1
  fi
  grep -q "error:" "$TMP/err" || { echo "✗ $f 没有清晰错误" >&2; cat "$TMP/err" >&2; exit 1; }
done
echo "✓ C 驱动严格性测试通过（4 项）"
