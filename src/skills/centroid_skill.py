"""
质心提取技能 — 封装 QGIS native:centroids 算法。

计算面图层每个要素的几何中心点，生成新的点图层。
"""

from typing import Any, Dict, List

from qgis.core import QgsProject, QgsVectorLayer, QgsMapLayer

from skills.base_skill import BaseSkill


class CentroidSkill(BaseSkill):
    """质心提取技能：面 → 点。"""

    def get_name(self) -> str:
        return "centroid"

    def get_description(self) -> str:
        return "用于提取面图层的几何质心/中心点（例如：计算各个小区的中心点）"

    def execute(
        self,
        canvas=None,
        layer_tree=None,
        arguments: str = "",
        active_layer=None,
        main_window=None,
        **kwargs,
    ) -> Dict[str, Any]:
        import processing

        input_layer = active_layer
        if input_layer is None or not isinstance(input_layer, QgsVectorLayer):
            layers = list(QgsProject.instance().mapLayers().values())
            for lyr in layers:
                if isinstance(lyr, QgsVectorLayer) and lyr.geometryType() == 2:  # Polygon
                    input_layer = lyr
                    break
            # 如果没有面图层，回退到任意矢量图层
            if input_layer is None:
                for lyr in layers:
                    if isinstance(lyr, QgsVectorLayer):
                        input_layer = lyr
                        break

        if input_layer is None:
            return {"success": False, "message": "未找到矢量图层"}

        params = {
            "INPUT": input_layer,
            "ALL_PARTS": False,
            "OUTPUT": "TEMPORARY_OUTPUT",
        }

        result = processing.run("native:centroids", params)
        centroid_layer: QgsVectorLayer = result["OUTPUT"]

        new_name = f"[质心] {input_layer.name()}"
        centroid_layer.setName(new_name)

        QgsProject.instance().addMapLayer(centroid_layer)
        added: List[QgsMapLayer] = [centroid_layer]

        if canvas and hasattr(canvas, "refresh"):
            canvas.refresh()

        return {
            "success": True,
            "message": f"质心提取完成：{input_layer.name()} → {new_name}",
            "added_layers": added,
        }