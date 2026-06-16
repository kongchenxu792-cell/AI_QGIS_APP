"""AI 驱动轻量桌面 GIS 应用 - 程序入口。

负责初始化 PyQGIS 环境、创建 PyQt5 应用程序和主窗口，并启动事件循环。
"""

from __future__ import annotations

import logging
import os
import sys
import traceback

# ── PROJ 环境硬编码激活：基于 QGIS portable 标准布局，不再动态巡检 ──
# 必须在任何 GIS/GDAL 导入前设置 PROJ_LIB/PROJ_DATA，否则 GDAL 初始化会缓存空路径。
_app_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "qgis-portable")
_proj_path = os.path.join(_app_path, "share", "proj")
os.environ.setdefault("PROJ_LIB", _proj_path)      # 旧版 PROJ (<9.x)
os.environ.setdefault("PROJ_DATA", _proj_path)     # 新版 PROJ (9.x+)

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
        qgs_app = QgsApplication([], True)
        qgs_app.setApplicationName("AI 驱动轻量桌面 GIS")
        qgs_app.setOrganizationName("AI_QGIS_APP")

        # ── 强制修复便携版环境：QGIS 官方接口替代动态巡检 ──
        def _force_fix_portable_env():
            app_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "qgis-portable",
            )
            QgsApplication.setPrefixPath(app_path, True)
            os.environ["PROJ_LIB"] = os.path.join(app_path, "share", "proj")
            os.environ["PROJ_DATA"] = os.path.join(app_path, "share", "proj")

        _force_fix_portable_env()
        qgs_app.initQgis()
        # initQgis() 内部会基于 prefix_path 重新推算并覆盖 PROJ 路径，立即修复
        _force_fix_portable_env()

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