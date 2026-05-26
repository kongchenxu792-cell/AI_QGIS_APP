"""
裁剪技能 — 封装 QGIS native:clip 算法。

用叠加图层的边界裁剪输入图层，保留重叠区域内的要素。
"""

from typing import Any, Dict, List

from qgis.core import QgsProject, QgsVectorLayer, QgsMapLayer

from skills.base_skill import BaseSkill


class ClipSkill(BaseSkill):
    """裁剪技能：用边界图层裁剪输入图层。"""

    def get_name(self) -> str:
        return "clip"

    def get_description(self) -> str:
        return "用于裁剪矢量图层（例如：用边界裁剪道路，提取某个区域内的要素）"

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

        layers = list(QgsProject.instance().mapLayers().values())
        if len(layers) < 2:
            return {
                "success": False,
                "message": "裁剪需要至少两个矢量图层（输入图层 + 边界图层）",
            }

        input_layer = active_layer
        if input_layer is None or not isinstance(input_layer, QgsVectorLayer):
            input_layer = layers[0]

        overlay_layer = None
        for lyr in layers:
            if lyr != input_layer and isinstance(lyr, QgsVectorLayer):
                overlay_layer = lyr
                break

        if overlay_layer is None:
            return {"success": False, "message": "未找到可作为裁剪边界的矢量图层"}

        params = {
            "INPUT": input_layer,
            "OVERLAY": overlay_layer,
            "OUTPUT": "TEMPORARY_OUTPUT",
        }

        result = processing.run("native:clip", params)
        clipped_layer: QgsVectorLayer = result["OUTPUT"]

        new_name = f"[裁剪] {input_layer.name()}"
        clipped_layer.setName(new_name)

        QgsProject.instance().addMapLayer(clipped_layer)
        added: List[QgsMapLayer] = [clipped_layer]

        if canvas and hasattr(canvas, "refresh"):
            canvas.refresh()

        return {
            "success": True,
            "message": f"裁剪完成：{input_layer.name()} × {overlay_layer.name()} → {new_name}",
            "added_layers": added,
        }