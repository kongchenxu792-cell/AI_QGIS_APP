"""
保存 QGIS 项目文件技能 — 支持 .qgz / .qgs 格式。

将当前工作状态（图层、样式、布局等）保存为标准 QGIS 项目文件。
使用 core.project_manager 统一 API。
"""

import os
from typing import Any, Dict, List, Optional

from PyQt5.QtWidgets import QFileDialog, QMessageBox

from skills.base_skill import BaseSkill
from core.project_manager import get_project_manager, extract_file_path


class SaveProjectSkill(BaseSkill):
    """保存 QGIS 项目文件技能：保存当前工作状态为 .qgz / .qgs 文件。"""

    def __init__(self):
        super().__init__()
        self.project_manager = get_project_manager()

    def get_name(self) -> str:
        return "save_project"

    def get_description(self) -> str:
        return (
            "- 用途：保存当前 QGIS 项目为项目文件（.qgz / .qgs），包含所有图层、样式、布局\n"
            "- 触发词：保存项目、保存文件、另存为、导出项目、备份项目、\n"
            "  保存为 QGIS 文件、保存工作、保存到文件、保存当前状态\n"
            "- **优先级**：当用户意图是保存/导出 QGIS 项目文件时路由到此技能\n"
            "- 注意：此技能会弹出文件保存对话框让用户选择路径\n"
            "- arguments 可以是用户指定的路径（如 \"保存到 D:/data/我的项目.qgz\"），为空则弹出对话框"
        )

    def _extract_file_path(self, arguments: str) -> Optional[str]:
        """从用户指令中提取文件路径（委托给核心工具函数）。"""
        return extract_file_path(arguments)

    def execute(
        self,
        canvas=None,
        layer_tree=None,
        arguments: str = "",
        active_layer=None,
        main_window=None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        保存当前 QGIS 项目到文件。

        Parameters
        ----------
        canvas : QgsMapCanvas, optional
            地图画布（用于状态提示）。
        arguments : str
            用户指令，可包含项目文件路径。
        main_window : QMainWindow, optional
            主窗口实例（用于显示对话框）。
        active_layer : QgsMapLayer, optional
            当前活动图层（未使用，为接口兼容性保留）。

        Returns
        -------
        dict
            {"success": bool, "message": str, "saved_path": str or None, "backup_created": bool}
        """
        # 检查是否有图层可保存
        if len(self.project_manager.layers) == 0:
            return {
                "success": False,
                "message": "当前项目为空，没有图层可保存。请先加载数据。",
            }

        # 尝试从指令中提取路径
        file_path = self._extract_file_path(arguments)

        # 如果没有指定路径，弹出保存对话框
        if not file_path:
            if not main_window:
                return {
                    "success": False,
                    "message": "需要指定保存路径或通过主窗口调用",
                }

            # 设置默认文件名
            default_name = "AIQGIS_项目"
            if self.project_manager.current_path:
                default_name = os.path.splitext(os.path.basename(self.project_manager.current_path))[0]
            
            # 弹出保存对话框
            file_path, selected_filter = QFileDialog.getSaveFileName(
                main_window,
                "保存 QGIS 项目文件",
                os.path.join(os.path.expanduser("~"), "Desktop", f"{default_name}.qgz"),
                "QGIS 项目文件 (*.qgz *.qgs);;QGIS ZIP 项目 (*.qgz);;QGIS XML 项目 (*.qgs)",
            )

            if not file_path:
                return {"success": False, "message": "用户取消了保存"}

            # 确保文件扩展名
            if selected_filter:
                if "*.qgz" in selected_filter and not file_path.lower().endswith(".qgz"):
                    file_path += ".qgz"
                elif "*.qgs" in selected_filter and not file_path.lower().endswith(".qgs"):
                    file_path += ".qgs"
            else:
                # 默认使用 .qgz（现代 QGIS 项目格式）
                if not file_path.lower().endswith((".qgz", ".qgs")):
                    file_path += ".qgz"

        # 执行保存
        result = self.project_manager.save_project(file_path)

        # 如果保存成功，创建备份
        backup_created = False
        if result.get("success"):
            backup_result = self.project_manager.backup_current()
            backup_created = backup_result.get("success", False)

            # 更新主窗口状态
            if main_window and hasattr(main_window, "statusBar"):
                main_window.statusBar().showMessage(
                    f"项目已保存：{os.path.basename(file_path)}", 5000
                )

        # 补充备份信息
        if result.get("success"):
            result["backup_created"] = backup_created
            if backup_created:
                result["message"] += "（已创建自动备份）"

        return result


class SaveAsProjectSkill(BaseSkill):
    """另存为 QGIS 项目文件技能：总是弹出对话框选择新路径。"""

    def __init__(self):
        super().__init__()
        self.project_manager = get_project_manager()

    def get_name(self) -> str:
        return "save_as_project"

    def get_description(self) -> str:
        return (
            "- 用途：将当前项目另存为新文件（总是弹出保存对话框）\n"
            "- 触发词：另存为、保存为新文件、保存副本、导出为新项目\n"
            "- 注意：此技能忽略 arguments 中的路径，总是弹出对话框让用户选择新位置"
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
        """
        另存为 QGIS 项目文件（总是弹出对话框）。

        Parameters
        ----------
        main_window : QMainWindow, optional
            主窗口实例（用于显示对话框）。

        Returns
        -------
        dict
            {"success": bool, "message": str, "saved_path": str or None}
        """
        if not main_window:
            return {
                "success": False,
                "message": "需要主窗口实例来显示保存对话框",
            }

        # 检查是否有图层可保存
        if len(self.project_manager.layers) == 0:
            return {
                "success": False,
                "message": "当前项目为空，没有图层可保存。请先加载数据。",
            }

        # 设置默认文件名
        default_name = "AIQGIS_项目_副本"
        if self.project_manager.current_path:
            base_name = os.path.splitext(os.path.basename(self.project_manager.current_path))[0]
            default_name = f"{base_name}_副本"

        # 弹出保存对话框
        file_path, selected_filter = QFileDialog.getSaveFileName(
            main_window,
            "另存为 QGIS 项目文件",
            os.path.join(os.path.expanduser("~"), "Desktop", f"{default_name}.qgz"),
            "QGIS 项目文件 (*.qgz *.qgs);;QGIS ZIP 项目 (*.qgz);;QGIS XML 项目 (*.qgs)",
        )

        if not file_path:
            return {"success": False, "message": "用户取消了另存为"}

        # 确保文件扩展名
        if selected_filter:
            if "*.qgz" in selected_filter and not file_path.lower().endswith(".qgz"):
                file_path += ".qgz"
            elif "*.qgs" in selected_filter and not file_path.lower().endswith(".qgs"):
                file_path += ".qgs"
        else:
            # 默认使用 .qgz（现代 QGIS 项目格式）
            if not file_path.lower().endswith((".qgz", ".qgs")):
                file_path += ".qgz"

        # 执行保存
        result = self.project_manager.save_project(file_path)

        # 更新主窗口状态
        if result.get("success") and main_window and hasattr(main_window, "statusBar"):
            main_window.statusBar().showMessage(
                f"项目已另存为：{os.path.basename(file_path)}", 5000
            )

        return result