"""
图层样式技能 — 动态为矢量图层应用 PyQGIS 渲染器。

支持两种样式模式：
- single：统一单色渲染（点/线/面自动适配）
- graduated：基于数值字段的分级设色（choropleth map）

依赖 QGIS 内置符号体系和颜色渐变库，不产生磁盘文件。
"""

import json
from typing import Any, Dict, List

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsSingleSymbolRenderer,
    QgsGraduatedSymbolRenderer,
    QgsMarkerSymbol,
    QgsLineSymbol,
    QgsFillSymbol,
    QgsSymbol,
    QgsRendererRange,
    QgsStyle,
    QgsClassificationEqualInterval,
    QgsClassificationQuantile,
)
from qgis.PyQt.QtGui import QColor

from skills.base_skill import BaseSkill


class StyleLayerSkill(BaseSkill):
    """图层样式技能：单色 / 分级设色。"""

    def get_name(self) -> str:
        return "style_layer"

    def get_description(self) -> str:
        return (
            "用于为矢量图层动态应用渲染样式。支持 single（统一单色）和 graduated"
            "（基于数值字段的分级设色）两种模式。参数：layer_name（图层名）、"
            "style_type（single/graduated）、field（graduated 模式下的数值字段）、"
            "color（颜色名/十六进制 或 色带名，默认 blue）"
        )

    # ------------------------------------------------------------------
    # 参数解析
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_arguments(arguments: str) -> Dict[str, Any]:
        """解析 arguments 字符串，支持 JSON 和 key=value 两种格式。"""
        if not arguments or not arguments.strip():
            return {}

        s = arguments.strip()
        if s.startswith("{"):
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                pass

        params: Dict[str, Any] = {}
        for token in s.split():
            if "=" in token:
                key, _, val = token.partition("=")
                params[key.strip()] = val.strip()
        return params

    # ------------------------------------------------------------------
    # 图层查找
    # ------------------------------------------------------------------
    @staticmethod
    def _find_layer_by_name(name: str) -> QgsVectorLayer:
        """按名称查找矢量图层，找不到返回 None。"""
        for lyr in QgsProject.instance().mapLayers().values():
            if isinstance(lyr, QgsVectorLayer) and lyr.name() == name:
                return lyr
        return None

    @staticmethod
    def _list_vector_layer_names() -> List[str]:
        """返回当前工程中所有矢量图层的名称列表。"""
        return [
            lyr.name()
            for lyr in QgsProject.instance().mapLayers().values()
            if isinstance(lyr, QgsVectorLayer)
        ]

    # ------------------------------------------------------------------
    # 单色渲染
    # ------------------------------------------------------------------
    def _apply_single_style(
        self, layer: QgsVectorLayer, color_str: str
    ) -> Dict[str, Any]:
        """应用统一单色渲染，根据几何类型自动选择符号。"""
        color = QColor(color_str)
        if not color.isValid():
            return {
                "success": False,
                "message": f"无效颜色：{color_str}，请使用如 blue / red / #FF0000 等格式",
            }

        geom_type = layer.geometryType()

        if geom_type == 0:  # Point
            symbol = QgsMarkerSymbol.createSimple({})
        elif geom_type == 1:  # Line
            symbol = QgsLineSymbol.createSimple({})
        elif geom_type == 2:  # Polygon
            symbol = QgsFillSymbol.createSimple({})
        else:
            return {
                "success": False,
                "message": f"图层「{layer.name()}」的几何类型不支持单色渲染",
            }

        symbol.setColor(color)
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))

        return {"success": True, "message": f"已对「{layer.name()}」应用单色渲染（{color_str}）"}

    # ------------------------------------------------------------------
    # 分级设色
    # ------------------------------------------------------------------
    def _apply_graduated_style(
        self,
        layer: QgsVectorLayer,
        field: str,
        ramp_name: str,
    ) -> Dict[str, Any]:
        """应用基于数值字段的分级设色渲染。"""

        # 验证字段存在
        if field not in [f.name() for f in layer.fields()]:
            available = [f.name() for f in layer.fields()]
            return {
                "success": False,
                "message": (
                    f"字段「{field}」不存在于图层「{layer.name()}」中。"
                    f"可用数值字段：{available}"
                ),
            }

        # 验证字段为数值类型
        idx = layer.fields().indexOf(field)
        if not layer.fields().at(idx).isNumeric():
            return {
                "success": False,
                "message": f"字段「{field}」不是数值类型，无法用于分级设色",
            }

        # 获取色带
        color_ramp = QgsStyle.defaultStyle().colorRamp(ramp_name)
        if color_ramp is None:
            # 回退：常见色带名映射
            fallback_map = {
                "reds": "Reds",
                "blues": "Blues",
                "greens": "Greens",
                "oranges": "Oranges",
                "purples": "Purples",
                "grey": "Greys",
                "gray": "Greys",
                "red": "Reds",
                "blue": "Blues",
                "green": "Greens",
                "orange": "Oranges",
                "purple": "Purples",
            }
            resolved = fallback_map.get(ramp_name.lower(), "Blues")
            color_ramp = QgsStyle.defaultStyle().colorRamp(resolved)
            if color_ramp is None:
                return {
                    "success": False,
                    "message": (
                        f"找不到色带「{ramp_name}」。"
                        f"请使用如 Reds / Blues / Greens / Oranges / Purples 等名称"
                    ),
                }

        # 获取全量值用于分类
        values = []
        for feat in layer.getFeatures():
            val = feat[field]
            if val is not None:
                try:
                    values.append(float(val))
                except (ValueError, TypeError):
                    continue

        if not values:
            return {
                "success": False,
                "message": f"字段「{field}」没有有效数值，无法分级",
            }

        num_classes = 5

        # 使用等间隔分类（若值域过小回退到分位数）
        if max(values) - min(values) < 1e-9:
            return {
                "success": False,
                "message": f"字段「{field}」的值全相等（{min(values)}），无法分级",
            }

        classification = QgsClassificationEqualInterval()
        classification.setLabelFormat("%1 - %2")
        classification.setValues(values)
        classification.setNumberOfClasses(num_classes)

        # 如果类边界数量不足，尝试分位数
        if len(classification.classes()) < num_classes:
            classification = QgsClassificationQuantile()
            classification.setLabelFormat("%1 - %2")
            classification.setValues(values)
            classification.setNumberOfClasses(num_classes)

        class_bounds = classification.classes()
        if len(class_bounds) < 2:
            return {
                "success": False,
                "message": f"无法为字段「{field}」生成有效的分级",
            }

        # 构建符号渲染器
        geom_type = layer.geometryType()
        symbol_layer_type = {0: "Marker", 1: "Line", 2: "Fill"}.get(geom_type, "Fill")

        renderer = QgsGraduatedSymbolRenderer()
        renderer.setClassAttribute(field)
        renderer.setClassificationMethod(classification)

        # 生成分级区间和颜色
        ranges = []
        bounds = sorted(class_bounds)
        for i in range(len(bounds) - 1):
            lower = bounds[i]
            upper = bounds[i + 1]
            label = f"{lower:.2f} - {upper:.2f}"

            # 从色带中取色
            ramp_position = i / max(len(bounds) - 2, 1)
            color = color_ramp.color(ramp_position)
            color = QColor(color)

            symbol = QgsSymbol.defaultSymbol(layer.geometryType())
            symbol.setColor(color)

            render_range = QgsRendererRange(lower, upper, symbol, label)
            ranges.append(render_range)

        renderer.updateRanges(ranges)
        renderer.updateColorRamp(color_ramp)

        layer.setRenderer(renderer)

        return {
            "success": True,
            "message": (
                f"已对「{layer.name()}」应用分级设色 "
                f"（字段={field}，色带={ramp_name}，{len(ranges)} 级）"
            ),
        }

    # ------------------------------------------------------------------
    # 执行入口
    # ------------------------------------------------------------------
    def execute(
        self,
        canvas=None,
        layer_tree=None,
        arguments: str = "",
        active_layer=None,
        main_window=None,
        **kwargs,
    ) -> Dict[str, Any]:

        # ---------- 1. 解析参数 ----------
        try:
            params = self._parse_arguments(arguments)
        except Exception as e:
            return {"success": False, "message": f"参数解析失败：{e}"}

        layer_name = params.get("layer_name", "")
        style_type = params.get("style_type", "single").lower()
        field = params.get("field", "")
        color = params.get("color", "blue")

        # ---------- 2. 定位目标图层 ----------
        available = self._list_vector_layer_names()

        if layer_name:
            layer = self._find_layer_by_name(layer_name)
            if layer is None:
                return {
                    "success": False,
                    "message": (
                        f"未找到图层「{layer_name}」。"
                        f"当前可用矢量图层：{available}"
                    ),
                }
        elif active_layer is not None and isinstance(active_layer, QgsVectorLayer):
            layer = active_layer
        else:
            for lyr in QgsProject.instance().mapLayers().values():
                if isinstance(lyr, QgsVectorLayer):
                    layer = lyr
                    break
            else:
                return {
                    "success": False,
                    "message": "未找到任何矢量图层，请先加载数据",
                }

        # ---------- 3. 校验样式类型 ----------
        if style_type not in ("single", "graduated"):
            return {
                "success": False,
                "message": f"不支持的样式类型「{style_type}」，可选：single / graduated",
            }

        # ---------- 4. 执行渲染 ----------
        if style_type == "single":
            result = self._apply_single_style(layer, color)
        else:
            if not field:
                return {
                    "success": False,
                    "message": "graduated 模式必须提供 field 参数（数值字段名）",
                }
            result = self._apply_graduated_style(layer, field, color)

        # ---------- 5. 刷新画布 ----------
        if result["success"]:
            layer.triggerRepaint()
            if canvas and hasattr(canvas, "refresh"):
                canvas.refresh()

        return result
