"""AIQGIS 技能框架 - 可插拔的 GIS 技能模块。

所有技能由 SkillManager 在启动时自动扫描注册。
"""

from skills.base_skill import BaseSkill
from skills.skill_manager import SkillManager, get_skill_manager

__all__ = ["BaseSkill", "SkillManager", "get_skill_manager"]