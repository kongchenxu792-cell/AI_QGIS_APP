"""提示词 Agent UI 面板。

独立 QDialog，包含：
1. 拖拽文档区域 → 自动识别 .docx/.pdf
2. 原文预览区 → 展示提取的纯文本
3. AI 提炼按钮 → 调用 RefinerEngine
4. 提炼结果展示区
5. 一键应用按钮 → 将指令填入主窗口 AI 输入框
6. 一键瘦身按钮 → 清空 user_data 临时文件
"""

from __future__ import annotations

import importlib
import logging
import os
import re
from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal, QThread
from PyQt5.QtGui import QDragEnterEvent, QDropEvent
from PyQt5.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QMessageBox,
    QGroupBox,
    QFormLayout,
)

from .extractor import extract_text
from .refiner import RefinerEngine

_log = logging.getLogger("prompt_agent.widget")

# ── 支持的文件扩展名白名单 ────────────────────────────────────────────
SUPPORTED_EXTENSIONS = {".docx", ".pdf"}


# ── 后台提炼工作线程 ──────────────────────────────────────────────────

class _RefineWorker(QThread):
    """在后台线程中调用 LLM API，避免阻塞 UI。"""

    finished = pyqtSignal(dict)   # {"instruction": ..., "raw_length": ..., "refined_length": ...}
    failed = pyqtSignal(str)      # 错误描述

    def __init__(self, engine: RefinerEngine, raw_text: str, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._raw_text = raw_text

    def run(self):
        try:
            result = self._engine.refine(self._raw_text)
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(str(e))


class _DragDropZone(QFrame):
    """拖拽文件放置区域。"""

    file_accepted = pyqtSignal(str)  # 发射文件绝对路径

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("dragDropZone")
        self.setMinimumHeight(100)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        self._icon_label = QLabel("📄", self)
        self._icon_label.setAlignment(Qt.AlignCenter)
        self._icon_label.setStyleSheet("font-size: 28px;")

        self._hint_label = QLabel("拖拽 .docx 或 .pdf 文件到此区域\n或点击选择文件", self)
        self._hint_label.setAlignment(Qt.AlignCenter)
        self._hint_label.setStyleSheet("color: #94a3b8; font-size: 13px;")

        layout.addWidget(self._icon_label)
        layout.addWidget(self._hint_label)

        self.setStyleSheet("""
            #dragDropZone {
                background: #f8fafc;
                border: 2px dashed #cbd5e1;
                border-radius: 12px;
            }
            #dragDropZone:hover {
                border-color: #2563eb;
                background: #eff6ff;
            }
        """)

    def mousePressEvent(self, event):
        """点击打开文件选择对话框。"""
        from PyQt5.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择文档",
            "",
            "文档文件 (*.docx *.pdf);;所有文件 (*)",
        )
        if file_path:
            self.file_accepted.emit(file_path)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if len(urls) == 1:
                ext = os.path.splitext(urls[0].toLocalFile())[1].lower()
                if ext in SUPPORTED_EXTENSIONS:
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event: QDropEvent):
        file_path = event.mimeData().urls()[0].toLocalFile()
        self.file_accepted.emit(file_path)


class PromptAgentWidget(QDialog):
    """提示词 Agent 工具窗口。"""

    #: 提炼结果应用到主窗口时发射（指令字符串）
    instruction_applied = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("提示词 Agent — 文档提炼")
        self.resize(680, 640)
        self.setMinimumSize(520, 480)

        self._engine = RefinerEngine()
        self._worker: Optional[_RefineWorker] = None
        self._raw_text: str = ""
        self._refined_instruction: str = ""
        self._current_file: str = ""

        self._build_ui()
        self._apply_styles()

    # ── UI 构建 ────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # (1) 拖拽区域
        self._drop_zone = _DragDropZone(self)
        self._drop_zone.file_accepted.connect(self._on_file_accepted)
        root.addWidget(self._drop_zone)

        # 当前文件路径
        self._file_label = QLabel("尚未加载文档", self)
        self._file_label.setStyleSheet("color: #64748b; font-size: 12px;")
        root.addWidget(self._file_label)

        # (2) 原文预览区
        preview_header = QHBoxLayout()
        preview_label = QLabel("原文预览", self)
        preview_label.setStyleSheet("font-weight: 600; font-size: 13px; color: #1e293b;")
        self._preview_char_count = QLabel("", self)
        self._preview_char_count.setStyleSheet("color: #94a3b8; font-size: 11px;")
        preview_header.addWidget(preview_label)
        preview_header.addStretch()
        preview_header.addWidget(self._preview_char_count)
        root.addLayout(preview_header)

        self._preview_text = QTextEdit(self)
        self._preview_text.setReadOnly(True)
        self._preview_text.setPlaceholderText("文档原文将显示在此处...")
        self._preview_text.setMinimumHeight(140)
        root.addWidget(self._preview_text, 2)

        # (3) 提炼按钮
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self._refine_btn = QPushButton("AI 提炼核心指令", self)
        self._refine_btn.setEnabled(False)
        self._refine_btn.clicked.connect(self._on_refine_clicked)
        self._refine_btn.setMinimumHeight(44)
        self._refine_btn.setStyleSheet("""
            QPushButton {
                background: #7c3aed;
                color: #fff;
                font-weight: 600;
                font-size: 14px;
                border-radius: 10px;
            }
            QPushButton:hover { background: #6d28d9; }
            QPushButton:disabled { background: #cbd5e1; color: #94a3b8; }
        """)
        btn_row.addWidget(self._refine_btn)

        self._clear_btn = QPushButton("清空", self)
        self._clear_btn.clicked.connect(self._on_clear)
        btn_row.addWidget(self._clear_btn)

        self._settings_btn = QPushButton("⚙ API 设置", self)
        self._settings_btn.setToolTip("配置提示词 Agent 独立 API 密钥与模型（与主分析管线隔离）")
        self._settings_btn.clicked.connect(self._show_api_settings)
        self._settings_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #64748b;
                border: 1px solid #cbd5e1;
                font-weight: 500;
                font-size: 13px;
                border-radius: 8px;
                min-width: 90px;
            }
            QPushButton:hover { background: #f1f5f9; color: #334155; }
        """)
        btn_row.addWidget(self._settings_btn)

        btn_row.addStretch()
        root.addLayout(btn_row)

        # (4) 提炼结果展示区
        result_header = QHBoxLayout()
        result_label = QLabel("提炼结果", self)
        result_label.setStyleSheet("font-weight: 600; font-size: 13px; color: #1e293b;")
        result_header.addWidget(result_label)
        result_header.addStretch()
        root.addLayout(result_header)

        self._result_text = QTextEdit(self)
        self._result_text.setReadOnly(True)
        self._result_text.setPlaceholderText("提炼后的核心指令将显示在此处...")
        self._result_text.setMinimumHeight(60)
        self._result_text.setMaximumHeight(100)
        self._result_text.setStyleSheet("""
            QTextEdit {
                background: #f0fdf4;
                border: 1px solid #86efac;
                border-radius: 10px;
                padding: 8px;
                font-size: 14px;
            }
        """)
        root.addWidget(self._result_text)

        # (5) 一键应用按钮
        self._apply_btn = QPushButton("一键应用至主分析框", self)
        self._apply_btn.setEnabled(False)
        self._apply_btn.clicked.connect(self._on_apply_clicked)
        self._apply_btn.setMinimumHeight(44)
        self._apply_btn.setStyleSheet("""
            QPushButton {
                background: #2563eb;
                color: #fff;
                font-weight: 600;
                font-size: 14px;
                border-radius: 10px;
            }
            QPushButton:hover { background: #1d4ed8; }
            QPushButton:disabled { background: #cbd5e1; color: #94a3b8; }
        """)
        root.addWidget(self._apply_btn)

    def _apply_styles(self):
        self.setStyleSheet("""
            QDialog {
                background: #ffffff;
            }
            QTextEdit {
                background: #fbfdff;
                border: 1px solid #dbe3ec;
                border-radius: 10px;
                padding: 8px;
                font-size: 13px;
            }
        """)

    # ── 事件处理 ────────────────────────────────────────────────────

    def _on_file_accepted(self, file_path: str):
        """文档被拖入/选择后执行提取。"""
        self._current_file = file_path
        self._file_label.setText(f"当前文档: {file_path}")
        self._refine_btn.setEnabled(False)
        self._apply_btn.setEnabled(False)
        self._preview_text.setPlainText("正在提取文本...")
        self._result_text.clear()

        try:
            self._raw_text = extract_text(file_path)
        except FileNotFoundError:
            QMessageBox.warning(self, "文件错误", f"文件不存在: {file_path}")
            return
        except ValueError as e:
            QMessageBox.warning(self, "格式错误", str(e))
            return
        except ImportError as e:
            QMessageBox.warning(
                self,
                "缺少依赖",
                f"{e}\n\n请安装后重试。",
            )
            return
        except RuntimeError as e:
            QMessageBox.warning(self, "提取失败", str(e))
            return
        except Exception as e:
            QMessageBox.critical(self, "未知错误", f"提取文本时出错:\n{e}")
            return

        # 显示原文（最多 3000 字符预览）
        preview = self._raw_text[:3000]
        if len(self._raw_text) > 3000:
            preview += f"\n\n... (共 {len(self._raw_text)} 字符，已截断显示)"
        self._preview_text.setPlainText(preview)
        self._preview_char_count.setText(f"共 {len(self._raw_text)} 字符")
        self._refine_btn.setEnabled(True)

    def _on_refine_clicked(self):
        """启动后台线程调用 LLM 提炼。"""
        if not self._raw_text:
            return

        self._refine_btn.setEnabled(False)
        self._refine_btn.setText("提炼中...")
        self._refine_btn.setStyleSheet("""
            QPushButton {
                background: #c4b5fd;
                color: #5b21b6;
                font-weight: 600;
                font-size: 14px;
                border-radius: 10px;
            }
        """)
        self._result_text.setPlainText("正在调用 AI 提炼，请稍候...")
        self._apply_btn.setEnabled(False)

        self._worker = _RefineWorker(self._engine, self._raw_text, self)
        self._worker.finished.connect(self._on_refine_done)
        self._worker.failed.connect(self._on_refine_error)
        self._worker.start()

    def _on_refine_done(self, result: dict):
        """提炼成功回调。"""
        self._refined_instruction = result["instruction"]
        self._result_text.setPlainText(
            f"[{self._refined_instruction}]\n\n"
            f"原文 {result['raw_length']} 字符 → 提炼后 {result['refined_length']} 字符"
        )
        self._refine_btn.setEnabled(True)
        self._restore_refine_button()
        self._apply_btn.setEnabled(True)

    def _on_refine_error(self, error_msg: str):
        """提炼失败回调。"""
        QMessageBox.critical(self, "提炼失败", error_msg)
        self._result_text.clear()
        self._refine_btn.setEnabled(True)
        self._restore_refine_button()

    def _restore_refine_button(self):
        self._refine_btn.setText("AI 提炼核心指令")
        self._refine_btn.setStyleSheet("""
            QPushButton {
                background: #7c3aed;
                color: #fff;
                font-weight: 600;
                font-size: 14px;
                border-radius: 10px;
            }
            QPushButton:hover { background: #6d28d9; }
            QPushButton:disabled { background: #cbd5e1; color: #94a3b8; }
        """)

    def _on_apply_clicked(self):
        """将提炼结果发射出去，由主窗口接入。"""
        if self._refined_instruction:
            self.instruction_applied.emit(self._refined_instruction)
            self.accept()  # 关闭对话框

    def _on_clear(self):
        """清空所有状态。"""
        # 若后台线程仍在运行则终止
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait()
            self._worker = None

        self._raw_text = ""
        self._refined_instruction = ""
        self._current_file = ""
        self._file_label.setText("尚未加载文档")
        self._preview_text.clear()
        self._preview_char_count.clear()
        self._result_text.clear()
        self._refine_btn.setEnabled(False)
        self._restore_refine_button()
        self._apply_btn.setEnabled(False)

    # ── API 配置 ────────────────────────────────────────────────────

    def _show_api_settings(self):
        """打开提示词 Agent 独立 API 配置对话框。"""
        from . import config as pa_config

        dialog = _PromptAgentApiDialog(self, {
            "api_key": pa_config.API_KEY,
            "base_url": pa_config.BASE_URL,
            "model_name": pa_config.MODEL_NAME,
        })
        if dialog.exec_() != QDialog.Accepted:
            return

        result = dialog.config
        config_path = os.path.join(os.path.dirname(__file__), "config.py")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                content = f.read()
            content = re.sub(
                r'API_KEY\s*=\s*"[^"]*"',
                f'API_KEY = "{result["api_key"]}"',
                content,
            )
            content = re.sub(
                r'BASE_URL\s*=\s*"[^"]*"',
                f'BASE_URL = "{result["base_url"]}"',
                content,
            )
            content = re.sub(
                r'MODEL_NAME\s*=\s*"[^"]*"',
                f'MODEL_NAME = "{result["model_name"]}"',
                content,
            )
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(content)

            # 重新加载配置模块并重建引擎实例
            importlib.reload(pa_config)
            self._engine = RefinerEngine()
            QMessageBox.information(
                self, "配置已保存",
                "提示词 Agent API 配置已更新，下次提炼将使用新设置。",
            )
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"无法保存配置：{e}")


class _PromptAgentApiDialog(QDialog):
    """提示词 Agent 专用 API 配置对话框。"""

    def __init__(self, parent=None, current_config=None):
        super().__init__(parent)
        self.setWindowTitle("提示词 Agent API 配置")
        self.setMinimumWidth(500)
        self.setModal(True)
        self.current_config = current_config or {}
        self.config = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        title = QLabel(
            "<b>提示词 Agent 独立 API</b><br>"
            "<span style='color:#64748b;font-size:12px;'>"
            "此配置与主分析管线完全隔离，可接入不同模型（建议轻量模型）</span>"
        )
        title.setWordWrap(True)
        layout.addWidget(title)

        api_group = QGroupBox("API 设置")
        form = QFormLayout(api_group)

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("sk-...")
        form.addRow("API Key:", self.api_key_edit)

        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText("https://dashscope.aliyuncs.com/compatible-mode/v1")
        form.addRow("Base URL:", self.base_url_edit)

        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("qwen-turbo")
        form.addRow("模型名称:", self.model_edit)

        layout.addWidget(api_group)

        note = QLabel(
            "提示：此模块只需文本提炼能力，推荐使用轻量低价模型<br>"
            "（如 qwen-turbo / glm-4-flash），不必与主分析的强推理模型一致。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #64748b; font-size: 12px;")
        layout.addWidget(note)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        save_btn = QPushButton("保存配置")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._validate_and_accept)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

        self._load_config()

    def _load_config(self):
        self.api_key_edit.setText(self.current_config.get("api_key", ""))
        self.base_url_edit.setText(self.current_config.get("base_url", ""))
        self.model_edit.setText(self.current_config.get("model_name", ""))

    def _validate_and_accept(self):
        api_key = self.api_key_edit.text().strip()
        base_url = self.base_url_edit.text().strip()
        model_name = self.model_edit.text().strip()

        if not api_key:
            QMessageBox.warning(self, "验证失败", "API Key 不能为空。")
            return
        if not base_url:
            QMessageBox.warning(self, "验证失败", "Base URL 不能为空。")
            return
        if not model_name:
            QMessageBox.warning(self, "验证失败", "模型名称不能为空。")
            return
        if not base_url.startswith(("http://", "https://")):
            QMessageBox.warning(self, "验证失败", "Base URL 必须以 http:// 或 https:// 开头。")
            return

        self.config = {
            "api_key": api_key,
            "base_url": base_url,
            "model_name": model_name,
        }
        self.accept()