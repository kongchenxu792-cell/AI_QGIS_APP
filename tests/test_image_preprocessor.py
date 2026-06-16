"""
ImagePreprocessor 单元测试

覆盖：
    1. from_file — 本地文件加载
    2. from_pixmap — QPixmap 缩放与编码
    3. from_bytes — 原始字节解析
    4. from_data_uri — 已有 data URI 标准化
    5. _resize_if_needed — 缩放边界测试
    6. _split_data_uri — URI 解析
    7. 异常路径 — 不存在/损坏/超大/格式不支持
"""

import base64
import io
import os
import sys
import tempfile
import unittest

# ── 准备测试环境：确保 QApplication 存在 ──
from PyQt5.QtWidgets import QApplication

_app = QApplication.instance()
if _app is None:
    _app = QApplication(sys.argv)

from PyQt5.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PyQt5.QtGui import QImage, QPixmap

# 把 AIQGIS_APP 加入搜索路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.multimodal.image_preprocessor import ImagePreprocessor


class TestImagePreprocessor(unittest.TestCase):
    """ImagePreprocessor 核心功能测试"""

    @classmethod
    def setUpClass(cls):
        """创建测试用图片素材"""
        cls.tmpdir = tempfile.mkdtemp(prefix="aiqgis_test_img_")

        # 200×100 的小图（无需缩放）
        cls.small_pixmap = cls._make_test_pixmap(200, 100, Qt.red)
        cls.small_path = os.path.join(cls.tmpdir, "small.png")
        cls.small_pixmap.save(cls.small_path, "PNG")

        # 2048×1024 的大图（需要缩放至 1024）
        cls.large_pixmap = cls._make_test_pixmap(2048, 1024, Qt.blue)
        cls.large_path = os.path.join(cls.tmpdir, "large.png")
        cls.large_pixmap.save(cls.large_path, "PNG")

        # 1024×1024 的边界图（刚好等于 MAX_EDGE）
        cls.exact_pixmap = cls._make_test_pixmap(1024, 1024, Qt.green)
        cls.exact_path = os.path.join(cls.tmpdir, "exact.png")
        cls.exact_pixmap.save(cls.exact_path, "PNG")

        # JPEG 格式（测试格式统一）
        cls.jpeg_path = os.path.join(cls.tmpdir, "test.jpg")
        cls.small_pixmap.save(cls.jpeg_path, "JPEG", quality=90)

        # 无效图片（空文件）
        cls.bad_path = os.path.join(cls.tmpdir, "bad.png")
        with open(cls.bad_path, "wb") as f:
            f.write(b"not an image")

        # 不存在文件
        cls.missing_path = os.path.join(cls.tmpdir, "missing.png")

        # 不支持格式
        cls.unsupported_path = os.path.join(cls.tmpdir, "test.svg")
        with open(cls.unsupported_path, "w") as f:
            f.write("<svg></svg>")

    @staticmethod
    def _make_test_pixmap(width, height, color):
        """生成纯色测试 QPixmap"""
        pixmap = QPixmap(width, height)
        pixmap.fill(color)
        return pixmap

    # ── from_file 测试 ──

    def test_from_file_small_no_resize(self):
        """200×100 小图不触发缩放"""
        uri = ImagePreprocessor.from_file(self.small_path)
        self.assertIsInstance(uri, str)
        self.assertTrue(uri.startswith("data:image/png;base64,"))
        self.assertIn(";base64,", uri)

    def test_from_file_large_resize(self):
        """2048×1024 大图应缩放至最长边 ≤ 1024"""
        uri = ImagePreprocessor.from_file(self.large_path)
        # 解码 base64 获取像素尺寸
        raw = ImagePreprocessor._split_data_uri(uri)[1]
        img_bytes = base64.b64decode(raw)
        image = QImage.fromData(img_bytes)
        self.assertLessEqual(max(image.width(), image.height()),
                             ImagePreprocessor.MAX_EDGE + 1,  # 允许 1px 舍入
                             f"缩放后最长边应 ≤ {ImagePreprocessor.MAX_EDGE}")

    def test_from_file_exact_boundary(self):
        """1024×1024 边界图不触发缩放"""
        uri = ImagePreprocessor.from_file(self.exact_path)
        raw = ImagePreprocessor._split_data_uri(uri)[1]
        image = QImage.fromData(base64.b64decode(raw))
        self.assertLessEqual(image.width(), 1024)
        self.assertLessEqual(image.height(), 1024)

    def test_from_file_jpeg_to_png(self):
        """JPEG 自动转为 PNG"""
        uri = ImagePreprocessor.from_file(self.jpeg_path)
        self.assertTrue(uri.startswith("data:image/png;base64,"))

    def test_from_file_not_found(self):
        """不存在的文件抛出 FileNotFoundError"""
        with self.assertRaises(FileNotFoundError):
            ImagePreprocessor.from_file(self.missing_path)

    def test_from_file_unsupported_format(self):
        """不支持的格式抛出 ValueError"""
        with self.assertRaises(ValueError) as ctx:
            ImagePreprocessor.from_file(self.unsupported_path)
        self.assertIn("不支持", str(ctx.exception))

    def test_from_file_corrupt(self):
        """损坏的图片抛出 ValueError"""
        # 空 PNG 文件 QPixmap 加载会为 null
        with self.assertRaises(ValueError) as ctx:
            ImagePreprocessor.from_file(self.bad_path)
        # 可能提示无法加载或格式不支持
        self.assertIn("无法加载", str(ctx.exception).lower())

    # ── from_pixmap 测试 ──

    def test_from_pixmap_small(self):
        """小 QPixmap 直接编码，不缩放"""
        uri = ImagePreprocessor.from_pixmap(self.small_pixmap)
        self.assertTrue(uri.startswith("data:image/png;base64,"))
        # 尺寸不变
        raw = ImagePreprocessor._split_data_uri(uri)[1]
        image = QImage.fromData(base64.b64decode(raw))
        self.assertEqual(image.width(), 200)
        self.assertEqual(image.height(), 100)

    def test_from_pixmap_large_resize(self):
        """大 QPixmap 自动缩放"""
        uri = ImagePreprocessor.from_pixmap(self.large_pixmap)
        raw = ImagePreprocessor._split_data_uri(uri)[1]
        image = QImage.fromData(base64.b64decode(raw))
        self.assertLessEqual(max(image.width(), image.height()),
                             ImagePreprocessor.MAX_EDGE)

    def test_from_pixmap_null_rejects(self):
        """空 QPixmap 抛出 ValueError"""
        null_pixmap = QPixmap()
        with self.assertRaises(ValueError):
            ImagePreprocessor.from_pixmap(null_pixmap)

    # ── from_bytes 测试 ──

    def test_from_bytes_valid_png(self):
        """有效 PNG 字节解析"""
        byte_array = QByteArray()
        buffer = QBuffer(byte_array)
        buffer.open(QIODevice.ReadWrite)
        self.small_pixmap.save(buffer, "PNG")
        buffer.close()
        uri = ImagePreprocessor.from_bytes(byte_array.data())
        self.assertTrue(uri.startswith("data:image/png;base64,"))

    def test_from_bytes_invalid(self):
        """无效字节抛出 ValueError"""
        with self.assertRaises(ValueError):
            ImagePreprocessor.from_bytes(b"not an image")

    # ── from_data_uri 测试 ──

    def test_from_data_uri_jpeg_to_png(self):
        """JPEG data URI 标准化为 PNG"""
        byte_array = QByteArray()
        buffer = QBuffer(byte_array)
        buffer.open(QIODevice.ReadWrite)
        self.small_pixmap.save(buffer, "JPEG")
        buffer.close()
        b64 = base64.b64encode(byte_array.data()).decode("ascii")
        jpeg_uri = f"data:image/jpeg;base64,{b64}"
        result = ImagePreprocessor.from_data_uri(jpeg_uri)
        self.assertTrue(result.startswith("data:image/png;base64,"))

    def test_from_data_uri_missing_header(self):
        """非 data: 前缀抛出 ValueError"""
        with self.assertRaises(ValueError):
            ImagePreprocessor.from_data_uri("https://example.com/img.png")

    def test_from_data_uri_not_base64(self):
        """非 base64 编码的 data URI 抛出 ValueError"""
        with self.assertRaises(ValueError):
            ImagePreprocessor.from_data_uri("data:image/png,rawcontenthere")

    # ── _resize_if_needed 测试 ──

    def test_resize_if_needed_noop(self):
        """200×100 不触发缩放"""
        result = ImagePreprocessor._resize_if_needed(self.small_pixmap)
        self.assertEqual(result.width(), 200)
        self.assertEqual(result.height(), 100)

    def test_resize_if_needed_landscape(self):
        """2048×1024 → 1024×512（等比缩放）"""
        result = ImagePreprocessor._resize_if_needed(self.large_pixmap)
        self.assertEqual(result.width(), 1024)
        self.assertEqual(result.height(), 512)

    def test_resize_if_needed_square(self):
        """2048×2048 → 1024×1024"""
        big_square = self._make_test_pixmap(2048, 2048, Qt.blue)
        result = ImagePreprocessor._resize_if_needed(big_square)
        self.assertEqual(result.width(), 1024)
        self.assertEqual(result.height(), 1024)

    def test_resize_if_needed_portrait(self):
        """500×2000 → 256×1024"""
        tall = self._make_test_pixmap(500, 2000, Qt.blue)
        result = ImagePreprocessor._resize_if_needed(tall)
        self.assertEqual(result.width(), 256)
        self.assertEqual(result.height(), 1024)

    # ── _split_data_uri 测试 ──

    def test_split_data_uri_png(self):
        header, b64 = ImagePreprocessor._split_data_uri(
            "data:image/png;base64,abc123"
        )
        self.assertEqual(header, "data:image/png;base64")
        self.assertEqual(b64, "abc123")

    def test_split_data_uri_jpeg(self):
        header, b64 = ImagePreprocessor._split_data_uri(
            "data:image/jpeg;base64,dGVzdA=="
        )
        self.assertEqual(header, "data:image/jpeg;base64")
        self.assertEqual(b64, "dGVzdA==")

    def test_split_data_uri_invalid(self):
        """非 data URI 抛出 ValueError"""
        with self.assertRaises(ValueError):
            ImagePreprocessor._split_data_uri("not a data uri")

    def test_split_data_uri_no_base64(self):
        """无 base64 标记抛出 ValueError"""
        with self.assertRaises(ValueError):
            ImagePreprocessor._split_data_uri("data:image/png,rawdata")

    # ── 常量检查 ──

    def test_max_edge_value(self):
        """MAX_EDGE 必须为 1024（v1.1 防御契约）"""
        self.assertEqual(ImagePreprocessor.MAX_EDGE, 1024,
                         "MAX_EDGE 必须保持 1024（v1.1 防御契约）")

    def test_max_size_bytes(self):
        """MAX_SIZE_BYTES 为 20MB"""
        self.assertEqual(ImagePreprocessor.MAX_SIZE_BYTES, 20 * 1024 * 1024)

    # ── 数据完整性：往返测试 ──

    def test_roundtrip_small(self):
        """小图：from_pixmap → from_data_uri → 仍为 PNG"""
        original_uri = ImagePreprocessor.from_pixmap(self.small_pixmap)
        roundtrip = ImagePreprocessor.from_data_uri(original_uri)
        self.assertTrue(roundtrip.startswith("data:image/png;base64,"))

    # ── 清理 ──

    @classmethod
    def tearDownClass(cls):
        """清理测试临时文件"""
        import shutil
        shutil.rmtree(cls.tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
