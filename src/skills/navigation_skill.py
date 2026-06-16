"""画布导航技能 — 从 GeoAgent QGIS 工具层移植的 CRS 自适应导航能力。

核心改进：
- zoom_to_layer: CRS 自适应变换（EPSG:4326 图层 → EPSG:3857 画布自动重投影）
- zoom_to_extent: 经纬度 bbox → 画布投影自动变换（LLM 直接给地名经纬度即可）
- set_center: 单点居中 + 可选比例尺
- set_scale: 直接设置比例尺分母
- refresh_canvas: 强制刷新画布（解决 XYZ 瓦片不重新拉取问题）
"""

from typing import Any, Dict

from qgis.core import (
    QgsProject,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsRectangle,
    QgsPointXY,
)
from qgis.gui import QgsMapCanvas

from skills.base_skill import BaseSkill


# ── CRS 变换工具函数（移植自 GeoAgent qgis.py）───────────────────────────

def _transform_extent_to_canvas_crs(layer, canvas, extent):
    """将图层的 extent 从其原生 CRS 变换到画布 CRS。

    解决 EPSG:4326 图层在 EPSG:3857 画布上 zoom 后白板的死穴。
    """
    if not (hasattr(layer, "crs") and hasattr(canvas, "mapSettings")):
        return extent
    try:
        src_crs = layer.crs()
        dst_crs = canvas.mapSettings().destinationCrs()
        if src_crs is None or dst_crs is None:
            return extent
        if src_crs == dst_crs:
            return extent
        transform = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
        return transform.transformBoundingBox(extent)
    except Exception:
        return extent


def _transform_bbox_to_canvas_crs(canvas, west, south, east, north, src_crs_str):
    """将 [west, south, east, north] bbox 从 src_crs 变换到画布 CRS。

    LLM 给出的地名经纬度通常是 EPSG:4326，画布可能是 EPSG:3857。
    不经变换直接 setExtent 会把经纬度当米解读，缩放到 (0,0) 附近 → 白板。
    """
    rect = QgsRectangle(west, south, east, north)
    if not hasattr(canvas, "mapSettings"):
        return rect
    try:
        src = QgsCoordinateReferenceSystem(src_crs_str)
        dst = canvas.mapSettings().destinationCrs()
        if dst is None:
            return rect
        if src == dst:
            return rect
        transform = QgsCoordinateTransform(src, dst, QgsProject.instance())
        return transform.transformBoundingBox(rect)
    except Exception:
        return rect


def _transform_point_to_canvas_crs(canvas, lon, lat, src_crs_str):
    """将经纬度点变换到画布 CRS。"""
    point = QgsPointXY(lon, lat)
    if not hasattr(canvas, "mapSettings"):
        return point
    try:
        src = QgsCoordinateReferenceSystem(src_crs_str)
        dst = canvas.mapSettings().destinationCrs()
        if dst is None:
            return point
        if src == dst:
            return point
        transform = QgsCoordinateTransform(src, dst, QgsProject.instance())
        return transform.transform(point)
    except Exception:
        return point


class NavigationSkill(BaseSkill):
    """画布导航技能：CRS 自适应缩放、居中、比例尺控制。"""

    def get_name(self) -> str:
        return "navigation"

    def get_description(self) -> str:
        return (
            "用于控制 QGIS 画布导航：缩放至图层、缩放至给定范围（经纬度自适应投影变换）、"
            "居中到指定坐标、设置比例尺、刷新画布。LLM 可直接给出地名经纬度，"
            "本技能自动完成 EPSG:4326 → 画布投影的 CRS 变换。\n"
            "参数：action（zoom_layer / zoom_extent / center / scale / refresh）、"
            "layer_name / west south east north / lat lon / scale"
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

        if canvas is None:
            return {"success": False, "message": "画布不可用"}

        # 解析 arguments（支持 JSON 和自然语言参数提取）
        parsed = self._parse_arguments(arguments)
        action = parsed.get("action", "").strip().lower()

        if action == "zoom_layer":
            return self._zoom_to_layer(canvas, parsed)
        elif action == "zoom_extent":
            return self._zoom_to_extent(canvas, parsed)
        elif action == "center":
            return self._set_center(canvas, parsed)
        elif action == "scale":
            return self._set_scale(canvas, parsed)
        elif action == "refresh":
            return self._refresh_canvas(canvas)
        elif action == "zoom_in":
            canvas.zoomIn()
            return {"success": True, "message": "已放大"}
        elif action == "zoom_out":
            canvas.zoomOut()
            return {"success": True, "message": "已缩小"}
        else:
            return {
                "success": False,
                "message": f"未知导航操作: {action}。支持: zoom_layer, zoom_extent, center, scale, refresh, zoom_in, zoom_out",
            }

    @staticmethod
    def _parse_arguments(arguments: str) -> Dict[str, Any]:
        """解析 arguments，支持 JSON 和自然语言参数提取。"""
        if not arguments or not arguments.strip():
            return {}

        import json
        import re

        arguments = arguments.strip()

        # 尝试 JSON
        if arguments.startswith("{"):
            try:
                return json.loads(arguments)
            except json.JSONDecodeError:
                pass

        result = {}

        # 正则提取常见参数
        patterns = {
            "action": r'\b(zoom_layer|zoom_extent|center|scale|refresh|zoom_in|zoom_out)\b',
            "layer_name": r'(?:图层|layer)[:=]?\s*["\x27]?([^"\',\s]+)',
            "west": r'(?:west|西|经度左)[:=]?\s*(-?[\d.]+)',
            "south": r'(?:south|南|纬度下)[:=]?\s*(-?[\d.]+)',
            "east": r'(?:east|东|经度右)[:=]?\s*(-?[\d.]+)',
            "north": r'(?:north|北|纬度上)[:=]?\s*(-?[\d.]+)',
            "lat": r'(?:lat|纬度)[:=]?\s*(-?[\d.]+)',
            "lon": r'(?:lon|lng|经度)[:=]?\s*(-?[\d.]+)',
            "scale": r'(?:scale|比例尺)[:=]?\s*([\d.]+)',
            "crs": r'(?:crs|坐标系)[:=]?\s*["\x27]?([^\s"\'",}]+)',
            "zoom_to": r'zoom_to[:=]?\s*["\x27]?([^\s"\'",}]+)',
        }

        for key, pattern in patterns.items():
            match = re.search(pattern, arguments, re.IGNORECASE)
            if match:
                val = match.group(1).strip().strip("\"'")
                if key in ("west", "south", "east", "north", "lat", "lon", "scale"):
                    try:
                        result[key] = float(val)
                    except ValueError:
                        result[key] = val
                else:
                    result[key] = val

        # 推测 action
        if "action" not in result:
            if "layer_name" in result or "zoom_to" in result:
                result["action"] = "zoom_layer"
                if "zoom_to" in result:
                    result["layer_name"] = result.pop("zoom_to")
            elif all(k in result for k in ("west", "south", "east", "north")):
                result["action"] = "zoom_extent"
            elif "lat" in result and "lon" in result:
                result["action"] = "center"
            elif "scale" in result:
                result["action"] = "scale"

        return result

    def _zoom_to_layer(self, canvas, parsed: Dict) -> Dict[str, Any]:
        """缩放至指定图层的范围（CRS 自适应变换）。"""
        from qgis.core import QgsProject

        layer_name = parsed.get("layer_name", "")
        if not layer_name:
            return {"success": False, "message": "未指定图层名称"}

        layers = QgsProject.instance().mapLayersByName(layer_name)
        if not layers:
            # 尝试模糊匹配
            all_layers = QgsProject.instance().mapLayers().values()
            for ly in all_layers:
                if layer_name.lower() in ly.name().lower():
                    layers = [ly]
                    layer_name = ly.name()
                    break
            if not layers:
                return {"success": False, "message": f"未找到图层: {layer_name}"}

        layer = layers[0]
        extent = layer.extent() if hasattr(layer, "extent") else None
        if extent is None:
            return {"success": False, "message": "无法获取图层范围"}

        # CRS 自适应变换
        extent = _transform_extent_to_canvas_crs(layer, canvas, extent)
        canvas.setExtent(extent)
        canvas.refresh()

        return {"success": True, "message": f"已缩放至图层: {layer_name}"}

    def _zoom_to_extent(self, canvas, parsed: Dict) -> Dict[str, Any]:
        """缩放至经纬度 bbox（自动 CRS 变换）。"""
        west = parsed.get("west")
        south = parsed.get("south")
        east = parsed.get("east")
        north = parsed.get("north")

        if None in (west, south, east, north):
            return {"success": False, "message": "缺少边界参数 (west/south/east/north)"}

        crs = parsed.get("crs", "EPSG:4326")
        rect = _transform_bbox_to_canvas_crs(canvas, west, south, east, north, crs)
        canvas.setExtent(rect)
        canvas.refresh()

        return {
            "success": True,
            "message": f"已缩放至 [{west}, {south}, {east}, {north}] ({crs})",
        }

    def _set_center(self, canvas, parsed: Dict) -> Dict[str, Any]:
        """居中到指定坐标。"""
        lat = parsed.get("lat")
        lon = parsed.get("lon")
        if lat is None or lon is None:
            return {"success": False, "message": "缺少 lat/lon 参数"}

        crs = parsed.get("crs", "EPSG:4326")
        point = _transform_point_to_canvas_crs(canvas, lon, lat, crs)

        if hasattr(canvas, "setCenter"):
            canvas.setCenter(point)
        else:
            return {"success": False, "message": "画布不支持 setCenter"}

        scale = parsed.get("scale")
        if scale is not None:
            canvas.zoomScale(scale)

        canvas.refresh()
        return {"success": True, "message": f"已居中至 ({lat}, {lon})"}

    def _set_scale(self, canvas, parsed: Dict) -> Dict[str, Any]:
        """设置比例尺。"""
        scale = parsed.get("scale")
        if scale is None:
            return {"success": False, "message": "缺少 scale 参数"}
        canvas.zoomScale(float(scale))
        canvas.refresh()
        return {"success": True, "message": f"比例尺已设为 1:{int(scale)}"}

    def _refresh_canvas(self, canvas) -> Dict[str, Any]:
        """强制刷新画布（解决 XYZ 瓦片不重新拉取）。"""
        canvas.refresh()
        return {"success": True, "message": "画布已刷新"}
