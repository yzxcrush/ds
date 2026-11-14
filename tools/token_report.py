#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对比「经典写法」与「精简写法」的 token 数（以参考词法器的有效 token 计）。

用法：python3 tools/token_report.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dsv01.lexer import COMMENT, NEWLINE, tokenize  # noqa: E402

PAIRS = [
    ("hello world", """package hello
fn main() {
    println("hello, Ds")
}""", """println("hello, Ds")"""),
    ("斐波那契 10 项", """package demo
fn fib(n: i32) -> i32 {
    if n < 2 { n } else { fib(n - 1) + fib(n - 2) }
}
fn main() {
    for i in range(0, 10) {
        println(str(fib(i)))
    }
}""", """fn fib(n)=if n<2: n else fib(n-1)+fib(n-2)
for i in 0..10: println(f"fib({i})={fib(i)}")"""),
    ("值类型 + 方法", """package demo
type Point { x: f32, y: f32 }
impl Point {
    fn length(ref self) -> f32 {
        math.sqrt(self.x * self.x + self.y * self.y)
    }
}
fn main() {
    let p = Point(x: 3.0, y: 4.0)
    println(p.length())
}""", """type Point { x: f32, y: f32 }
impl Point {
    fn len(ref self)=math.sqrt(self.x*self.x + self.y*self.y)
}
let p=Point(x:3.0, y:4.0)
println(p.len())"""),
    ("类 + 继承", """package demo
class Shape {
    name: str
    fn new(name: str) { self.name = name }
}
class Circle extends Shape {
    fn new(name: str) { super.init(name) }
}
fn main() {
    let c = Circle.new("c")
    println(c.name)
}""", """class Shape {
    name: str
    fn new(name: str): self.name = name
}
class Circle extends Shape {
    fn new(name: str): super.init(name)
}
let c=Circle.new("c")
println(c.name)"""),
    ("错误处理 + f-string", """package demo
fn div(a: i32, b: i32) -> res[i32, error] {
    if b == 0 { return err(error("zero")) }
    ok(a / b)
}
fn main() {
    var total = 0
    for i in range(1, 6) {
        total = total + i
    }
    println(format("total={} div={}", total, div(6, 3)))
}""", """fn div(a,b)=if b==0: err(error("zero")) else ok(a/b)
var total=0
for i in 1..6: total+=i
println(f"total={total} div={div(6,3)}")"""),
]


FLOW_PAIRS = [
    ("hello world", """package hello
fn main() {
    println("hello, Ds")
}""", 'println("hello, Ds")', 'p "hello, Ds"'),
    ("斐波那契", """package demo
fn fib(n: i32) -> i32 {
    if n < 2 { n } else { fib(n - 1) + fib(n - 2) }
}
fn main() {
    for i in range(0, 10) {
        println(str(fib(i)))
    }
}""", """fn fib(n)=if n<2: n else fib(n-1)+fib(n-2)
for i in 0..10: println(f"fib({i})={fib(i)}")""", """\\fib n = ?n<2: n; fib(n-1)+fib(n-2)
for i in 0..10: p f"fib({i})={fib(i)}"
"""),
    ("累加 + 调用", """package demo
fn add(a: i32, b: i32) -> i32 {
    a + b
}
fn main() {
    var total = 0
    for i in range(1, 6) { total = total + i }
    println(total)
    println(add(2, 3))
}""", """var total=0
for i in 1..6: total+=i
println(f"total={total}")
fn add(a,b)=a+b
println(add(2,3))""", """var total=0
for i in 1..6: total+=i
p f"total={total}"
\\add a b = a+b
p add(2,3)
"""),
]


def count(src: str) -> tuple[int, int]:
    toks = [t for t in tokenize(src) if t.kind not in (COMMENT, NEWLINE)]
    return len(toks), len(src)


def main() -> int:
    print("| 场景 | 经典 token | 精简 token | 省 | 经典字符 | 精简字符 |")
    print("|---|---|---|---|---|---|")
    tot_a = tot_b = 0
    for name, classic, concise in PAIRS:
        a, ca = count(classic)
        b, cb = count(concise)
        tot_a += a
        tot_b += b
        print(f"| {name} | {a} | {b} | -{100 * (a - b) // a}% | {ca} | {cb} |")
    print(f"| **合计** | **{tot_a}** | **{tot_b}** | **-{100 * (tot_a - tot_b) // tot_a}%** | | |")

    print()
    print("### Flow 写法（并置调用 + `.` 结束块 + `\\` 定义）")
    print("| 场景 | 经典 token | 0.1c token | Flow token | vs 经典 | vs 0.1c |")
    print("|---|---|---|---|---|---|")
    ta = tb = tc = 0
    for name, classic, concise, flow in FLOW_PAIRS:
        a, _ = count(classic)
        b, _ = count(concise)
        c, _ = count(flow)
        ta += a
        tb += b
        tc += c
        print(f"| {name} | {a} | {b} | {c} | -{100 * (a - c) // a}% | -{100 * (b - c) // b}% |")
    print(f"| **合计** | **{ta}** | **{tb}** | **{tc}** | **-{100 * (ta - tc) // ta}%** | **-{100 * (tb - tc) // tb}%** |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
