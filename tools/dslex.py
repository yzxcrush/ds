#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ds v0.1 参考词法器（对应规范 §1 词法、§3 字面量、§4 注释）。

用途：证明《Ds v0.1》的词法定义可自洽执行，并检查 examples/*.ds 能被词法接受。
它只做词法，不做语法/类型/借用检查，因此示例"能过词法"不等于"能编译"。

用法:
  python3 tools/dslex.py            # 词法规则自检 + 扫描 examples/
  python3 tools/dslex.py --selftest # 仅自检（关键字 / 字面量 / 注释 / 错误路径）
  python3 tools/dslex.py --dump FILE
  python3 tools/dslex.py FILE...    # 仅检查给定 .ds 文件
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "spec" / "keywords.json"
EXAMPLES = ROOT / "examples"

# 字符级词法表（顺序无关；匹配时按长度降序）
OPS = [
    "|>", "->", "=>", "<<", ">>", "<=", ">=", "==", "!=", "&&", "||",
    "+", "-", "*", "/", "%", "=", "!", "<", ">", "&", "|", "^", "~", ".", "@",
]
PUNCT = set("(){}[],:;")
SYMBOL_KEYWORDS = {"@", "->", "=>", "|>"}


@dataclass
class Token:
    kind: str      # KEYWORD | IDENT | RAW_IDENT | INT | FLOAT | STRING | BYTES | OP | PUNCT | BLANK | COMMENT | NEWLINE | EOF
    text: str
    line: int
    col: int

    def __str__(self) -> str:
        return f"{self.line}:{self.col} {self.kind:<9} {self.text!r}"


class LexError(Exception):
    def __init__(self, path: str, line: int, col: int, msg: str):
        super().__init__(f"{path}:{line}:{col}: {msg}")
        self.path, self.line, self.col, self.msg = path, line, col, msg


def load_keywords() -> set[str]:
    if not INDEX.exists():
        sys.exit(f"✗ 缺少 {INDEX.relative_to(ROOT)}，请先运行 "
                 f"`python3 tools/ds_keywords.py build`")
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    words = {e["word"] for e in data["alphabetical"]}
    if len(words) != 77:
        sys.exit(f"✗ 关键词索引应为 77 项，实为 {len(words)}")
    return words


def tokenize(src: str, path: str = "<source>") -> list[Token]:
    kw = load_keywords()
    ops = sorted(OPS, key=len, reverse=True)
    toks: list[Token] = []
    i, line, line_start = 0, 1, 0
    n = len(src)

    def err(msg: str, at: int | None = None) -> LexError:
        at = i if at is None else at
        return LexError(path, line, at - line_start + 1, msg)

    def push(kind: str, text: str, start: int) -> None:
        toks.append(Token(kind, text, line, start - line_start + 1))

    while i < n:
        c = src[i]

        # 换行
        if c == "\n":
            push("NEWLINE", "\n", i)
            i += 1
            line += 1
            line_start = i
            continue
        # 空白
        if c in " \t\r":
            i += 1
            continue

        # 注释：块 #| ... |#（可嵌套）优先
        if src.startswith("#|", i):
            start, depth = i, 0
            while i < n:
                if src.startswith("#|", i):
                    depth += 1
                    i += 2
                elif src.startswith("|#", i):
                    depth -= 1
                    i += 2
                    if depth == 0:
                        break
                elif src[i] == "\n":
                    i += 1
                    line += 1
                    line_start = i
                else:
                    i += 1
            if depth != 0:
                raise err("块注释 #| 未闭合（缺少 |#）", start)
            push("COMMENT", src[start:i], start)
            continue
        # 行注释 # 与 //
        if c == "#" or src.startswith("//", i):
            start = i
            while i < n and src[i] != "\n":
                i += 1
            push("COMMENT", src[start:i], start)
            continue

        # 字符串 "..."（有转义，不可含裸换行）
        if c == '"':
            start = i
            i += 1
            while i < n:
                ch = src[i]
                if ch == "\n":
                    raise err("字符串不可含裸换行", start)
                if ch == "\\":
                    i += 1
                    if i >= n:
                        raise err("转义序列未结束", start)
                    e = src[i]
                    if e in 'nrt\\"0':
                        i += 1
                    elif e == "x":
                        h = src[i + 1:i + 3]
                        if len(h) != 2 or not re.fullmatch(r"[0-9a-fA-F]{2}", h):
                            raise err("非法 \\xNN 转义", start)
                        i += 3
                    elif e == "u" and src.startswith("u{", i):
                        j = src.find("}", i)
                        if j < 0:
                            raise err("非法 \\u{...} 转义", start)
                        body = src[i + 2:j]
                        if not re.fullmatch(r"[0-9a-fA-F]{1,6}", body):
                            raise err("非法 \\u{...} 码点", start)
                        i = j + 1
                    else:
                        raise err(f"未知转义 \\{e}", start)
                    continue
                if ch == '"':
                    i += 1
                    push("STRING", src[start:i], start)
                    break
                i += 1
            else:
                raise err("字符串未闭合", start)
            continue

        # 原始字节串 b"..."（不做转义）
        if c == "b" and src.startswith('b"', i):
            start = i
            j = src.find('"', i + 2)
            if j < 0:
                raise err("字节串未闭合", start)
            i = j + 1
            push("BYTES", src[start:i], start)
            continue

        # 原始标识符 `名`
        if c == "`":
            start = i
            j = src.find("`", i + 1)
            if j <= i + 1:
                raise err("原始标识符必须为非空且以反引号闭合", start)
            body = src[i + 1:j]
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", body):
                raise err("原始标识符内容非法", start)
            i = j + 1
            push("RAW_IDENT", src[start:i], start)
            continue

        # 数字
        if c.isdigit():
            start = i
            if src.startswith(("0x", "0X"), i):
                i += 2
                m = re.match(r"[0-9a-fA-F_]+", src[i:])
                if not m:
                    raise err("十六进制字面量缺少数字", start)
                i += m.end()
                kind = "INT"
                if i < n and src[i] == ".":
                    m2 = re.match(r"\.[0-9a-fA-F_]+", src[i:])
                    if m2:
                        i += m2.end()
                        kind = "FLOAT"
                if i < n and src[i] in "pP":
                    m3 = re.match(r"[pP][+-]?\d+", src[i:])
                    if not m3:
                        raise err("十六进制浮点指数非法", start)
                    i += m3.end()
                    kind = "FLOAT"
                push(kind, src[start:i], start)
                continue
            if src.startswith(("0b", "0B"), i):
                i += 2
                m = re.match(r"[01_]+", src[i:])
                if not m:
                    raise err("二进制字面量缺少 0/1", start)
                i += m.end()
                if i < n and re.match(r"[0-9]", src[i]):
                    raise err("二进制字面量含非法数字", start)
                push("INT", src[start:i], start)
                continue
            m = re.match(r"[0-9_]+", src[i:])
            i += m.end()
            kind = "INT"
            if i < n and src[i] == "." and i + 1 < n and src[i + 1].isdigit():
                m2 = re.match(r"\.[0-9_]+", src[i:])
                i += m2.end()
                kind = "FLOAT"
            if i < n and src[i] in "eE":
                m3 = re.match(r"[eE][+-]?[0-9_]+", src[i:])
                if m3:
                    i += m3.end()
                    kind = "FLOAT"
            push(kind, src[start:i], start)
            continue

        # 标识符 / 关键字 / 空白占位符
        if c.isalpha() or c == "_":
            start = i
            while i < n and (src[i].isalnum() or src[i] == "_"):
                i += 1
            text = src[start:i]
            if text == "_":
                push("BLANK", text, start)
            elif text in kw:
                push("KEYWORD", text, start)
            else:
                push("IDENT", text, start)
            continue

        # 运算符（最长匹配）
        for op in ops:
            if src.startswith(op, i):
                start = i
                i += len(op)
                push("KEYWORD" if op in SYMBOL_KEYWORDS else "OP", op, start)
                break
        else:
            # 标点
            if c in PUNCT:
                start = i
                i += 1
                push("PUNCT", c, start)
                continue
            raise err(f"未知字符 {c!r}")

    toks.append(Token("EOF", "", line, i - line_start + 1))
    return toks


def significant(toks: list[Token]) -> list[Token]:
    return [t for t in toks if t.kind not in ("COMMENT", "NEWLINE")]


def check_delimiters(toks: list[Token], path: str) -> list[str]:
    pairs = {")": "(", "]": "[", "}": "{"}
    stack: list[Token] = []
    problems: list[str] = []
    for t in toks:
        if t.kind != "PUNCT":
            continue
        if t.text in "([{":
            stack.append(t)
        elif t.text in ")]}":
            if not stack or stack[-1].text != pairs[t.text]:
                problems.append(f"{path}:{t.line}:{t.col}: 括号不匹配 {t.text!r}")
            else:
                stack.pop()
    for t in stack:
        problems.append(f"{path}:{t.line}:{t.col}: 未闭合 {t.text!r}")
    return problems


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------
def selftest() -> int:
    kw = load_keywords()
    failures: list[str] = []
    total = 0

    def expect(label: str, ok: bool, detail: str = "") -> None:
        nonlocal total
        total += 1
        if not ok:
            failures.append(f"{label}{(' — ' + detail) if detail else ''}")

    # 1) 77 个关键字都能被词法识别
    soup = " ".join(sorted(kw))
    toks = significant(tokenize(soup, "<kw-soup>"))[:-1]
    expect("关键字全部可词法识别", len(toks) == 77, f"得到 {len(toks)}")
    expect("关键字文本一致", {t.text for t in toks} == kw)
    expect("符号关键字归类正确",
           all(t.kind == "KEYWORD" for t in toks if t.text in SYMBOL_KEYWORDS))

    # 2) 字面量
    lit_src = '5 -3 0xFF 0b1010 "str" b"raw" [1 2] {k:v} _'
    lit = significant(tokenize(lit_src, "<lit>"))[:-1]
    kinds = [(t.kind, t.text) for t in lit]
    expect("十进制整数", ("INT", "5") in kinds, str(kinds))
    expect("一元负号 + 整数", ("OP", "-") in kinds and ("INT", "3") in kinds)
    expect("十六进制", ("INT", "0xFF") in kinds, str(kinds))
    expect("二进制", ("INT", "0b1010") in kinds, str(kinds))
    expect("字符串", ("STRING", '"str"') in kinds, str(kinds))
    expect("原始字节串", ("BYTES", 'b"raw"') in kinds, str(kinds))
    expect("数组字面量", [t.text for t in lit if t.kind == "PUNCT"].count("[") == 1)
    expect("映射键值", [t.text for t in lit if t.kind == "PUNCT"].count(":") == 1)
    expect("空白占位符", any(t.kind == "BLANK" and t.text == "_" for t in lit))

    # 3) 注释
    cm = tokenize('a = 1 # line\n// slash\n#| block #| nested |# still |# b = 2', "<cm>")
    comments = [t.text for t in cm if t.kind == "COMMENT"]
    expect("三种注释均识别", len(comments) == 3, str(comments))
    expect("块注释可嵌套", "still" in comments[2])
    expect("注释后代码恢复", any(t.kind == "IDENT" and t.text == "b" for t in cm))
    expect("字符串内 # 不是注释",
           [t.kind for t in tokenize('"# not comment"', "<s>")] == ["STRING", "EOF"])

    # 4) 字节串不做转义：b"a\nb" 为 5 个源字符
    bt = tokenize(r'b"a\nb"', "<b>")[0]
    expect("字节串保留反斜杠", bt.kind == "BYTES" and bt.text == r'b"a\nb"', bt.text)

    # 5) 原始标识符
    ri = significant(tokenize("`free`", "<ri>"))
    expect("原始标识符绕过关键字", ri[0].kind == "RAW_IDENT" and ri[0].text == "`free`")

    # 6) 运算符最长匹配
    op_src = "a |> b -> c => d || e | f << g"
    ops = [t.text for t in significant(tokenize(op_src, "<op>")) if t.kind != "IDENT"]
    expect("最长匹配 |> / ||", ops[:5] == ["|>", "->", "=>", "||", "|"], str(ops))

    # 7) 错误路径
    for bad, why in [('"unterminated', "字符串未闭合"), ("#| x", "块注释"),
                     ("0b2", "二进制"), ("5 @ 6", None)]:
        try:
            tokenize(bad, "<bad>")
        except LexError:
            if why is None:
                failures.append(f"不应报错：{bad!r}")
        else:
            if why is not None:
                failures.append(f"应当报错：{bad!r}（{why}）")
    total += 1

    if failures:
        print(f"✗ 词法自检失败（{len(failures)}/{total}）：", file=sys.stderr)
        for f in failures:
            print("  - " + f, file=sys.stderr)
        return 1
    print(f"✓ 词法自检：{total}/{total} 通过（关键字 77、字面量 9、注释 4 类、错误路径）")
    return 0


# ---------------------------------------------------------------------------
# 示例扫描
# ---------------------------------------------------------------------------
def scan(files: list[Path]) -> int:
    kw = load_keywords()
    used: set[str] = set()
    problems: list[str] = []
    rows: list[tuple[str, int, int, int]] = []

    for f in sorted(files):
        src = f.read_text(encoding="utf-8")
        try:
            toks = tokenize(src, f.name)
        except LexError as e:
            problems.append(str(e))
            continue
        problems.extend(check_delimiters(toks, f.name))
        sig = significant(toks)
        if not sig or sig[0].text != "package":
            problems.append(f"{f.name}: 首个有效记号应为 `package`（规范 §0.3）")
        used |= {t.text for t in toks if t.kind == "KEYWORD"}
        n_comment = sum(1 for t in toks if t.kind == "COMMENT")
        rows.append((f.name, len(toks) - 1, len(sig), n_comment))

    if problems:
        print(f"✗ 示例词法检查失败（{len(problems)} 个问题）：", file=sys.stderr)
        for p in problems:
            print("  - " + p, file=sys.stderr)
        return 1

    print("✓ 示例词法检查通过：")
    for name, total, sig, cmt in rows:
        print(f"  - {name:<16} 记号 {total:>4}（有效 {sig:>3}，注释 {cmt:>2}）")

    missing = sorted(kw - used)
    covered = len(kw & used)
    print(f"✓ 示例关键词覆盖：{covered}/{len(kw)}")
    if missing:
        print("  未在示例中出现：" + " ".join(missing))
    return 0


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()

    files = [Path(a) for a in argv if not a.startswith("--")] or sorted(EXAMPLES.glob("*.ds"))

    if "--dump" in argv:
        target = Path(argv[argv.index("--dump") + 1])
        toks = tokenize(target.read_text(encoding="utf-8"), target.name)
        for t in toks:
            print(t)
        return 0

    rc = selftest()
    if rc:
        return rc
    if not files:
        print("✗ 没有可检查的 .ds 文件", file=sys.stderr)
        return 1
    return scan(files)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
