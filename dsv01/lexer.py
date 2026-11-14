# -*- coding: utf-8 -*-
"""Ds v0.1 词法分析器（驱动内部使用）。

与 `tools/dslex.py`（规范自检器）保持同一套规则，但这里服务于解析器：
注释与换行也保留为 token，由解析器决定如何跳过。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

# 符号式关键字（在 §1.3 中与字母关键字同属 77 项）
SYMBOL_KEYWORDS = {"@", "->", "=>", "|>"}

# 兜底关键字表（与 spec/keywords.json 一致；__init__ 中有一致性测试）
FALLBACK_KEYWORDS = frozenset({
    "fn", "let", "var", "type", "class", "trait", "impl", "mod", "package",
    "if", "else", "loop", "while", "for", "break", "continue", "return", "goto",
    "->", "=>", "|>",
    "try", "catch", "panic", "recover", "assert", "res", "opt",
    "use", "as", "export", "pub", "priv", "prot", "static", "extern",
    "spawn", "go", "thread", "chan", "send", "recv", "mutex", "wait",
    "raw", "free", "alloc", "rc", "arc", "gc", "ptr", "ref", "mut",
    "@", "asm", "volatile", "at", "irq", "section", "packed",
    "comptime", "macro", "typeinfo", "attr",
    "self", "super", "new", "drop", "extends", "dyn",
    "match", "when", "where", "in", "is", "sizeof", "alignof",
})

_SPEC_INDEX = Path(__file__).resolve().parent.parent / "spec" / "keywords.json"


def load_keywords() -> frozenset[str]:
    """优先读取 spec/keywords.json，保证驱动与规范不漂移。"""
    try:
        data = json.loads(_SPEC_INDEX.read_text(encoding="utf-8"))
        words = frozenset(e["word"] for e in data["alphabetical"])
        if len(words) == 77:
            return words
    except Exception:
        pass
    return FALLBACK_KEYWORDS


KEYWORDS = load_keywords()

# 字符级运算符表（按长度降序匹配；`[]` 是标点不是单一 token）
OPS = [
    "|>", "->", "=>", "<<=", ">>=", "<<", ">>", "<=", ">=", "==", "!=", "&&", "||",
    "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "..",
    "+", "-", "*", "/", "%", "=", "!", "<", ">", "&", "|", "^", "~", ".", "@",
    "\\", "?",
]
_OPS_SORTED = sorted(OPS, key=len, reverse=True)
PUNCT = set("(){}[],:;")

KEYWORD, IDENT, RAW_IDENT = "KEYWORD", "IDENT", "RAW_IDENT"
INT, FLOAT, STRING, BYTES = "INT", "FLOAT", "STRING", "BYTES"
OP, PUNCT_KIND, BLANK = "OP", "PUNCT", "BLANK"
FSTRING = "FSTRING"
COMMENT, NEWLINE, EOF = "COMMENT", "NEWLINE", "EOF"

_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", '"': '"', "0": "\0"}


@dataclass
class Token:
    kind: str
    text: str
    line: int
    col: int

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"Token({self.kind}, {self.text!r}, {self.line}:{self.col})"


class DsSyntaxError(Exception):
    """词法/语法错误（CLI 统一转成退出码 1）。"""

    def __init__(self, msg: str, filename: str = "<source>", line: int = 0, col: int = 0):
        super().__init__(f"{filename}:{line}:{col}: {msg}")
        self.msg, self.filename, self.line, self.col = msg, filename, line, col


def _decode_string(raw: str, filename: str, line: int, col: int) -> str:
    """raw 形如 "a\\nb"（含引号），按 §3.4 规则解码。"""
    out: list[str] = []
    i, n = 1, len(raw) - 1
    while i < n:
        c = raw[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        i += 1
        e = raw[i]
        if e in _ESCAPES:
            out.append(_ESCAPES[e])
            i += 1
        elif e == "x":
            out.append(chr(int(raw[i + 1:i + 3], 16)))
            i += 3
        elif e == "u" and raw[i + 1] == "{":
            j = raw.index("}", i)
            out.append(chr(int(raw[i + 2:j], 16)))
            i = j + 1
        else:  # 理论上词法阶段已拦截
            raise DsSyntaxError(f"未知转义 \\{e}", filename, line, col)
    return "".join(out)


def tokenize(src: str, filename: str = "<source>") -> list[Token]:
    toks: list[Token] = []
    ops = _OPS_SORTED
    kw = KEYWORDS
    i, line, line_start = 0, 1, 0
    n = len(src)

    def err(msg: str, at: int | None = None):
        at = i if at is None else at
        return DsSyntaxError(msg, filename, line, at - line_start + 1)

    def push(kind: str, text: str, start: int) -> None:
        toks.append(Token(kind, text, line, start - line_start + 1))

    while i < n:
        c = src[i]

        if c == "\n":
            push(NEWLINE, "\n", i)
            i += 1
            line += 1
            line_start = i
            continue
        if c in " \t\r":
            i += 1
            continue

        # 注释
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
            push(COMMENT, src[start:i], start)
            continue
        if c == "#" or src.startswith("//", i):
            start = i
            while i < n and src[i] != "\n":
                i += 1
            push(COMMENT, src[start:i], start)
            continue

        # 字符串
        if c == '"':
            start, j = i, i + 1
            buf = ['"']
            while j < n:
                ch = src[j]
                if ch == "\n":
                    raise err("字符串不可含裸换行", start)
                if ch == "\\":
                    e = src[j + 1] if j + 1 < n else ""
                    if e in _ESCAPES:
                        buf.append(ch + e)
                        j += 2
                    elif e == "x" and re.fullmatch(r"[0-9a-fA-F]{2}", src[j + 2:j + 4]):
                        buf.append(src[j:j + 4])
                        j += 4
                    elif e == "u" and src.startswith("{", j + 2):
                        k = src.find("}", j)
                        if k < 0:
                            raise err("非法 \\u{...} 转义", start)
                        buf.append(src[j:k + 1])
                        j = k + 1
                    else:
                        raise err(f"未知转义 \\{e}", start)
                    continue
                if ch == '"':
                    buf.append('"')
                    j += 1
                    break
                buf.append(ch)
                j += 1
            else:
                raise err("字符串未闭合", start)
            raw = "".join(buf)
            val = _decode_string(raw, filename, line, start - line_start + 1)
            toks.append(Token(STRING, val, line, start - line_start + 1))
            i = j
            continue

        # 原始字节串 b"..."
        if c == "b" and src.startswith('b"', i):
            start = i
            j = src.find('"', i + 2)
            if j < 0:
                raise err("字节串未闭合", start)
            payload = src[i + 2:j]
            toks.append(Token(BYTES, payload.encode("utf-8"), line, start - line_start + 1))
            i = j + 1
            continue

        # 插值字符串 f"...{expr}..."
        if c in ("f", "F") and i + 1 < n and src[i + 1] == '"':
            start = i
            j = i + 2
            buf = []
            while j < n:
                ch = src[j]
                if ch == "\\":
                    buf.append(src[j:j + 2])
                    j += 2
                    continue
                if ch == "\n":
                    raise err("字符串不可含裸换行", start)
                if ch == '"':
                    j += 1
                    break
                buf.append(ch)
                j += 1
            else:
                raise err("字符串未闭合", start)
            toks.append(Token(FSTRING, "".join(buf), line, start - line_start + 1))
            i = j
            continue

        # 原始标识符 `名`
        if c == "`":
            start = i
            j = src.find("`", i + 1)
            if j <= i + 1:
                raise err("原始标识符必须非空且以反引号闭合", start)
            body = src[i + 1:j]
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", body):
                raise err("原始标识符内容非法", start)
            toks.append(Token(RAW_IDENT, body, line, start - line_start + 1))
            i = j + 1
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
                text = src[start:i]
                if i < n and src[i] == ".":
                    m2 = re.match(r"\.[0-9a-fA-F_]+", src[i:])
                    if m2:
                        i += m2.end()
                        text = src[start:i]
                        if i < n and src[i] in "pP":
                            m3 = re.match(r"[pP][+-]?\d+", src[i:])
                            if not m3:
                                raise err("十六进制浮点指数非法", start)
                            i += m3.end()
                            text = src[start:i]
                        toks.append(Token(FLOAT, float.fromhex(text.replace("_", "")),
                                          line, start - line_start + 1))
                        continue
                toks.append(Token(INT, int(text.replace("_", ""), 16),
                                  line, start - line_start + 1))
                continue
            if src.startswith(("0b", "0B"), i):
                i += 2
                m = re.match(r"[01_]+", src[i:])
                if not m:
                    raise err("二进制字面量缺少 0/1", start)
                i += m.end()
                if i < n and re.match(r"[0-9]", src[i]):
                    raise err("二进制字面量含非法数字", start)
                toks.append(Token(INT, int(src[start + 2:i].replace("_", ""), 2),
                                  line, start - line_start + 1))
                continue
            m = re.match(r"[0-9_]+", src[i:])
            i += m.end()
            text = src[start:i]
            is_float = False
            if i < n and src[i] == "." and i + 1 < n and src[i + 1].isdigit():
                m2 = re.match(r"\.[0-9_]+", src[i:])
                i += m2.end()
                text = src[start:i]
                is_float = True
            if i < n and src[i] in "eE":
                m3 = re.match(r"[eE][+-]?[0-9_]+", src[i:])
                if m3:
                    i += m3.end()
                    text = src[start:i]
                    is_float = True
            if is_float:
                toks.append(Token(FLOAT, float(text.replace("_", "")),
                                  line, start - line_start + 1))
            else:
                toks.append(Token(INT, int(text.replace("_", "")),
                                  line, start - line_start + 1))
            continue

        # 标识符 / 关键字 / 空白占位符（规范 §1.1：仅 ASCII [A-Za-z_][A-Za-z0-9_]*）
        if c.isascii() and (c.isalpha() or c == "_"):
            start = i
            while i < n and src[i].isascii() and (src[i].isalnum() or src[i] == "_"):
                i += 1
            text = src[start:i]
            if text == "_":
                push(BLANK, text, start)
            elif text in kw:
                push(KEYWORD, text, start)
            else:
                push(IDENT, text, start)
            continue

        # 运算符（最长匹配）
        for op in ops:
            if src.startswith(op, i):
                start = i
                i += len(op)
                push(KEYWORD if op in SYMBOL_KEYWORDS else OP, op, start)
                break
        else:
            if c in PUNCT:
                push(PUNCT_KIND, c, i)
                i += 1
                continue
            raise err(f"未知字符 {c!r}")

    toks.append(Token(EOF, "", line, i - line_start + 1))
    return toks


def significant(tokens: list[Token]) -> list[Token]:
    return [t for t in tokens if t.kind not in (COMMENT, NEWLINE)]
