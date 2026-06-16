"""
自动符号化渲染管理器 (Auto-Symbology Pipeline)

为 AIQGIS 注入"视觉美化基因"：
- 栅格图层：单带伪彩色渲染（Magma / Viridis / Spectral 等高级色带）
- 矢量图层：数值字段分级渲染（Equal Interval / Quantile，5 级渐变）
- 自动保存 .qgz 工程文件

作为 exec() 沙箱中的全局对象注入，AI 生成的代码可以直接调用：
    style_manager.apply_raster_pseudo_color(result_layer, "Magma")
    style_manager.apply_vector_graduated_renderer(result_layer, "人口密度", "YlOrRd")
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from qgis.core import (
    QgsClassificationEqualInterval,
    QgsClassificationQuantile,
    QgsColorRampShader,
    QgsFillSymbol,
    QgsGraduatedSymbolRenderer,
    QgsMarkerSymbol,
    QgsProject,
    QgsRasterLayer,
    QgsRasterShader,
    QgsSingleBandPseudoColorRenderer,
    QgsStyle,
    QgsVectorLayer,
)
from PyQt5.QtGui import QColor

from skills.base_skill import BaseSkill

_log = logging.getLogger("style_manager")

# ── 预置高级色带 → QGIS 内置色带名称映射 ──
# QGIS 内置色带名称（通过 QgsStyle 获取）
_PRESET_RAMPS = {
    "magma": "Magma",
    "viridis": "Viridis",
    "inferno": "Inferno",
    "plasma": "Plasma",
    "spectral": "Spectral",
    "rdylgn": "RdYlGn",
    "ylorrd": "YlOrRd",
    "ylgnbu": "YlGnBu",
    "rdbu": "RdBu",
    "pubu": "PuBu",
    "orrd": "OrRd",
    "greens": "Greens",
    "blues": "Blues",
    "coolwarm": "RdYlBu",
    "turbo": "Turbo",
}


def _resolve_color_ramp_name(name: str) -> str:
    """将用户友好名称解析为 QGIS 内置色带名。"""
    key = name.strip().lower()
    return _PRESET_RAMPS.get(key, name)


def _get_qgis_color_ramp(ramp_name: str) -> Optional[Any]:
    """从 QGIS 内置样式库获取色带对象。"""
    resolved = _resolve_color_ramp_name(ramp_name)
    style = QgsStyle.defaultStyle()
    ramp = style.colorRamp(resolved)
    if ramp is None:
        # 尝试大小写不敏感匹配
        for ramp_name_candidate in style.colorRampNames():
            if ramp_name_candidate.lower() == resolved.lower():
                return style.colorRamp(ramp_name_candidate)
    return ramp


# ═══════════════════════════════════════════════════════
# StyleManager — exec() 沙箱直接调用的模块级单例
# ═══════════════════════════════════════════════════════

class StyleManager:
    """自动符号化渲染管理器。

    提供一组零配置、开箱即用的图层美化接口。
    AI 生成的代码通过此单例为空间分析输出图层上色。
    """

    # ── 栅格伪彩色渲染 ──────────────────────────────────

    @staticmethod
    def apply_raster_pseudo_color(
        layer: QgsRasterLayer,
        color_ramp_name: str = "Magma",
        num_classes: int = 5,
    ) -> bool:
        """对单波段栅格图层应用伪彩色渲染。

        自动读取栅格数据范围（min / max），利用 QGIS 内置高级色带
        （如 Magma / Viridis / Spectral）生成连续渐变色。

        Parameters
        ----------
        layer : QgsRasterLayer
            目标栅格图层（如核密度 / 热力图 TIF）。
        color_ramp_name : str
            QGIS 内置色带名称，默认 "Magma"。
            可选：Viridis / Inferno / Plasma / Spectral / RdYlGn / YlOrRd 等。
        num_classes : int
            渐变分级数，默认 5 级。

        Returns
        -------
        bool
            渲染是否成功应用。
        """
        if layer is None or not layer.isValid():
            _log.warning("apply_raster_pseudo_color: 图层无效")
            return False

        provider = layer.dataProvider()
        if provider is None:
            _log.warning("apply_raster_pseudo_color: 无法获取数据提供者")
            return False

        # 读取波段 1 的统计值
        band = 1
        stats = provider.bandStatistics(band, QgsRasterLayer.MinMaxMin, layer.extent(), 0)
        data_min = stats.minimumValue
        data_max = stats.maximumValue

        if data_min == data_max:
            # 全常量栅格：扩展一微小值域避免除零
            data_min -= 0.001
            data_max += 0.001

        _log.info(
            "栅格伪彩色: %s, 值域 [%.4f, %.4f], 色带=%s",
            layer.name(), data_min, data_max, color_ramp_name,
        )

        # 构建色带着色器
        ramp = _get_qgis_color_ramp(color_ramp_name)
        if ramp is None:
            _log.warning("色带 '%s' 未找到，回退到 Magma", color_ramp_name)
            ramp = _get_qgis_color_ramp("Magma")

        if ramp is None:
            # 终极回退：硬编码红→黄→白渐变
            _log.error("无法加载任何 QGIS 内置色带，使用硬编码回退")
            color_ramp_shader = QgsColorRampShader(data_min, data_max)
            items = [
                QgsColorRampShader.ColorRampItem(data_min, QColor(0, 0, 0), "最低"),
                QgsColorRampShader.ColorRampItem(
                    data_min + (data_max - data_min) * 0.5,
                    QColor(200, 50, 50),
                    "中",
                ),
                QgsColorRampShader.ColorRampItem(data_max, QColor(255, 255, 100), "最高"),
            ]
            color_ramp_shader.setColorRampItemList(items)
            color_ramp_shader.classifyColorRamp()
        else:
            # QGIS 色带成功加载 → 生成分级色阶
            color_ramp_shader = QgsColorRampShader(data_min, data_max, ramp)
            items = []
            step = (data_max - data_min) / num_classes
            for i in range(num_classes):
                lower = data_min + i * step
                upper = lower + step
                value = lower + step * 0.5
                items.append(
                    QgsColorRampShader.ColorRampItem(value, ramp.color(value), f"Level {i+1}")
                )
            color_ramp_shader.setColorRampItemList(items)
            color_ramp_shader.classifyColorRamp()

        raster_shader = QgsRasterShader()
        raster_shader.setRasterShaderFunction(color_ramp_shader)

        renderer = QgsSingleBandPseudoColorRenderer(provider, band, raster_shader)
        layer.setRenderer(renderer)
        layer.triggerRepaint()

        _log.info("栅格伪彩色渲染完成: %s", layer.name())
        return True

    # ── 矢量分级渲染 ────────────────────────────────────

    @staticmethod
    def apply_vector_graduated_renderer(
        layer: QgsVectorLayer,
        column_name: str,
        color_ramp_name: str = "YlOrRd",
        num_classes: int = 5,
        mode: str = "equal_interval",
    ) -> bool:
        """对矢量图层按数值字段进行分级渲染（Choropleth / Graduated）。

        自动检测字段类型，使用 Equal Interval 或 Quantile 分类，
        配合预设色带（如 YlOrRd 黄橙红）生成 5 级渐变符号。

        Parameters
        ----------
        layer : QgsVectorLayer
            目标矢量图层（点/面）。
        column_name : str
            用于分级的数值字段名称。
        color_ramp_name : str
            QGIS 内置色带名称，默认 "YlOrRd"（黄→橙→红）。
        num_classes : int
            分级数，默认 5。
        mode : str
            分类模式："equal_interval"（等间距）或 "quantile"（分位数）。

        Returns
        -------
        bool
            渲染是否成功应用。
        """
        if layer is None or not layer.isValid():
            _log.warning("apply_vector_graduated_renderer: 图层无效")
            return False

        if not layer.isSpatial():
            _log.warning("apply_vector_graduated_renderer: 图层不是空间图层")
            return False

        # 校验字段存在且为数值类型
        field_index = layer.fields().indexOf(column_name)
        if field_index < 0:
            # 模糊匹配
            for field in layer.fields():
                if field.name().lower() == column_name.lower():
                    column_name = field.name()
                    field_index = layer.fields().indexOf(column_name)
                    break
            if field_index < 0:
                _log.warning(
                    "字段 '%s' 不存在于图层 '%s'，可用字段: %s",
                    column_name,
                    layer.name(),
                    [f.name() for f in layer.fields()],
                )
                return False

        field = layer.fields().at(field_index)
        if not field.isNumeric():
            _log.warning("字段 '%s' 不是数值类型", column_name)
            return False

        _log.info(
            "矢量分级渲染: %s, 字段=%s, 色带=%s, 模式=%s",
            layer.name(), column_name, color_ramp_name, mode,
        )

        # 选择分类器
        if mode == "quantile":
            classification = QgsClassificationQuantile()
        else:
            classification = QgsClassificationEqualInterval()

        # 获取色带
        ramp = _get_qgis_color_ramp(color_ramp_name)
        if ramp is None:
            _log.warning("色带 '%s' 未找到，回退到 YlOrRd", color_ramp_name)
            ramp = _get_qgis_color_ramp("YlOrRd")

        # 创建分级渲染器
        renderer = QgsGraduatedSymbolRenderer()
        renderer.setClassAttribute(column_name)
        renderer.setClassificationMethod(classification)
        renderer.updateClasses(layer, num_classes)

        if ramp is not None:
            renderer.updateColorRamp(ramp)

        # 补设符号（防止 QGIS 部分版本不自动创建）
        if renderer.ranges():
            geom_type = layer.geometryType()
            for rng in renderer.ranges():
                if rng.symbol() is None:
                    if geom_type == 1:  # Line
                        from qgis.core import QgsLineSymbol
                        rng.setSymbol(QgsLineSymbol.createSimple({}))
                    elif geom_type == 2:  # Polygon
                        rng.setSymbol(QgsFillSymbol.createSimple({
                            "color": "white",
                            "outline_color": "black",
                            "outline_width": "0.26",
                        }))
                    else:  # Point
                        rng.setSymbol(QgsMarkerSymbol.createSimple({
                            "color": "red",
                            "size": "2",
                        }))

        layer.setRenderer(renderer)
        layer.triggerRepaint()

        _log.info("矢量分级渲染完成: %s (%d 级)", layer.name(), num_classes)
        return True

    # ── 自动判别 ─────────────────────────────────────────

    @staticmethod
    def auto_style(
        layer: Any,
        column_name: Optional[str] = None,
        color_ramp_name: str = "Magma",
    ) -> bool:
        """自动识别图层类型并应用最佳渲染方案。

        栅格图层 → apply_raster_pseudo_color
        矢量图层 → apply_vector_graduated_renderer（需提供字段名）

        Parameters
        ----------
        layer : QgsMapLayer
            待渲染的图层。
        column_name : str, optional
            矢量分级字段名。若不提供且为矢量层，将自动选取第一个数值字段。
        color_ramp_name : str
            色带名称。

        Returns
        -------
        bool
            渲染是否成功。
        """
        if layer is None:
            return False

        if isinstance(layer, QgsRasterLayer):
            return StyleManager.apply_raster_pseudo_color(layer, color_ramp_name)

        if isinstance(layer, QgsVectorLayer):
            if column_name is None:
                # 自动选第一个数值字段
                for field in layer.fields():
                    if field.isNumeric():
                        column_name = field.name()
                        _log.info("auto_style: 自动选择字段 '%s'", column_name)
                        break
                if column_name is None:
                    _log.warning("auto_style: 矢量图层无数值字段，跳过渲染")
                    return False
            return StyleManager.apply_vector_graduated_renderer(
                layer, column_name, color_ramp_name
            )

        _log.warning("auto_style: 不支持的图层类型 %s", type(layer).__name__)
        return False

    # ── 工程自动保存 ─────────────────────────────────────

    @staticmethod
    def save_project(output_path: Optional[str] = None) -> str:
        """将当前 QGIS 工程（图层、样式、视口）保存为 .qgz 文件。

        Parameters
        ----------
        output_path : str, optional
            目标 .qgz 路径。若不提供，自动生成到 AIQGIS 项目 output/ 目录。

        Returns
        -------
        str
            实际保存的 .qgz 文件绝对路径。
        """
        if output_path is None:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            output_dir = os.path.join(project_root, "output", "projects")
            os.makedirs(output_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = os.path.join(output_dir, f"aiqgis_{timestamp}.qgz")

        project = QgsProject.instance()
        success = project.write(output_path)

        if success:
            _log.info("工程已保存: %s", output_path)
        else:
            _log.error("工程保存失败: %s", output_path)

        return output_path if success else ""


# ── 模块级单例（AI 代码通过此对象调用）──
style_manager = StyleManager()


# ═══════════════════════════════════════════════════════
# StyleManagerSkill — 注册到 SkillManager 的技能包装类
# ═══════════════════════════════════════════════════════

class StyleManagerSkill(BaseSkill):
    """自动符号化渲染技能 — 为图层提供一键美化与工程保存。

    触发词：美化图层、渲染样式、自动配色、符号化、上色、保存工程。
    """

    def get_name(self) -> str:
        return "style_manager"

    def get_description(self) -> str:
        return (
            "自动符号化渲染：为矢量图层（分级渲染）和栅格图层（伪彩色）一键上色，"
            "支持 Magma/Viridis/Spectral/YlOrRd 等 QGIS 内置高级色带。"
            "同时支持将当前工程自动保存为 .qgz 文件。"
            "触发词：美化/渲染/样式/配色/符号化/上色/保存工程"
        )

    def execute(
        self,
        canvas=None,
        layer_tree=None,
        arguments: str = "",
        active_layer=None,
        **kwargs,
    ) -> Dict[str, Any]:
        """执行自动符号化渲染。

        根据 arguments 中的关键词自动判断栅格/矢量渲染方案。
        """
        layer = active_layer
        if layer is None:
            # 尝试从工程中获取第一个图层
            layers = list(QgsProject.instance().mapLayers().values())
            if layers:
                layer = layers[0]
            else:
                return {"success": False, "message": "没有可渲染的图层"}

        # 解析参数中的字段名和色带
        arg_lower = arguments.lower()
        column_name = None
        for field in layer.fields() if isinstance(layer, QgsVectorLayer) else []:
            if field.name().lower() in arg_lower:
                column_name = field.name()
                break

        ramp_name = "Magma"
        for key in _PRESET_RAMPS:
            if key in arg_lower:
                ramp_name = _PRESET_RAMPS[key]
                break

        ok = StyleManager.auto_style(layer, column_name, ramp_name)
        if ok:
            return {
                "success": True,
                "message": f"图层 '{layer.name()}' 已自动渲染（色带: {ramp_name}）",
                "styled_layers": [layer],
            }
        return {"success": False, "message": "自动渲染失败，请检查图层类型和字段"}
