"""
记忆桥接器 — mem0 向量存储 + 语义检索封装

将 mem0 的向量存储和语义检索能力封装为 AIQGIS 的记忆底层，
实现跨会话持久化和历史经验语义检索。

核心特性：
- 完全离线：Qdrant 本地文件 + fastembed 中文 embedding 模型
- 代码剥离：add_experience 自动过滤 Python 代码块，防止向量污染
- 多维度检索：通用历史对话检索 + 空间分析专用经验检索
- 降级容错：mem0 不可用时自动降级为空操作，不影响主流程
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

_log = logging.getLogger("memory_bridge")

# ── 存储路径 ──
MEM0_STORE_PATH = Path.home() / ".aiqgis" / "mem0_store"

# ── 单例 ──
_memory_instance: Optional["MemoryBridge"] = None

# ── Python 代码块剥离正则 ──
_CODE_BLOCK_RE = re.compile(
    r"```(?:python|py|python3)?\s*\n.*?\n```", re.DOTALL
)
_INLINE_CODE_RE = re.compile(r"`[^`]+`")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")


def _strip_code_blocks(text: str) -> str:
    """剥离 Python 代码块和内联代码，保留纯自然语言部分。

    向量存储如果混入代码块会导致检索漂移——语义搜索会把
    "for layer in layers" 和实际的图层操作查询错误匹配。
    """
    cleaned = _CODE_BLOCK_RE.sub(" ", text)
    cleaned = _INLINE_CODE_RE.sub("", cleaned)
    cleaned = _MULTI_NEWLINE_RE.sub("\n\n", cleaned)
    return cleaned.strip()


# ═══════════════════════════════════════════════════════════════
# MemoryBridge 单例
# ═══════════════════════════════════════════════════════════════


class MemoryBridge:
    """mem0 记忆桥接器。

    封装 mem0 的 add/search 接口，提供三个公开方法：
    - add_experience: 存入历史经验
    - search_relevant_history: 语义检索历史
    - search_spatial_experience: 空间分析专用检索
    """

    _USER_ID = "aiqgis"

    def __init__(self) -> None:
        self._memory: Any = None
        self._ready: bool = False
        self._init()

    # ── 初始化 ─────────────────────────────────────────────

    def _init(self) -> None:
        """初始化 mem0 实例（离线模式，fastembed + Qdrant 本地文件）。"""
        try:
            import mem0  # noqa: F401 — 仅在初始化时导入
        except ImportError:
            _log.info("mem0ai 未安装，记忆桥接器降级为空操作模式")
            return

        MEM0_STORE_PATH.mkdir(parents=True, exist_ok=True)

        # 从 ai_config 读取 LLM 配置（复用用户已配置的端点）
        try:
            from core.ai_config import API_KEY, BASE_URL, MODEL_NAME
        except ImportError:
            API_KEY = "sk-placeholder"
            BASE_URL = "https://api.openai.com/v1"
            MODEL_NAME = "gpt-4o-mini"

        config = {
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "path": str(MEM0_STORE_PATH),
                    "on_disk": True,
                },
            },
            "embedder": {
                "provider": "fastembed",
                "config": {
                    "model": "BAAI/bge-small-zh-v1.5",
                },
            },
            "llm": {
                "provider": "openai",
                "config": {
                    "model": MODEL_NAME,
                    "openai_base_url": BASE_URL,
                    "api_key": API_KEY,
                },
            },
            "history_db_path": str(MEM0_STORE_PATH / "history.db"),
        }

        try:
            self._memory = mem0.Memory.from_config(config_dict=config)
            self._ready = True
            _log.info(
                "记忆桥接器初始化成功 | 存储: %s | Embedding: %s",
                MEM0_STORE_PATH,
                "BAAI/bge-small-zh-v1.5",
            )
        except Exception as exc:
            _log.error("记忆桥接器初始化失败: %s", exc)
            self._memory = None

    @property
    def ready(self) -> bool:
        return self._ready and self._memory is not None

    # ── 公开接口 ①：存入经验 ──────────────────────────────

    def add_experience(
        self,
        user_query: str,
        agent_reasoning: str,
        session_id: str = "default",
    ) -> bool:
        """将用户意图与 Agent 推理合并，剥离代码块后存入向量库。

        Parameters
        ----------
        user_query : str
            用户的原始自然语言输入。
        agent_reasoning : str
            Agent 的输出（含推理过程，自动剥离代码块）。
        session_id : str
            会话标识，用于跨会话分组检索。

        Returns
        -------
        bool
            是否成功存入。
        """
        if not self.ready:
            return False

        # 剥离代码块
        clean_reasoning = _strip_code_blocks(agent_reasoning)

        # 合并为一条结构化经验文本
        experience_text = (
            f"[会话: {session_id}]\n"
            f"用户意图: {user_query}\n"
            f"执行反馈: {clean_reasoning}"
        )

        if len(experience_text.strip()) < 20:
            _log.debug("经验文本过短（<%d 字符），跳过存储", len(experience_text))
            return False

        try:
            self._memory.add(
                experience_text,
                user_id=self._USER_ID,
                metadata={
                    "session_id": session_id,
                    "type": "conversation_turn",
                },
            )
            _log.debug("经验已存入: %s", user_query[:60])
            return True
        except Exception as exc:
            _log.warning("经验存入失败: %s", exc)
            return False

    # ── 公开接口 ②：通用历史检索 ──────────────────────────

    def search_relevant_history(
        self, query: str, top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """语义检索与当前查询最相关的历史经验。

        Parameters
        ----------
        query : str
            当前用户输入文本，用于语义匹配。
        top_k : int
            返回的最大条目数。

        Returns
        -------
        list of dict
            [{"memory": str, "score": float, "metadata": dict}, ...]
        """
        if not self.ready:
            return []

        try:
            results = self._memory.search(
                query, user_id=self._USER_ID, limit=top_k
            )
            out = []
            for item in results:
                out.append({
                    "memory": item.get("memory", ""),
                    "score": item.get("score", 0.0),
                    "metadata": item.get("metadata", {}),
                })
            _log.debug("记忆检索: '%s' → %d 条命中", query[:50], len(out))
            return out
        except Exception as exc:
            _log.warning("记忆检索失败: %s", exc)
            return []

    # ── 公开接口 ③：空间分析专用经验 ──────────────────────

    def search_spatial_experience(
        self, layer_name: str, skill_name: str
    ) -> str:
        """检索上一次对该图层或同类算子操作时的成功/失败经验。

        专为 GeoAgent 设计：在执行 PyQGIS 代码前检索历史避坑记录，
        将命中结果格式化为可直接拼入 code generation prompt 的文本。

        Parameters
        ----------
        layer_name : str
            当前操作的目标图层名称。
        skill_name : str
            当前执行的算子/技能名称（如 "heatmap"、"clip"、"buffer"）。

        Returns
        -------
        str
            格式化的历史经验文本块。
            无命中时返回空字符串。
        """
        if not self.ready:
            return ""

        # 构造语义检索查询：兼顾图层名和算子名
        query = f"空间分析 {skill_name} 操作 {layer_name} 图层"
        results = self._memory.search(
            query, user_id=self._USER_ID, limit=3
        )

        if not results:
            return ""

        tips: List[str] = []
        for item in results:
            memory_text = item.get("memory", "")
            score = item.get("score", 0.0)
            if score < 0.35:  # 低相关度跳过
                continue
            # 截取关键句
            short = memory_text[:200].replace("\n", " ").strip()
            tips.append(f"- [{score:.2f}] {short}")

        if not tips:
            return ""

        return (
            "## 历史避坑指南 (Historical Safeguards)\n\n"
            "以下是从过往同类操作中提取的经验，请在生成代码时主动规避：\n\n"
            + "\n".join(tips)
            + "\n"
        )

    # ── 辅助：获取会话元数据 ──────────────────────────────

    def get_all_memories(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取全部已持久化的记忆（用于启动时加载）。"""
        if not self.ready:
            return []
        try:
            raw = self._memory.get_all(user_id=self._USER_ID, limit=limit)
            return list(raw) if raw else []
        except Exception as exc:
            _log.warning("获取全部记忆失败: %s", exc)
            return []

    def memory_count(self) -> int:
        """已存储的记忆数量。"""
        if not self.ready:
            return 0
        try:
            all_mem = self._memory.get_all(user_id=self._USER_ID, limit=10000)
            return len(list(all_mem)) if all_mem else 0
        except Exception:
            return 0


# ═══════════════════════════════════════════════════════════════
# 模块级单例工厂
# ═══════════════════════════════════════════════════════════════


def get_memory_bridge() -> MemoryBridge:
    """获取全局 MemoryBridge 单例。"""
    global _memory_instance
    if _memory_instance is None:
        _memory_instance = MemoryBridge()
    return _memory_instance


def init_memory_bridge() -> MemoryBridge:
    """显式初始化并返回记忆桥接器（供应用启动时调用）。"""
    bridge = get_memory_bridge()
    if bridge.ready:
        count = bridge.memory_count()
        _log.info("记忆桥接器已就绪，当前存储 %d 条记忆", count)
    return bridge
