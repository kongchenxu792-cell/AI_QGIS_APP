"""图层检查技能 — 移植自 GeoAgent 的数据探索能力。

核心功能：
- list_layers: 列出所有图层的元数据（名称/类型/CRS/范围/要素数/是否可见/透明度）
- inspect_fields: 检查指定图层的字段列表（字段名/类型/长度）
- layer_summary: 获取图层的统计摘要（范围/CRS/要素数/几何类型/字段数）
- get_selected: 获取选中要素的属性
- select_by_expression: 按表达式选择要素
- clear_selection: 清除选择
"""

from typing import Any, Dict, List, Optional

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsMapLayer,
    QgsFeatureRequest,
    QgsExpression,
)

from skills.base_skill import BaseSkill


def _layer_metadata(layer) -> dict:
    """收集图层可序列化元数据（移植自 GeoAgent _layer_metadata）。"""
    record = {}
    try:
        record["id"] = str(layer.id()) if hasattr(layer, "id") else None
        record["name"] = layer.name() if hasattr(layer, "name") else str(layer)
        record["type"] = (
            str(layer.type()) if hasattr(layer, "type") else type(layer).__name__
        )
        record["source"] = layer.source() if hasattr(layer, "source") else None

        if hasattr(layer, "crs") and layer.crs():
            crs = layer.crs()
            record["crs"] = crs.authid() if hasattr(crs, "authid") else str(crs)

        if hasattr(layer, "extent"):
            extent = layer.extent()
            record["extent"] = [
                extent.xMinimum(), extent.yMinimum(),
                extent.xMaximum(), extent.yMaximum(),
            ]

        if isinstance(layer, QgsVectorLayer):
            record["feature_count"] = layer.featureCount()
            record["geometry_type"] = layer.geometryType()

        record = {k: v for k, v in record.items() if v is not None}
    except Exception as e:
        record["error"] = str(e)
    return record


def _field_info(layer: QgsVectorLayer) -> List[dict]:
    """获取字段信息列表。"""
    fields = []
    try:
        for field in layer.fields():
            fields.append({
                "name": field.name(),
                "type": field.typeName(),
                "length": field.length(),
                "precision": field.precision(),
                "comment": field.comment() or "",
            })
    except Exception:
        pass
    return fields


class InspectSkill(BaseSkill):
    """图层检查技能：元数据、字段、统计摘要、特征选择。"""

    def get_name(self) -> str:
        return "inspect"

    def get_description(self) -> str:
        return (
            "用于检查和探索图层数据：列出所有图层元数据、查看字段列表、获取统计摘要、"
            "查看选中要素、按表达式选择要素、清除选择。\n"
            "参数：action（list_layers / fields / summary / selected / select / clear_selection）、"
            "layer_name（图层名）、expression（选择表达式）"
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
        action = parsed.get("action", "list_layers").strip().lower()

        handlers = {
            "list_layers": self._list_layers,
            "fields": self._inspect_fields,
            "summary": self._layer_summary,
            "selected": self._get_selected,
            "select": self._select_by_expression,
            "clear_selection": self._clear_selection,
        }

        handler = handlers.get(action)
        if handler is None:
            return {
                "success": False,
                "message": f"未知操作: {action}。支持: {', '.join(handlers.keys())}",
            }
        return handler(parsed)

    @staticmethod
    def _parse_arguments(arguments: str) -> Dict[str, Any]:
        """解析 arguments。"""
        if not arguments or not arguments.strip():
            return {"action": "list_layers"}

        import json
        arguments = arguments.strip()

        if arguments.startswith("{"):
            try:
                return json.loads(arguments)
            except json.JSONDecodeError:
                pass

        result = {}
        import re

        action_match = re.search(r'\b(list_layers|fields|summary|selected|select|clear_selection)\b', arguments, re.IGNORECASE)
        if action_match:
            result["action"] = action_match.group(1).lower()

        layer_match = re.search(r'(?:layer_name|图层|layer)[:=]?\s*["\x27]?([^\s"\'",}]+)', arguments, re.IGNORECASE)
        if layer_match:
            result["layer_name"] = layer_match.group(1).strip("\"'")

        expr_match = re.search(r'(?:expression|expr|表达式|查询)[:=]?\s*["\x27](.+?)["\x27]', arguments, re.IGNORECASE)
        if expr_match:
            result["expression"] = expr_match.group(1)
        elif "select" in arguments.lower():
            # 尝试提取引号内或等号后的内容
            after_select = arguments.split("select", 1)[-1].strip()
            if after_select.startswith(('"', "'")):
                result["expression"] = after_select.strip("\"'").strip()
            elif "=" in after_select:
                result["expression"] = after_select.split("=", 1)[-1].strip().strip("\"'")

        return result

    def _resolve_layer(self, layer_name: str):
        """解析图层名，支持精确匹配和模糊匹配。"""
        if not layer_name:
            return None

        layers = QgsProject.instance().mapLayersByName(layer_name)
        if layers and isinstance(layers[0], QgsVectorLayer):
            return layers[0]

        # 模糊匹配
        all_vector = [
            ly for ly in QgsProject.instance().mapLayers().values()
            if isinstance(ly, QgsVectorLayer)
        ]
        for ly in all_vector:
            if layer_name.lower() in ly.name().lower():
                return ly
        return None

    def _list_layers(self, parsed: Dict) -> Dict[str, Any]:
        """列出所有图层元数据。"""
        project = QgsProject.instance()
        layers = []
        for ly in project.mapLayers().values():
            meta = _layer_metadata(ly)
            # 查询图层树可见性
            try:
                root = project.layerTreeRoot()
                tree_layer = root.findLayer(ly.id())
                if tree_layer:
                    meta["visible"] = tree_layer.isVisible()
            except Exception:
                pass
            layers.append(meta)

        return {
            "success": True,
            "message": f"共 {len(layers)} 个图层",
            "layers": layers,
        }

    def _inspect_fields(self, parsed: Dict) -> Dict[str, Any]:
        """检查图层字段列表。"""
        layer_name = parsed.get("layer_name", "")
        layer = self._resolve_layer(layer_name) or parsed.get("active_layer")

        if layer is None or not isinstance(layer, QgsVectorLayer):
            return {"success": False, "message": f"未找到矢量图层: {layer_name}"}

        fields = _field_info(layer)
        return {
            "success": True,
            "message": f"{layer.name()} 共 {len(fields)} 个字段",
            "layer_name": layer.name(),
            "feature_count": layer.featureCount(),
            "fields": fields,
        }

    def _layer_summary(self, parsed: Dict) -> Dict[str, Any]:
        """获取图层统计摘要。"""
        layer_name = parsed.get("layer_name", "")
        layer = self._resolve_layer(layer_name)

        if layer is None:
            return {"success": False, "message": f"未找到图层: {layer_name}"}

        summary = _layer_metadata(layer)
        summary["field_count"] = len(layer.fields())
        summary["field_names"] = [f.name() for f in layer.fields()]

        if isinstance(layer, QgsVectorLayer):
            # 几何类型可读名称
            geom_types = {0: "Point", 1: "LineString", 2: "Polygon", 3: "Unknown",
                          4: "MultiPoint", 5: "MultiLineString", 6: "MultiPolygon"}
            summary["geometry_name"] = geom_types.get(layer.geometryType(), str(layer.geometryType()))

        return {
            "success": True,
            "message": f"{layer.name()} 摘要",
            "summary": summary,
        }

    def _get_selected(self, parsed: Dict) -> Dict[str, Any]:
        """获取选中要素。"""
        layer_name = parsed.get("layer_name", "")
        layer = self._resolve_layer(layer_name)

        if layer is None or not isinstance(layer, QgsVectorLayer):
            return {"success": False, "message": "未指定或未找到图层"}

        selected = layer.selectedFeatures()
        if not selected:
            return {"success": True, "message": "没有选中的要素", "count": 0, "features": []}

        features = []
        fields = layer.fields()
        for feat in selected[:100]:  # 最多 100 条
            attrs = {}
            for field in fields:
                attrs[field.name()] = str(feat[field.name()])
            features.append(attrs)

        return {
            "success": True,
            "message": f"选中 {len(selected)} 个要素（显示前 {len(features)} 条）",
            "count": len(selected),
            "layer_name": layer.name(),
            "features": features,
        }

    def _select_by_expression(self, parsed: Dict) -> Dict[str, Any]:
        """按表达式选择。"""
        layer_name = parsed.get("layer_name", "")
        expression = parsed.get("expression", "")

        if not expression:
            return {"success": False, "message": "未指定选择表达式"}

        layer = self._resolve_layer(layer_name)
        if layer is None or not isinstance(layer, QgsVectorLayer):
            return {"success": False, "message": f"未找到图层: {layer_name}"}

        result = layer.selectByExpression(expression)
        if result:
            count = layer.selectedFeatureCount()
            return {
                "success": True,
                "message": f"表达式 '{expression}' 选中 {count} 个要素",
                "layer_name": layer.name(),
                "selected_count": count,
            }
        else:
            return {
                "success": False,
                "message": f"表达式 '{expression}' 未匹配任何要素或执行失败",
            }

    def _clear_selection(self, parsed: Dict) -> Dict[str, Any]:
        """清除选择。"""
        layer_name = parsed.get("layer_name", "")

        if layer_name:
            layer = self._resolve_layer(layer_name)
            if layer and isinstance(layer, QgsVectorLayer):
                layer.removeSelection()
                return {"success": True, "message": f"已清除 {layer.name()} 的选择"}
            return {"success": False, "message": f"未找到图层: {layer_name}"}

        # 清除所有图层选择
        project = QgsProject.instance()
        for ly in project.mapLayers().values():
            if isinstance(ly, QgsVectorLayer):
                ly.removeSelection()

        return {"success": True, "message": "已清除所有图层的选择"}
