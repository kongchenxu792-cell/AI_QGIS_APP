"""提示词 Agent 模块 — 独立扩展。

将实验指导书/任务书（.docx / .pdf）脱敏提炼为一句精准的
"AI 核心分析指令"，包含图层名与核心空间分析动作。

模块组成：
- config:     独立 LLM API 配置（与主分析管线完全隔离）
- extractor:  PDF / DOCX 文本提取核心
- refiner:    LLM 提炼引擎（专用 System Prompt）
- widget:     UI 面板（拖拽区域 + 结果展示 + 一键应用）
"""

__all__ = [
    "PromptAgentConfig",
    "extract_text",
    "extract_docx",
    "extract_pdf",
    "RefinerEngine",
    "PromptAgentWidget",
]