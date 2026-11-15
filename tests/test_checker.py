"""语义检查回归测试：明显非法代码必须在执行前被拒绝。"""
import unittest

from dsv01.parser import parse_program
from dsv01.checker import check_program, DsCheckError


def check(src):
    check_program(parse_program(src, "test.ds"))


class TestChecker(unittest.TestCase):
    def assert_error(self, src, code_fragment):
        with self.assertRaises(DsCheckError) as cm:
            check(src)
        self.assertIn(code_fragment, cm.exception.msg)

    def test_return_type_mismatch(self):
        self.assert_error('fn f() -> i32 { "x" }\np(f())\n', "返回类型不匹配")

    def test_tail_expression_type(self):
        self.assert_error('fn f() -> bool { 1 }\np(f())\n', "返回类型不匹配")

    def test_annotation_mismatch(self):
        self.assert_error('let x: i32 = "s"\np(x)\n', "类型不匹配")

    def test_missing_return(self):
        self.assert_error("fn f() -> i32 { }\np(f())\n", "没有 return")

    def test_return_without_value(self):
        self.assert_error("fn f() -> i32 { return }\np(f())\n", "需要值")

    def test_top_level_return(self):
        self.assert_error("return 1\n", "只能出现在函数内")

    def test_break_outside_loop(self):
        self.assert_error("break\n", "只能出现在循环内")

    def test_duplicate_top_let(self):
        self.assert_error("let a = 1\nlet a = 2\n", "重复定义")

    def test_duplicate_local_let(self):
        self.assert_error("fn f() { let a = 1\nlet a = 2 }\nf()\n", "重复定义")

    def test_call_argument_type(self):
        self.assert_error('fn f(a: i32) { p(a) }\nf("s")\n', "类型不匹配")

    def test_call_arity(self):
        self.assert_error("fn f(a: i32) { p(a) }\nf()\n", "参数个数不匹配")

    def test_non_bool_condition(self):
        self.assert_error('if 1 { p("yes") }\n', "条件必须是 bool")

    def test_valid_tail_if(self):
        check("fn f(n: i32) -> i32 { if n < 2 { n } else { n * 2 } }\np(f(3))\n")

    def test_valid_class_and_generics(self):
        check('class A { x: i32\n fn get(ref self) -> i32 { self.x } }\n'
              'fn show[T](x: T) -> str { "x" }\np("ok")\n')

    def test_bad_string_concat(self):
        self.assert_error('p(1 + "x")\n', "类型不匹配")


if __name__ == "__main__":
    unittest.main()
