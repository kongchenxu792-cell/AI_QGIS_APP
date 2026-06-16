"""栅格样式技能 — 移植自 GeoAgent _apply_raster_symbology 的伪彩色渲染能力。

核心功能：
- 对 DEM / 单波段栅格应用伪彩色渲染器（QgsSingleBandPseudoColorRenderer）
- 内置常用色带：terrain（高程地形）、viridis（科学可视化）、grayscale（灰度）
- 自动值域检测（本地文件 bandStatistics / 远程 COG 安全默认值）
- 支持手动指定 min/max 值域和颜色
"""

from typing import Any, Dict, List, Optional, Tuple

from qgis.core import (
    QgsProject,
    QgsMapLayer,
    QgsRasterLayer,
    QgsVectorLayer,
    QgsColorRampShader,
    QgsRasterShader,
    QgsSingleBandPseudoColorRenderer,
)

from skills.base_skill import BaseSkill


# ── 色带定义 ──────────────────────────────────────────────────────────────

def _qcolor(value):
    """安全创建 QColor，失败返回 None。"""
    if value is None:
        return None
    try:
        from qgis.PyQt.QtGui import QColor
        if isinstance(value, (list, tuple)):
            return QColor(*[int(float(c)) for c in value])
        return QColor(str(value))
    except Exception:
        return None


def _palette_colors(name: str) -> List[Tuple[float, Any, str]]:
    """返回归一化的颜色断点列表 [(ratio, color, label), ...]。
    
    移植自 GeoAgent qgis.py _palette_colors。
    """
    palette = (name or "").strip().lower()
    
    if palette in {"terrain", "dem", "elevation", "earth", ""}:
        return [
            (0.0, _qcolor("#1a9850"), "low"),
            (0.35, _qcolor("#91cf60"), "lower"),
            (0.55, _qcolor("#fee08b"), "mid"),
            (0.75, _qcolor("#d08b39"), "high"),
            (1.0, _qcolor("#f5f5f5"), "highest"),
        ]
    if palette in {"viridis"}:
        return [
            (0.0, _qcolor("#440154"), "low"),
            (0.33, _qcolor("#31688e"), "mid-low"),
            (0.66, _qcolor("#35b779"), "mid-high"),
            (1.0, _qcolor("#fde725"), "high"),
        ]
    if palette in {"grayscale", "grey", "gray"}:
        return [
            (0.0, _qcolor("#000000"), "low"),
            (1.0, _qcolor("#ffffff"), "high"),
        ]
    # 默认：白 → 用户指定色
    color = _qcolor("#8c510a")
    return [(0.0, _qcolor("#ffffff"), "low"), (1.0, color, "high")]


# ── 值域检测 ──────────────────────────────────────────────────────────────

def _is_raster_layer(layer) -> bool:
    """判断是否为栅格图层。"""
    try:
        if hasattr(layer, "type") and layer.type() == QgsMapLayer.RasterLayer:
            return True
    except Exception:
        pass
    return hasattr(layer, "bandCount") and callable(getattr(layer, "bandCount"))


def _is_remote_raster(layer) -> bool:
    """判断栅格源是否为远程文件（避免 bandStatistics 阻塞 GUI）。"""
    try:
        source = str(layer.source() if hasattr(layer, "source") else "")
    except Exception:
        source = ""
    source = source.strip().lower()
    return any(source.startswith(p) for p in ("http://", "https://", "/vsicurl/"))


def _raster_value_range(layer, min_val=None, max_val=None) -> Tuple[float, float, bool]:
    """获取栅格值域。
    
    Returns:
        (min, max, estimated): estimated=True 表示使用了默认值。
    
    移植自 GeoAgent qgis.py _raster_value_range。
    """
    if min_val is not None and max_val is not None and max_val > min_val:
        return float(min_val), float(max_val), False

    if _is_remote_raster(layer):
        return (
            float(min_val or 0.0),
            float(max_val or 3000.0),
            True,
        )

    # 尝试 dataProvider().bandStatistics()
    try:
        provider = layer.dataProvider()
        stats = provider.bandStatistics(1)
        low = float(getattr(stats, "minimumValue"))
        high = float(getattr(stats, "maximumValue"))
        if high > low:
            return low, high, False
    except Exception:
        pass

    return (
        float(min_val or 0.0),
        float(max_val or 3000.0),
        True,
    )


# ── 渲染应用 ───────────────────────────────────────────────────────────────

def _apply_raster_symbology(
    layer,
    palette: str = "terrain",
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
) -> Dict[str, Any]:
    """对栅格图层应用伪彩色渲染器。
    
    移植自 GeoAgent qgis.py _apply_raster_symbology。
    """
    if not _is_raster_layer(layer):
        return {"applied": False, "reason": "不是栅格图层"}

    low, high, estimated = _raster_value_range(layer, min_value, max_value)
    stops = _palette_colors(palette)

    try:
        shader = QgsRasterShader()
        color_ramp = QgsColorRampShader()
        ramp_type = getattr(QgsColorRampShader, "Interpolated", None)
        if ramp_type is None:
            ramp_type = getattr(getattr(QgsColorRampShader, "Type", object), "Interpolated")
        color_ramp.setColorRampType(ramp_type)
        color_ramp.setColorRampItemList([
            QgsColorRampShader.ColorRampItem(
                low + ratio * (high - low),
                qcolor,
                label,
            )
            for ratio, qcolor, label in stops
        ])
        shader.setRasterShaderFunction(color_ramp)
        provider = layer.dataProvider()
        renderer = QgsSingleBandPseudoColorRenderer(provider, 1, shader)
        layer.setRenderer(renderer)
        return {
            "applied": True,
            "palette": palette,
            "band": 1,
            "min": low,
            "max": high,
            "estimated": estimated,
        }
    except Exception as e:
        return {"applied": False, "reason": str(e)}


class RasterStyleSkill(BaseSkill):
    """栅格样式技能：对 DEM/单波段栅格应用伪彩色渲染。"""

    def get_name(self) -> str:
        return "raster_style"

    def get_description(self) -> str:
        return (
            "用于对 DEM 高程栅格或单波段栅格应用伪彩色渲染器。\n"
            "内置色带：terrain（绿→黄→白 高程地形）、viridis（紫→蓝→绿→黄 科学可视化）、"
            "grayscale（黑白灰度）。自动检测值域，也可手动指定 min/max。\n"
            "参数：layer_name（图层名）、palette（色带名，默认 terrain）、"
            "min_value / max_value（可选值域）"
        )

    def execute(
        self,
        canvas=None,
        layer_tree=None,
        arguments: str = "",
        active_layer=None,
        main_window=None,
        **kwargs,
    ) -> Dict[str, Any]:
        import json
        import re

        parsed = self._parse_arguments(arguments)
        layer_name = parsed.get("layer_name", "")

        # 确定目标图层
        layer = None
        if layer_name:
            layers = QgsProject.instance().mapLayersByName(layer_name)
            if layers:
                layer = layers[0]
        if layer is None and active_layer is not None:
            layer = active_layer

        # 模糊匹配
        if layer is None and layer_name:
            for ly in QgsProject.instance().mapLayers().values():
                if layer_name.lower() in ly.name().lower():
                    layer = ly
                    break

        if layer is None:
            return {"success": False, "message": f"未找到图层: {layer_name or '未指定'}"}
        if not _is_raster_layer(layer):
            return {"success": False, "message": f"{layer.name()} 不是栅格图层"}

        palette = parsed.get("palette", "terrain")
        min_val = parsed.get("min_value")
        max_val = parsed.get("max_value")

        result = _apply_raster_symbology(
            layer,
            palette=palette,
            min_value=min_val,
            max_value=max_val,
        )

        if canvas and hasattr(canvas, "refresh"):
            canvas.refresh()

        if result.get("applied"):
            return {
                "success": True,
                "message": (
                    f"已对 {layer.name()} 应用 {palette} 色带 "
                    f"(值域 [{result['min']:.1f}, {result['max']:.1f}])"
                    + (" [估算]" if result.get("estimated") else "")
                ),
                "details": result,
            }
        else:
            return {
                "success": False,
                "message": f"样式应用失败: {result.get('reason', '未知原因')}",
            }

    @staticmethod
    def _parse_arguments(arguments: str) -> Dict[str, Any]:
        """解析 arguments。"""
        if not arguments or not arguments.strip():
            return {}

        import json
        arguments = arguments.strip()

        if arguments.startswith("{"):
            try:
                return json.loads(arguments)
            except json.JSONDecodeError:
                pass

        result = {}
        import re

        layer_match = re.search(r'(?:layer_name|图层|layer)[:=]?\s*["\x27]?([^\s"\'",}]+)', arguments, re.IGNORECASE)
        if layer_match:
            result["layer_name"] = layer_match.group(1).strip("\"'")

        palette_match = re.search(r'(?:palette|色带|色表|配色)[:=]?\s*["\x27]?(\w+)', arguments, re.IGNORECASE)
        if palette_match:
            result["palette"] = palette_match.group(1).lower()

        for key in ("min_value", "max_value"):
            pattern = rf'(?:{key}|{"最小值" if "min" in key else "最大值"})[:=]?\s*(-?[\d.]+)'
            match = re.search(pattern, arguments, re.IGNORECASE)
            if match:
                try:
                    result[key] = float(match.group(1))
                except ValueError:
                    pass

        return result
