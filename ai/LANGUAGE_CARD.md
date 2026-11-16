# Ds v0.1 Language Card

> 给 AI 的「一页纸」语言卡：完整关键词表、语法骨架、语义要点、可验证示例。
> 规范全文见 `spec/DS-v0.1.md`；机器可读索引见 `spec/keywords.json`。
> 版本 0.1.0 ｜ 关键词 77 项 ｜ 许可证：规范 CC-BY-4.0，代码 MIT

## 0. 精简写法（默认推荐，省 token）

Ds 0.1c 精简写法与 v0.1 语义相同、可混用，AI 生成时**优先使用**：

| 规则 | 写法 |
|---|---|
| 无样板 | 不需要 `package`，也不需要 `fn main`；顶层语句即入口 |
| 表达式函数体 | `fn add(a,b)=a+b`；单语句体 `fn say(x): println(x)` |
| 单语句块 | `for i in 0..10: println(i)`；`if c: a else b` |
| 变量 | 首次赋值 `x = 1` 即不可变定义；可变用 `var`；支持 `+= -= *= /= %=` 等 |
| 范围 | `0..10`（半开区间，等价 `range(0,10)`） |
| 插值 | `f"x={x} n={x+1}"` |
| 类型 | 全部可省 |

实测常见程序平均省 31% token（hello 省 61%）。**旧写法仍完全合法**，混合使用没问题。
完整规则见 `spec/DS-CONCISE.md`。

## 0b. Flow 写法（结构性最省 token）

`\` 定义函数、参数空白分隔、并置调用、`.` 结束块、`?` 条件、`^` 返回、`p/s/l/r` 短别名；
无 `{}`、无 `fn main`、无逗号参数表。文件名 `.dsf` 或首行 `#!flow` 启用。

```dsf
\fib n = ?n<2: n; fib(n-1)+fib(n-2)
for i in 0..10: p f"fib({i})={fib(i)}"
```

经典/0.1c/Flow 三者可分别混用；Flow 相比 0.1c 再省约 15% token。详见 `spec/DS-FLOW.md`。

## 0c. Ds+（plus 分支）与 dspm

**Ds+ 是 Ds 的严格超集**（分支 `ds-plus`，base `main` 不受影响），新增 16 个 `@` 令牌：

- 硬件 12：`@asm @inb @outb @inw @outw @inl @outl @rdmsr @wrmsr @rdcr @wrcr @mmio`
- 区域 4：`@stack @static @raw @mmap`

规则：硬件仅 `--bare`；`@asm`/端口 IO/MSR/CR/`@raw`/`@mmap` 需要 `@unsafe`；
`@rdcr/@wrcr` 的 cr ∈ {0,2,3,4}；`@static` 初始化器必须常量；`@mmap` 字面量地址须页对齐。
`compat` profile 保留全部 base 语义（严格超集），`bare` 无 GC/无语言运行时。

**dspm（包管理）**：包 = GitHub 仓库，版本 = git tag；短名 `./dspm install ds-hello`（索引在 `yzxcrush/ds-packages`），也可 `./dspm install <user>/<repo>[@tag]`；
`~/.ds/pkg/<user>/<repo>@<tag>/`、`~/.ds/dspm.lock`、`~/.ds/cache`；不执行包脚本，unsafe 包需确认。
编译器 `use <module>` 解析到已安装包；C 驱动已原生支持，调用写成 `模块名.函数名`。

详见 `docs/DS-PLUS.md`、`docs/DSPM.md`。

## 0d. Ds/Cut 与 DsOS（裸机子语言）

- Cut ⊂ Ds ⊂ Ds+；`--cut` / `--app` / `--plus` 三模式，用错层给 `E_CUT_LAYER_DS` / `E_CUT_LAYER_PLUS`。
- Cut 冻结 16 token：`let fn if else while for return u8 u16 u32 i32 bool * @static @asm @irq`（中文别名仅文档）。
- 禁指针算术、堆、浮点、字符串表达式、结构体/闭包/异常/并发；`@asm` 支持 `in("r0")/out("r0")`、纯汇编函数、文件级汇编。
- 后端：Thumb 全子集；AArch64 **纯 @asm**（启动/上下文切换）；`cut/uf2.py` 生成 RP2350 UF2（family 0xE48BFF56）。
- DsOS：RP2350 → Thumb/.uf2；Zero 2 W → AArch64/kernel8.img（不是 UF2）。
- **DSOSS**（DsOS Standard Specification）：C0–C4 一致性、双板 profile、manifest + 检查器；DsOS 是实现，DSOSS 是标准。
- 详见 `spec/DS-CUT.md`、`docs/DSOS.md`、`spec/DSOSS.md`。

## 0e. 当前验证状态（2026-11，AI 必读）

**Base 语法冻结候选；语义尚未冻结**（`ds-core-v1` 未发布）。

- **已冻结批次**：Batch 1（词法/关键字/字面量/换行）、Batch 3（控制流/作用域/求值顺序）
- **部分冻结**：Batch 2（类型/值/宽度：字面量范围、异构数组、if 分支、64 位位运算已修；**B1 固定宽度整数未完成**）、Batch 4（指针/AddrSymbol：`*T` 类型、`@static` base 模拟已修；**B3 未完成**）、Batch 5（错误/并发/元宏：顶层 try 已修；C/Android 子系统缺口）
- **冻结标签**：`base-partial-freeze-2026-11`（partial-freeze；Ds+/Cut 不冻结）
- **下一批**：Batch 7（仅 base 未验证项/扩展 conformance，不冻结 Ds+/Cut）
- **下游同步**：Ds+ 已把 base checker 接成 `E_DS_BASE`；Cut 已接受 `*T` 与 `@irq(5) irq fn` 的 base 形式，并有 `cut/tests/test_base_compat.py` 回归
- 状态文件：`audit/batches.json`、`spec/freeze.json`、`docs/FOUNDATION.md`

### 语法消歧（写代码/生成代码必须遵守）

1. `*`：表达式起始/运算符后是解引用；操作数后是乘法。`&` 同理（前缀取地址 / 中缀位与）。
2. `1..3` 是区间；`1.` 不是合法浮点（写 `1.0`）；`...` 无 spread，报错。
3. `<` 永远是比较；泛型/定长数组用 `[]`。
4. `[`：表达式起始=数组字面量；后缀=索引；类型位置=`[]T`/`[T; N]`/泛型参数。
5. `:`：语句起始 `IDENT:` 是标签；`{}` 内是映射键；声明/参数位置是类型注解。
6. `{`：`{k:v}`/`{:}` 是映射，其余是块。
7. `@`：只接属性名或 `{`；Ds+ 的 `@inb/@outb/...` 只在 Ds+ 层；Cut 的 `@static/@asm/@irq` 是属性拼写。
8. `|>` 是管道；`|` 是按位或；`->` 是返回/函数类型；`=>` 是值分支。
9. Cut 的指针类型 `*T` 在 base 中作为 `ptr[T]` 的别名接受；`@static NAME: T = ADDR` 是地址符号。

### 当前严格检查

- 无隐式整数宽度转换（`i32 -> u8` 报错，需 `as`）；整数字面量按目标范围检查。
- 异构数组报错；`if` 分支类型必须一致。
- 硬关键字不能作绑定名（`new`/`drop` 方法除外）。
- `try` 在顶层 err 会明确报错，不再产生 internal error。

### Android 扩展（不是 base）

- emoji/Unicode 标识符（Python/C/base 仍 ASCII）；
- Ds+ 虚拟硬件（`@inb/@outb/@mmap/@asm` 模拟；`@asm` no-op）。

## 1. 定位

Ds 是一门**静态类型、显式内存、可裸机运行、编译期可元编程**的系统级语言。
设计契约：小核心（77 硬关键字）、显式内存（栈/静态/`alloc`/`rc`/`arc`/`gc` 五选一）、
确定性析构、错误分层（`res`/`opt` → `panic` → `assert`）、结构化并发、裸机优先（`--bare`）、
编译期元编程（`comptime`/`macro`/`typeinfo`/`attr`）、单继承 + trait。

`dscc` 一次编译一个包；经典写法首行 `package 名`，0.1c 可省略。

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
- 无八进制、无字符字面量；经典写法无插值，0.1c 使用 `f"{x}"`。

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
9. `for 模式 in 可迭代`；经典写法无 range 语法糖（用 `range(a,b)`），0.1c 支持 `a..b`。
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
