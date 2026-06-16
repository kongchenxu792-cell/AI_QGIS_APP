"""LLM 提炼引擎 — 独立 API + 专用 System Prompt。

将几千字的实验指导书/任务书脱敏并压缩为一句
"AI 核心分析指令"（含图层名 + 空间分析动作）。
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Dict, Optional

from .config import (
    API_KEY,
    BASE_URL,
    MAX_INPUT_CHARS,
    MODEL_NAME,
    REQUEST_TIMEOUT,
)

_log = logging.getLogger("prompt_agent.refiner")

# ── 专用 System Prompt（固定前缀，不可修改）─────────────────────────
SYSTEM_PROMPT = """你是一个地理信息任务提炼专家。你的任务是阅读用户提供的实验指导书或任务书全文，然后输出一句精确的"AI 核心分析指令"。

## 提炼规则

1. **脱敏**：剔除学校名称、教师姓名、日期、页码、格式标记、"实验目的""实验步骤"等教学元数据。
2. **提取核心**：仅保留"对什么图层/数据→做什么空间分析→输出什么结果"这条逻辑链。
3. **包含图层名**：如果原文提到具体图层文件名（如 "gis_osm_roads_free"、"成都市行政区划.shp"），必须原样出现在指令中。
4. **包含空间分析动作**：使用专业术语（缓冲区分析、裁剪、相交、叠加、网络分析、插值、坡度分析、分类等）。
5. **一句话**：输出必须是单句汉语，不含列表、分号、换行，字数控制在 15-40 字。

## 输出格式（严格遵守）

你必须只输出一个 JSON 对象，格式如下：

{"instruction": "提炼后的一句核心指令"}

不要输出任何其他内容、解释、Markdown 标记。"""


class RefinerEngine:
    """调用独立 LLM API 完成文本→指令提炼。"""

    def __init__(self) -> None:
        self._api_key = API_KEY
        self._base_url = BASE_URL.rstrip("/")
        self._model = MODEL_NAME

    # ── 公开接口 ──────────────────────────────────────────────────

    def refine(self, raw_text: str) -> Dict[str, str]:
        """提炼原始文本为一句核心指令。

        Args:
            raw_text: 文档提取的纯文本

        Returns:
            {"instruction": "...", "raw_length": int, "refined_length": int}

        Raises:
            ValueError: 输入为空或过长
            RuntimeError: API 调用失败
        """
        if not raw_text or not raw_text.strip():
            raise ValueError("输入文本为空，无法提炼")

        # 截断过长文本
        processed = raw_text[:MAX_INPUT_CHARS]
        if len(processed) < len(raw_text):
            _log.warning("输入文本过长 (%d→%d 字符)，已截断", len(raw_text), len(processed))

        instruction = self._call_api(processed)
        result = {
            "instruction": instruction,
            "raw_length": len(raw_text),
            "refined_length": len(instruction),
        }
        _log.info("提炼完成: %d→%d 字符", result["raw_length"], result["refined_length"])
        return result

    # ── API 调用 ──────────────────────────────────────────────────

    def _call_api(self, user_text: str) -> str:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.1,
            "max_tokens": 200,
        }

        url = f"{self._base_url}/chat/completions"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"API 返回 HTTP {e.code}: {err_body[:200]}"
            )
        except urllib.error.URLError as e:
            raise RuntimeError(f"网络错误: {e.reason}")
        except Exception as e:
            raise RuntimeError(f"API 调用异常: {e}")

        content = body["choices"][0]["message"]["content"]
        # 解析 JSON 响应
        try:
            parsed = json.loads(content)
            return parsed.get("instruction", content)
        except json.JSONDecodeError:
            # 容错：直接取内容文本
            return content.strip()