"""本地 PyQGIS 运行时检测与引导工具模块。

负责自动探测本地 QGIS 安装路径、配置进程级环境变量（PATH、PYTHONPATH、
QT_PLUGIN_PATH 等），并验证 PyQGIS 核心模块的导入可用性。
"""

from __future__ import annotations

import glob
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


_PROCESSING_INITIALIZED = False


@dataclass(slots=True)
class QgisBootstrapResult:
    """QGIS 引导尝试的结果数据类。"""

    available: bool
    """PyQGIS 环境是否可用。"""

    message: str
    """引导结果的描述信息。"""

    prefix_path: Optional[str] = None
    """成功解析的 QGIS 前缀路径。"""

    candidate_paths: List[str] = field(default_factory=list)
    """所有尝试过的候选路径列表。"""

    import_error: Optional[str] = None
    """最近一次导入错误的详细信息。"""


def normalize_prefix_path(path: str | Path) -> Path:
    """将用户提供的 QGIS 路径规范化为 ``apps/qgis`` 格式的前缀路径。

    参数
    ----
    path : str | Path
        用户提供的原始路径，可以是 QGIS 安装根目录或 apps/qgis 子目录。

    返回
    ----
    Path
        规范化为 ``apps/qgis`` 或 ``apps/qgis-ltr`` 的前缀路径。
    """

    raw_path = Path(path).expanduser()
    lower_name = raw_path.name.lower()

    if lower_name in {"qgis", "qgis-ltr"}:
        return raw_path

    app_prefix_candidates = [
        raw_path / "apps" / "qgis",
        raw_path / "apps" / "qgis-ltr",
    ]
    for app_prefix in app_prefix_candidates:
        if app_prefix.exists():
            return app_prefix

    return raw_path


def discover_qgis_prefix_candidates() -> List[str]:
    """在 Windows 系统上自动发现所有可能的 QGIS 安装前缀路径。

    返回
    ----
    List[str]
        去重后的候选路径列表，按优先级排序。
    """

    candidates: List[Path] = []
    env_prefix = os.environ.get("QGIS_PREFIX_PATH")
    if env_prefix:
        candidates.append(normalize_prefix_path(env_prefix))

    known_paths = [
        # 独立安装版路径 — 优先于 OSGeo4W
        Path(r"C:\Program Files\QGIS 3.44.9\apps\qgis-ltr"),
        Path(r"C:\Program Files\QGIS 3.44.9\apps\qgis"),
        # OSGeo4W 路径
        Path(r"C:\OSGeo4W\apps\qgis"),
        Path(r"C:\OSGeo4W\apps\qgis-ltr"),
        Path(r"C:\OSGeo4W64\apps\qgis"),
        Path(r"C:\OSGeo4W64\apps\qgis-ltr"),
    ]
    candidates.extend(known_paths)

    program_files_patterns = [
        r"C:\Program Files\QGIS *",
        r"C:\Program Files (x86)\QGIS *",
    ]
    for pattern in program_files_patterns:
        for match in glob.glob(pattern):
            candidates.append(normalize_prefix_path(match))

    unique_candidates: List[str] = []
    seen_paths = set()
    for candidate in candidates:
        resolved = str(candidate)
        if resolved in seen_paths:
            continue
        seen_paths.add(resolved)
        unique_candidates.append(resolved)

    return unique_candidates


def _prepend_env_path(path: Path) -> None:
    """将目录添加到 PATH 环境变量的最前面（若目录存在且尚未加入）。"""

    if not path.exists():
        return

    path_str = str(path)
    existing_parts = os.environ.get("PATH", "").split(os.pathsep)
    if path_str not in existing_parts:
        os.environ["PATH"] = path_str + os.pathsep + os.environ.get("PATH", "")

    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(path_str)
        except OSError:
            pass


def _prepend_python_path(path: Path) -> None:
    """将目录添加到 ``sys.path`` 头部（若目录存在且尚未加入）。"""

    if path.exists():
        path_str = str(path)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)


def configure_qgis_environment(prefix_path: str | Path) -> str:
    """配置 PyQGIS 导入所需的全部进程环境变量。

    参数
    ----
    prefix_path : str | Path
        QGIS 前缀路径（指向 apps/qgis 或 apps/qgis-ltr）。

    返回
    ----
    str
        规范化后的 QGIS 前缀路径字符串。
    """

    normalized_prefix = normalize_prefix_path(prefix_path)
    install_root = normalized_prefix.parent.parent

    os.environ["QGIS_PREFIX_PATH"] = str(normalized_prefix)

    qgis_python_path = normalized_prefix / "python"
    _prepend_python_path(qgis_python_path)
    _prepend_python_path(qgis_python_path / "plugins")
    for site_packages_path in install_root.glob(r"apps\Python*\Lib\site-packages"):
        _prepend_python_path(site_packages_path)

    path_candidates = [
        install_root / "bin",
        normalized_prefix / "bin",
    ]
    # 动态扫描 apps/*/bin 目录以覆盖 Qt5、Qt6、GDAL 等
    for bin_dir in install_root.glob("apps/*/bin"):
        path_candidates.append(bin_dir)
    for path_candidate in path_candidates:
        _prepend_env_path(path_candidate)

    gdal_data_path = install_root / "share" / "gdal"
    proj_data_path = install_root / "share" / "proj"
    if gdal_data_path.exists():
        os.environ.setdefault("GDAL_DATA", str(gdal_data_path))
    if proj_data_path.exists():
        proj_data_str = str(proj_data_path)
        os.environ["PROJ_DATA"] = proj_data_str  # PROJ 9.x uses PROJ_DATA
        os.environ["PROJ_LIB"] = proj_data_str   # GDAL 向后兼容 PROJ_LIB
    else:
        # 回退：全局搜索 proj.db
        for candidate in install_root.rglob("proj.db"):
            proj_data_str = str(candidate.parent)
            os.environ["PROJ_DATA"] = proj_data_str
            os.environ["PROJ_LIB"] = proj_data_str
            break

    return str(normalized_prefix)


def initialize_processing(qgs_app) -> None:
    """初始化 QGIS 处理框架，使 ``processing.run()`` 可正常调用。

    参数
    ----
    qgs_app : QgsApplication
        已完成 initQgis() 的 QGIS 应用程序实例。
    """

    global _PROCESSING_INITIALIZED  # pylint: disable=global-statement

    if _PROCESSING_INITIALIZED:
        return

    from qgis.analysis import QgsNativeAlgorithms  # type: ignore
    from processing.core.Processing import Processing  # type: ignore

    Processing.initialize()

    provider_ids = {provider.id() for provider in qgs_app.processingRegistry().providers()}
    if "native" not in provider_ids:
        qgs_app.processingRegistry().addProvider(QgsNativeAlgorithms())

    _PROCESSING_INITIALIZED = True


def bootstrap_qgis(custom_prefix_path: Optional[str] = None) -> QgisBootstrapResult:
    """准备环境变量并验证 PyQGIS 导入是否可用。

    参数
    ----
    custom_prefix_path : Optional[str]
        用户自定义的 QGIS 安装前缀路径。若为 ``None`` 则自动探测。

    返回
    ----
    QgisBootstrapResult
        包含引导结果、消息和路径信息的数据对象。
    """

    candidates = discover_qgis_prefix_candidates()
    if custom_prefix_path:
        normalized_custom_path = str(normalize_prefix_path(custom_prefix_path))
        if normalized_custom_path not in candidates:
            candidates.insert(0, normalized_custom_path)

    attempted_paths: List[str] = []
    last_error: Optional[str] = None

    for candidate in candidates:
        attempted_paths.append(candidate)
        python_path = Path(candidate) / "python"
        if not python_path.exists():
            continue

        try:
            configured_prefix = configure_qgis_environment(candidate)

            from qgis.core import QgsApplication  # type: ignore  # noqa: F401
            from qgis.gui import QgsMapCanvas  # type: ignore  # noqa: F401

            return QgisBootstrapResult(
                available=True,
                message=f"已成功加载 PyQGIS 环境：{configured_prefix}",
                prefix_path=configured_prefix,
                candidate_paths=attempted_paths,
            )
        except Exception as exc:  # pragma: no cover - 依赖运行环境
            last_error = str(exc)

    message = (
        "无法初始化 PyQGIS。请设置环境变量 QGIS_PREFIX_PATH，指向本机 "
        "QGIS 安装目录中的 'apps\\qgis' 或 'apps\\qgis-ltr'。"
    )
    if last_error:
        message += f" 最近一次导入错误：{last_error}"

    return QgisBootstrapResult(
        available=False,
        message=message,
        candidate_paths=attempted_paths,
        import_error=last_error,
    )


def shutdown_qgis() -> None:
    """预留的 QGIS 关闭清理钩子，供未来扩展使用。"""

    return None