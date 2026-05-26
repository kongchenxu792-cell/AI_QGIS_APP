"""技能基类 - 所有 Skills 必须继承此接口。"""

from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseSkill(ABC):
    """可插拔技能的抽象基类。

    每个 Skill 必须实现以下三个方法：
    - get_name(): 唯一标识符
    - get_description(): 中文描述（自动注入系统提示词）
    - execute(): 执行逻辑
    """

    @abstractmethod
    def get_name(self) -> str:
        """返回技能的唯一标识符。例如 "spatial_analysis"。"""
        ...

    @abstractmethod
    def get_description(self) -> str:
        """
        返回技能的中文描述文本，用于动态构建 AI 系统提示词。

        描述应包含：
        - 技能用途
        - 触发词/使用场景
        - 参数说明
        - 优先级提示（如有）
        """
        ...

    @abstractmethod
    def execute(
        self,
        canvas=None,
        layer_tree=None,
        arguments: str = "",
        **kwargs,
    ) -> Dict[str, Any]:
        """
        执行技能逻辑。

        Parameters
        ----------
        canvas : QgsMapCanvas, optional
            当前地图画布。
        layer_tree : QgsLayerTreeView, optional
            图层树视图。
        arguments : str
            传递给技能的参数文本。
        **kwargs
            额外参数（如 active_layer、iface 等）。

        Returns
        -------
        dict
            执行结果，至少包含 {"success": bool, "message": str}。
        """
        ...