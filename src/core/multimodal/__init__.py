"""
AIQGIS 多模态模块

提供图片预处理、视口截图、提示词构建三大核心能力，
支持 DeepSeek Vision API 的多模态输入管线。

模块清单：
    ImagePreprocessor       — 图片缩放/编码/格式统一 (MAX_EDGE=1024)
    CanvasCapture           — QGIS画布截图（含视口元数据）
    MultimodalPromptBuilder — OpenAI Vision API messages构建
"""

from .image_preprocessor import ImagePreprocessor
from .canvas_capture import CanvasCapture
from .prompt_builder import MultimodalPromptBuilder

__all__ = ["ImagePreprocessor", "CanvasCapture", "MultimodalPromptBuilder"]
