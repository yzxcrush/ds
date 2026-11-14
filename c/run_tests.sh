#!/bin/sh
# C 驱动对拍测试：同一批 .ds/.dsf 用 Python 参考驱动与 C 驱动各跑一次，比较 stdout。
set -u
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(dirname "$here")
cd "$root" || exit 1
mkdir -p .tmp
make -C c >/dev/null || exit 1
fail=0
for f in c/tests/*.ds c/tests/*.dsf; do
    [ -f "$f" ] || continue
    PYTHONPATH=. timeout 30 python3 -m dsv01 "$f" > .tmp/py.out 2> .tmp/py.err
    pyrc=$?
    timeout 20 ./c/build/ds "$f" > .tmp/c.out 2> .tmp/c.err
    crc=$?
    if [ $pyrc -eq $crc ] && diff -q .tmp/py.out .tmp/c.out >/dev/null; then
        echo "✓ $f"
    else
        echo "✗ $f (py rc=$pyrc, c rc=$crc)"
        diff .tmp/py.out .tmp/c.out | head -10
        head -3 .tmp/c.err
        fail=1
    fi
done
[ $fail -eq 0 ] && echo "✓ C 驱动对拍全部通过" || echo "✗ C 驱动对拍失败"
exit $fail
