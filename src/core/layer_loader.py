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


def is_supported_path(file_path: str) -> bool:
    """判断给定文件路径是否为可拖放加载的 GIS 数据格式。

    参数
    ----
    file_path : str
        待检测的文件路径。

    返回
    ----
    bool
        若文件扩展名在支持的矢量或栅格格式范围内则返回 ``True``。
    """

    return Path(file_path).suffix.lower() in VECTOR_EXTENSIONS | RASTER_EXTENSIONS


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
            if not is_supported_path(file_path):
                errors.append(f"已跳过不支持的文件：{file_path}")
                continue

            layer = create_layer_from_path(file_path)
            QgsProject.instance().addMapLayer(layer)
            loaded_layers.append(layer)
        except Exception as exc:  # pragma: no cover - 依赖本地数据质量
            errors.append(f"{file_path}：{exc}")

    return loaded_layers, errors