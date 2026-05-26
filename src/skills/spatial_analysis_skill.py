"""
空间分析技能 - 自然语言驱动的 PyQGIS 处理流水线。

继承 BaseSkill 接口，由 SkillManager 自动发现注册。
"""

import os
import tempfile
from typing import Any, Dict, List, Optional

from qgis.core import QgsProject, QgsVectorLayer, QgsRasterLayer, QgsMapLayer

from skills.base_skill import BaseSkill


class SpatialAnalysisSkill(BaseSkill):
    """空间分析技能：自然语言 → PyQGIS 代码 → 执行 → 图层加载。"""

    def get_name(self) -> str:
        return "spatial_analysis"

    def get_description(self) -> str:
        return (
            "- 用途：几何/栅格/矢量 GIS 空间处理（缓冲区、裁剪、相交、合并、\n"
            "  质心、坡度、面积、距离、重投影、融合、凸包、泰森多边形、字段计算等）\n"
            "- 注意：此技能用于生成并执行 PyQGIS 处理代码，arguments 为客户原始指令正文"
        )

    def execute(
        self,
        canvas=None,
        layer_tree=None,
        arguments: str = "",
        active_layer=None,
        layers_by_name: Optional[Dict[str, Any]] = None,
        ai_code: str = "",
        **kwargs,
    ) -> Dict[str, Any]:
        """
        执行空间分析。

        Parameters
        ----------
        canvas : QgsMapCanvas, optional
            地图画布（执行后刷新用）。
        arguments : str
            用户原始指令（占位，实际代码由外部 AI 生成后传入 ai_code）。
        active_layer : QgsMapLayer, optional
            当前活动图层。
        layers_by_name : dict, optional
            按名称索引的图层字典。
        ai_code : str
            AI 生成的 PyQGIS 代码。

        Returns
        -------
        dict
            {"success": bool, "message": str, "added_layers": list}
        """
        import processing

        if not ai_code:
            return {"success": False, "message": "未提供 AI 生成的代码"}

        if layers_by_name is None:
            layers_by_name = {
                layer.name(): layer
                for layer in QgsProject.instance().mapLayers().values()
            }

        safe_builtins = {
            "len": len, "min": min, "max": max, "sum": sum,
            "str": str, "int": int, "float": float, "bool": bool,
            "list": list, "dict": dict, "tuple": tuple, "set": set,
            "range": range, "enumerate": enumerate, "zip": zip, "sorted": sorted,
            "RuntimeError": RuntimeError, "ValueError": ValueError,
            "__import__": __import__, "isinstance": isinstance, "type": type,
            "super": super, "hasattr": hasattr, "getattr": getattr,
        }

        exec_globals = {
            "__builtins__": safe_builtins,
            "processing": processing,
            "QgsProject": QgsProject,
            "QgsVectorLayer": QgsVectorLayer,
            "QgsRasterLayer": QgsRasterLayer,
            "active_layer": active_layer,
            "layers_by_name": layers_by_name,
            "TEMPORARY_OUTPUT": "TEMPORARY_OUTPUT",
            "os": os,
            "tempfile": tempfile,
        }

        exec_locals: Dict[str, Any] = {}
        exec(ai_code, exec_globals, exec_locals)

        if "result" not in exec_locals:
            return {"success": False, "message": "AI 代码未生成 result 变量"}

        result = exec_locals["result"]
        added = self._collect_result_layers(result)

        # 刷新画布
        if canvas and hasattr(canvas, 'refresh'):
            canvas.refresh()

        return {
            "success": True,
            "message": f"空间分析完成，添加了 {len(added)} 个图层",
            "added_layers": added,
            "result": result,
        }

    def _collect_result_layers(self, result: Any) -> List[QgsMapLayer]:
        """从处理结果中递归收集并注册新图层。"""
        added: List[QgsMapLayer] = []

        def _collect(value):
            if value is None:
                return
            if isinstance(value, QgsMapLayer):
                if QgsProject.instance().mapLayer(value.id()) is None:
                    QgsProject.instance().addMapLayer(value)
                added.append(value)
            elif isinstance(value, (list, tuple, set)):
                for item in value:
                    _collect(item)
            elif isinstance(value, dict):
                for item in value.values():
                    _collect(item)
            elif isinstance(value, str):
                existing = QgsProject.instance().mapLayer(value)
                if existing is not None:
                    added.append(existing)
                elif os.path.exists(value):
                    from core.layer_loader import is_supported_path, create_layer_from_path
                    if is_supported_path(value):
                        layer = create_layer_from_path(value)
                        QgsProject.instance().addMapLayer(layer)
                        added.append(layer)

        _collect(result)
        return added