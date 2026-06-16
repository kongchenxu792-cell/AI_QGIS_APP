"""矢量图层与栅格图层的拖放加载辅助工具。

提供文件类型判断、图层对象创建和批量加载功能，支持 SHP、GeoJSON、
GPKG、KML、GeoTIFF 等常见 GIS 数据格式。
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Tuple

from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer


#: 支持的矢量数据文件扩展名集合。
VECTOR_EXTENSIONS = {
    ".shp",
    ".geojson",
    ".json",
    ".gpkg",
    ".kml",
    ".gml",
}

#: 支持的栅格数据文件扩展名集合。
RASTER_EXTENSIONS = {
    ".tif",
    ".tiff",
    ".img",
    ".vrt",
    ".jpg",
    ".jpeg",
    ".png",
}

#: 支持的表格数据文件扩展名集合（Excel/CSV）。
TABLE_EXTENSIONS = {
    ".xlsx",
    ".xls",
    ".csv",
}

#: QGIS 项目文件扩展名集合。
PROJECT_EXTENSIONS = {".qgz", ".qgs"}

#: 所有支持拖放加载的扩展名并集。
ALL_SUPPORTED_EXTENSIONS = VECTOR_EXTENSIONS | RASTER_EXTENSIONS | TABLE_EXTENSIONS | PROJECT_EXTENSIONS


def is_supported_path(file_path: str) -> bool:
    """判断给定文件路径是否为可拖放加载的 GIS 数据或项目格式。

    参数
    ----
    file_path : str
        待检测的文件路径。

    返回
    ----
    bool
        若文件扩展名在支持的格式范围内则返回 ``True``。
    """

    return Path(file_path).suffix.lower() in ALL_SUPPORTED_EXTENSIONS


def is_table_path(file_path: str) -> bool:
    """判断给定文件路径是否为表格数据文件（Excel/CSV）。

    参数
    ----
    file_path : str
        待检测的文件路径。

    返回
    ----
    bool
        若文件扩展名属于表格格式则返回 ``True``。
    """

    return Path(file_path).suffix.lower() in TABLE_EXTENSIONS


def create_layer_from_path(file_path: str):
    """从本地文件路径创建 QGIS 图层对象。

    根据文件扩展名自动判断图层类型（矢量或栅格）。

    参数
    ----
    file_path : str
        本地 GIS 数据文件的绝对路径。

    返回
    ----
    QgsVectorLayer 或 QgsRasterLayer
        创建并验证后的图层对象。

    异常
    ----
    ValueError
        若文件类型不受支持或图层加载失败时抛出。
    """

    path = Path(file_path)
    extension = path.suffix.lower()
    layer_name = path.stem

    if extension in VECTOR_EXTENSIONS:
        layer = QgsVectorLayer(str(path), layer_name, "ogr")
    elif extension in RASTER_EXTENSIONS:
        layer = QgsRasterLayer(str(path), layer_name)
    else:
        raise ValueError(f"暂不支持该文件类型：{path.suffix}")

    if not layer.isValid():
        raise ValueError(f"无法加载图层文件：{path}")

    return layer


def load_layers_from_paths(file_paths: Iterable[str]) -> Tuple[List[object], List[str]]:
    """批量加载文件路径并将其注册到当前 QGIS 项目中。

    对于矢量/栅格图层文件调用 create_layer_from_path 添加到当前项目；
    对于 .qgz/.qgs 项目文件调用 QgsProject.read()，由 QGIS 原生引擎处理。

    参数
    ----
    file_paths : Iterable[str]
        待加载的 GIS 文件路径可迭代对象。

    返回
    ----
    Tuple[List[object], List[str]]
        二元组：``(已成功加载的图层列表, 错误信息列表)``。
    """

    loaded_layers = []
    errors: List[str] = []

    for file_path in file_paths:
        try:
            suffix = Path(file_path).suffix.lower()

            if suffix in PROJECT_EXTENSIONS:
                # 交给 QGIS 原生读取引擎，项目内的图层由 QGIS 自己管理
                QgsProject.instance().read(file_path)
                for layer in QgsProject.instance().mapLayers().values():
                    loaded_layers.append(layer)
                continue

            if not is_supported_path(file_path):
                errors.append(f"已跳过不支持的文件：{file_path}")
                continue

            layer = create_layer_from_path(file_path)
            QgsProject.instance().addMapLayer(layer)
            loaded_layers.append(layer)
        except Exception as exc:  # pragma: no cover - 依赖本地数据质量
            errors.append(f"{file_path}：{exc}")

    return loaded_layers, errors