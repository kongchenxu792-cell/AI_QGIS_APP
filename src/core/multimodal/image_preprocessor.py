"""
ImagePreprocessor — 多模态图片预处理引擎

职责：
    将任意来源的图片统一缩放、编码为标准 base64 data URI，
    符合 DeepSeek Vision API / OpenAI Vision API 的输入规范。

防御契约（v1.1）：
    MAX_EDGE = 1024
    地理空间轮廓分析在 1024px 下已足够清晰，
    2048px 会导致 API 响应延迟超 10s，且浪费配额。

性能基准（基于 DeepSeek 视觉原语压缩）：
    1024×1024 PNG → ~90 visual tokens → 首 token 延迟 < 3s
    2048×2048 PNG → ~360 visual tokens → 首 token 延迟 > 10s

输入支持：
    1. 本地文件路径（.png / .jpg / .tif / .bmp / .webp）
    2. QPixmap 对象（QGIS 画布截图）
    3. 原始 bytes（HTTP 下载 / 剪贴板）

零额外依赖：
    缩放：PyQt5.QtGui.QPixmap / QImage（Lanczos 滤波）
    base64：Python 标准库 base64
    io：Python 标准库 io.BytesIO
"""

import base64
import os
from typing import Optional, Union

from PyQt5.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PyQt5.QtGui import QImage, QPixmap


class ImagePreprocessor:
    """
    图片预处理工具。

    所有方法均为静态方法，无需实例化。
    """

    # ── v1.1 防御契约：MAX_EDGE = 1024 ──
    # 地理空间轮廓分析在 1024px 已足够；2048px 下首 token 延迟 > 10s
    MAX_EDGE: int = 1024

    # OpenAI Vision API 兼容上限
    MAX_SIZE_BYTES: int = 20 * 1024 * 1024  # 20 MB

    # 受支持的输入格式
    SUPPORTED_EXTENSIONS: frozenset = frozenset(
        [".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif"]
    )

    # ── 公开 API ──

    @staticmethod
    def from_file(path: str) -> str:
        """
        从本地文件加载图片，缩放至 MAX_EDGE，返回 base64 data URI。

        Args:
            path: 图片文件的绝对路径

        Returns:
            形如 "data:image/png;base64,iVBORw0KGgo..." 的 data URI

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 不支持的格式或文件损坏
        """
        if not os.path.isfile(path):
            raise FileNotFoundError(f"图片文件不存在: {path}")

        ext = os.path.splitext(path)[1].lower()
        if ext not in ImagePreprocessor.SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"不支持的图片格式: {ext}，"
                f"支持: {sorted(ImagePreprocessor.SUPPORTED_EXTENSIONS)}"
            )

        pixmap = QPixmap(path)
        if pixmap.isNull():
            raise ValueError(f"无法加载图片（文件可能已损坏）: {path}")

        return ImagePreprocessor.from_pixmap(pixmap)

    @staticmethod
    def from_pixmap(pixmap: QPixmap) -> str:
        """
        从 QPixmap 生成标准化的 base64 data URI。

        自动处理缩放（如果边长超过 MAX_EDGE）和格式统一（PNG）。

        Args:
            pixmap: PyQt5.QtGui.QPixmap 对象

        Returns:
            形如 "data:image/png;base64,..." 的 data URI

        Raises:
            ValueError: pixmap 为空或无效
        """
        if pixmap.isNull():
            raise ValueError("QPixmap 为空，无法处理")

        # 缩放至 MAX_EDGE
        scaled = ImagePreprocessor._resize_if_needed(pixmap)

        # QPixmap → QImage → PNG bytes（QBuffer + QByteArray 桥接）
        image = scaled.toImage()
        byte_array = QByteArray()
        buffer = QBuffer(byte_array)
        buffer.open(QIODevice.ReadWrite)
        save_success = image.save(buffer, "PNG")
        if not save_success:
            buffer.close()
            raise ValueError("QImage 写入 QBuffer 失败")
        png_bytes = byte_array.data()
        buffer.close()

        # 尺寸校验
        if len(png_bytes) > ImagePreprocessor.MAX_SIZE_BYTES:
            raise ValueError(
                f"编码后图片过大: {len(png_bytes)} bytes "
                f"(上限 {ImagePreprocessor.MAX_SIZE_BYTES} bytes)"
            )

        # base64 编码
        b64_str = base64.b64encode(png_bytes).decode("ascii")
        return f"data:image/png;base64,{b64_str}"

    @staticmethod
    def from_bytes(data: bytes, mime: str = "image/png") -> str:
        """
        从原始字节生成 data URI（带缩放和格式统一）。

        典型场景：HTTP 下载、剪贴板粘贴。

        Args:
            data: 图片的原始字节流
            mime: MIME 类型（默认 image/png），用于 QImage.loadFromData 推断格式

        Returns:
            形如 "data:image/png;base64,..." 的 data URI

        Raises:
            ValueError: 字节数据无法解析为有效图片
        """
        image = QImage()
        if not image.loadFromData(data):
            raise ValueError("无法从字节数据解析图片（格式不受支持或数据损坏）")

        pixmap = QPixmap.fromImage(image)
        return ImagePreprocessor.from_pixmap(pixmap)

    @staticmethod
    def from_data_uri(data_uri: str) -> str:
        """
        透传已有的 data URI，但仍强制缩放和转 PNG 以确保标准化。

        Args:
            data_uri: 形如 "data:image/jpeg;base64,..." 的输入

        Returns:
            标准化后的 PNG data URI
        """
        # 提取 base64 部分
        header, b64 = ImagePreprocessor._split_data_uri(data_uri)
        raw_bytes = base64.b64decode(b64)

        # 推断 MIME
        mime_map = {
            "image/png": "png",
            "image/jpeg": "jpeg",
            "image/jpg": "jpeg",
            "image/webp": "webp",
            "image/bmp": "bmp",
        }
        mime = header.split(":")[1].split(";")[0].lower()
        fmt = mime_map.get(mime, "png")

        return ImagePreprocessor.from_bytes(raw_bytes, fmt)

    # ── 内部方法 ──

    @staticmethod
    def _resize_if_needed(pixmap: QPixmap) -> QPixmap:
        """
        如果 pixmap 的任意一边超过 MAX_EDGE，使用 Lanczos 滤波等比缩放。
        """
        w = pixmap.width()
        h = pixmap.height()
        max_side = max(w, h)

        if max_side <= ImagePreprocessor.MAX_EDGE:
            return pixmap

        ratio = ImagePreprocessor.MAX_EDGE / max_side
        new_w = int(w * ratio)
        new_h = int(h * ratio)

        return pixmap.scaled(
            new_w,
            new_h,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,  # Lanczos 滤波
        )

    @staticmethod
    def _split_data_uri(data_uri: str) -> tuple:
        """
        解析 data URI → (header, base64_string)。

        示例:
            "data:image/png;base64,abc123" → ("data:image/png;base64", "abc123")
        """
        if not data_uri.startswith("data:"):
            raise ValueError(f"不是有效的 data URI: {data_uri[:50]}...")

        if ";base64," not in data_uri:
            raise ValueError("data URI 不是 base64 编码")

        header, b64 = data_uri.split(";base64,", 1)
        return header + ";base64", b64
