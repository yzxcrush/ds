"""B2 政策：base 只允许 ASCII 标识符。"""
import unittest
from dsv01.lexer import DsSyntaxError, tokenize


class TestUnicodePolicy(unittest.TestCase):
    def test_base_rejects_unicode_identifier(self):
        for src in ("let 变量 = 1\n", "let 🌱 = 1\n"):
            with self.assertRaises(DsSyntaxError):
                tokenize(src, "u.ds")

    def test_android_extension_is_not_base(self):
        # Android 内核有自己的 Unicode 扩展；base 词法必须拒绝。
        with self.assertRaises(DsSyntaxError):
            tokenize("let 🚀speed = 1\n", "u.ds")


if __name__ == "__main__":
    unittest.main()
