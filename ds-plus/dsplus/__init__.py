"""Ds+ 前端（P1）：复用 Ds base parser，注入 16 个 @ 令牌的 plus AST 节点。"""
from .frontend import DsPlusError, parse_program, detect_plus_tokens
from . import ast_plus

__all__ = ["DsPlusError", "parse_program", "detect_plus_tokens", "ast_plus"]
