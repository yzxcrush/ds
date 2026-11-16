"""Batch 4: memory / pointers / AddrSymbol / Cut boundary."""
import json, subprocess, sys, pathlib, tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
CASES = {
 "addr_deref": 'let x = 1\nlet p = &x\np(*p)\n*p = 2\np(x)\n',
 "deref_addr": 'let x = 1\nlet y = *&x\np(y)\n',
 "ptr_type": 'let x = 1\nlet p: ptr[i32] = &x\np(*p)\n',
 "static_deref": '@static UART: u32 = 0x1000\np(*UART)\n',
 "static_base": '@static var s: u32 = 3\np(s)\n',
 "static_keyword": 'static var s: u32 = 3\np(s)\n',
 "unsafe_block": '@unsafe {\n  let x = 1\n  p(x)\n}\n',
 "alloc_free": 'let p = alloc(4)\n*p = 65\np(*p)\nfree(p)\n',
 "ptr_arith": 'let x = 1\nlet p = &x\nlet q = p + 1\np(q)\n',
 "raw_type": 'let p: raw[u8] = raw(0x1000)\np("ok")\n',
 "cut_asm": '@asm "nop"\nfn f() { @asm "nop" }\nf()\np("ok")\n',
 "cut_static_name": '@static UART: *u32 = 0x1000\np(UART)\n',
 "cut_irq": '@irq(5) irq fn tick() { }\ntick()\np("ok")\n',
 "cut_stack": '@stack var s: i32 = 1\np(s)\n',
}

def run_py(src):
    path = pathlib.Path(tempfile.mkstemp(suffix=".ds")[1]); path.write_text(src, encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "dsv01", str(path)], cwd=ROOT, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()

def run_c(src):
    path = pathlib.Path(tempfile.mkstemp(suffix=".ds")[1]); path.write_text(src, encoding="utf-8")
    r = subprocess.run([str(ROOT/"c/build/ds"), str(path)], capture_output=True)
    return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace").strip()

out={}
for n,src in CASES.items():
    py=run_py(src); c=run_c(src)
    out[n]={"py_rc":py[0],"py":py[1][:200],"c_rc":c[0],"c":c[1][:200]}
print(json.dumps(out, ensure_ascii=False, indent=1))
