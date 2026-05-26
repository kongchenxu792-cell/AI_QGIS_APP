"""轻量桌面 GIS 应用程序的主窗口实现。

提供完整的桌面 GIS 界面，包含：
- 左侧：QGIS 原生图层树面板
- 中央：支持拖放加载的 QGIS 地图画布
- 底部：AI 自然语言处理控制台
- 顶部：地图导航工具栏
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from typing import Any, Dict, Iterable, List

from PyQt5.QtCore import Qt, pyqtSignal, QEvent, QThread
from PyQt5.QtGui import QColor, QDragEnterEvent, QDropEvent, QKeySequence
from PyQt5.QtWidgets import (
    QAction,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QShortcut,
    QSplitter,
    QStatusBar,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)
from qgis.core import (
    QgsLayerTreeGroup,
    QgsLayerTreeLayer,
    QgsLayerTreeModel,
    QgsMapLayer,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import (
    QgsLayerTreeMapCanvasBridge,
    QgsLayerTreeView,
    QgsLayerTreeViewMenuProvider,
    QgsMapCanvas,
    QgsMapToolPan,
    QgsMapToolZoom,
)




from core.ai_worker import AIProcessingWorker, parse_agent_response, request_spatial_code
from core.layer_loader import create_layer_from_path, is_supported_path, load_layers_from_paths
from core.qgis_env import QgisBootstrapResult
from ui.api_config_dialog import ApiConfigDialog
from ui.ai_code_preview import AiCodePreviewDialog
from ui.attribute_table import AttributeTableDialog
from skills.spatial_analysis_skill import SpatialAnalysisSkill
from skills.skill_manager import get_skill_manager

_log = logging.getLogger("main_window")


class DroppableMapCanvas(QgsMapCanvas):
    """支持本地文件拖放加载的 QGIS 地图画布。

    信号
    ----
    filesDropped : pyqtSignal(list)
        当用户拖放支持的 GIS 文件到画布时触发，携带文件路径列表。
    """

    filesDropped = pyqtSignal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        """初始化可拖放画布。"""

        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """接受包含支持 GIS 文件的拖放事件。"""

        if _extract_supported_paths(event.mimeData().urls()):
            event.acceptProposedAction()
            return

        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        """发射拖放文件路径信号。"""

        file_paths = _extract_supported_paths(event.mimeData().urls())
        if file_paths:
            event.acceptProposedAction()
            self.filesDropped.emit(file_paths)
            return

        event.ignore()


def _extract_supported_paths(urls: Iterable) -> List[str]:
    """从拖放 URL 中提取支持的本地文件路径。

    参数
    ----
    urls : Iterable
        QMimeData 中的 URL 对象列表。

    返回
    ----
    List[str]
        去重后的支持文件路径列表。
    """

    file_paths = []
    for url in urls:
        if not url.isLocalFile():
            continue

        local_file = url.toLocalFile()
        if is_supported_path(local_file):
            file_paths.append(local_file)

    return file_paths


class LayerTreeMenuProvider(QgsLayerTreeViewMenuProvider):
    """QGIS 官方右键菜单接口，通过 setMenuProvider() 注册，不与 C++ 事件冲突。"""

    def __init__(
        self,
        view: QgsLayerTreeView,
        on_attribute_table=None,
        on_zoom=None,
        on_remove=None,
        on_rename=None,
        on_copy=None,
    ) -> None:
        super().__init__()
        self._view = view
        self._on_attribute_table = on_attribute_table
        self._on_zoom = on_zoom
        self._on_remove = on_remove
        self._on_rename = on_rename
        self._on_copy = on_copy

    def createContextMenu(self) -> QMenu | None:
        # QGIS 先设置 currentIndex 再调用此方法
        node = self._view.currentNode()
        if node is None:
            node = self._view.layerTreeModel().index2node(self._view.currentIndex())
        if not isinstance(node, QgsLayerTreeLayer):
            return None
        layer = node.layer()
        if layer is None:
            return None

        menu = QMenu()

        if layer.type() == QgsMapLayer.VectorLayer:
            attr_action = menu.addAction("查看属性表")
            attr_action.triggered.connect(lambda: self._on_attribute_table(layer))

        zoom_action = menu.addAction("缩放到图层")
        zoom_action.triggered.connect(lambda: self._on_zoom(layer))

        menu.addSeparator()

        rename_action = menu.addAction("重命名图层")
        rename_action.triggered.connect(lambda: self._on_rename_triggered(layer))

        copy_action = menu.addAction("复制图层")
        copy_action.triggered.connect(lambda: self._on_copy(layer))

        menu.addSeparator()

        remove_action = menu.addAction("移除图层")
        remove_action.triggered.connect(lambda: self._on_remove(layer))

        # QGIS 负责调用 menu.exec()
        return menu

    def _on_rename_triggered(self, layer) -> None:
        new_name, ok = QInputDialog.getText(
            self._view, "重命名图层", "新名称：", text=layer.name(),
        )
        if ok and new_name.strip() and self._on_rename:
            self._on_rename(layer, new_name.strip())


class MainWindow(QMainWindow):
    """桌面 GIS MVP 应用程序的主窗口类。

    布局
    ----
    - 左侧：QGIS 原生图层树面板
    - 中央：QGIS 地图画布（支持拖放加载）
    - 底部：AI 自然语言处理控制台
    - 顶部：地图导航工具栏
    """

    def __init__(self, bootstrap_result: QgisBootstrapResult) -> None:
        """初始化主窗口及其子控件。"""

        super().__init__()
        self.bootstrap_result = bootstrap_result
        self.layer_tree_view = None
        self.layer_tree_model = None
        self.map_canvas = None
        self.canvas_bridge = None
        self.pan_tool = None
        self.zoom_in_tool = None
        self.zoom_out_tool = None
        self.ai_worker = None
        self.last_ai_code = ""
        self.skip_preview = False  # 是否跳过代码预览

        self.ai_prompt_input = QTextEdit(self)
        self.run_button = QPushButton("运行 AI 分析", self)
        self.ai_response_display = QTextEdit(self)
        self.ai_response_display.setReadOnly(True)

        self.setWindowTitle("AI 驱动轻量桌面 GIS")
        self.resize(1440, 900)
        self._build_ui()
        self._apply_styles()
        self.statusBar().showMessage("系统就绪，可将 SHP、GeoJSON、TIF 等图层文件拖拽到地图画布中。", 5000)

    def _build_ui(self) -> None:
        """构建完整的窗口布局。"""

        self._build_menubar()
        self._build_toolbar()

        central_widget = QWidget(self)
        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(12)

        splitter = QSplitter(Qt.Horizontal, central_widget)
        splitter.addWidget(self._build_sidebar())
        splitter.addWidget(self._build_canvas_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 1100])

        root_layout.addWidget(splitter, 1)
        root_layout.addWidget(self._build_ai_console(), 0)
        self.setCentralWidget(central_widget)
        self.setStatusBar(QStatusBar(self))

        # 键盘快捷键
        QShortcut(QKeySequence(Qt.CTRL + Qt.Key_Equal), self, self._zoom_in)
        QShortcut(QKeySequence(Qt.CTRL + Qt.Key_Minus), self, self._zoom_out)
        QShortcut(QKeySequence(Qt.CTRL + Qt.Key_0), self, self._zoom_full)

    def _build_menubar(self) -> None:
        """构建菜单栏。"""
        menubar = self.menuBar()

        file_menu = menubar.addMenu("文件(&F)")
        settings_action = QAction("API 设置(&S)...", self)
        settings_action.triggered.connect(self._show_api_config)
        file_menu.addAction(settings_action)
        file_menu.addSeparator()
        exit_action = QAction("退出(&X)", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        view_menu = menubar.addMenu("视图(&V)")
        preview_action = QAction(
            "启用代码预览(&P)",
            self,
            checkable=True,
            checked=not self.skip_preview,
        )
        preview_action.triggered.connect(self._toggle_preview)
        view_menu.addAction(preview_action)

        help_menu = menubar.addMenu("帮助(&H)")
        view_log_action = QAction("查看日志(&L)...", self)
        view_log_action.triggered.connect(self._show_log_viewer)
        help_menu.addAction(view_log_action)
        help_menu.addSeparator()
        about_action = QAction("关于 AIQGIS(&A)", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _show_api_config(self) -> None:
        """显示 API 配置对话框。"""
        import core.ai_config as ai_config
        current = {
            "api_key": ai_config.API_KEY,
            "base_url": ai_config.BASE_URL,
            "model_name": ai_config.MODEL_NAME,
        }
        result = ApiConfigDialog.get_config(self, current)
        if not result:
            return

        # 读取文件、替换、写回
        import re
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "core", "ai_config.py"
        )
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

            # 动态更新已加载的模块
            ai_config.API_KEY = result["api_key"]
            ai_config.BASE_URL = result["base_url"]
            ai_config.MODEL_NAME = result["model_name"]

            QMessageBox.information(self, "配置已保存", "API 配置已更新，下次分析将使用新设置。")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"无法保存配置：{e}")

    def _toggle_preview(self, checked: bool) -> None:
        """切换代码预览开关。"""
        self.skip_preview = not checked
        self.statusBar().showMessage(
            "代码预览已启用" if checked else "代码预览已关闭，AI 代码将直接执行",
            3000,
        )

    def _show_about(self) -> None:
        """显示关于对话框。"""
        QMessageBox.about(
            self,
            "关于 AIQGIS",
            "<h2>AIQGIS</h2>"
            "<p>AI 驱动轻量桌面 GIS 应用</p>"
            "<p>版本 0.2.0</p>"
            "<p>基于 PyQGIS + DeepSeek</p>"
            "<p>开源项目 - GitHub</p>",
        )

    def _show_log_viewer(self) -> None:
        """显示日志查看对话框，ERROR/CRITICAL 行前加红色感叹号标记。"""
        from PyQt5.QtWidgets import QDialog, QVBoxLayout
        from PyQt5.QtGui import QTextCursor

        # 定位日志文件
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        log_path = os.path.join(project_root, "logs", "aiqgis.log")

        # 读取并标记错误行
        lines: List[str] = []
        error_count = 0
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                raw_lines = f.readlines()
        except FileNotFoundError:
            raw_lines = ["日志文件尚未生成。请先运行程序触发一次日志记录。"]
        except Exception as exc:
            raw_lines = [f"读取日志文件失败：{exc}"]

        for line in raw_lines:
            stripped = line.strip()
            if "| ERROR " in stripped or "| CRITICAL " in stripped or "| WARNING " in stripped:
                if "| ERROR " in stripped or "| CRITICAL " in stripped:
                    lines.append(f"  {stripped}")
                    error_count += 1
                else:
                    lines.append(f"  {stripped}")
            else:
                lines.append(f"    {stripped}")

        full_text = "\n".join(lines)

        # 构建对话框
        dialog = QDialog(self)
        dialog.setWindowTitle("运行日志")
        dialog.resize(1000, 650)
        dialog.setMinimumSize(700, 400)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)

        text_edit = QTextEdit(dialog)
        text_edit.setReadOnly(True)
        text_edit.setPlainText(full_text)
        # 等宽字体
        text_edit.setStyleSheet("""
            QTextEdit {
                font-family: "Consolas", "Microsoft YaHei", monospace;
                font-size: 13px;
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: none;
            }
        """)

        # 高亮 ERROR/CRITICAL 行 — 红色前景 + 感叹号前缀
        doc = text_edit.document()
        cursor = QTextCursor(doc)
        fmt_error = text_edit.currentCharFormat()
        fmt_error.setForeground(QColor("#f44747"))
        fmt_error.setFontWeight(75)

        fmt_warn = text_edit.currentCharFormat()
        fmt_warn.setForeground(QColor("#e5c07b"))

        fmt_normal = text_edit.currentCharFormat()
        fmt_normal.setForeground(QColor("#d4d4d4"))
        fmt_normal.setFontWeight(50)

        cursor.movePosition(QTextCursor.Start)
        block = doc.begin()
        while block.isValid():
            text = block.text()
            if text.lstrip().startswith("!"):
                cursor.setPosition(block.position())
                cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
                if "| ERROR " in text or "| CRITICAL " in text:
                    cursor.mergeCharFormat(fmt_error)
                else:
                    cursor.mergeCharFormat(fmt_warn)
            else:
                cursor.setPosition(block.position())
                cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
                cursor.mergeCharFormat(fmt_normal)
            block = block.next()

        # 滚动到底部（最新日志）
        cursor.movePosition(QTextCursor.End)
        text_edit.setTextCursor(cursor)
        text_edit.ensureCursorVisible()

        layout.addWidget(text_edit)

        status_label = QLabel(
            f"日志共 {len(raw_lines)} 行 | 错误 {error_count} 条"
            if error_count
            else f"日志共 {len(raw_lines)} 行 | 无错误"
        )
        status_label.setStyleSheet(
            "font-size: 12px; color: #888; padding: 4px 8px;"
        )
        layout.addWidget(status_label)

        dialog.exec_()

    def _build_toolbar(self) -> None:
        """构建顶部地图导航工具栏。"""

        toolbar = QToolBar("地图工具", self)
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)

        pan_action = QAction("平移", self)
        pan_action.setToolTip("启用地图平移（按住鼠标左键拖动）")
        zoom_in_action = QAction("放大", self)
        zoom_in_action.setToolTip("启用框选放大（按住鼠标左键拖拽矩形区域）")
        zoom_out_action = QAction("缩小", self)
        zoom_out_action.setToolTip("启用框选缩小（点击地图或拖拽矩形区域）")

        pan_action.triggered.connect(self._handle_pan)
        zoom_in_action.triggered.connect(self._handle_zoom_in)
        zoom_out_action.triggered.connect(self._handle_zoom_out)

        toolbar.addAction(pan_action)
        toolbar.addAction(zoom_in_action)
        toolbar.addAction(zoom_out_action)
        self.addToolBar(toolbar)

    def _build_sidebar(self) -> QWidget:
        """构建左侧原生 QGIS 图层树面板。"""

        sidebar = QFrame(self)
        sidebar.setObjectName("sidebarPanel")
        sidebar.setMinimumWidth(280)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QLabel("图层列表", sidebar)
        title.setObjectName("panelTitle")

        self.layer_tree_view = QgsLayerTreeView(sidebar)
        self.layer_tree_view.setObjectName("layerTreeView")
        self.layer_tree_view.setHeaderHidden(True)

        menu_provider = LayerTreeMenuProvider(
            self.layer_tree_view,
            on_attribute_table=self._open_attribute_table,
            on_zoom=self._zoom_to_layer,
            on_remove=self._remove_layer_from_menu,
            on_rename=self._rename_layer,
            on_copy=self._copy_layer,
        )
        self.layer_tree_view.setMenuProvider(menu_provider)

        if self.bootstrap_result.available:
            root = QgsProject.instance().layerTreeRoot()
            self.layer_tree_model = QgsLayerTreeModel(root)
            self.layer_tree_model.setFlag(QgsLayerTreeModel.AllowNodeReorder, True)
            self.layer_tree_model.setFlag(QgsLayerTreeModel.AllowNodeChangeVisibility, True)
            self.layer_tree_view.setModel(self.layer_tree_model)

        layout.addWidget(title)
        layout.addWidget(self.layer_tree_view, 1)

        # 图层操作按钮
        btn_row = QHBoxLayout()
        btn_remove = QPushButton("移除图层")
        btn_remove.setToolTip("从工程中移除选中的图层（不删除文件）")
        btn_remove.clicked.connect(self._remove_selected_layer)
        btn_zoom = QPushButton("缩放到图层")
        btn_zoom.setToolTip("将地图缩放至选中图层的范围")
        btn_zoom.clicked.connect(self._zoom_to_selected_layer)
        btn_row.addWidget(btn_remove)
        btn_row.addWidget(btn_zoom)
        layout.addLayout(btn_row)

        return sidebar

    def _build_canvas_panel(self) -> QWidget:
        """构建中央地图画布面板。"""

        container = QFrame(self)
        container.setObjectName("canvasPanel")

        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        if not self.bootstrap_result.available:
            message_label = QLabel(self.bootstrap_result.message, container)
            message_label.setObjectName("canvasStatus")
            message_label.setWordWrap(True)
            message_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(message_label)
            return container

        self.map_canvas = DroppableMapCanvas(container)
        self.map_canvas.setCanvasColor(QColor("#ffffff"))
        self.map_canvas.setToolTip("可将 SHP、GeoJSON、TIF 等图层文件拖拽到此处加载。")
        self.map_canvas.filesDropped.connect(self._load_dropped_files)

        root = QgsProject.instance().layerTreeRoot()
        self.canvas_bridge = QgsLayerTreeMapCanvasBridge(root, self.map_canvas)

        self.pan_tool = QgsMapToolPan(self.map_canvas)
        self.zoom_in_tool = QgsMapToolZoom(self.map_canvas, False)
        self.zoom_out_tool = QgsMapToolZoom(self.map_canvas, True)
        self.map_canvas.setMapTool(self.pan_tool)

        layout.addWidget(self.map_canvas, 1)
        return container

    def _build_ai_console(self) -> QWidget:
        """构建底部 AI 提示控制台。"""

        container = QFrame(self)
        container.setObjectName("aiConsole")

        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # 输入行
        input_row = QHBoxLayout()
        input_row.setSpacing(12)

        self.ai_prompt_input.setObjectName("aiPromptInput")
        self.ai_prompt_input.setPlaceholderText(
            "请输入自然语言空间分析指令，例如：“为当前图层创建 30 米缓冲区”"
        )
        self.ai_prompt_input.setToolTip(
            "AI 会将自然语言指令转换为 PyQGIS 处理代码并自动执行。"
        )
        self.ai_prompt_input.setFixedHeight(96)

        button_column = QVBoxLayout()
        button_column.setContentsMargins(0, 0, 0, 0)
        button_column.setSpacing(8)
        button_column.addStretch(1)

        self.run_button.setToolTip("执行当前 AI 地理空间分析指令")
        self.run_button.clicked.connect(self._handle_run_clicked)
        button_column.addWidget(self.run_button)

        input_row.addWidget(self.ai_prompt_input, 1)
        input_row.addLayout(button_column)

        main_layout.addLayout(input_row)

        # AI 响应显示区
        self.ai_response_display.setObjectName("aiResponseDisplay")
        self.ai_response_display.setPlaceholderText("AI 响应将显示在此处...")
        self.ai_response_display.setToolTip("AI 返回的原始响应内容")
        self.ai_response_display.setFixedHeight(120)
        main_layout.addWidget(self.ai_response_display)

        return container

    def _apply_styles(self) -> None:
        """应用现代化简约样式表。"""

        self.setStyleSheet(
            """
            QMainWindow {
                background: #f4f7fb;
            }
            QToolBar {
                background: #ffffff;
                border: none;
                spacing: 8px;
                padding: 8px 12px;
            }
            QToolButton {
                background: #e7edf6;
                border: 1px solid #d4dde8;
                border-radius: 8px;
                padding: 8px 14px;
            }
            #sidebarPanel, #aiConsole, #canvasPanel {
                background: #ffffff;
                border: 1px solid #dbe3ec;
                border-radius: 14px;
            }
            #panelTitle {
                font-size: 16px;
                font-weight: 600;
                color: #16202a;
            }
            #canvasStatus {
                color: #b54708;
                font-size: 14px;
                padding: 24px;
            }
            QTextEdit, #aiPromptInput, #aiResponseDisplay {
                background: #fbfdff;
                border: 1px solid #dbe3ec;
                border-radius: 10px;
                padding: 8px;
            }
            #layerTreeView {
                background: #fbfdff;
                border: 1px solid #dbe3ec;
                border-radius: 10px;
            }
            QPushButton {
                min-width: 100px;
                min-height: 40px;
                background: #2563eb;
                color: #ffffff;
                border: none;
                border-radius: 10px;
                font-weight: 600;
                padding: 0 16px;
            }
            QPushButton:hover {
                background: #1d4ed8;
            }
            QStatusBar {
                background: #ffffff;
                color: #475467;
            }
            """
        )

    def _handle_pan(self) -> None:
        """激活平移模式。"""

        if self.map_canvas is None or self.pan_tool is None:
            self._show_qgis_error()
            return

        self.map_canvas.setMapTool(self.pan_tool)
        self.statusBar().showMessage("当前工具：平移（按住鼠标左键拖动地图）", 3000)

    def _handle_zoom_in(self) -> None:
        """激活放大模式。"""

        if self.map_canvas is None or self.zoom_in_tool is None:
            self._show_qgis_error()
            return

        self.map_canvas.setMapTool(self.zoom_in_tool)
        self.statusBar().showMessage("当前工具：放大（拖拽矩形区域）", 3000)

    def _handle_zoom_out(self) -> None:
        """激活缩小模式。"""

        if self.map_canvas is None or self.zoom_out_tool is None:
            self._show_qgis_error()
            return

        self.map_canvas.setMapTool(self.zoom_out_tool)
        self.statusBar().showMessage("当前工具：缩小（点击或拖拽矩形区域）", 3000)

    def _handle_run_clicked(self) -> None:
        """将当前 AI 指令发送至后台工作线程。"""

        user_text = self.ai_prompt_input.toPlainText().strip()
        if not user_text:
            QMessageBox.warning(
                self,
                "缺少分析指令",
                "请输入地理空间分析指令后再运行。",
            )
            return

        # 本地关键词预检：明显的属性表请求直接路由
        table_keywords = ["属性表", "查看属性", "查看数据", "看属性", "打开表", "表格"]
        if any(kw in user_text for kw in table_keywords):
            mgr = get_skill_manager()
            result = mgr.execute_skill("open_table", active_layer=self._get_active_layer(),
                                       layer_tree=self.layer_tree_view)
            if result.get("success") and result.get("layer"):
                self._open_attribute_table(result["layer"])
            else:
                QMessageBox.information(self, "提示", result.get("message", "无法打开属性表"))
            return

        layer_metadata = self._collect_layer_metadata()
        if not layer_metadata:
            QMessageBox.warning(
                self,
                "缺少图层数据",
                "当前没有可分析的图层，请先拖拽加载至少一个图层。",
            )
            return

        self.run_button.setEnabled(False)
        self.statusBar().showMessage("AI 正在思考并计算中，请稍候...")

        self.ai_worker = AIProcessingWorker(user_text, layer_metadata)
        self.ai_worker.succeeded.connect(self._handle_ai_response)
        self.ai_worker.failed.connect(self._handle_ai_error)
        self.ai_worker.finished.connect(self._reset_ai_worker_state)
        self.ai_worker.start()

    def _show_qgis_error(self) -> None:
        """当 QGIS 不可用时显示中文错误对话框。"""

        QMessageBox.critical(
            self,
            "QGIS 环境不可用",
            self.bootstrap_result.message,
        )

    def _load_dropped_files(self, file_paths: List[str]) -> None:
        """加载拖放的图层文件并立即刷新地图画布。"""

        try:
            loaded_layers, errors = load_layers_from_paths(file_paths)

            if not loaded_layers and errors:
                QMessageBox.warning(
                    self,
                    "图层加载失败",
                    "\n".join(errors),
                )
                return

            if loaded_layers:
                self._zoom_to_layers(loaded_layers)
                self.statusBar().showMessage(
                    f"已成功加载 {len(loaded_layers)} 个图层。",
                    5000,
                )

            if errors:
                QMessageBox.warning(
                    self,
                    "部分文件未加载",
                    "\n".join(errors),
                )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "拖拽加载异常",
                f"处理拖拽文件时发生错误：{exc}",
            )

    def _zoom_to_layers(self, layers: List[object]) -> None:
        """将地图画布缩放至新加载图层的合并范围。"""

        if self.map_canvas is None:
            return

        combined_extent = None
        for layer in layers:
            layer_extent = layer.extent()
            if layer_extent.isEmpty():
                continue

            if combined_extent is None:
                combined_extent = QgsRectangle(layer_extent)
            else:
                combined_extent.combineExtentWith(layer_extent)

        if combined_extent is not None:
            self.map_canvas.setExtent(combined_extent)

        self.map_canvas.refresh()

    def _open_attribute_table(self, layer) -> None:
        """打开矢量图层属性表查看器。"""
        dialog = AttributeTableDialog(layer, self)
        dialog.exec_()

    def _zoom_to_layer(self, layer) -> None:
        """缩放到指定图层范围（右键菜单回调）。"""
        if layer is None or not self.map_canvas:
            return
        extent = layer.extent()
        if not extent.isEmpty():
            self.map_canvas.setExtent(extent)
            self.map_canvas.refresh()

    def _remove_layer_node(self, node) -> None:
        """移除指定图层节点（右键菜单回调）。"""
        layer = node.layer()
        if layer is None:
            return
        reply = QMessageBox.question(
            self,
            "确认移除",
            f"确定要移除图层「{layer.name()}」吗？\n此操作不会删除原始文件。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        parent = node.parent()
        if parent:
            parent.removeChildNode(node)
        self.map_canvas.refresh()
        self.statusBar().showMessage(f"已移除图层：{layer.name()}", 3000)

    def _remove_layer_from_menu(self, layer) -> None:
        """移除图层（右键菜单回调，接收 QgsMapLayer 而非 QgsLayerTreeLayer）。"""
        node = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
        if node is not None:
            self._remove_layer_node(node)

    def _rename_layer(self, layer, new_name: str) -> None:
        """重命名图层（右键菜单回调）。"""
        old_name = layer.name()
        layer.setName(new_name)
        self.statusBar().showMessage(f"已重命名：{old_name} → {new_name}", 3000)
        self.map_canvas.refresh()

    def _copy_layer(self, layer) -> None:
        """复制图层（右键菜单回调）。"""
        if isinstance(layer, QgsVectorLayer):
            geom_type_str = QgsWkbTypes.displayString(layer.wkbType())
            crs = layer.crs().authid()
            uri = f"{geom_type_str}?crs={crs}"
            for field in layer.fields():
                uri += f"&field={field.name()}:{field.typeName()}"
            new_layer = QgsVectorLayer(uri, f"{layer.name()} (副本)", "memory")
            features = list(layer.getFeatures())
            if features:
                new_layer.dataProvider().addFeatures(features)
                new_layer.updateExtents()
            QgsProject.instance().addMapLayer(new_layer)
            self.map_canvas.refresh()
            self.statusBar().showMessage(f"已复制图层：{new_layer.name()}", 3000)
        else:
            QMessageBox.information(self, "提示", "暂不支持复制栅格图层。")

    def _remove_selected_layer(self) -> None:
        """使用 QGIS 原生 LayerTree API 移除图层。"""
        current = self._get_selected_layer_node()
        if not current:
            QMessageBox.information(self, "提示", "请先在图层列表中选中一个图层。")
            return
        layer = current.layer()
        if layer is None:
            return
        reply = QMessageBox.question(
            self,
            "确认移除",
            f"确定要移除图层「{layer.name()}」吗？\n此操作不会删除原始文件。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        # QGIS 原生方式：从父节点移除子节点（QGIS 内部就是这样做的）
        parent = current.parent()
        if parent:
            parent.removeChildNode(current)
        self.map_canvas.refresh()
        self.statusBar().showMessage(f"已移除图层：{layer.name()}", 3000)

    def _zoom_to_selected_layer(self) -> None:
        """缩放到当前选中图层的范围。"""
        current = self._get_selected_layer_node()
        if not current:
            return
        layer = current.layer()
        if layer is None or not self.map_canvas:
            return
        extent = layer.extent()
        if not extent.isEmpty():
            self.map_canvas.setExtent(extent)
            self.map_canvas.refresh()

    def _zoom_in(self) -> None:
        """放大一级。"""
        if self.map_canvas:
            self.map_canvas.zoomIn()

    def _zoom_out(self) -> None:
        """缩小一级。"""
        if self.map_canvas:
            self.map_canvas.zoomOut()

    def _zoom_full(self) -> None:
        """缩放到所有图层的完整范围。"""
        if self.map_canvas:
            self.map_canvas.zoomToFullExtent()

    def _get_selected_layer_node(self):
        """获取当前选中的图层树节点。"""
        if not self.layer_tree_view:
            return None
        try:
            node = self.layer_tree_view.currentNode()
            if node and hasattr(node, 'layer') and node.layer():
                return node
        except Exception:
            pass
        if self.layer_tree_model:
            try:
                sm = self.layer_tree_view.selectionModel()
                if sm and sm.selectedIndexes():
                    idx = sm.selectedIndexes()[0]
                    node = self.layer_tree_model.index2node(idx)
                    if node and hasattr(node, 'layer') and node.layer():
                        return node
            except Exception:
                pass
        return None

    def _collect_layer_metadata(self) -> List[Dict[str, Any]]:
        """收集当前已加载图层的元数据供 AI 工作线程使用。"""

        active_layer = self._get_active_layer()
        metadata = []
        for layer in QgsProject.instance().mapLayers().values():
            metadata.append(
                {
                    "name": layer.name(),
                    "type": self._layer_type_name(layer),
                    "path": layer.source(),
                    "provider": layer.providerType(),
                    "is_active": active_layer is not None and layer.id() == active_layer.id(),
                }
            )

        return metadata

    def _get_active_layer(self):
        """返回当前活动图层（若存在）。"""

        if self.layer_tree_view is not None and hasattr(self.layer_tree_view, "currentLayer"):
            layer = self.layer_tree_view.currentLayer()
            if layer is not None:
                return layer

        layers = list(QgsProject.instance().mapLayers().values())
        return layers[0] if layers else None

    @staticmethod
    def _layer_type_name(layer: QgsMapLayer) -> str:
        """将图层实例转换为可读的类型名称。"""

        if layer.type() == QgsMapLayer.VectorLayer:
            return "矢量图层"
        if layer.type() == QgsMapLayer.RasterLayer:
            return "栅格图层"

        return "未知类型"

    def _handle_ai_response(self, response_text: str) -> None:
        """解析 AI JSON 路由指令，通过 SkillManager 分派执行。"""

        self.ai_response_display.setPlainText(response_text)

        try:
            route = parse_agent_response(response_text)
            skill_name = route.get("skill", "unknown")
            reasoning = route.get("reasoning", "")
            arguments = route.get("arguments", "")

            _log.info("AI 路由 → %s，理由：%s", skill_name, reasoning)
            self.statusBar().showMessage(f"路由：{skill_name} — {reasoning}", 5000)

            if skill_name == "unknown":
                QMessageBox.information(self, "AI 响应", reasoning or "无法识别该指令。")
                return

            # spatial_analysis 需要两步走（AI 生成代码 → 执行），走独立通道
            if skill_name == "spatial_analysis":
                self._dispatch_spatial_analysis(
                    arguments or self.ai_prompt_input.toPlainText().strip()
                )
                return

            # 其余技能通过 SkillManager 统一执行
            mgr = get_skill_manager()
            result = mgr.execute_skill(
                skill_name,
                canvas=self.map_canvas,
                layer_tree=self.layer_tree_view,
                arguments=arguments,
                active_layer=self._get_active_layer(),
                main_window=self,
            )

            if not result.get("success"):
                QMessageBox.information(self, "技能返回", result.get("message", "未知错误"))
                return

            if skill_name == "open_table":
                layer = result.get("layer")
                if layer:
                    self._open_attribute_table(layer)

            elif skill_name == "layer_styling":
                self.statusBar().showMessage(result.get("message", "样式已应用"), 5000)

            elif skill_name == "map_export":
                self.statusBar().showMessage(result.get("message", "导出完成"), 5000)

            # 处理新增图层
            added = result.get("added_layers", [])
            if added:
                self._zoom_to_layers(added)

        except Exception as exc:
            _log.exception("AI 响应处理异常，进入回退执行")
            self._fallback_legacy_execution(response_text, exc)

    def _dispatch_spatial_analysis(self, user_text: str) -> None:
        """分派空间分析任务：生成代码 → 预览 → 执行。"""
        layer_metadata = self._collect_layer_metadata()
        if not layer_metadata:
            QMessageBox.warning(self, "缺少图层", "请先加载图层数据。")
            return

        _log.info("分派空间分析任务，图层数：%d", len(layer_metadata))
        self.statusBar().showMessage("正在生成空间分析代码...")

        # 异步请求代码
        class CodeWorker(QThread):
            done = pyqtSignal(str)
            error = pyqtSignal(str)
            def run(self):
                try:
                    text = request_spatial_code(user_text, layer_metadata)
                    self.done.emit(text)
                except Exception as e:
                    self.error.emit(str(e))

        self._code_worker = CodeWorker(self)
        self._code_worker.done.connect(self._on_spatial_code_response)
        self._code_worker.error.connect(
            lambda e: (_log.error("代码生成失败：%s", e), QMessageBox.critical(self, "代码生成失败", e))
        )
        self._code_worker.start()

    def _on_spatial_code_response(self, response_text: str) -> None:
        """处理空间分析代码生成响应（第二轮 AI 调用）。"""
        _log.info("收到空间分析代码响应，长度：%d", len(response_text))
        self.ai_response_display.append(f"\n--- 空间分析代码 ---\n{response_text}")
        try:
            code = self._extract_python_code(response_text)
            self.last_ai_code = code

            if not self.skip_preview:
                result = AiCodePreviewDialog.preview_and_execute(
                    self, code, self.ai_prompt_input.toPlainText().strip()
                )
                if result is None:
                    self.statusBar().showMessage("用户取消了执行。", 3000)
                    return
                code, skip_confirm = result
                if skip_confirm:
                    self.skip_preview = True

            exec_result = self._execute_ai_code(code)
            added_layers = self._register_result_layers(exec_result)
            if added_layers:
                self._zoom_to_layers(added_layers)
                self.statusBar().showMessage("空间分析完成，已添加新图层！", 6000)
            elif exec_result:
                self.statusBar().showMessage("空间分析完成。", 6000)
            else:
                self.statusBar().showMessage("代码已执行（未生成新图层）。", 6000)
        except Exception as exc:
            _log.exception("空间分析执行失败")
            QMessageBox.critical(self, "空间分析失败", f"{exc}\n\n{self.last_ai_code[:500]}")

    def _fallback_legacy_execution(self, response_text: str, original_error: Exception) -> None:
        """回退：尝试旧版 Python 代码块提取。"""
        try:
            code = self._extract_python_code(response_text)
            self.last_ai_code = code
            if not self.skip_preview:
                result = AiCodePreviewDialog.preview_and_execute(
                    self, code, self.ai_prompt_input.toPlainText().strip()
                )
                if result is None:
                    return
                code, _ = result
            exec_result = self._execute_ai_code(code)
            added_layers = self._register_result_layers(exec_result)
            if added_layers:
                self._zoom_to_layers(added_layers)
            self.statusBar().showMessage("空间分析完成（旧版兼容模式）", 6000)
        except Exception as exc:
            QMessageBox.critical(self, "执行失败", f"{exc}\n\n原始错误：{original_error}")

    def _handle_ai_error(self, error_message: str) -> None:
        """显示 API 或工作线程错误信息（中文）。"""

        QMessageBox.critical(
            self,
            "AI 请求失败",
            error_message,
        )
        self.statusBar().showMessage("AI 请求失败。", 6000)

    def _reset_ai_worker_state(self) -> None:
        """AI 请求完成后恢复 UI 状态。"""

        self.run_button.setEnabled(True)
        self.ai_worker = None

    @staticmethod
    def _extract_python_code(response_text: str) -> str:
        """从 Markdown 代码块中提取 Python 代码。"""

        match = re.search(
            r"```(?:python)?\s*([\s\S]*?)```",
            response_text,
            re.IGNORECASE,
        )
        if not match:
            raise ValueError(
                "AI 返回内容中未找到合法的 Python 代码块，请检查模型输出是否为 ```python ... ``` 格式。"
            )

        return match.group(1).strip()

    def _execute_ai_code(self, code: str) -> Dict[str, Any]:
        """在受控上下文中执行 AI 生成的 PyQGIS 处理代码。"""

        import processing

        # 防御：禁止 iface，它是 QGIS 插件接口，独立应用不存在
        if re.search(r'\biface\b', code):
            raise RuntimeError(
                "AI 生成的代码使用了 iface（QGIS 插件接口），但本应用是独立 QGIS 程序，"
                "iface 不存在。请用 QgsProject.instance() 代替。\n\n"
                "如需帮助，请重试分析并确保 AI 不使用 iface。"
            )

        active_layer = self._get_active_layer()
        layers_by_name = {
            layer.name(): layer for layer in QgsProject.instance().mapLayers().values()
        }
        safe_builtins = {
            "len": len,
            "min": min,
            "max": max,
            "sum": sum,
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "set": set,
            "range": range,
            "enumerate": enumerate,
            "zip": zip,
            "sorted": sorted,
            "RuntimeError": RuntimeError,
            "ValueError": ValueError,
            "__import__": __import__, "isinstance": isinstance,
            "type": type, "hasattr": hasattr, "getattr": getattr,
        }
        exec_globals = {
            "__builtins__": safe_builtins,
            "processing": processing,
            "QgsProject": QgsProject,
            "QgsVectorLayer": QgsVectorLayer,
            "QgsRasterLayer": QgsRasterLayer,
            "active_layer": active_layer,
            "layers_by_name": layers_by_name,
            "TEMPORARY_OUTPUT": "TEMPORARY_OUTPUT",
            "os": os,
            "tempfile": tempfile,
        }
        exec_locals: Dict[str, Any] = {}
        exec(code, exec_globals, exec_locals)

        if "result" not in exec_locals:
            _log.warning("AI 代码未生成 result 变量，跳过图层注册")
            return {}

        return exec_locals["result"]

    def _register_result_layers(self, result: Dict[str, Any]) -> List[QgsMapLayer]:
        """将 processing.run() 产生的输出图层注册到工程中。"""

        added_layers: List[QgsMapLayer] = []

        if isinstance(result, dict):
            for value in result.values():
                self._collect_result_layers(value, added_layers)
        elif isinstance(result, QgsMapLayer):
            self._add_layer_if_needed(result, added_layers)
        elif isinstance(result, str):
            # 可能是图层 ID 或文件路径
            layer = QgsProject.instance().mapLayer(result)
            if layer is not None:
                self._add_layer_if_needed(layer, added_layers)
            elif os.path.exists(result) and is_supported_path(result):
                layer = create_layer_from_path(result)
                self._add_layer_if_needed(layer, added_layers)
        elif isinstance(result, (list, tuple)):
            for item in result:
                self._collect_result_layers(item, added_layers)
        else:
            raise RuntimeError(
                f"result 类型为 {type(result).__name__}，不支持自动解析。"
                f"请使用更简单的指令重试。"
            )

        if not added_layers:
            raise RuntimeError("空间分析已执行，但未识别到可自动添加的新图层输出。")

        self.map_canvas.refresh()
        return added_layers

    def _collect_result_layers(self, value: Any, added_layers: List[QgsMapLayer]) -> None:
        """递归检查处理输出并注册新图层。"""

        if value is None:
            return

        if isinstance(value, QgsMapLayer):
            self._add_layer_if_needed(value, added_layers)
            return

        if isinstance(value, (list, tuple, set)):
            for item in value:
                self._collect_result_layers(item, added_layers)
            return

        if isinstance(value, dict):
            for item in value.values():
                self._collect_result_layers(item, added_layers)
            return

        if isinstance(value, str):
            existing_layer = QgsProject.instance().mapLayer(value)
            if existing_layer is not None:
                self._add_layer_if_needed(existing_layer, added_layers)
                return

            if os.path.exists(value) and is_supported_path(value):
                loaded_layer = create_layer_from_path(value)
                self._add_layer_if_needed(loaded_layer, added_layers)

    def _add_layer_if_needed(
        self,
        layer: QgsMapLayer,
        added_layers: List[QgsMapLayer],
    ) -> None:
        """仅当图层尚未加入工程时才将其添加。"""

        project = QgsProject.instance()
        if project.mapLayer(layer.id()) is None:
            project.addMapLayer(layer)

        if all(existing.id() != layer.id() for existing in added_layers):
            added_layers.append(layer)