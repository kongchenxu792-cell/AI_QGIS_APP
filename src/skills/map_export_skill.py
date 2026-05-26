"""
地图导出技能 - 将当前地图画布导出为 PNG/JPG/PDF 文件。

继承 BaseSkill，由 SkillManager 自动发现注册。
使用 QGIS 原生渲染引擎导出高质量地图画面。
"""

import os
from datetime import datetime
from typing import Any, Dict

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPainter
from PyQt5.QtWidgets import QMessageBox, QFileDialog

from qgis.core import (
    QgsMapSettings,
    QgsMapRendererCustomPainterJob,
)

from skills.base_skill import BaseSkill


class MapExportSkill(BaseSkill):
    """地图导出技能：将画布视图导出为图片或 PDF。"""

    def get_name(self) -> str:
        return "map_export"

    def get_description(self) -> str:
        return (
            "- 用途：导出当前地图画布为图片（PNG/JPG）或 PDF 文件\n"
            "- 触发词：导出、保存、截图、图片、PDF、输出、保存画面、\n"
            "  导出地图、保存到桌面、高清图、截图保存、打印\n"
            "- 注意：默认保存到桌面，文件名包含时间戳\n"
            "- arguments 可以是用户指定的路径或文件名，为空则自动使用桌面默认路径"
        )

    def execute(
        self,
        canvas=None,
        layer_tree=None,
        arguments: str = "",
        main_window=None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        导出地图画布到文件。

        Parameters
        ----------
        canvas : QgsMapCanvas, optional
            地图画布。
        arguments : str
            用户指令（可含路径、格式、DPI 如"导出为300dpi"）。
        main_window : QWidget, optional
            用于显示消息框的父窗口。

        Returns
        -------
        dict
            {"success": bool, "message": str, "file_path": str or None}
        """
        if canvas is None:
            return {"success": False, "message": "地图画布未初始化"}

        if canvas.layerCount() == 0:
            return {"success": False, "message": "画布中没有图层，请先加载数据"}

        # ── 弹出保存对话框让用户选路径 ──
        desktop = os.path.expanduser("~/Desktop")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"GIS_Export_{timestamp}.png"

        file_path, _ = QFileDialog.getSaveFileName(
            main_window,
            "导出地图",
            os.path.join(desktop, default_name),
            "PNG 图片 (*.png);;JPEG 图片 (*.jpg);;PDF 文件 (*.pdf)",
        )
        if not file_path:
            return {"success": False, "message": "用户取消了导出"}

        # ── 解析 DPI ──
        dpi = self._parse_dpi(arguments)

        ext = os.path.splitext(file_path)[1].lower()
        if ext not in (".png", ".jpg", ".jpeg", ".pdf"):
            file_path += ".png"
            ext = ".png"

        # ── 导出 ──
        try:
            if ext == ".pdf":
                success = self._export_pdf(canvas, file_path, dpi)
            else:
                success = self._export_image(canvas, file_path, ext, dpi)

            if not success:
                return {"success": False, "message": "导出失败"}

            parent = main_window
            msg = QMessageBox(parent)
            msg.setWindowTitle("导出成功")
            msg.setIcon(QMessageBox.Information)
            msg.setText("地图已成功导出！")
            msg.setInformativeText(f"文件位置：{file_path}\n分辨率：{dpi} DPI")
            msg.setStandardButtons(QMessageBox.Ok)
            msg.setModal(False)
            msg.show()

            return {
                "success": True,
                "message": f"地图已导出到：{file_path}（{dpi} DPI）",
                "file_path": file_path,
            }
        except Exception as e:
            return {"success": False, "message": f"导出异常：{e}"}

    # ── 内部方法 ──────────────────────────────────────────

    def _parse_dpi(self, arguments: str) -> int:
        """
        解析 DPI 参数。
        识别关键词：超清=600, 高清=300, 清晰=200, 或显式"300dpi"。
        """
        import re

        dpi = 150
        if not arguments:
            return dpi

        m = re.search(r"(\d+)\s*dpi", arguments, re.IGNORECASE)
        if m:
            return max(72, min(1200, int(m.group(1))))

        kw = {"超清": 600, "高清": 300, "清晰": 200, "超高": 600, "ultra": 600, "high": 300}
        for k, v in kw.items():
            if k in arguments:
                dpi = max(dpi, v)
        return dpi

    def _export_image(self, canvas, file_path: str, ext: str, dpi: int = 150) -> bool:
        """使用 QgsMapRendererCustomPainterJob 高 DPI 导出图片。"""
        settings = canvas.mapSettings()
        size = settings.outputSize()

        # 按目标 DPI 缩放
        orig_dpi = settings.outputDpi()
        scale = dpi / orig_dpi
        export_size = size * scale

        image = QImage(export_size, QImage.Format_ARGB32_Premultiplied)
        image.setDotsPerMeterX(int(dpi * 39.37))
        image.setDotsPerMeterY(int(dpi * 39.37))
        image.fill(Qt.white)

        # 临时修改 DPI 渲染
        settings.setOutputDpi(dpi)
        settings.setOutputSize(export_size)

        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)

        job = QgsMapRendererCustomPainterJob(settings, painter)
        job.start()
        job.waitForFinished()
        painter.end()

        # 恢复原始设置
        settings.setOutputDpi(orig_dpi)
        settings.setOutputSize(size)

        fmt = "PNG" if ext in (".png",) else "JPEG"
        quality = 95 if fmt == "JPEG" else -1
        return image.save(file_path, fmt, quality)

    def _export_pdf(self, canvas, file_path: str, dpi: int = 150) -> bool:
        """导出为矢量 PDF。"""
        from PyQt5.QtGui import QPdfWriter, QPageSize

        settings = canvas.mapSettings()
        size = settings.outputSize()

        writer = QPdfWriter(file_path)
        writer.setPageSize(QPageSize(size, QPageSize.Point))
        writer.setResolution(dpi)

        painter = QPainter(writer)
        job = QgsMapRendererCustomPainterJob(settings, painter)
        job.start()
        job.waitForFinished()
        painter.end()

        return True