"""属性表查看器 - 独立 PyQt5 窗口显示矢量图层的属性数据。"""

from PyQt5.QtCore import Qt, QAbstractTableModel, QModelIndex, QVariant
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableView,
    QHeaderView,
    QAbstractItemView,
    QStatusBar,
)


class AttributeTableModel(QAbstractTableModel):
    """矢量图层属性表的 Qt 模型。"""

    def __init__(self, layer, parent=None):
        """
        初始化属性表模型。

        Parameters
        ----------
        layer : QgsVectorLayer
            要显示属性表的矢量图层。
        """
        super().__init__(parent)
        self.layer = layer
        self.fields = layer.fields()
        self.features = []
        self.feature_count = 0
        self._load_features()

    def _load_features(self) -> None:
        """从图层中加载要素和字段信息。"""
        self.features = []
        self.feature_count = self.layer.featureCount()
        # 限制最大加载数防止内存溢出
        max_load = min(self.feature_count, 50000)
        for i, feature in enumerate(self.layer.getFeatures()):
            if i >= max_load:
                break
            self.features.append(feature)

    def rowCount(self, parent=QModelIndex()) -> int:
        """返回行数。"""
        return len(self.features)

    def columnCount(self, parent=QModelIndex()) -> int:
        """返回列数。"""
        return self.fields.count()

    def data(self, index, role=Qt.DisplayRole):
        """返回指定单元格的数据。"""
        if not index.isValid():
            return QVariant()
        if role == Qt.DisplayRole:
            feature = self.features[index.row()]
            field_index = index.column()
            value = feature.attribute(field_index)
            if value is None:
                return ""
            return str(value)
        if role == Qt.BackgroundRole and index.row() % 2 == 0:
            return QColor("#f5f7fa")
        return QVariant()

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        """返回表头数据。"""
        if role != Qt.DisplayRole:
            return QVariant()
        if orientation == Qt.Horizontal:
            if section < self.fields.count():
                return self.fields.at(section).name()
        if orientation == Qt.Vertical:
            return str(section + 1)  # 行号从 1 开始
        return QVariant()


class AttributeTableDialog(QDialog):
    """属性表查看器对话框。"""

    def __init__(self, layer, parent=None):
        """
        初始化属性表对话框。

        Parameters
        ----------
        layer : QgsVectorLayer
            要显示属性表的矢量图层。
        """
        super().__init__(parent)
        self.layer = layer
        self.setWindowTitle(f"属性表 - {layer.name()}")
        self.resize(900, 550)
        self.setMinimumSize(600, 350)
        self.setModal(False)  # 非模态，不阻塞主窗口

        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建对话框 UI。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # 标题和信息行
        info_layout = QHBoxLayout()

        title_label = QLabel(f"图层：{self.layer.name()}")
        title_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #1a1a2e;")
        info_layout.addWidget(title_label)

        feature_count = self.layer.featureCount()
        field_count = self.layer.fields().count()
        count_label = QLabel(f"要素：{feature_count}  |  字段：{field_count}")
        count_label.setStyleSheet("color: #666; font-size: 12px;")
        info_layout.addWidget(count_label)

        info_layout.addStretch()

        self.close_btn = QPushButton("关闭")
        self.close_btn.clicked.connect(self.close)
        info_layout.addWidget(self.close_btn)

        layout.addLayout(info_layout)

        # 表格视图
        self.table_view = QTableView()
        self.table_view.setAlternatingRowColors(False)
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table_view.setSortingEnabled(True)
        self.table_view.setWordWrap(False)
        self.table_view.setShowGrid(True)

        # 表头样式
        header = self.table_view.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStyleSheet(
            "QHeaderView::section { background: #e8ecf1; padding: 6px; "
            "font-weight: bold; border: 1px solid #d0d5dd; }"
        )

        self.table_view.verticalHeader().setStyleSheet(
            "QHeaderView::section { background: #f5f7fa; padding: 4px; "
            "color: #666; border: 1px solid #d0d5dd; }"
        )

        # 加载数据
        self.model = AttributeTableModel(self.layer)
        self.table_view.setModel(self.model)

        # 自适应列宽
        self.table_view.resizeColumnsToContents()

        layout.addWidget(self.table_view, stretch=1)

        # 底部状态栏
        status = QStatusBar()
        loaded = self.model.rowCount()
        total = self.model.feature_count
        if loaded < total:
            status.showMessage(f"已加载 {loaded} / {total} 条记录（超出 50000 条限制）")
        else:
            status.showMessage(f"共 {total} 条记录")
        layout.addWidget(status)

        # 样式
        self.setStyleSheet(
            """
            QTableView {
                font-size: 12px;
                gridline-color: #d0d5dd;
                selection-background-color: #c8daf5;
                selection-color: #1a1a2e;
            }
            QTableView::item {
                padding: 4px 8px;
            }
            """
        )