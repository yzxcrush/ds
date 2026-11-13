# -*- coding: utf-8 -*-
"""Ds v0.1 —— 语言定义 + Python 参考驱动。

在 Python 中直接使用：

    import dsv01
    dsv01.run_source('package demo\\nfn main() { println("hi") }')
    dsv01.run_file('examples/tour.ds')

命令行：

    dscc examples/tour.ds --app        # 编译器风格
    ds  examples/tour.ds               # Python 风格
    ds                                 # REPL
"""

from __future__ import annotations

from . import ast, builtins, lexer, parser
from .interp import Env, Interpreter
from .lexer import DsSyntaxError, tokenize

__version__ = "0.1.0"
__all__ = [
    "run_source", "run_file", "Interpreter", "Env", "tokenize",
    "DsSyntaxError", "DsRuntimeError", "DsPanic", "Opt", "Res", "UNIT", "NONE",
    "ast", "lexer", "parser",
]

# 运行时值/异常直接从 builtins 暴露，方便 Python 侧断言
UNIT = builtins.UNIT
NONE = builtins.NONE
Opt = builtins.Opt
Res = builtins.Res
DsRuntimeError = builtins.DsRuntimeError
DsPanic = builtins.DsPanic


def run_source(src: str, filename: str = "<string>", **options):
    """执行一段 Ds 源码，返回 main 的返回值（无 main 时为 unit）。"""
    interp = Interpreter(filename=filename, **options)
    return interp.run_source(src, filename)


def run_file(path: str, **options):
    """执行一个 .ds 文件。"""
    interp = Interpreter(**options)
    return interp.run_file(path)
