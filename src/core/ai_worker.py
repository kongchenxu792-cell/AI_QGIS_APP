"""后台异步工作线程，负责将自然语言 GIS 任务路由至大语言模型。

Phase 2 升级：Skill-based Agent 架构。
模型返回 JSON 格式的技能路由指令，不再直接生成代码。
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, List

from PyQt5.QtCore import QThread, pyqtSignal

from core.ai_config import API_KEY, BASE_URL, MODEL_NAME

_log = logging.getLogger("ai_worker")


def build_system_prompt() -> str:
    """动态构建技能路由系统提示词（从 SkillManager 获取技能清单）。"""

    from skills.skill_manager import get_skill_manager

    mgr = get_skill_manager()
    skills_section = mgr.build_system_prompt_skills_section()

    return (
        "你是 AIQGIS 的 GIS 智能体调度中心（Agent Coordinator）。\n"
        "你的职责是：根据用户的自然语言指令，将其路由到正确的技能模块。\n\n"
        "## 可用技能清单\n\n"
        f"{skills_section}\n"
        "## 输出格式要求\n\n"
        "你必须**只输出**一个严格的 JSON 对象，不要输出任何其他内容：\n"
        "{\n"
        '  "skill": "技能名称",\n'
        '  "arguments": "传递给技能的参数文本",\n'
        '  "reasoning": "简短的路由理由（中文）"\n'
        "}\n\n"
        "## 路由规则（严格遵守）\n"
        "1. 用户意图是查看/浏览属性数据 → open_table（最高优先级）\n"
        "2. 用户意图是导出/保存/截图地图 → map_export\n"
        "3. 用户意图是修改图层外观/样式/颜色/标注 → layer_styling\n"
        "4. 用户意图是空间计算/分析/处理 → spatial_analysis\n"
        "5. 对于 open_table，arguments 为空字符串 \"\"\n"
        "6. 对于其他技能，arguments 为完整原始指令\n"
        "7. 无法匹配 → skill=\"unknown\"，reasoning 解释原因"
    )


def build_user_prompt(user_text: str, layer_metadata: List[Dict[str, Any]]) -> str:
    """构建包含当前图层元数据的用户提示词。"""

    payload = {
        "user_request": user_text,
        "active_layers": layer_metadata,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_chat_completions_url(base_url: str) -> str:
    """将兼容 OpenAI 格式的基础 URL 规范化为对话补全端点。"""

    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


class AIProcessingWorker(QThread):
    """后台工作线程，向大语言模型 API 请求技能路由指令。"""

    succeeded = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, user_text: str, layer_metadata: List[Dict[str, Any]]) -> None:
        super().__init__()
        self.user_text = user_text
        self.layer_metadata = layer_metadata

    def run(self) -> None:
        try:
            self._validate_config()
            _log.info("发起 AI 路由请求，用户指令长度：%d 字符", len(self.user_text))
            response_text = self._request_llm_code()
            _log.debug("AI 路由响应：%s", response_text[:200])
            self.succeeded.emit(response_text)
        except Exception as exc:
            _log.error("AI 路由请求失败：%s", exc)
            self.failed.emit(str(exc))

    def _validate_config(self) -> None:
        """验证 AI 配置是否已替换为真实值。"""

        invalid_values = {
            "YOUR_API_KEY_HERE",
            "https://your-openai-compatible-endpoint.example.com/v1",
            "your-model-name",
        }
        if API_KEY in invalid_values or BASE_URL in invalid_values or MODEL_NAME in invalid_values:
            raise RuntimeError(
                "AI 配置尚未完成。请先在 src/core/ai_config.py 中填写 API_KEY、BASE_URL 和 MODEL_NAME。"
            )

    def _request_llm_code(self) -> str:
        """调用 API 获取技能路由指令。"""

        request_body = {
            "model": MODEL_NAME,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": build_system_prompt()},
                {
                    "role": "user",
                    "content": build_user_prompt(self.user_text, self.layer_metadata),
                },
            ],
        }

        request = urllib.request.Request(
            build_chat_completions_url(BASE_URL),
            data=json.dumps(request_body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {API_KEY}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            _log.error("AI HTTP %s：%s", exc.code, detail[:500])
            raise RuntimeError(f"AI 接口请求失败，HTTP {exc.code}：{detail}") from exc
        except urllib.error.URLError as exc:
            _log.error("AI 连接失败：%s", exc.reason)
            raise RuntimeError(f"AI 接口连接失败：{exc.reason}") from exc

        try:
            return payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"AI 接口返回格式异常：{payload}") from exc


def build_code_generation_prompt() -> str:
    """构建空间分析代码生成的系统提示词（第二轮调用）。"""

    return (
        "你是 PyQGIS 代码生成专家，同时能用中文简要回答用户的问题。\n"
        "你的输出必须严格满足以下要求：\n"
        "1. 先用中文简要回答用户的问题（如计算结果、分析结论等）。\n"
        "2. 然后在 ```python ... ``` 代码块中给出执行的 PyQGIS 代码。\n"
        "3. 代码必须以 processing.run() 结尾，返回值直接赋给 result。\n"
        "4. result = processing.run(...)，不得修改或包装。\n"
        "5. 优先使用 active_layer 作为输入图层。\n"
        "6. 输出图层使用 'TEMPORARY_OUTPUT' 或 'memory:'。\n"
        "7. 禁止调用 print、input、sys、subprocess、eval、exec、open、__import__。\n"
        "8. 禁止定义类和函数，只输出顺序代码。\n"
        "9. 禁止使用 iface — 这是独立 QGIS 应用，iface 不存在。用 QgsProject.instance() 代替。\n"
        "10. 禁止仅做图层显隐操作。所有空间操作（提取、裁剪、筛选、缓冲等）都必须通过 processing.run() 完成。\n"
        "11. 示例：\n"
        "该图层共有 15 个要素，总面积约 320.5 平方公里。\n"
        "```python\n"
        "result = processing.run(\"native:fieldcalculator\", {\n"
        "    'INPUT': active_layer,\n"
        "    'FIELD_NAME': 'area',\n"
        "    'FORMULA': '$area',\n"
        "    'OUTPUT': 'TEMPORARY_OUTPUT'\n"
        "})\n"
        "```\n"
        "12. 如果无法生成代码，返回解释原因的中文文本。"
    )


def request_spatial_code(user_text: str, layer_metadata: List[Dict[str, Any]]) -> str:
    """
    向 API 请求空间分析代码（第二轮调用）。
    """
    _log.info("发起空间分析代码生成请求")
    body = {
        "model": MODEL_NAME,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": build_code_generation_prompt()},
            {"role": "user", "content": json.dumps(
                {"user_request": user_text, "active_layers": layer_metadata},
                ensure_ascii=False, indent=2,
            )},
        ],
    }

    url = build_chat_completions_url(BASE_URL)
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        result = data["choices"][0]["message"]["content"]
        _log.debug("空间分析代码响应：%s", result[:200])
        return result
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        _log.error("空间分析代码 HTTP %s：%s", exc.code, detail[:500])
        raise RuntimeError(f"AI 接口请求失败，HTTP {exc.code}：{detail}") from exc
    except urllib.error.URLError as exc:
        _log.error("空间分析代码连接失败：%s", exc.reason)
        raise RuntimeError(f"AI 接口连接失败：{exc.reason}") from exc


def parse_agent_response(response_text: str) -> Dict[str, str]:
    """
    解析 AI 返回的 JSON 路由指令。
    """
    text = response_text.strip()

    # 去掉 markdown 代码块标记
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:] if lines[0].startswith("```") else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        import re
        match = re.search(r'\{[^{}]*"skill"[^{}]*\}', response_text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        _log.warning("AI 响应不是合法 JSON，原始内容前 500 字符：%s", response_text[:500])
        raise RuntimeError(
            f"AI 返回的不是合法 JSON。\n\n原始响应：\n{response_text[:500]}"
        )