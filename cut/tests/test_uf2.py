"""UF2 打包测试。"""
import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("uf2", ROOT / "cut" / "uf2.py")
uf2 = importlib.util.module_from_spec(spec)
sys.modules["uf2"] = uf2
spec.loader.exec_module(uf2)


class TestUF2(unittest.TestCase):
    def test_block_count_and_magic(self):
        data = bytes(range(256)) * 3
        out = uf2.bin_to_uf2(data)
        info = uf2.parse_uf2(out)
        self.assertEqual(info["blocks"], 3)
        self.assertEqual(info["num_blocks"], 3)
        self.assertEqual(info["family"], uf2.RP2350_FAMILY)
        self.assertEqual(info["end_magic"], uf2.MAGIC_END)
        self.assertEqual(info["magic"], (uf2.MAGIC0, uf2.MAGIC1))

    def test_payload_roundtrip(self):
        data = b"DsOS!" * 100
        out = uf2.bin_to_uf2(data, payload=256)
        self.assertEqual(len(out) % 512, 0)
        payloads = b"".join(out[i * 512 + 32: i * 512 + 32 + 256] for i in range(len(out) // 512))
        self.assertTrue(payloads.startswith(data[:256]))
        self.assertEqual(payloads[:len(data)], data)

    def test_empty(self):
        self.assertEqual(uf2.bin_to_uf2(b""), b"")


if __name__ == "__main__":
    unittest.main()
