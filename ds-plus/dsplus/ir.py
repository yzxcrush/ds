"""P3：Ds+ IR 与 ABI 指纹（不依赖位置的规范化形式）。"""
from __future__ import annotations

import hashlib
import json
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any

from dsv01 import ast

from . import ast_plus

ROOT = Path(__file__).resolve().parents[2]
SKIP = {"line", "col"}

PRIMITIVES = {
    "i8": (1, 1), "i16": (2, 2), "i32": (4, 4), "i64": (8, 8),
    "u8": (1, 1), "u16": (2, 2), "u32": (4, 4), "u64": (8, 8),
    "f32": (4, 4), "f64": (8, 8), "bool": (1, 1), "unit": (0, 1),
}


def to_ir(node: Any) -> Any:
    """AST → 规范化 IR（去掉行列，保留结构）。"""
    if isinstance(node, list):
        return [to_ir(x) for x in node]
    if isinstance(node, tuple):
        return [to_ir(x) for x in node]
    if not is_dataclass(node):
        return node
    if isinstance(node, ast_plus.Intrinsic):
        return {"ir": "Intrinsic", "name": node.name, "token": node.token,
                "width": node.width, "args": to_ir(node.args), "type": node.type_name}
    if isinstance(node, ast_plus.InlineAsm):
        return {"ir": "InlineAsm", "template": node.template,
                "volatile": node.volatile, "inputs": to_ir(node.inputs)}
    if isinstance(node, ast_plus.RegionAnnotated):
        return {"ir": "Region", "region": node.region, "node": to_ir(node.node)}
    out = {"ir": type(node).__name__}
    for f in fields(node):
        if f.name in SKIP:
            continue
        out[f.name] = to_ir(getattr(node, f.name))
    return out


def module_ir(prog: ast.Program) -> dict:
    return {"ir": "Module", "package": prog.package,
            "uses": to_ir(prog.uses), "items": to_ir(prog.items)}


def canonical(node: Any) -> str:
    return json.dumps(node, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def ir_hash(prog: ast.Program) -> str:
    return hashlib.sha256(canonical(module_ir(prog)).encode("utf-8")).hexdigest()


def abi_fingerprint(target: str = "x86_64-linux-gnu", layout: str = "repr(Ds)") -> dict:
    abi = json.loads((ROOT / "ds-core" / "abi" / "abi.json").read_text(encoding="utf-8"))
    tgt = next((t for t in abi["build_targets"] if t["triple"] == target), None)
    if tgt is None:
        raise ValueError(f"未知 target: {target}")
    ptr = 4 if target.startswith(("thumbv7em", "riscv32", "wasm32")) else 8
    sizes = {k: {"size": v[0], "align": v[1]} for k, v in PRIMITIVES.items()}
    sizes["ptr"] = {"size": ptr, "align": ptr}
    return {
        "target": target,
        "abi": tgt["abi"],
        "layout": layout,
        "pointer": {"size": ptr, "align": ptr},
        "primitives": sizes,
        "c_layout_selector": abi["c_layout"],
        "ds_default_layout": abi["default_layout"],
        "bare_extern_abi": abi["bare_extern_abi"],
    }


def fingerprint_hash(fp: dict) -> str:
    return hashlib.sha256(canonical(fp).encode("utf-8")).hexdigest()
