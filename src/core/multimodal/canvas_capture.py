"""
CanvasCapture — QGIS 画布截图与空间元数据提取

防御契约 (v1.1)：
    每个 capture 方法必须返回复合 Dict，而非纯 base64 字符串。
    视口元数据注入后，LLM 可获得精确的空间尺度感知。

典型输出：
    {
        "image_base64": "data:image/png;base64,...",
        "spatial_context": {
            "crs": "EPSG:3857",
            "extent": {"xmin": 103.9, "ymin": 30.5, "xmax": 104.2, "ymax": 30.8},
            "scale": 150000.0
        }
    }
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from PyQt5.QtCore import QRect, QSize
from PyQt5.QtGui import QPainter, QPixmap

from .image_preprocessor import ImagePreprocessor

_log = logging.getLogger("multimodal.canvas_capture")


class CanvasCapture:
    """QGIS 画布截图工具 — 捕获视口像素 + 空间元数据。"""

    @staticmethod
    def capture_viewport(canvas) -> Dict[str, Any]:
        """捕获当前画布完整可见区域。

        使用 canvas.render() 离屏渲染到 QPixmap，然后通过 ImagePreprocessor
        统一转码为 base64 PNG。同时提取画布的空间元数据。

        Parameters
        ----------
        canvas : QgsMapCanvas
            QGIS 地图画布实例。

        Returns
        -------
        dict
            {
                "image_base64": "data:image/png;base64,...",
                "spatial_context": {
                    "crs": str,
                    "extent": {"xmin": float, "ymin": float, "xmax": float, "ymax": float},
                    "scale": float
                }
            }

        Raises
        ------
        ValueError
            画布尺寸为零（尚未初始化）时抛出。
        RuntimeError
            画布渲染失败时抛出。
        """
        # ── 尺寸校验 ──
        canvas_size: QSize = canvas.size()
        if canvas_size.width() <= 0 or canvas_size.height() <= 0:
            raise ValueError(
                f"画布尺寸无效 ({canvas_size.width()}×{canvas_size.height()})，"
                f"请确认 QGIS 窗口已完全初始化"
            )

        # ── 像素渲染：QPixmap + canvas.render() ──
        pixmap = QPixmap(canvas_size)
        pixmap.fill(canvas.canvasColor())  # 用画布背景色填充

        painter = QPainter(pixmap)
        try:
            # 渲染整个画布可见区到 pixmap
            canvas.render(painter)
        except Exception as exc:
            _log.error("画布渲染失败: %s", exc)
            raise RuntimeError(f"画布渲染失败: {exc}") from exc
        finally:
            painter.end()

        # ── 空间元数据提取 ──
        spatial_context = CanvasCapture._extract_spatial_context(canvas)

        # ── 图片转码 ──
        image_base64 = ImagePreprocessor.from_pixmap(pixmap)

        _log.info(
            "视口截图完成: %d×%d, CRS=%s, scale=%.0f",
            canvas_size.width(),
            canvas_size.height(),
            spatial_context["crs"],
            spatial_context["scale"],
        )

        return {
            "image_base64": image_base64,
            "spatial_context": spatial_context,
        }

    # ── 内部方法 ──

    @staticmethod
    def _extract_spatial_context(canvas) -> Dict[str, Any]:
        """从画布提取空间元数据。

        Returns
        -------
        dict
            {"crs": str, "extent": {"xmin","ymin","xmax","ymax"}, "scale": float}
        """
        # CRS
        try:
            crs = canvas.mapSettings().destinationCrs().authid()
        except Exception:
            crs = "UNKNOWN"

        # 视口范围
        try:
            extent = canvas.extent()
            extent_dict = {
                "xmin": extent.xMinimum(),
                "ymin": extent.yMinimum(),
                "xmax": extent.xMaximum(),
                "ymax": extent.yMaximum(),
            }
        except Exception:
            extent_dict = {"xmin": 0, "ymin": 0, "xmax": 0, "ymax": 0}

        # 比例尺
        try:
            scale = canvas.scale()
        except Exception:
            scale = 0.0

        return {
            "crs": crs,
            "extent": extent_dict,
            "scale": scale,
        }
