"""Batch 3: control flow / functions / scopes / evaluation order."""
import json, subprocess, sys, pathlib, tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
CASES = {
 "return_nested": 'fn f() -> i32 { if true { if true { return 7 } } 0 }\np(f())\n',
 "return_in_loop": 'fn f() -> i32 { for i in 0..5 { if i == 3 { return i } } 9 }\np(f())\n',
 "break_nested": 'var s = 0\nfor i in 0..3 { for j in 0..3 { if j == 1 { break } s = s + 1 } }\np(s)\n',
 "continue_nested": 'var s = 0\nfor i in 0..3 { for j in 0..3 { if j == 1 { continue } s = s + 1 } }\np(s)\n',
 "for_var_scope": 'for i in 0..3 { }\np(i)\n',
 "loop_expr": 'let x = loop { break 42 }\np(x)\n',
 "short_and": 'var n = 0\nfn side() -> bool { n = n + 1; true }\np(false && side())\np(n)\n',
 "short_or": 'var n = 0\nfn side() -> bool { n = n + 1; true }\np(true || side())\np(n)\n',
 "eval_order": 'var n = 0\nfn a() -> i32 { n = n * 10 + 1; 1 }\nfn b() -> i32 { n = n * 10 + 2; 2 }\np(a() + b())\np(n)\n',
 "default_eval": 'var n = 0\nfn bump() -> i32 { n = n + 1; n }\nfn f(x: i32 = bump()) -> i32 { x }\np(f())\np(f())\np(n)\n',
 "closure": 'fn make() -> fn() -> i32 { var x = 0; fn inner() -> i32 { x = x + 1; x }; inner }\nlet f = make()\np(f())\np(f())\n',
 "shadow": 'let x = 1\nfn f() { let x = 2; p(x) }\nf()\np(x)\n',
 "tail_if": 'fn f(n: i32) -> i32 { if n < 2 { n } else { n * 2 } }\np(f(3))\n',
 "while_false": 'var n = 0\nwhile false { n = n + 1 }\np(n)\n',
 "break_value": 'let x = loop { break 5 + 2 }\np(x)\n',
 "pipe_order": 'var n = 0\nfn a() -> i32 { n = n * 10 + 1; 1 }\nfn b(x: i32) -> i32 { n = n * 10 + 2; x }\np(a() |> b)\np(n)\n',
}

def run_py(src):
    fd, name = tempfile.mkstemp(suffix=".ds"); path = pathlib.Path(name)
    path.write_text(src, encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "dsv01", str(path)], cwd=ROOT, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()

def run_c(src):
    fd, name = tempfile.mkstemp(suffix=".ds"); path = pathlib.Path(name)
    path.write_text(src, encoding="utf-8")
    r = subprocess.run([str(ROOT/"c/build/ds"), str(path)], capture_output=True)
    return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace").strip()

out={}
for n,src in CASES.items():
    py=run_py(src); c=run_c(src)
    out[n]={"py_rc":py[0],"py":py[1][:160],"c_rc":c[0],"c":c[1][:160]}
print(json.dumps(out, ensure_ascii=False, indent=1))
