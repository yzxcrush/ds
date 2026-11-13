# Ds v0.1 Language Card

> 给 AI 的「一页纸」语言卡：完整关键词表、语法骨架、语义要点、可验证示例。
> 规范全文见 `spec/DS-v0.1.md`；机器可读索引见 `spec/keywords.json`。
> 版本 0.1.0 ｜ 关键词 77 项 ｜ 许可证：规范 CC-BY-4.0，代码 MIT

## 1. 定位

Ds 是一门**静态类型、显式内存、可裸机运行、编译期可元编程**的系统级语言。
设计契约：小核心（77 硬关键字）、显式内存（栈/静态/`alloc`/`rc`/`arc`/`gc` 五选一）、
确定性析构、错误分层（`res`/`opt` → `panic` → `assert`）、结构化并发、裸机优先（`--bare`）、
编译期元编程（`comptime`/`macro`/`typeinfo`/`attr`）、单继承 + trait。

`dscc` 一次编译一个包；包根文件第一行必须是 `package 名`。

## 2. 全量关键词表（77）

**定义（9）** `fn` `let` `var` `type` `class` `trait` `impl` `mod` `package`
**控制（9）** `if` `else` `loop` `while` `for` `break` `continue` `return` `goto`
**管道（3）** `->` `=>` `|>`
**错误（7）** `try` `catch` `panic` `recover` `assert` `res` `opt`
**模块（8）** `use` `as` `export` `pub` `priv` `prot` `static` `extern`
**并发（8）** `spawn` `go` `thread` `chan` `send` `recv` `mutex` `wait`
**内存（9）** `raw` `free` `alloc` `rc` `arc` `gc` `ptr` `ref` `mut`
**裸机（7）** `@` `asm` `volatile` `at` `irq` `section` `packed`
**元编程（4）** `comptime` `macro` `typeinfo` `attr`
**OOP（6）** `self` `super` `new` `drop` `extends` `dyn`
**模式（7）** `match` `when` `where` `in` `is` `sizeof` `alignof`

= 73 个字母关键字 + `@` `->` `=>` `|>` 4 个符号关键字。全部为**硬关键字**，不可作标识符；
需要与外部符号同名时用反引号原始标识符：`` `free` ``。

## 3. 词法

- 标识符：`[A-Za-z_][A-Za-z0-9_]*`（仅 ASCII；`_` 单独出现是占位符）。
- 语句以换行终止，`;` 等价；`{}` 界定块，缩进无语义。
- 注释：`#` 行注释、`//` 行注释、`#| ... |#` 可嵌套块注释。
- 字面量：`5` `-3` `0xFF` `0b1010` `"str"`（转义 `\n \r \t \\ \" \0 \xNN \u{...}`）
  `b"raw"`（原始字节串，不转义）、`[1 2 3]`（数组，空白或逗号分隔）、`{k:v}`（映射）、
  `{:}`（空映射）、`_`（占位）。
- 无八进制、无字符字面量、无字符串插值。

## 4. 语法骨架

```ebnf
unit      = "package" IDENT { use } { item }
item      = { attr } [ "pub"|"priv"|"prot" ] ( fn | type | class | trait | impl
          | mod | static | extern | macro | attr-decl | section | let | var )
fn        = [ "comptime" | "irq" ] "fn" IDENT [ generics ] "(" params ")"
            [ "->" type ] [ "where" bounds ] ( block | "=>" expr )
class     = "class" IDENT [ "extends" type ] "{" { field | fn } "}"
impl      = "impl" [ type "for" ] type "{" { fn } "}"
stmt      = let | var | assign | if | while | loop | for | break | continue
          | return | goto | send | assert | block | try-block | expr
expr      = assign | pipe ;  pipe = or { "|>" or }
```

表达式优先级（高→低）：后缀 `. [] ()` → 一元 `- ! ~ & *` + 前缀关键字（`try recv sizeof alignof typeinfo comptime`）
→ `as` → `* / %` → `+ -` → `<< >>` → `< > <= >= is in` → `== !=` → `&` → `^` → `|` → `&&` → `||` → `|>` → `=`（仅语句层）。

## 5. 语义要点

- **类型**：`i8..i128` `u8..u128` `isize` `usize` `f32` `f64` `bool` `str` `unit`；无隐式数值转换（用 `as`）。
- **内存**：值默认栈/静态；堆必须显式选 `alloc`+`free`、`rc[T]`、`arc[T]`（`--gc` 开启时）或 `gc[T]`；
  `ref` 是受检借用（同时 1×`ref mut` 或 N×`ref`），`ptr`/`raw` 是 `@unsafe` 逃逸口。
- **析构**：离开作用域/引用计数归零时确定性调用 `drop`；`drop` 内禁止 `panic`。
- **错误**：可恢复错误用 `res[T,E]`/`opt[T]` + `try`/`catch`；不可恢复用 `panic`（`--bare` 恒 abort）；
  `assert` 只查不变量。
- **并发**：`spawn` 结构化（作用域结束自动 `wait`）、`go` 分离、`thread` 独占 OS 线程；
  共享可变状态只能经 `mutex`/`chan`。
- **裸机**：`@` 属性前缀 + `asm`/`volatile`/`at`/`irq`/`section`/`packed`；`@unsafe { }` 不安全块。
- **元编程**：`macro`（解析期语法）→ `comptime`（编译期求值）→ `typeinfo`（类型反射）→ `attr`（自定义属性）。
- **OOP**：`class` 单继承 + `extends`/`super`；`trait`/`impl`/`dyn` 负责接口与动态派发。

## 6. 关键消歧（必须记住）

1. `{}` 是空块，`{:}` 是空映射；`{k:v}` 是映射。**0.1 没有结构体字面量**：值类型用 `名(字段: 值)` 构造，类用 `类.new(...)`。
2. 泛型/数组用 `[]`：`Vec[T]`、`res[T,E]`、`[]u8`、`[u8; 4]`。
3. 三个箭头：`->` 类型（返回/函数类型）、`=>` 值（match 分支/单表达式函数体）、`|>` 表达式管道。
4. `let` 不可变，`var` 可变；不存在 `let mut`。
5. `mut` 只修饰借用/指针/接收者：`ref mut T`、`ptr mut T`、`mut self`。
6. `@` 只能跟属性名或 `{`（`@unsafe {`）；`@at(...)`、`@section(...)`、`@irq(n)` 是属性形式。
7. `use a.b as c`、`use a.b.{x, y}`；路径用 `.` 分隔。
8. `match` 必须穷尽，`_` 兜底；`when` 是守卫；`is` 可在 `if` 中绑定：`if x is Circle(c) { }`。
9. `for 模式 in 可迭代`；无 range 语法糖，整数区间用 prelude `range(a,b)`。
10. `goto 标签` 只在同函数内，标签写作 `标签:`；不可跨函数。

## 7. dscc 编译驱动

```
dscc input.ds -o out --app|--bare --target <triple> --opt 0|1|2|3|s|z \
     --gc none|rc|arc|tracing --rt none|minimal|full
```

| 选项 | 默认（app / bare） |
|---|---|
| `--gc` | `tracing` / `none`（bare 只允许 none） |
| `--rt` | `full` / `minimal`（bare 不允许 full） |
| `--opt` | `2` |
| `--target` | 宿主；bare 目标如 `thumbv7em-none-eabi`、`riscv32-unknown-none-elf` |

退出码：0 成功 / 1 编译或运行错误 / 2 用法错误 / 3 ICE / 4 链接不可用。

## 8. 黄金示例

```ds
package hello

fn main() {
    let who = "Ds"
    println("hello, " + who)
}
```

```ds
package demo

fn fib(n: i32) -> i32 {
    if n < 2 { n } else { fib(n - 1) + fib(n - 2) }
}

fn main() {
    for i in range(0, 10) {
        println(str(fib(i)))
    }
}
```

```ds
package demo

type Point { x: f32, y: f32 }

impl Point {
    fn length(ref self) -> f32 {
        math.sqrt(self.x * self.x + self.y * self.y)
    }
}

fn main() {
    let p = Point(x: 3.0, y: 4.0)
    println(p.length())          // 5.0
}
```

```ds
package demo

class Animal {
    name: str
    fn new(name: str) { self.name = name }
    fn speak(self) -> str { "..." }
}
class Dog extends Animal {
    fn new(name: str) { super.init(name) }
    fn speak(self) -> str { "woof" }
    drop(self) { println("bye " + self.name) }
}
fn main() {
    let d = Dog.new("rex")
    println(d.speak())           // woof
}
```

```ds
package demo

fn parse(s: str) -> res[i32, error] {
    if s == "" { return err(error("empty")) }
    ok(len(s))
}

fn main() {
    let v = try parse("abc")
    match v {
        n when n > 0 => println("ok"),
        _ => println("bad"),
    }
    try { panic "boom" } catch panic { println("recovered") }
}
```

```ds
package demo

fn main() {
    let xs = [1 2 3 4]
    let m = {"a": 1, "b": 2}
    println(xs |> len)            // 4
    println(m["b"])               // 2
}
```

```ds
package firmware
# 裸机：dscc --bare --target thumbv7em-none-eabi
section ".boot" {
    fn reset() at 0x0000_0000 {
        loop { @unsafe { asm "wfi" } }
    }
}
packed type Header { magic: u16, len: u32 }
@irq(5) irq fn tick() { }
```

## 9. 常见错误

- 用 `class` 的 `T(...)` 构造 → 错；类用 `T.new(...)`。
- 在 `match` 分支写表达式而不写 `=>` → 错。
- 泛型写 `<T>` → 错，用 `[T]`。
- 用 `let mut x` → 错；可变绑定用 `var x`。
- 把 `#| ... |#` 当普通注释且不闭合 → 词法错误。
- 期望 `{}` 是映射 → 错，空映射是 `{:}`。

## 10. 如何验证

```bash
python3 tools/ds_keywords.py check --json spec/keywords.json   # 关键词表完整性
python3 -m unittest discover -s tests                           # 参考驱动测试
./dscc examples/tour.ds                                        # 跑示例
```
