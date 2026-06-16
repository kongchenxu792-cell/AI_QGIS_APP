"""
项目管理核心服务 — 统一处理 QGIS 项目文件 (.qgz / .qgs) 的打开、保存、备份、状态查询。

提供与 QgsProject 实例交互的集中化 API，供 open_project_skill 和主窗口调用。
"""

import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from qgis.core import QgsProject, QgsMapLayer, QgsVectorLayer, QgsRasterLayer
from qgis.gui import QgsMapCanvas


class ProjectManager:
    """QGIS 项目管理器：单例封装 QgsProject 操作。"""

    def __init__(self):
        self.project = QgsProject.instance()
        self._current_path: Optional[str] = None

    @property
    def current_path(self) -> Optional[str]:
        """当前项目文件路径（如果已从磁盘加载）。"""
        return self._current_path

    @property
    def is_dirty(self) -> bool:
        """项目是否有未保存的修改。"""
        return self.project.isDirty()

    @property
    def layers(self) -> List[QgsMapLayer]:
        """当前项目中所有图层的列表。"""
        return list(self.project.mapLayers().values())

    @property
    def layer_names(self) -> List[str]:
        """当前项目中所有图层的名称列表。"""
        return [layer.name() for layer in self.layers]

    def open_project(self, file_path: str, canvas: Optional[QgsMapCanvas] = None) -> Dict[str, Any]:
        """打开 QGIS 项目文件。

        Parameters
        ----------
        file_path : str
            .qgz 或 .qgs 文件路径。
        canvas : QgsMapCanvas, optional
            地图画布（用于刷新显示）。

        Returns
        -------
        dict
            {
                "success": bool,
                "message": str,
                "loaded_layers": List[QgsMapLayer],
                "layer_names": List[str],
                "project_path": str,
                "layer_count": int,
            }
        """
        # 验证文件
        if not os.path.exists(file_path):
            return {
                "success": False,
                "message": f"项目文件不存在：{file_path}",
            }

        ext = os.path.splitext(file_path)[1].lower()
        if ext not in ['.qgz', '.qgs']:
            return {
                "success": False,
                "message": f"不支持的文件格式：{ext}。请使用 .qgz 或 .qgs 格式的 QGIS 项目文件。",
            }

        try:
            # 清空当前项目
            self.project.clear()
            self._current_path = None

            # 读取项目文件
            success = self.project.read(file_path)
            if not success:
                return {
                    "success": False,
                    "message": f"项目文件读取失败：{file_path}。可能是文件损坏或版本不兼容。",
                }

            self._current_path = file_path

            # 获取加载的图层
            loaded_layers = self.layers
            layer_names = self.layer_names

            # 刷新画布
            if canvas and hasattr(canvas, "refresh"):
                canvas.refresh()

            return {
                "success": True,
                "message": f"成功加载项目：{os.path.basename(file_path)}，包含 {len(loaded_layers)} 个图层",
                "loaded_layers": loaded_layers,
                "layer_names": layer_names,
                "project_path": file_path,
                "layer_count": len(loaded_layers),
            }

        except Exception as e:
            return {
                "success": False,
                "message": f"打开项目时发生错误：{str(e)}",
            }

    def save_project(self, file_path: str) -> Dict[str, Any]:
        """保存当前项目到指定路径。

        Parameters
        ----------
        file_path : str
            保存路径（.qgz 或 .qgs）。

        Returns
        -------
        dict
            {"success": bool, "message": str, "saved_path": str}
        """
        try:
            success = self.project.write(file_path)
            if success:
                self._current_path = file_path
                return {
                    "success": True,
                    "message": f"项目已保存：{file_path}",
                    "saved_path": file_path,
                }
            else:
                return {
                    "success": False,
                    "message": f"项目保存失败：{file_path}",
                }
        except Exception as e:
            return {
                "success": False,
                "message": f"保存项目时发生错误：{str(e)}",
            }

    def save_as(self, file_path: str) -> Dict[str, Any]:
        """另存为项目文件（不清空当前项目）。"""
        return self.save_project(file_path)

    def create_new(self, canvas: Optional[QgsMapCanvas] = None) -> Dict[str, Any]:
        """创建新项目（清空当前内容）。

        Returns
        -------
        dict
            {"success": bool, "message": str, "project_path": None}
        """
        try:
            self.project.clear()
            self._current_path = None

            if canvas and hasattr(canvas, "refresh"):
                canvas.refresh()

            return {
                "success": True,
                "message": "已创建新的空白项目",
                "project_path": None,
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"创建新项目时发生错误：{str(e)}",
            }

    def close_project(self, canvas: Optional[QgsMapCanvas] = None) -> Dict[str, Any]:
        """关闭当前项目（清空内容，不保存）。"""
        return self.create_new(canvas)

    def get_layer_by_name(self, name: str) -> Optional[QgsMapLayer]:
        """按名称查找图层（不区分大小写）。"""
        for layer in self.layers:
            if layer.name().lower() == name.lower():
                return layer
        return None

    def get_layers_by_type(self, layer_type: int) -> List[QgsMapLayer]:
        """按类型筛选图层。

        Parameters
        ----------
        layer_type : int
            QgsMapLayer.VectorLayer 或 QgsMapLayer.RasterLayer。

        Returns
        -------
        List[QgsMapLayer]
            匹配类型的图层列表。
        """
        return [layer for layer in self.layers if layer.type() == layer_type]

    def get_vector_layers(self) -> List[QgsVectorLayer]:
        """获取所有矢量图层。"""
        return [layer for layer in self.layers if isinstance(layer, QgsVectorLayer)]

    def get_raster_layers(self) -> List[QgsRasterLayer]:
        """获取所有栅格图层。"""
        return [layer for layer in self.layers if isinstance(layer, QgsRasterLayer)]

    def generate_backup_path(self, prefix: str = "backup") -> str:
        """生成带时间戳的项目备份路径。

        Returns
        -------
        str
            格式：user_data/projects/backup_YYYYMMDD_HHMMSS.qgz
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "user_data", "projects"
        )
        os.makedirs(backup_dir, exist_ok=True)
        return os.path.join(backup_dir, f"{prefix}_{timestamp}.qgz")

    def backup_current(self) -> Dict[str, Any]:
        """备份当前项目到 user_data/projects/ 目录。"""
        if not self.layers:
            return {
                "success": False,
                "message": "当前项目为空，无需备份",
            }

        backup_path = self.generate_backup_path()
        return self.save_project(backup_path)


# 全局单例
_project_manager: Optional[ProjectManager] = None


def get_project_manager() -> ProjectManager:
    """获取全局项目管理器单例。"""
    global _project_manager
    if _project_manager is None:
        _project_manager = ProjectManager()
    return _project_manager


# 路径提取工具函数
def extract_file_path(text: str) -> Optional[str]:
    """从自然语言文本中提取可能的 QGIS 项目文件路径。

    支持多种格式：
    - 绝对路径：D:/data/project.qgz
    - 相对路径：./my_project.qgs
    - 带引号路径："C:/Users/name/Desktop/project.qgz"
    - 自然语言描述：打开 D 盘 data 文件夹下的 test.qgz
    """
    if not text or not text.strip():
        return None

    text = text.strip()

    # 1. 直接路径模式（带扩展名）
    path_patterns = [
        r'[A-Za-z]:[\\/][^\s"\']+\.qg[sz]',  # Windows 绝对路径
        r'[\\/][^\s"\']+\.qg[sz]',           # Unix 绝对路径
        r'\.[\\/][^\s"\']+\.qg[sz]',         # 相对路径
        r'~[\\/][^\s"\']+\.qg[sz]',          # 用户目录
    ]

    for pattern in path_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            path = match.group()
            # 清理可能的引号
            path = path.strip('"\'')
            return path

    # 2. 引号包裹的路径
    quoted_path = re.search(r'["\']([^"\']+\.qg[sz])["\']', text, re.IGNORECASE)
    if quoted_path:
        return quoted_path.group(1)

    # 3. 尝试从自然语言提取
    # 例如："打开 D 盘 data 文件夹下的 test.qgz"
    # 提取可能的文件名部分
    filename_match = re.search(r'([\w\-_]+\.qg[sz])', text, re.IGNORECASE)
    if filename_match:
        filename = filename_match.group(1)
        # 尝试在当前目录查找
        if os.path.exists(filename):
            return filename
        # 尝试在桌面查找
        desktop_path = os.path.join(os.path.expanduser("~"), "Desktop", filename)
        if os.path.exists(desktop_path):
            return desktop_path

    return None