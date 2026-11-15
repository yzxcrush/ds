# cutc — Ds/Cut 原型编译器（v0.1）

Ds/Cut 是 Ds 三层的裸机子语言：`Cut ⊂ Ds ⊂ Ds+`。
本目录是 **语法/语义/Thumb 代码生成** 的可运行原型；规范见 [`spec/DS-CUT.md`](../spec/DS-CUT.md)。

## 用法

```bash
python3 cut/cutc.py cut/examples/uart_hello.ds --cut --emit asm -o /tmp/uart.s
python3 cut/cutc.py dsos/boot/rp2350_start.ds --cut --emit obj \
  --target thumbv8m.main-none-eabi -o /tmp/start.o
sh cut/test_build.sh        # 生成 + clang 汇编 + ld.lld 链接冒烟
python3 -m unittest discover -s cut/tests -v
```

模式：
- `--cut`：只允许 16 个 Cut token；Ds 关键字 → `E_CUT_LAYER_DS`，Ds+ `@` 令牌 → `E_CUT_LAYER_PLUS`。
- `--app`（默认）：Cut + Ds；Ds+ 令牌 → `E_CUT_LAYER_PLUS`。
- `--plus`：三层全部允许（v0.1 后端仍只实现 Cut 子集）。

## 词法分析核心伪代码

```text
lex(src):
  while not EOF:
    skip whitespace/comments (#, //, /* */)
    if '\n': emit NL token                      # 语句边界，不丢
    if '@name': emit AT(name)
    if string: decode escapes -> STR
    if number: 0x / 0b / decimal -> INT
    if identifier: [A-Za-z_][A-Za-z0-9_]* -> IDENT
    match longest operator: .. -> == != <= >= << >> && || + - * / % & | ^ ! ~ = < > ( ) { } [ ] , ; : .
  emit EOF

check_layer(tokens, mode):                      # 先于语法
  for t in tokens:
    if IDENT and t in CUT_KEYWORDS|CUT_TYPES: continue
    if IDENT and t in DS_KEYWORDS:
        if mode == cut: error E_CUT_LAYER_DS "请使用 --app"
        else: continue
    if AT and t in CUT_ATTRS (@static/@asm/@irq): continue
    if AT and t in DS_PLUS_AT:
        if mode != plus: error E_CUT_LAYER_PLUS "请使用 --plus"
        else: continue
```

## 语法分析核心伪代码

```text
parse_program():
  while not EOF:
    skip_nl
    if '@asm'  -> global asm (string 或 ("..."))
    if '@static' -> static_decl
    if '@irq' [(n)] 'fn' -> fn_decl(irq=true)
    if 'fn' -> fn_decl
    else error("顶层只允许 @asm/@static/@irq fn/fn")

stmt():
  skip_nl
  'let' IDENT [':' type] '=' expr semi
  'if' expr block ['else' (if_stmt|block)]
  'while' expr block
  'for' IDENT 'in' expr '..' expr block
  'return' [expr] semi
  '@asm' [ '(' ] string { ',' ('in'|'out') '(' REG ')' expr/IDENT } [ ')' ] semi
  expr [ '=' expr ] semi        # lvalue = Var | '*' expr

expr(min_prec):                 # Pratt
  left = unary()
  while current is binary op with prec >= min_prec:
      op = advance; right = expr(prec+1); left = Binary(op,left,right)
unary():
  '-'|'!'|'~' unary | '*' unary | '(' expr ')' | INT | true/false | IDENT ['(' args ')']
```

## 语义检查

- `@static` 地址必须是整数字面量；生成 `.equ NAME, ADDR`。
- `*x` 仅允许 `@static` 名字或 `*T` 参数/变量；`p+1`、`p-1`、`p*2` → `E_CUT_PTR_ARITH`。
- 调用目标必须已定义函数；最多 4 参数（AAPCS r0-r3）。
- `@irq` 只用于函数；生成 `.vector_table` 条目。
- 无堆/浮点/字符串表达式/结构体/闭包/异常/并发/指针算术；遇到即 `E_CUT_FORBIDDEN`/`E_CUT_UNSUPPORTED`。

## Thumb 代码生成（原型子集）

| Cut | Thumb |
|---|---|
| 函数序言 | `push {r4, lr}` + `sub sp,#frame`（帧=槽数×4 对齐 8） |
| 函数返回 | `movs r0,#0` / 表达式值；`add sp,#frame; pop {r4,pc}` |
| `@irq` | `push {lr}` … `pop {pc}`；`.word fn` |
| 纯 `@asm` 函数 | 原样输出，无 prologue/epilogue |
| `let` / 变量 | `str/ldr [sp,#off]` |
| `*p` / `*p=e` | `ldr r0,[r0]` / 求值后 `str r0,[r1]` |
| 算术 | `adds/subs/muls/ands/orrs/eors/lsls/asrs` |
| 比较 | `cmp` + `mov<cond> r0,#1` |
| 调用 | 参数入 r0-r3；`bl f` |
| `@static` | `.equ NAME,ADDR`；取地址 `ldr r0,=NAME` |
| `@asm "..."` | 原样输出（`;` 分多行，标签可用） |

完整表见 `spec/DS-CUT.md` §6。

## 当前原型限制

- 仅 Thumb（RP2350/RP2040）；AArch64（Zero 2 W）后端待 v0.2。
- 无寄存器分配/优化；每个局部变量固定栈槽。
- 无除法/取模代码生成（无硬件除法保证）→ 编译错误。
- 无 UF2 生成；由链接后 `uf2conv.py` 处理。
- `@static` 仅整数字面量地址；不支持段属性（@section 属 Ds+）。
- 纯汇编函数不做参数搬运；调用约定由调用者保证（上下文切换用 r0/r1）。

## DsOS

启动代码、上下文切换、链接脚本见 [`dsos/`](../dsos/) 与 [`docs/DSOS.md`](../docs/DSOS.md)。
