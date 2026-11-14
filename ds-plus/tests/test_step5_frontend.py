"""Step 5 (P1)：Ds+ 前端 —— base AST 等价、16 令牌、三档写法、属性兼容。"""
import dataclasses
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ds-plus"))

from dsplus.frontend import (  # noqa: E402
    DsPlusError, collect_plus_features, detect_plus_tokens, parse_program,
)
from dsv01.parser import parse_program as base_parse  # noqa: E402


def ser(x):
    if isinstance(x, list):
        return [ser(i) for i in x]
    if dataclasses.is_dataclass(x):
        return {f.name: ser(getattr(x, f.name)) for f in dataclasses.fields(x)}
    return x


def summary(node):
    feats = collect_plus_features(node)
    return {
        "regions": sorted(f[1] for f in feats if f[0] == "Region"),
        "intrinsics": [f for f in feats if f[0] == "Intrinsic"],
        "asm": [f for f in feats if f[0] == "InlineAsm"],
    }


class TestP1(unittest.TestCase):
    def test_base_ast_identical(self):
        files = ["examples/concise/hello.ds", "examples/concise/fib.ds",
                 "examples/flow/fib.dsf", "examples/tour.ds"]
        for rel in files:
            src = (ROOT / rel).read_text(encoding="utf-8")
            self.assertEqual(ser(parse_program(src, rel)), ser(base_parse(src, rel)), rel)

    def test_16_tokens(self):
        src = (ROOT / "ds-plus" / "examples" / "p1_hardware.ds").read_text(encoding="utf-8")
        prog = parse_program(src, "p1_hardware.ds")
        feats = collect_plus_features(prog)
        regions = [f for f in feats if f[0] == "Region"]
        intrinsics = [f for f in feats if f[0] == "Intrinsic"]
        asm = [f for f in feats if f[0] == "InlineAsm"]
        self.assertEqual(len(regions), 4)
        self.assertEqual(len(intrinsics), 11)   # 6 端口 IO + 2 MSR + 2 CR + @mmio
        self.assertEqual(len(asm), 2)           # @asm volatile + @asm
        self.assertEqual(len({f[0] for f in feats}), 3)
        src_tokens = (ROOT / "ds-plus" / "examples" / "p1_hardware.ds").read_text(encoding="utf-8")
        self.assertEqual({t["name"] for t in detect_plus_tokens(src_tokens)}, {
            "@asm", "@inb", "@outb", "@inw", "@outw", "@inl", "@outl",
            "@rdmsr", "@wrmsr", "@rdcr", "@wrcr", "@mmio",
            "@stack", "@static", "@raw", "@mmap",
        })
        self.assertIn(("@mmio", "mmio", 0, "u8"), [i[1:] for i in intrinsics])
        self.assertIn(("InlineAsm", "cli", True), asm)
        self.assertIn(("InlineAsm", "nop", False), asm)

    def test_three_surfaces_same_plus_features(self):
        classic = '''@stack var s: i32 = 42
fn f() {
    @outb(0x20, 0x20)
    let k = @inb(0x60)
}
'''
        concise = '''@stack s = 42
fn f() {
    @outb(0x20, 0x20)
    let k = @inb(0x60)
}
'''
        flow = '''#!flow
@stack s = 42
\\f
    @outb(0x20, 0x20)
    let k = @inb(0x60)
.
'''
        a = summary(parse_program(classic, "a.ds"))
        b = summary(parse_program(concise, "b.ds"))
        c = summary(parse_program(flow, "c.dsf"))
        self.assertEqual(a, b)
        self.assertEqual(a, c)

    def test_attributes_remain_base(self):
        for src in ('@raw fn f() {}\n', '@stack type T { x: i32 }\n', '@inb fn g() {}\n'):
            self.assertEqual(ser(parse_program(src, "attr.ds")), ser(base_parse(src, "attr.ds")), src)

    def test_literals_comments_not_rewritten(self):
        src = 'fn f() {\n    let s = "@inb(1)"\n    # @outb(1, 2)\n}\n'
        self.assertEqual(ser(parse_program(src, "x.ds")), ser(base_parse(src, "x.ds")))
        self.assertEqual(detect_plus_tokens(src), [])

    def test_region_targets(self):
        src = '''@static var g: u64 = 0x1000
@raw var dma: ptr[u8] = malloc(64)
@mmap var page: ptr[u8] = map_page(0xC0000000, 4096)
'''
        feats = collect_plus_features(parse_program(src, "regions.ds"))
        self.assertEqual(sorted(f[1] for f in feats if f[0] == "Region"),
                         ["@mmap", "@raw", "@static"])

    def test_asm_operand_inputs(self):
        prog = parse_program('@unsafe fn f() { @asm volatile("mov %0, %1", 1, 2) }\n', "x.ds")
        asm = [f for f in collect_plus_features(prog) if f[0] == "InlineAsm"]
        self.assertEqual(asm, [("InlineAsm", "mov %0, %1", True)])
        nodes = []

        def walk(x):
            if isinstance(x, list):
                for i in x: walk(i)
                return
            if dataclasses.is_dataclass(x):
                if type(x).__name__ == "InlineAsm":
                    nodes.append(x)
                for f in dataclasses.fields(x):
                    walk(getattr(x, f.name))
        walk(prog)
        self.assertEqual(len(nodes[0].inputs), 2)

    def test_bad_arity_rejected(self):
        with self.assertRaises(DsPlusError) as cm:
            parse_program('fn f() { @inb() }\n', "x.ds")
        self.assertEqual(cm.exception.code, "E_DS_PLUS_ARGS")

    def test_flow_region(self):
        src = '#!flow\n@static g = 0\n\\f\n    p @inb(0x60)\n.\n'
        feats = collect_plus_features(parse_program(src, "f.dsf"))
        self.assertIn(("Region", "@static", "AssignStmt"), feats)


if __name__ == "__main__":
    unittest.main()
