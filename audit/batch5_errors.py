"""Batch 5 smoke: errors/concurrency/meta/ABI (Python reference first)."""
import subprocess, sys, pathlib, tempfile, json
ROOT=pathlib.Path(__file__).resolve().parents[1]
CASES={
 "res_try": 'fn f() -> res[i32, error] { ok(1) }\nlet v = try f()\np(v)\n',
 "res_err": 'fn f() -> res[i32, error] { err(error("x")) }\nlet v = try f()\np(v)\n',
 "try_catch": 'try { panic "x" } catch panic { p("caught") }\n',
 "assert": 'assert 1 == 1\np("ok")\n',
 "assert_fail": 'assert 1 == 2\np("bad")\n',
 "opt": 'fn f() -> opt[i32] { none }\nlet x = try f()\np(x)\n',
 "spawn": 'spawn { p("spawn") }\nwait\n',
 "chan": 'let c = chan[i32](1)\nsend c, 1\np(recv c)\n',
 "comptime": 'comptime { p("ct") }\n',
 "sizeof": 'p(sizeof(i32))\n',
 "typeinfo": 'p(typeinfo(i32))\n',
}
def run(src):
 p=pathlib.Path(tempfile.mkstemp(suffix='.ds')[1]); p.write_text(src,encoding='utf-8')
 r=subprocess.run([sys.executable,'-m','dsv01',str(p)],cwd=ROOT,capture_output=True,text=True)
 return r.returncode,(r.stdout+r.stderr).strip()[:200]
out={}
for n,s in CASES.items():
 rc,msg=run(s); out[n]={'rc':rc,'msg':msg}
print(json.dumps(out,ensure_ascii=False,indent=1))
