"""图层控制技能 — 移植自 GeoAgent 的图层可见性/透明度/移除管理能力。

核心功能：
- 添加矢量图层（从文件路径加载 .shp / .gpkg / .geojson 等）
- 添加栅格图层（从文件/URL 加载 .tif / COG 等）
- 添加 XYZ 瓦片图层（OpenStreetMap / 自定义 XYZ URL）
- 设置图层可见性
- 设置图层透明度
- 移除图层
- 创建山体阴影图层（对 DEM 栅格应用 hillshade 渲染器）
"""

import os
from typing import Any, Dict, List, Optional

from qgis.core import (
    QgsProject,
    QgsMapLayer,
    QgsRasterLayer,
    QgsVectorLayer,
    QgsCoordinateReferenceSystem,
    QgsHillshadeRenderer,
)
from qgis.gui import QgsMapCanvas

from skills.base_skill import BaseSkill


# ── XYZ 瓦片数据源 URI ─────────────────────────────────────────────────

def _xyz_tile_uri(source: str, zmin: int = 0, zmax: int = 18) -> str:
    """构建 QGIS XYZ 瓦片数据源 URI。
    
    移植自 GeoAgent qgis.py _xyz_tile_uri。
    """
    templates = {
        "osm": (
            "type=xyz&url=https://tile.openstreetmap.org/"
            "{z}/{x}/{y}.png&zmax=19&zmin=0"
        ),
        "google_satellite": (
            "type=xyz&url=https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}"
        ),
        "google_terrain": (
            "type=xyz&url=https://mt1.google.com/vt/lyrs=p&x={x}&y={y}&z={z}"
        ),
        "google_hybrid": (
            "type=xyz&url=https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}"
        ),
        "carto_light": (
            "type=xyz&url=https://a.basemaps.cartocdn.com/light_all/"
            "{z}/{x}/{y}.png&zmax=19&zmin=0"
        ),
        "carto_dark": (
            "type=xyz&url=https://a.basemaps.cartocdn.com/dark_all/"
            "{z}/{x}/{y}.png&zmax=19&zmin=0"
        ),
        "esri_satellite": (
            "type=xyz&url=https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}.jpg&zmax=19&zmin=0"
        ),
        "stamen_terrain": (
            "type=xyz&url=https://stamen-tiles.a.ssl.fastly.net/terrain/"
            "{z}/{x}/{y}.jpg&zmax=16&zmin=0"
        ),
    }

    key = source.strip().lower()
    if key in templates:
        return templates[key]

    # 自定义 XYZ 模板
    if "{x}" in source or "{z}" in source:
        return f"type=xyz&url={source}&zmax={zmax}&zmin={zmin}"

    return f"type=xyz&url={source}&zmax={zmax}&zmin={zmin}"


class LayerControlSkill(BaseSkill):
    """图层控制技能：添加/移除/显示/隐藏/透明度。"""

    def get_name(self) -> str:
        return "layer_control"

    def get_description(self) -> str:
        return (
            "用于管理 QGIS 图层：添加矢量/栅格/XYZ瓦片图层、设置可见性和透明度、"
            "移除图层、创建山体阴影图层。\n"
            "参数：action（add_vector / add_raster / add_xyz / set_visibility / "
            "set_opacity / remove / hillshade）、layer_name / file_path / "
            "visible（true/false）/ opacity（0~1）"
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
        action = parsed.get("action", "").strip().lower()

        handlers = {
            "add_vector": self._add_vector,
            "add_raster": self._add_raster,
            "add_xyz": self._add_xyz,
            "set_visibility": self._set_visibility,
            "set_opacity": self._set_opacity,
            "remove": self._remove_layer,
            "hillshade": self._create_hillshade,
        }

        handler = handlers.get(action)
        if handler is None:
            return {
                "success": False,
                "message": f"未知操作: {action}。支持: {', '.join(handlers.keys())}",
            }
        return handler(canvas, parsed)

    @staticmethod
    def _parse_arguments(arguments: str) -> Dict[str, Any]:
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

        action_match = re.search(
            r'\b(add_vector|add_raster|add_xyz|set_visibility|set_opacity|remove|hillshade)\b',
            arguments, re.IGNORECASE
        )
        if action_match:
            result["action"] = action_match.group(1).lower()

        layer_match = re.search(
            r'(?:layer_name|图层|layer)[:=]?\s*["\x27]?([^\s"\'",}]+)',
            arguments, re.IGNORECASE
        )
        if layer_match:
            result["layer_name"] = layer_match.group(1).strip("\"'")

        path_match = re.search(
            r'(?:file_path|文件路径|路径|path|url|source)[:=]?\s*["\x27]?([^\s"\'",}]+)',
            arguments, re.IGNORECASE
        )
        if path_match:
            result["file_path"] = path_match.group(1).strip("\"'")

        visible_match = re.search(r'(?:visible|可见)[:=]?\s*(true|false)', arguments, re.IGNORECASE)
        if visible_match:
            result["visible"] = visible_match.group(1).lower() == "true"

        opacity_match = re.search(r'(?:opacity|透明度)[:=]?\s*([\d.]+)', arguments, re.IGNORECASE)
        if opacity_match:
            try:
                result["opacity"] = float(opacity_match.group(1))
            except ValueError:
                pass

        source_match = re.search(r'(?:source|数据源|底图|tiles)[:=]?\s*["\x27]?(\w+)', arguments, re.IGNORECASE)
        if source_match:
            result["source"] = source_match.group(1).lower()

        return result

    def _resolve_layer(self, layer_name: str):
        """解析图层名。"""
        if not layer_name:
            return None
        layers = QgsProject.instance().mapLayersByName(layer_name)
        if layers:
            return layers[0]
        for ly in QgsProject.instance().mapLayers().values():
            if layer_name.lower() in ly.name().lower():
                return ly
        return None

    def _add_vector(self, canvas, parsed: Dict) -> Dict[str, Any]:
        """添加矢量图层。"""
        file_path = parsed.get("file_path", "")
        if not file_path:
            return {"success": False, "message": "未指定文件路径"}

        if not os.path.exists(file_path):
            return {"success": False, "message": f"文件不存在: {file_path}"}

        name = parsed.get("layer_name") or os.path.splitext(os.path.basename(file_path))[0]
        layer = QgsVectorLayer(file_path, name, "ogr")

        if not layer.isValid():
            return {"success": False, "message": f"无法加载矢量图层: {file_path}"}

        QgsProject.instance().addMapLayer(layer)
        if canvas and hasattr(canvas, "refresh"):
            canvas.refresh()

        return {
            "success": True,
            "message": f"已添加矢量图层: {name}",
            "layer_name": name,
            "feature_count": layer.featureCount(),
        }

    def _add_raster(self, canvas, parsed: Dict) -> Dict[str, Any]:
        """添加栅格图层（支持本地文件和远程 COG）。"""
        file_path = parsed.get("file_path", "")
        if not file_path:
            return {"success": False, "message": "未指定文件路径"}

        # 远程 URL 不需要检查本地存在
        if not file_path.startswith(("http://", "https://", "/vsicurl/")):
            if not os.path.exists(file_path):
                return {"success": False, "message": f"文件不存在: {file_path}"}

        name = parsed.get("layer_name") or os.path.basename(file_path).rsplit(".", 1)[0]
        layer = QgsRasterLayer(file_path, name)

        if not layer.isValid():
            return {"success": False, "message": f"无法加载栅格图层: {file_path}"}

        QgsProject.instance().addMapLayer(layer)
        if canvas and hasattr(canvas, "refresh"):
            canvas.refresh()

        return {
            "success": True,
            "message": f"已添加栅格图层: {name}",
            "layer_name": name,
        }

    def _add_xyz(self, canvas, parsed: Dict) -> Dict[str, Any]:
        """添加 XYZ 瓦片图层。"""
        source = parsed.get("source", "osm")
        layer_name = parsed.get("layer_name", f"XYZ {source.title()}")

        uri = _xyz_tile_uri(source)
        layer = QgsRasterLayer(uri, layer_name, "wms")

        if not layer.isValid():
            return {"success": False, "message": f"无法加载 XYZ 瓦片: {source}"}

        QgsProject.instance().addMapLayer(layer)
        if canvas and hasattr(canvas, "refresh"):
            canvas.refresh()

        return {
            "success": True,
            "message": f"已添加 XYZ 瓦片图层: {layer_name}",
            "layer_name": layer_name,
            "source": source,
        }

    def _set_visibility(self, canvas, parsed: Dict) -> Dict[str, Any]:
        """设置图层可见性。"""
        layer_name = parsed.get("layer_name", "")
        visible = parsed.get("visible", True)

        layer = self._resolve_layer(layer_name)
        if layer is None:
            return {"success": False, "message": f"未找到图层: {layer_name}"}

        root = QgsProject.instance().layerTreeRoot()
        tree_layer = root.findLayer(layer.id())
        if tree_layer:
            tree_layer.setItemVisibilityChecked(visible)
        else:
            return {"success": False, "message": "无法操作图层树节点"}

        if canvas and hasattr(canvas, "refresh"):
            canvas.refresh()

        return {
            "success": True,
            "message": f"{'显示' if visible else '隐藏'} 图层: {layer.name()}",
        }

    def _set_opacity(self, canvas, parsed: Dict) -> Dict[str, Any]:
        """设置图层透明度。"""
        layer_name = parsed.get("layer_name", "")
        opacity = parsed.get("opacity")
        if opacity is None:
            return {"success": False, "message": "未指定透明度（0~1）"}

        opacity = max(0.0, min(1.0, float(opacity)))
        layer = self._resolve_layer(layer_name)
        if layer is None:
            return {"success": False, "message": f"未找到图层: {layer_name}"}

        if hasattr(layer, "setOpacity"):
            layer.setOpacity(opacity)
        else:
            return {"success": False, "message": "该图层不支持透明度设置"}

        if canvas and hasattr(canvas, "refresh"):
            canvas.refresh()

        return {
            "success": True,
            "message": f"图层 {layer.name()} 透明度设为 {opacity:.2f}",
        }

    def _remove_layer(self, canvas, parsed: Dict) -> Dict[str, Any]:
        """移除图层。"""
        layer_name = parsed.get("layer_name", "")
        if not layer_name:
            return {"success": False, "message": "未指定图层名称"}

        layer = self._resolve_layer(layer_name)
        if layer is None:
            return {"success": False, "message": f"未找到图层: {layer_name}"}

        removed_name = layer.name()
        QgsProject.instance().removeMapLayer(layer.id())

        if canvas and hasattr(canvas, "refresh"):
            canvas.refresh()

        return {"success": True, "message": f"已移除图层: {removed_name}"}

    def _create_hillshade(self, canvas, parsed: Dict) -> Dict[str, Any]:
        """创建山体阴影图层（对 DEM 栅格应用 hillshade 渲染）。"""
        import math

        layer_name = parsed.get("layer_name", "")
        layer = self._resolve_layer(layer_name)

        if layer is None:
            return {"success": False, "message": f"未找到图层: {layer_name}"}

        if not hasattr(layer, "dataProvider") or not hasattr(layer, "bandCount"):
            return {"success": False, "message": f"{layer.name()} 不是栅格图层"}

        provider = layer.dataProvider()
        new_name = f"[山体阴影] {layer.name()}"

        try:
            renderer = QgsHillshadeRenderer(provider, 1)
            # 默认光照参数：方位角 315°（西北），高度角 45°
            renderer.setAzimuth(315)
            renderer.setAltitude(45)
            renderer.setZFactor(1.0)
            renderer.setMultiply(1.0)
            layer.setRenderer(renderer)
        except Exception as e:
            return {"success": False, "message": f"应用山体阴影渲染失败: {e}"}

        if canvas and hasattr(canvas, "refresh"):
            canvas.refresh()

        return {"success": True, "message": f"已创建山体阴影: {layer.name()}"}
