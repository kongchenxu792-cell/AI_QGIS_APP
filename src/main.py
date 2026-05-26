"""AI 驱动轻量桌面 GIS 应用 - 程序入口。

负责初始化 PyQGIS 环境、创建 PyQt5 应用程序和主窗口，并启动事件循环。
"""

from __future__ import annotations

import logging
import os
import sys
import traceback

from core.logger import init_logging
from core.qgis_env import bootstrap_qgis, initialize_processing, shutdown_qgis

init_logging()
_log = logging.getLogger("main")


def run() -> int:
    """启动 GUI 应用程序并返回进程退出码。"""

    _log.info("AIQGIS 正在启动...")

    qgis_prefix_path = os.environ.get("QGIS_PREFIX_PATH")
    bootstrap_result = bootstrap_qgis(qgis_prefix_path)
    qgs_app = None

    try:
        if not bootstrap_result.available:
            raise RuntimeError(bootstrap_result.message)

        _log.info("PyQGIS 环境初始化成功：%s", bootstrap_result.prefix_path)

        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QMessageBox
        from qgis.core import QgsApplication
        from ui.main_window import MainWindow

        QgsApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QgsApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        QgsApplication.setPrefixPath(
            bootstrap_result.prefix_path or qgis_prefix_path or "",
            True,
        )
        qgs_app = QgsApplication([], True)
        qgs_app.setApplicationName("AI 驱动轻量桌面 GIS")
        qgs_app.setOrganizationName("AI_QGIS_APP")
        qgs_app.initQgis()
        initialize_processing(qgs_app)

        main_window = MainWindow(bootstrap_result)
        main_window.show()
        return qgs_app.exec()
    except Exception as exc:
        _log.critical("应用启动失败", exc_info=True)
        error_details = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )
        try:
            from PyQt5.QtWidgets import QApplication, QMessageBox

            app = QApplication.instance() or QApplication([])
            QMessageBox.critical(
                None,
                "应用启动失败",
                f"{exc}\n\n{error_details}",
            )
            if QApplication.instance() is not None and app is QApplication.instance():
                app.quit()
        except Exception:
            print("应用启动失败：")
            print(error_details)
        return 1
    finally:
        if qgs_app is not None:
            qgs_app.exitQgis()
        shutdown_qgis()


if __name__ == "__main__":
    sys.exit(run())