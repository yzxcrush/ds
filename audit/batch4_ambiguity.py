"""Batch 4: grammar ambiguity probes (base syntax)."""
import subprocess, sys, pathlib, tempfile, json
ROOT=pathlib.Path(__file__).resolve().parents[1]
CASES={
 "mul_vs_deref": 'let a = 2 * 3\nlet x = 1\nlet q = &x\np(*q)\np(a)\n',
 "and_vs_addr": 'let a = 6 & 3\nlet x = 1\nlet q = &x\np(*q)\np(a)\n',
 "range_vs_float": 'let r = 1..3\np(r)\n',
 "range_dots": 'let r = 1...3\n',
 "attr_irq": '@irq(5) irq fn tick() { }\ntick()\n',
 "attr_asm": '@asm "nop"\np("x")\n',
 "label_vs_type": 'fn f() { x: p("x") }\nf()\n',
 "map_vs_block": 'let m = {"a": 1}\np(m["a"])\n',
 "array_vs_type": 'let a = [1 2 3]\np(a)\n',
 "compare_vs_generic": 'let a = 1 < 2\np(a)\n',
 "pipe_vs_or": 'p(1 |> str)\np(1 | 2)\n',
 "fn_type_vs_fn_decl": 'fn f(g: fn(i32) -> i32) -> i32 { g(1) }\nfn inc(x: i32) -> i32 { x + 1 }\np(f(inc))\n',
 "flow_dot": '#!flow\n\\add a b = a + b\np add(1 2)\n.\n',
 "static_attr_vs_kw": '@static var s: u32 = 3\np(s)\n',
 "cut_static_type": '@static UART: *u32 = 0x1000\np("ok")\n',
}
def run(src):
 p=pathlib.Path(tempfile.mkstemp(suffix='.ds')[1]); p.write_text(src,encoding='utf-8')
 r=subprocess.run([sys.executable,'-m','dsv01',str(p),'--check'],cwd=ROOT,capture_output=True,text=True)
 return r.returncode,(r.stdout+r.stderr).strip()[:160]
out={}
for n,s in CASES.items(): rc,msg=run(s); out[n]={'ok':rc==0,'msg':msg,'src':s}
print(json.dumps(out,ensure_ascii=False,indent=1))
