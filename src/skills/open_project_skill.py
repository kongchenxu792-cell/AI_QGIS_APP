"""
打开 QGIS 项目文件技能 — 支持 .qgz / .qgs 格式。

加载标准 QGIS 项目文件，恢复完整的工作状态（图层、样式、布局等）。
使用 core.project_manager 统一 API。
"""

import os
from typing import Any, Dict, List, Optional

from qgis.gui import QgsMapCanvas

from skills.base_skill import BaseSkill
from core.project_manager import get_project_manager, extract_file_path


class OpenProjectSkill(BaseSkill):
    """打开 QGIS 项目文件技能：加载 .qgz / .qgs 项目文件。"""

    def __init__(self):
        super().__init__()
        self.project_manager = get_project_manager()

    def get_name(self) -> str:
        return "open_project"

    def get_description(self) -> str:
        return (
            "- 用途：打开 QGIS 项目文件（.qgz / .qgs），恢复完整工作状态\n"
            "- 触发词：打开项目、加载项目、打开文件、加载 .qgz、打开 .qgs、\n"
            "  打开我的项目、加载毕业设计项目、打开学校项目\n"
            "- **优先级**：当用户意图是打开/加载 QGIS 项目文件时路由到此技能\n"
            "- 注意：此技能会清空当前项目，加载新项目文件\n"
            "- arguments 应包含项目文件路径（如 \"D:/data/my_project.qgz\"）"
        )

    def _extract_file_path(self, arguments: str) -> Optional[str]:
        """从用户指令中提取文件路径（委托给核心工具函数）。"""
        return extract_file_path(arguments)

    def execute(
        self,
        canvas: Optional[QgsMapCanvas] = None,
        layer_tree=None,
        arguments: str = "",
        active_layer=None,
        main_window=None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        打开 QGIS 项目文件。

        Parameters
        ----------
        canvas : QgsMapCanvas, optional
            地图画布（用于刷新显示）。
        arguments : str
            用户指令，应包含项目文件路径。
        main_window : QMainWindow, optional
            主窗口实例（用于状态更新）。

        Returns
        -------
        dict
            {"success": bool, "message": str, "loaded_layers": list, "added_layers": list,
             "layer_names": list, "project_path": str, "layer_count": int}
        """
        if not arguments or not arguments.strip():
            return {
                "success": False,
                "message": "请指定要打开的 QGIS 项目文件路径（例如：打开 D:/data/my_project.qgz）",
            }

        file_path = self._extract_file_path(arguments)
        if not file_path:
            return {
                "success": False,
                "message": f"无法从指令中提取有效的项目文件路径。请提供完整路径，如：D:/data/project.qgz",
            }

        result = self.project_manager.open_project(file_path, canvas)

        # 补充流水线兼容字段：added_layers 与 loaded_layers 相同
        if result.get("success"):
            result["added_layers"] = result.get("loaded_layers", [])

        # 更新主窗口状态
        if main_window and hasattr(main_window, "statusBar"):
            if result.get("success"):
                main_window.statusBar().showMessage(
                    f"项目已加载：{os.path.basename(file_path)}", 5000
                )

        return result