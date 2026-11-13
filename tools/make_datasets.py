#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 Ds v0.1 的 AI 学习数据：SFT / 语料 / 评测集。

输出（仓库内直接可下载，无需运行）：
  datasets/ds_sft.jsonl     指令微调（chat messages）
  datasets/ds_corpus.jsonl  语料（{id,title,text}）
  datasets/ds_bench.jsonl   评测任务（隐藏参考输出，由参考驱动生成）
  datasets/STATS.md         统计

用法：python3 tools/make_datasets.py [--check]
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dsv01.interp import Interpreter  # noqa: E402
from dsv01 import builtins as bi      # noqa: E402

SYSTEM = (ROOT / "ai" / "system_prompt.txt").read_text(encoding="utf-8").strip()

# ---------------------------------------------------------------------------
# SFT：(用户需求, 助手回答)。回答 = 说明 + dr 代码。
# ---------------------------------------------------------------------------
SFT = [
    ("用 Ds 写一个 hello world 程序。",
     "```ds\npackage hello\n\nfn main() {\n    println(\"hello, Ds\")\n}\n```\n\n运行：`dscc hello.ds`（解释执行）或 `dscc hello.ds --app`。"),
    ("解释 Ds 中 let 和 var 的区别，并各给一个例子。",
     "`let` 是不可变绑定，只能初始化一次；`var` 是可变量绑定。不存在 `let mut`。\n\n```ds\npackage demo\n\nfn main() {\n    let pi = 3.14          // 不可再赋值\n    var n = 0              // 可赋值\n    n = n + 1\n    println(n)\n}\n```"),
    ("写一个 Ds 函数计算斐波那契数列第 n 项，并打印前 10 项。",
     "```ds\npackage algos\n\nfn fib(n: i32) -> i32 {\n    if n < 2 { n } else { fib(n - 1) + fib(n - 2) }\n}\n\nfn main() {\n    for i in range(0, 10) {\n        println(str(fib(i)))\n    }\n}\n```"),
    ("Ds 里怎么定义和遍历数组？",
     "数组字面量用 `[1 2 3]`（空白或逗号分隔），`for 元素 in 数组` 遍历，下标用 `xs[i]`。\n\n```ds\npackage demo\n\nfn main() {\n    let xs = [10 20 30]\n    var sum = 0\n    for v in xs {\n        sum = sum + v\n    }\n    xs[0] = 1\n    println(xs)\n    println(sum)\n}\n```"),
    ("Ds 的映射怎么用？空映射怎么写？",
     "映射是 `{k:v}`，空映射必须写 `{:}`（因为 `{}` 是空块）。\n\n```ds\npackage demo\n\nfn main() {\n    let m = {\"a\": 1, \"b\": 2}\n    println(m[\"a\"])\n    m[\"c\"] = 3\n    let empty = {:}\n    println(len(empty))\n}\n```"),
    ("写一个 Ds 程序判断质数并输出 60 以内的质数。",
     "```ds\npackage algos\n\nfn is_prime(n: i32) -> bool {\n    if n < 2 { return false }\n    var i = 2\n    while i * i <= n {\n        if n % i == 0 { return false }\n        i = i + 1\n    }\n    true\n}\n\nfn main() {\n    for n in range(2, 60) {\n        if is_prime(n) { print(str(n) + \" \") }\n    }\n    println(\"\")\n}\n```"),
    ("Ds 里的 if/else 有什么特别之处？",
     "`if` 同时是表达式，所有分支必须产生相同类型的值；条件是 `bool`，不存在隐式真值转换。\n\n```ds\npackage demo\n\nfn main() {\n    let a = 3\n    let m = if a > 2 { \"big\" } else { \"small\" }\n    println(m)\n}\n```"),
    ("用 Ds 的 match 做模式匹配，展示 when 守卫和通配符。",
     "```ds\npackage demo\n\nfn classify(n: i32) -> str {\n    match n {\n        0 => \"zero\",\n        x when x % 2 == 0 => \"even\",\n        _ => \"odd\",\n    }\n}\n\nfn main() {\n    println(classify(0))\n    println(classify(4))\n    println(classify(7))\n}\n```"),
    ("Ds 如何处理可恢复错误？给出 res 与 try 的例子。",
     "用 `res[T, E]` 表示成功/失败，`try e` 在失败时立即返回 err；`catch` 可捕获。\n\n```ds\npackage demo\n\nfn div(a: i32, b: i32) -> res[i32, error] {\n    if b == 0 { return err(error(\"divide by zero\")) }\n    ok(a / b)\n}\n\nfn main() {\n    match div(6, 3) {\n        ok(v) => println(\"ok\"),\n        err(e) => println(\"err\"),\n    }\n}\n```"),
    ("Ds 里 panic 和 recover 怎么用？",
     "`panic 值` 抛出不可恢复错误；`try { } catch panic { }` 可捕获，`recover` 取回载荷。\n\n```ds\npackage demo\n\nfn main() {\n    try {\n        panic \"boom\"\n    } catch panic {\n        println(\"recovered: \" + recover)\n    }\n}\n```"),
    ("用 Ds 定义一个类、继承并用 super 调用父类构造。",
     "`class` 单继承；类方法隐式持有 `self`；父类构造用 `super.init(...)`。\n\n```ds\npackage demo\n\nclass Animal {\n    name: str\n    fn new(name: str) { self.name = name }\n    fn speak(self) -> str { \"...\" }\n}\n\nclass Dog extends Animal {\n    fn new(name: str) { super.init(name) }\n    fn speak(self) -> str { \"woof\" }\n}\n\nfn main() {\n    let d = Dog.new(\"rex\")\n    println(d.speak())\n}\n```"),
    ("Ds 的 trait 和 impl 怎么写？",
     "`trait` 定义接口，`impl Trait for 类型` 实现；`dyn Trait` 是动态派发对象。\n\n```ds\npackage demo\n\ntrait Draw {\n    fn draw(ref self) -> str\n}\n\ntype Circle { r: f32 }\n\nimpl Draw for Circle {\n    fn draw(ref self) -> str { \"circle\" }\n}\n\nfn main() {\n    let c = Circle(r: 1.0)\n    println(c.draw())\n}\n```"),
    ("Ds 的管道运算符 |> 怎么用？",
     "`a |> f |> g` 等价 `g(f(a))`；右侧也可以是带实参的调用，左值作为第一个参数。\n\n```ds\npackage demo\n\nfn inc(x: i32) -> i32 { x + 1 }\nfn dbl(x: i32) -> i32 { x * 2 }\n\nfn main() {\n    println(5 |> inc |> dbl)\n}\n```"),
    ("写一个 Ds 程序演示 while、loop 和 break。",
     "```ds\npackage demo\n\nfn main() {\n    var i = 0\n    while i < 3 { i = i + 1 }\n\n    var n = 0\n    loop {\n        n = n + 1\n        if n >= 5 { break }\n    }\n    println(i)\n    println(n)\n}\n```"),
    ("Ds 的函数可以有默认参数吗？怎么声明返回类型？",
     "参数写成 `名: 类型 = 默认值`；返回类型在 `->` 后。\n\n```ds\npackage demo\n\nfn scale(x: i32, k: i32 = 2) -> i32 {\n    x * k\n}\n\nfn main() {\n    println(scale(5))\n    println(scale(5, 3))\n}\n```"),
    ("用 Ds 写一个闭包/函数值示例。",
     "函数是值，可以赋值给变量、作为参数传递。\n\n```ds\npackage demo\n\nfn apply_twice(f: fn(i32) -> i32, x: i32) -> i32 {\n    f(f(x))\n}\n\nfn inc(x: i32) -> i32 { x + 1 }\n\nfn main() {\n    let f = inc\n    println(f(41))\n    println(apply_twice(inc, 10))\n}\n```"),
    ("Ds 的 sizeof 和 alignof 返回什么？在 comptime 里怎么用？",
     "`sizeof(T)`/`alignof(T)` 是编译期常量（usize）；`comptime { ... }` 在编译期求值。\n\n```ds\npackage demo\n\ntype V { x: f32, y: f32 }\n\nfn main() {\n    comptime {\n        assert sizeof(V) == 8, \"size\"\n        assert alignof(V) == 4, \"align\"\n    }\n    println(\"compile-time checked\")\n}\n```"),
    ("写一个 Ds 宏（macro）的例子。",
     "`macro 名(参数: 片段种类) { 模板 }` 是解析期语法宏；片段在模板中按名字引用。\n\n```ds\npackage demo\n\nmacro unless(c: expr, b: block) {\n    if !c { b }\n}\n\nfn main() {\n    unless(false, { println(\"fired\") })\n}\n```"),
    ("Ds 的 spawn 和 chan 怎么用？给一个并发示例。",
     "`spawn` 启动结构化任务（作用域结束自动 wait）；`chan[T]`/`send`/`recv` 通信。\n\n```ds\npackage demo\n\nfn worker(ch: chan[i32]) {\n    send ch, 42\n}\n\nfn main() {\n    let ch = chan[i32](4)\n    spawn { worker(ch) }\n    match recv ch {\n        some(v) => println(\"got \" + str(v)),\n        none => println(\"closed\"),\n    }\n}\n```"),
    ("Ds 里 mutex 和 wait 的用法？",
     "共享可变状态必须经 `mutex`；`wait 句柄` 等待任务/线程完成。\n\n```ds\npackage demo\n\nfn job() { }\n\nfn main() {\n    let m = mutex(0)\n    {\n        let guard = m.lock()\n        _ = guard\n    }\n    let t = thread(job)\n    wait t\n}\n```"),
    ("Ds 的内存管理有哪些方式？",
     "五选一：栈/静态、`alloc`+`free`、`rc[T]`、`arc[T]`、`gc[T]`；`ref` 是受检借用，`ptr`/`raw` 只能在 `@unsafe` 中解引用。\n\n```ds\npackage demo\n\nfn main() {\n    let p = alloc(16, 8)\n    @unsafe { *p = 65 }\n    free(p)\n\n    let a = rc(1)\n    let b = arc(mutex(0))\n    let c = gc(2)\n    _ = a\n    _ = b\n    _ = c\n}\n```"),
    ("Ds 的裸机模式怎么写入口、中断和寄存器访问？",
     "`--bare` 下无 OS/GC；用 `section \".boot\"` 放入口，`@irq(n) irq fn` 声明中断服务例程，`volatile ptr[u32]` 访问 MMIO。\n\n```ds\npackage firmware\n\nsection \".boot\" {\n    fn reset() at 0x0000_0000 {\n        loop { @unsafe { asm \"wfi\" } }\n    }\n}\n\n@irq(5)\nirq fn timer_tick() { }\n\nfn read_reg(addr: usize) -> u32 {\n    @unsafe {\n        let p = addr as volatile ptr[u32]\n        *p\n    }\n}\n```"),
    ("Ds 的模块系统怎么用？",
     "`mod` 声明模块、`use` 导入、`pub`/`priv`/`prot` 控制可见性、`export` 重导出。\n\n```ds\npackage app\n\nmod math {\n    pub fn clamp(x: i32, lo: i32, hi: i32) -> i32 {\n        if x < lo { lo } else if x > hi { hi } else { x }\n    }\n}\n\nuse math.clamp\n\nexport math.clamp\n\nfn main() {\n    println(clamp(42, 0, 10))\n}\n```"),
    ("dscc 怎么用？给几个常用命令。",
     "`dscc 输入.ds -o 输出 --app|--bare --target 三元组 --opt 级别 --gc 策略 --rt 运行时`。\n\n```bash\ndscc hello.ds -o hello --app --opt 2 --gc tracing --rt full\ndscc main.ds -o fw.elf --bare --target thumbv7em-none-eabi --opt z --gc none --rt minimal\ndscc main.ds --check\n```"),
    ("把这段 Python 改写成 Ds：sum = 0; for i in range(10): sum += i; print(sum)",
     "```ds\npackage demo\n\nfn main() {\n    var sum = 0\n    for i in range(0, 10) {\n        sum = sum + i\n    }\n    println(sum)\n}\n```\n\n注意：Ds 的 `range(a, b)` 是半开区间；没有 `+=`，用 `sum = sum + i`；`print` 是 prelude 函数。"),
    ("把这段 Python 改写成 Ds：def fact(n): return 1 if n <= 1 else n * fact(n-1)",
     "```ds\npackage demo\n\nfn fact(n: i32) -> i32 {\n    if n <= 1 { 1 } else { n * fact(n - 1) }\n}\n\nfn main() {\n    println(fact(5))\n}\n```"),
    ("这段 Ds 代码有错误，请修好：\n```ds\npackage demo\n\nfn main() {\n    let xs = [1 2 3]\n    println(xs)\n    let m = {}\n}\n```",
     "错误：`{}` 在 Ds 里是空块，不是空映射。空映射必须写 `{:}`。\n\n```ds\npackage demo\n\nfn main() {\n    let xs = [1 2 3]\n    println(xs)\n    let m = {:}\n}\n```"),
    ("这段 Ds 代码有错误，请修好：\n```ds\npackage demo\n\nclass Point {\n    x: f32\n    fn new(x: f32) { self.x = x }\n}\n\nfn main() {\n    let p = Point(1.0)\n}\n```",
     "错误：类不能用 `Point(...)` 构造，必须用 `Point.new(...)`。\n\n```ds\npackage demo\n\nclass Point {\n    x: f32\n    fn new(x: f32) { self.x = x }\n}\n\nfn main() {\n    let p = Point.new(1.0)\n}\n```"),
    ("用 Ds 实现冒泡排序并打印结果。",
     "```ds\npackage algos\n\nfn main() {\n    let xs = [5 3 8 1]\n    let n = len(xs)\n    for i in range(0, n) {\n        for j in range(0, n - i - 1) {\n            if xs[j] > xs[j + 1] {\n                let tmp = xs[j]\n                xs[j] = xs[j + 1]\n                xs[j + 1] = tmp\n            }\n        }\n    }\n    println(xs)\n}\n```"),
    ("用 Ds 写二分查找。",
     "```ds\npackage algos\n\nfn bsearch(xs: [i32], target: i32) -> i32 {\n    var lo = 0\n    var hi = len(xs) - 1\n    while lo <= hi {\n        let mid = (lo + hi) / 2\n        if xs[mid] == target { return mid }\n        if xs[mid] < target { lo = mid + 1 } else { hi = mid - 1 }\n    }\n    -1\n}\n\nfn main() {\n    println(bsearch([1 3 5 7 9], 7))\n}\n```"),
    ("Ds 的位运算和移位怎么用？",
     "`& | ^ ~ << >>` 作用于整数；移位量越界会 panic。\n\n```ds\npackage demo\n\nfn main() {\n    println(0b1010 & 0b1100)\n    println(1 << 4)\n    println(~0)\n}\n```"),
    ("Ds 支持 goto 吗？怎么用？",
     "支持，但限制在同函数内；标签写作 `名字:`。\n\n```ds\npackage demo\n\nfn spin(limit: u32) -> u32 {\n    var n: u32 = 0\nagain:\n    n = n + 1\n    if n < limit { goto again }\n    n\n}\n\nfn main() {\n    println(spin(3))\n}\n```"),
    ("用最省 token 的 Ds 精简写法写一个 hello world。",
     "```ds\nprintln(\"hello, Ds\")\n```\n\n无需 `package` 与 `fn main`：顶层语句就是入口。"),
    ("用精简写法写斐波那契并输出前 10 项（含 f-string）。",
     "```ds\nfn fib(n)=if n<2: n else fib(n-1)+fib(n-2)\nfor i in 0..10: println(f\"fib({i})={fib(i)}\")\n```"),
    ("精简写法里怎么写循环和累加？",
     "```ds\nvar total=0\nfor i in 1..6: total+=i\nwhile total<20: total+=1\nprintln(total)\n```\n\n`a..b` 是半开区间；`+=` 是复合赋值；单语句体用 `:`。"),
    ("用精简写法定义值类型并加一个方法。",
     "```ds\ntype Point { x: f32, y: f32 }\nimpl Point {\n    fn len(ref self)=math.sqrt(self.x*self.x + self.y*self.y)\n}\nlet p=Point(x:3.0, y:4.0)\nprintln(f\"len={p.len()}\")\n```"),
    ("用精简写法写类与继承。",
     "```ds\nclass Shape {\n    name: str\n    fn new(name: str): self.name = name\n}\nclass Circle extends Shape {\n    fn new(name: str): super.init(name)\n}\nlet c=Circle.new(\"c\")\nprintln(f\"shape={c.name}\")\n```"),
    ("把这段经典写法改成最省 token 的精简写法：\n```ds\npackage demo\nfn add(a: i32, b: i32) -> i32 {\n    a + b\n}\nfn main() {\n    println(add(2, 3))\n}\n```",
     "```ds\nfn add(a,b)=a+b\nprintln(add(2,3))\n```\n\n省去 package/fn main、参数与返回类型、花括号与 return。"),

]

# ---------------------------------------------------------------------------
# 语料：{id, title, text}
# ---------------------------------------------------------------------------
CORPUS = [
    ("overview", "Ds v0.1 是什么",
     "Ds 是一门静态类型、显式内存、可裸机运行、编译期可元编程的系统级编程语言。"
     "设计契约：小核心（77 个硬关键字：73 个字母关键字 + @ -> => |> 四个符号关键字）、显式内存、"
     "确定性析构、错误分层（res/opt → panic → assert）、结构化并发、裸机优先（--bare）、"
     "编译期元编程（comptime/macro/typeinfo/attr）、单继承 + trait。"
     "dscc 一次编译一个包；包根文件第一行必须是 package 名。"),
    ("keywords", "全量关键词表（77）",
     "定义(9): fn let var type class trait impl mod package；"
     "控制(9): if else loop while for break continue return goto；"
     "管道(3): -> => |>；错误(7): try catch panic recover assert res opt；"
     "模块(8): use as export pub priv prot static extern；"
     "并发(8): spawn go thread chan send recv mutex wait；"
     "内存(9): raw free alloc rc arc gc ptr ref mut；"
     "裸机(7): @ asm volatile at irq section packed；"
     "元编程(4): comptime macro typeinfo attr；"
     "OOP(6): self super new drop extends dyn；"
     "模式(7): match when where in is sizeof alignof。"
     "全部为硬关键字，不可作标识符；需要外部符号同名时用反引号原始标识符。"),
    ("lexical", "词法规则",
     "标识符 [A-Za-z_][A-Za-z0-9_]*（仅 ASCII）；_ 单独出现是占位符。语句以换行终止，; 等价；"
     "注释：# 行注释、// 行注释、#| ... |# 可嵌套块注释。字面量：5 -3 0xFF 0b1010 \"str\" "
     "(转义 \\n \\r \\t \\\\ \\\" \\0 \\xNN \\u{...}) b\"raw\"（原始字节串）[1 2 3]（数组）{k:v}（映射）"
     "{:}（空映射）_（占位）。无八进制、无字符字面量、无字符串插值。"),
    ("grammar", "语法骨架",
     "unit = package IDENT { use } { item }；item = { attr } [vis] (fn|type|class|trait|impl|mod|static|extern|macro|attr|section|let|var)；"
     "fn = [comptime|irq] fn IDENT [generics] ( params ) [-> type] [where bounds] (block | => expr)；"
     "class = class IDENT [extends type] { {field|fn} }；impl = impl [type for] type { {fn} }。"
     "表达式优先级（高→低）：后缀 . [] () → 一元 - ! ~ & * 与前缀关键字 → as → * / % → + - → << >> → "
     "< > <= >= is in → == != → & → ^ → | → && → || → |> → =（仅语句层）。"),
    ("ambiguity", "关键消歧规则",
     "1) {} 是空块，{:} 是空映射，{k:v} 是映射；0.1 没有结构体字面量：值类型用 名(字段: 值) 构造，类用 类.new(...)。"
     "2) 泛型/数组用 []：Vec[T]、res[T,E]、[]u8、[u8; 4]。3) 箭头分工：-> 类型、=> 值、|> 表达式管道。"
     "4) let 不可变，var 可变；不存在 let mut。5) mut 只修饰借用/指针/接收者：ref mut T、ptr mut T、mut self。"
     "6) @ 只能跟属性名或 {（@unsafe {）。7) use a.b as c、use a.b.{x, y}；路径用 . 分隔。"
     "8) match 必须穷尽，_ 兜底，when 是守卫，is 可在 if 中绑定。9) for 模式 in 可迭代；无 range 语法糖。"
     "10) goto 标签只在同函数内。"),
    ("semantics", "语义契约",
     "类型：i8..i128 u8..u128 isize usize f32 f64 bool str unit；无隐式数值转换（用 as）。"
     "内存：值默认栈/静态；堆必须显式选 alloc+free、rc[T]、arc[T] 或 gc[T]（--gc 开启时）；"
     "ref 是受检借用（同时 1×ref mut 或 N×ref），ptr/raw 是 @unsafe 逃逸口。"
     "析构：离开作用域/引用计数归零时确定性调用 drop，drop 内禁止 panic。"
     "错误：可恢复错误用 res[T,E]/opt[T] + try/catch；不可恢复用 panic（--bare 恒 abort）；assert 只查不变量。"
     "并发：spawn 结构化（作用域结束自动 wait）、go 分离、thread 独占 OS 线程；共享可变状态只能经 mutex/chan。"
     "裸机：@ 属性前缀 + asm/volatile/at/irq/section/packed；@unsafe { } 不安全块。"
     "元编程：macro（解析期）→ comptime（编译期求值）→ typeinfo（类型反射）→ attr（自定义属性）。"
     "OOP：class 单继承 + extends/super；trait/impl/dyn 负责接口与动态派发。"),
    ("dscc", "dscc 编译驱动",
     "dscc input.ds -o out --app|--bare --target <triple> --opt 0|1|2|3|s|z --gc none|rc|arc|tracing --rt none|minimal|full。"
     "--app 默认 gc=tracing、rt=full；--bare 默认 gc=none、rt=minimal，且只允许 none（gc）与 none/minimal（rt）。"
     "--opt 默认 2。退出码：0 成功 / 1 编译或运行错误 / 2 用法错误 / 3 ICE / 4 链接不可用。"
     "0.1 支持目标：x86_64-unknown-linux-gnu、aarch64-unknown-linux-gnu、aarch64-linux-android、"
     "thumbv7em-none-eabi、riscv32-unknown-none-elf、wasm32-unknown-unknown、x86_64-unknown-none。"),
    ("example_app", "示例：应用模式综合",
     "package tour；fn fib 递归；type Vec2 值类型 + impl 方法；class Circle extends Shape 使用 super.init 与 drop；"
     "trait Draw + impl + dyn；res/opt + try/catch + panic/recover/assert；match/when；|> 管道；"
     "comptime/sizeof/alignof/typeinfo；macro unless。完整文件见 examples/tour.ds。"),
    ("example_bare", "示例：裸机",
     "package firmware；section \".boot\" 放入口；fn reset at 0x0000_0000；static mut TICKS；"
     "packed type FrameHeader；@irq(5) irq fn timer_tick；volatile ptr[u32] 访问 MMIO；@unsafe { asm \"wfi\" }。"
     "编译：dscc bare.ds -o firmware.elf --bare --target thumbv7em-none-eabi --opt z --gc none --rt minimal。"),
    ("faq", "常见错误",
     "用 class 的 T(...) 构造 → 错，类用 T.new(...)；match 分支漏写 => → 错；泛型写 <T> → 错，用 [T]；"
     "let mut x → 错，可变绑定用 var；#| 块注释不闭合 → 词法错误；期望 {} 是映射 → 错，空映射是 {:}。"
     "另外：res/opt 不是关键字以外的魔法，它们就是内建类型；try 只能用于 res。"),
]

# ---------------------------------------------------------------------------
# 评测：{id, title, prompt, solution}；预期输出由参考驱动生成
# ---------------------------------------------------------------------------
BENCH = [
    ("hello", "Hello World", "输出 hello, Ds!（使用 println）。",
     'package t\nfn main() {\n    println("hello, Ds!")\n}\n'),
    ("sum", "累加 1..10", "计算 1+2+...+10 并打印结果。",
     'package t\nfn main() {\n    var s = 0\n    for i in range(1, 11) { s = s + i }\n    println(s)\n}\n'),
    ("fib", "斐波那契", "打印 fib(10)。",
     'package t\nfn fib(n: i32) -> i32 { if n < 2 { n } else { fib(n-1) + fib(n-2) } }\nfn main() { println(fib(10)) }\n'),
    ("fizzbuzz", "FizzBuzz", "打印 1..15，3 的倍数打印 Fizz，5 的倍数打印 Buzz，都满足打印 FizzBuzz，否则打印数字。",
     '''package t
fn main() {
    for i in range(1, 16) {
        if i % 15 == 0 { println("FizzBuzz") }
        else if i % 3 == 0 { println("Fizz") }
        else if i % 5 == 0 { println("Buzz") }
        else { println(str(i)) }
    }
}
'''),
    ("primes", "质数表", "打印 30 以内的质数，以空格分隔，最后换行。",
     '''package t
fn is_prime(n: i32) -> bool {
    if n < 2 { return false }
    var i = 2
    while i * i <= n {
        if n % i == 0 { return false }
        i = i + 1
    }
    true
}
fn main() {
    for n in range(2, 30) {
        if is_prime(n) { print(str(n) + " ") }
    }
    println("")
}
'''),
    ("reverse", "反转数组", "把 [1 2 3 4 5] 反转为 [5 4 3 2 1] 并打印。",
     '''package t
fn main() {
    let xs = [1 2 3 4 5]
    var out = []
    for i in range(0, len(xs)) {
        out = out + [xs[len(xs) - 1 - i]]
    }
    println(out)
}
'''),
    ("wordcount", "词频统计", "统计 \"a b a c b a\" 中每个词出现次数并打印映射。",
     '''package t
fn main() {
    let words = ["a" "b" "a" "c" "b" "a"]
    let m = {:}
    for w in words {
        if w in m { m[w] = m[w] + 1 } else { m[w] = 1 }
    }
    println(m)
}
'''),
    ("bubble", "冒泡排序", "对 [5 3 8 1 9 2] 升序排序并打印。",
     '''package t
fn main() {
    let xs = [5 3 8 1 9 2]
    let n = len(xs)
    for i in range(0, n) {
        for j in range(0, n - i - 1) {
            if xs[j] > xs[j + 1] {
                let tmp = xs[j]
                xs[j] = xs[j + 1]
                xs[j + 1] = tmp
            }
        }
    }
    println(xs)
}
'''),
    ("gcd", "最大公约数", "打印 gcd(84, 36)。",
     '''package t
fn gcd(a: i32, b: i32) -> i32 {
    if b == 0 { a } else { gcd(b, a % b) }
}
fn main() { println(gcd(84, 36)) }
'''),
    ("bsearch", "二分查找", "在 [1 3 5 7 9] 中查找 7，打印下标。",
     '''package t
fn bsearch(xs: [i32], target: i32) -> i32 {
    var lo = 0
    var hi = len(xs) - 1
    while lo <= hi {
        let mid = (lo + hi) / 2
        if xs[mid] == target { return mid }
        if xs[mid] < target { lo = mid + 1 } else { hi = mid - 1 }
    }
    -1
}
fn main() { println(bsearch([1 3 5 7 9], 7)) }
'''),
    ("point", "值类型与方法", "定义 Point{x,y}，构造 Point(x:3,y:4)，打印 x*10+y。",
     '''package t
type Point { x: i32, y: i32 }
impl Point {
    fn weighted(ref self) -> i32 { self.x * 10 + self.y }
}
fn main() {
    let p = Point(x: 3, y: 4)
    println(p.weighted())
}
'''),
    ("shape", "类与继承", "定义 Shape(name) 与 Circle extends Shape，构造 Circle.new(\"c\") 并打印 name。",
     '''package t
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
}
'''),
    ("trait", "trait 与动态派发", "定义 trait Draw{draw}、type Box、impl Draw for Box 打印 box。",
     '''package t
trait Draw { fn draw(ref self) -> str }
type Box { w: i32 }
impl Draw for Box { fn draw(ref self) -> str { "box" } }
fn main() {
    let b = Box(w: 1)
    println(b.draw())
    let d: dyn Draw = b as dyn Draw
    println(d.draw())
}
'''),
    ("opt", "opt 与 match", "函数 pick(opt[i32])：some 返回值，none 返回 -1；打印 pick(some(5)) 与 pick(none)。",
     '''package t
fn pick(o: opt[i32]) -> i32 {
    match o {
        some(v) => v,
        none => -1,
    }
}
fn main() {
    println(pick(some(5)))
    println(pick(none))
}
'''),
    ("res", "res 与 try", "函数 div 返回 res；div(6,3) 打印 ok，div(1,0) 打印 err。",
     '''package t
fn div(a: i32, b: i32) -> res[i32, error] {
    if b == 0 { return err(error("zero")) }
    ok(a / b)
}
fn main() {
    match div(6, 3) { ok(v) => println("ok"), err(e) => println("err") }
    match div(1, 0) { ok(v) => println("ok"), err(e) => println("err") }
}
'''),
    ("pipe", "管道", "用 |> 把 5 依次传给 inc、dbl，打印结果。",
     '''package t
fn inc(x: i32) -> i32 { x + 1 }
fn dbl(x: i32) -> i32 { x * 2 }
fn main() { println(5 |> inc |> dbl) }
'''),
    ("comptime", "编译期检查", "用 comptime 检查 sizeof(u64)==8 且 alignof(u64)==8，然后打印 ok。",
     '''package t
fn main() {
    comptime {
        assert sizeof(u64) == 8, "size"
        assert alignof(u64) == 8, "align"
    }
    println("ok")
}
'''),
    ("macro", "宏", "定义宏 unless(c,b)，调用 unless(false,{ println(\"fired\") })。",
     '''package t
macro unless(c: expr, b: block) {
    if !c { b }
}
fn main() {
    unless(false, { println("fired") })
}
'''),
    ("concurrency", "通道", "chan[i32](4) 发送 42 再 recv，打印 got 42。",
     '''package t
fn main() {
    let ch = chan[i32](4)
    send ch, 42
    match recv ch {
        some(v) => println("got " + str(v)),
        none => println("closed"),
    }
}
'''),
    ("hello_c", "Hello（精简）", "用精简写法输出 hello, Ds!（无 package / 无 fn main）。",
     'println("hello, Ds!")\n'),
    ("fib_c", "斐波那契（精简）", "用精简写法打印 fib(10)。",
     'fn fib(n)=if n<2: n else fib(n-1)+fib(n-2)\nprintln(fib(10))\n'),
    ("fstr_c", "f-string（精简）", "用精简写法打印 ans=42（x=7，x*6）。",
     'let x=7\nprintln(f"ans={x*6}")\n'),

]

# ---------------------------------------------------------------------------
def run_solution(code: str) -> str:
    out = io.StringIO()
    interp = Interpreter(stdout=out)
    interp.run_source(code, "<bench>")
    return out.getvalue()


def main() -> int:
    check = "--check" in sys.argv
    root = ROOT
    ds = root / "datasets"
    ds.mkdir(exist_ok=True)

    # SFT
    sft_lines = []
    for i, (user, assistant) in enumerate(SFT, 1):
        sft_lines.append(json.dumps({
            "id": f"sft-{i:03d}",
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user},
                {"role": "assistant", "content": assistant},
            ],
        }, ensure_ascii=False))
    sft_text = "\n".join(sft_lines) + "\n"

    # corpus
    corpus_lines = [json.dumps({"id": cid, "title": title, "text": text}, ensure_ascii=False)
                    for cid, title, text in CORPUS]
    corpus_text = "\n".join(corpus_lines) + "\n"

    # bench（运行参考实现得到预期输出）
    bench_lines = []
    for bid, title, prompt, solution in BENCH:
        expected = run_solution(solution)
        bench_lines.append(json.dumps({
            "id": bid, "title": title, "prompt": prompt,
            "expected_stdout": expected,
            "difficulty": "easy" if bid in ("hello", "sum", "fib", "fizzbuzz", "primes") else "medium",
        }, ensure_ascii=False))
    bench_text = "\n".join(bench_lines) + "\n"

    stats = f"""# Ds v0.1 AI 数据集统计

| 数据 | 条数 | 用途 |
|---|---|---|
| `ds_sft.jsonl` | {len(SFT)} | 指令微调（system + user + assistant，含 ```ds 代码） |
| `ds_corpus.jsonl` | {len(CORPUS)} | 语料 / RAG（语言卡、关键词、语法、语义、FAQ） |
| `ds_bench.jsonl` | {len(BENCH)} | 评测（prompt + 参考 stdout，覆盖核心特性） |

- 系统提示词：`ai/system_prompt.txt`
- 生成脚本：`tools/make_datasets.py`（bench 预期输出由参考驱动实跑生成，保证可复现）
- 许可证：规范 CC-BY-4.0；代码与数据 MIT
"""

    outputs = {
        ds / "ds_sft.jsonl": sft_text,
        ds / "ds_corpus.jsonl": corpus_text,
        ds / "ds_bench.jsonl": bench_text,
        ds / "STATS.md": stats,
    }
    if check:
        bad = [str(p) for p, t in outputs.items() if not p.exists() or p.read_text(encoding="utf-8") != t]
        if bad:
            print("✗ 数据文件与生成器不一致：" + ", ".join(bad), file=sys.stderr)
            return 1
        print(f"✓ 数据集一致（SFT {len(SFT)} / corpus {len(CORPUS)} / bench {len(BENCH)}）")
        return 0
    for p, t in outputs.items():
        p.write_text(t, encoding="utf-8")
    print(f"✓ 生成 datasets：SFT {len(SFT)} 条、corpus {len(CORPUS)} 条、bench {len(BENCH)} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
