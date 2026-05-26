"""
API 配置对话框，允许用户通过 GUI 修改 DeepSeek API 设置。
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QMessageBox,
    QFormLayout,
    QGroupBox,
)


class ApiConfigDialog(QDialog):
    """API 配置对话框。"""

    def __init__(self, parent=None, current_config=None):
        """
        初始化对话框。

        Parameters
        ----------
        parent : QWidget, optional
            父窗口。
        current_config : dict, optional
            当前配置字典，包含：
            - api_key: str
            - base_url: str
            - model_name: str
        """
        super().__init__(parent)
        self.setWindowTitle("AI API 配置")
        self.setMinimumWidth(500)
        self.setModal(True)

        self.current_config = current_config or {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建对话框 UI。"""

        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # API 设置组
        api_group = QGroupBox("DeepSeek API 设置")
        form_layout = QFormLayout(api_group)

        # API Key
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("sk-...")
        form_layout.addRow("API Key:", self.api_key_edit)

        # Base URL
        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText("https://api.deepseek.com/v1")
        form_layout.addRow("Base URL:", self.base_url_edit)

        # Model Name
        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("deepseek-chat")
        form_layout.addRow("模型名称:", self.model_edit)

        layout.addWidget(api_group)

        # 说明标签
        note = QLabel(
            "提示：\n"
            "• API Key 可从 DeepSeek 控制台获取\n"
            "• Base URL 通常为 https://api.deepseek.com/v1\n"
            "• 模型名称默认为 deepseek-chat"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(note)

        # 按钮行
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)

        self.save_btn = QPushButton("保存配置")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._validate_and_accept)
        button_layout.addWidget(self.save_btn)

        layout.addLayout(button_layout)

        # 加载当前配置
        self._load_current_config()

    def _load_current_config(self) -> None:
        """将当前配置加载到输入框中。"""
        if self.current_config:
            self.api_key_edit.setText(self.current_config.get("api_key", ""))
            self.base_url_edit.setText(self.current_config.get("base_url", ""))
            self.model_edit.setText(self.current_config.get("model_name", ""))

    def _validate_and_accept(self) -> None:
        """验证输入并接受对话框。"""
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

        # 简单 URL 格式检查
        if not base_url.startswith(("http://", "https://")):
            QMessageBox.warning(self, "验证失败", "Base URL 必须以 http:// 或 https:// 开头。")
            return

        self.config = {
            "api_key": api_key,
            "base_url": base_url,
            "model_name": model_name,
        }
        self.accept()

    @classmethod
    def get_config(cls, parent=None, current_config=None):
        """
        静态方法：显示对话框并返回配置。

        Parameters
        ----------
        parent : QWidget, optional
            父窗口。
        current_config : dict, optional
            当前配置。

        Returns
        -------
        dict or None
            如果用户点击保存，返回配置字典；如果取消，返回 None。
        """
        dialog = cls(parent, current_config)
        if dialog.exec_() == QDialog.Accepted:
            return dialog.config
        return None