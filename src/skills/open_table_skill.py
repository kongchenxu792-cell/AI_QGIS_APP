"""打开属性表技能 - 直接弹出矢量图层属性表查看窗口。"""

from typing import Any, Dict

from qgis.core import QgsProject, QgsMapLayer

from skills.base_skill import BaseSkill


class OpenTableSkill(BaseSkill):
    """打开属性表技能：直接弹出属性表查看窗口，无需 AI 代码生成。"""

    def get_name(self) -> str:
        return "open_table"

    def get_description(self) -> str:
        return (
            "- 用途：查看或打开图层的属性表窗口\n"
            "- 触发词：打开属性表、查看属性、查看数据、看属性、表格、属性表、\n"
            "  查看、打开、看、属性、表、数据、字段\n"
            "- **优先级最高**：只要用户意图是查看/浏览/打开数据，必须路由到此技能\n"
            "- 注意：此技能直接打开 GUI 窗口，不需要生成任何代码\n"
            "- arguments 必须为空字符串"
        )

    def execute(
        self,
        canvas=None,
        layer_tree=None,
        arguments: str = "",
        active_layer=None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        打开属性表窗口。

        Parameters
        ----------
        canvas : QgsMapCanvas, optional
            地图画布。
        layer_tree : QgsLayerTreeView, optional
            图层树视图。
        arguments : str
            参数（本技能忽略）。
        active_layer : QgsMapLayer, optional
            当前活动图层。

        Returns
        -------
        dict
            {"success": bool, "message": str, "layer": QgsMapLayer or None}
        """
        # 优先使用传入的 active_layer
        layer = active_layer

        # 回退：从 layer_tree 获取选中节点
        if layer is None and layer_tree is not None:
            try:
                node = layer_tree.currentNode()
                if node and hasattr(node, 'layer') and node.layer():
                    layer = node.layer()
            except Exception:
                pass

        # 回退：取第一个矢量图层
        if layer is None:
            for l in QgsProject.instance().mapLayers().values():
                if l.type() == QgsMapLayer.VectorLayer:
                    layer = l
                    break

        if layer is None:
            return {"success": False, "message": "当前没有加载矢量图层"}

        if layer.type() != QgsMapLayer.VectorLayer:
            return {"success": False, "message": "只有矢量图层可以查看属性表"}

        # 返回成功，由调用方打开 GUI 窗口
        return {"success": True, "message": "已准备打开属性表", "layer": layer}