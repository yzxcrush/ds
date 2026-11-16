"""Batch 1: lexical / keyword / identifier / literal / layer boundary probe."""
import json, subprocess, sys, pathlib, tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
CASES = {
  # identifiers
  "ident_ascii": 'let alpha_1 = 1\np(alpha_1)\n',
  "ident_keyword": 'let if = 1\n',
  "ident_struct": 'let struct = 1\np(struct)\n',       # 0.1: not keyword
  "ident_raw": 'let `free` = 1\np(`free`)\n',
  "ident_underscore": 'let __ = 1\np(__)\n',
  "ident_lone_us": 'let _ = 1\n',
  "ident_chinese": 'let 变量 = 1\np(变量)\n',
  "ident_emoji": 'let 🌱 = 1\np(🌱)\n',
  "ident_nfd": 'let e\u0301 = 1\np(e\u0301)\n',
  # comments / strings
  "comment_nested": '#| a #| b |# c |#\np("ok")\n',
  "comment_hash_string": 'p("# not comment")\n',
  "string_unicode_escape": 'p("\\u{1F600}")\n',
  "string_hex_escape": 'p("\\x41")\n',
  "string_raw_bytes": 'p(b"a\\nb")\n',
  "string_smart_quotes": 'p(“hello”)\n',
  # numbers
  "num_underscore": 'p(1_000_000)\n',
  "num_bin": 'p(0b1010)\n',
  "num_hex": 'p(0xFF)\n',
  "num_bad_bin": 'p(0b102)\n',
  "num_leading_zero": 'p(007)\n',
  "num_float": 'p(1.5e-3)\n',
  "num_dot_float": 'p(1.)\n',
  # operators / punctuation
  "range": 'p(0..3)\n',
  "triple_dot": 'p(0...3)\n',
  "pipe": 'p(1 |> str)\n',
  "label": 'fn f() { x: p("x") }\nf()\n',
  "map_colon": 'let m = {"a": 1}\np(m["a"])\n',
  "attr_irq": '@irq fn f() { }\np("ok")\n',
  "attr_asm": '@asm "nop"\np("ok")\n',
  "cut_static": '@static UART: u32 = 0x1000\np("ok")\n',
  # layout
  "semicolon": 'let a = 1; let b = 2; p(a+b)\n',
  "newline_after_op": 'let a = 1 +\n 2\np(a)\n',
  "newline_before_op": 'let a = 1\n + 2\np(a)\n',
}

def run_py(src):
    p = pathlib.Path(tempfile.mkstemp(suffix=".ds")[1]); p.write_text(src, encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "dsv01", str(p), "--check"], cwd=ROOT,
                       capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()

def run_c(src):
    p = pathlib.Path(tempfile.mkstemp(suffix=".ds")[1]); p.write_text(src, encoding="utf-8")
    r = subprocess.run([str(ROOT/"c/build/ds"), str(p), "--check"], capture_output=True)
    txt = (r.stdout + r.stderr).decode("utf-8", "replace").strip()
    return r.returncode, txt

out = {}
for name, src in CASES.items():
    py = run_py(src); c = run_c(src)
    out[name] = {"py_ok": py[0] == 0, "py": py[1][:120],
                 "c_ok": c[0] == 0, "c": c[1][:120],
                 "same": (py[0] == 0) == (c[0] == 0)}
print(json.dumps(out, ensure_ascii=False, indent=1))
print("MISMATCH:", [k for k,v in out.items() if not v["same"]], file=sys.stderr)
