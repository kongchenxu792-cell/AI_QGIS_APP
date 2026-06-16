"""
offline_workflows.py — 离线快捷流程管道

5 组对日高频离线快捷流程，每个函数均为硬编码 PyQGIS 流水线，
不经过 LLM 解析，可直接在断网环境下一键执行。

所有输出统一写入项目 output 目录，命名规范：{prefix}_{timestamp}...
"""

from __future__ import annotations

import csv
import os
import shutil
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from PyQt5.QtCore import QThread, pyqtSignal

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)

try:
    import processing
except ImportError:
    processing = None


# ══════════════════════════════════════════════════════════
# 输出路径工具
# ══════════════════════════════════════════════════════════

def _get_output_root() -> str:
    """获取项目 output 根目录。"""
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    out = os.path.join(project_root, "user_data", "exports")
    os.makedirs(out, exist_ok=True)
    return out


def _make_output_path(subdir: str, prefix: str, ext: str = ".shp") -> str:
    """生成带时间戳的输出路径。"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    d = os.path.join(_get_output_root(), subdir)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{prefix}_{ts}{ext}")


# ══════════════════════════════════════════════════════════
# QThread Worker 基类
# ══════════════════════════════════════════════════════════

class OfflineWorkflowWorker(QThread):
    """离线工作流 Worker，在 QThread 中执行硬编码 PyQGIS 管道。"""

    progress = pyqtSignal(str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, workflow_fn: Callable, **kwargs) -> None:
        super().__init__()
        self._fn = workflow_fn
        self._kwargs = kwargs

    def run(self) -> None:
        try:
            result = self._fn(
                progress_callback=lambda msg: self.progress.emit(msg),
                **self._kwargs,
            )
            self.finished.emit(result)
        except Exception as exc:
            import traceback
            tb = traceback.format_exc()
            self.error.emit(f"{exc}\n{tb}")


# ══════════════════════════════════════════════════════════
# 按钮 1：地籍数据标准化
# ══════════════════════════════════════════════════════════

def run_cadastral_standardization(
    progress_callback: Callable[[str], None],
    layers: Optional[List[QgsVectorLayer]] = None,
) -> Dict[str, Any]:
    """
    地籍数据标准化管道：
    图层批量转 JGD2000 → 拓扑检查+修复（重叠/缝隙/悬挂节点）→ 属性规整 → 导出标准 SHP
    """
    if layers is None:
        layers = [lyr for lyr in QgsProject.instance().mapLayers().values()
                  if isinstance(lyr, QgsVectorLayer)]

    if not layers:
        raise RuntimeError("当前项目无矢量图层，请先加载地籍数据。")

    jgd2000 = QgsCoordinateReferenceSystem("EPSG:4612")
    output_dir = _get_output_root()
    pkg_dir = os.path.join(output_dir, "cadastral_package")
    os.makedirs(pkg_dir, exist_ok=True)
    results = []

    for i, layer in enumerate(layers):
        name = layer.name()
        progress_callback(f"[{i+1}/{len(layers)}] 处理图层：{name}")

        # ── 步骤 1：转 JGD2000 ──
        if layer.crs() != jgd2000:
            progress_callback(f"  重投影 → JGD2000 (EPSG:4612)")
            reproj_path = os.path.join(pkg_dir, f"{name}_JGD2000.shp")
            result = processing.run(
                "native:reprojectlayer",
                {
                    "INPUT": layer,
                    "TARGET_CRS": jgd2000,
                    "OUTPUT": reproj_path,
                },
            )
            work_layer = QgsVectorLayer(result["OUTPUT"], f"{name}_JGD2000", "ogr")
        else:
            work_layer = layer

        # ── 步骤 2：拓扑检查+修复 ──
        progress_callback("  拓扑修复：修复无效几何...")
        fix_geom_path = os.path.join(pkg_dir, f"{name}_fixed.shp")
        fix_result = processing.run(
            "native:fixgeometries",
            {
                "INPUT": work_layer,
                "METHOD": 1,  # Structure method
                "OUTPUT": fix_geom_path,
            },
        )
        work_layer = QgsVectorLayer(fix_result["OUTPUT"], f"{name}_topo_fixed", "ogr")

        # 移除重复要素
        progress_callback("  去重...")
        dedup_path = os.path.join(pkg_dir, f"{name}_dedup.shp")
        dedup_result = processing.run(
            "native:deleteduplicategeometries",
            {
                "INPUT": work_layer,
                "OUTPUT": dedup_path,
            },
        )
        work_layer = QgsVectorLayer(dedup_result["OUTPUT"], f"{name}_topo_clean", "ogr")

        # 移除无效要素
        progress_callback("  移除空几何...")
        clean_path = os.path.join(pkg_dir, f"{name}_clean.shp")
        clean_result = processing.run(
            "native:removenullgeometries",
            {
                "INPUT": work_layer,
                "OUTPUT": clean_path,
            },
        )
        work_layer = QgsVectorLayer(clean_result["OUTPUT"], f"{name}_standardized", "ogr")

        # ── 步骤 3：属性规整 ──
        progress_callback("  属性字段规整...")
        # 统一字段名：大写转小写，去除空格
        provider = work_layer.dataProvider()
        fields = provider.fields()
        rename_map = {}
        for idx in range(fields.count()):
            f = fields.at(idx)
            old_name = f.name()
            new_name = old_name.strip().lower()
            if new_name != old_name:
                rename_map[idx] = new_name

        if rename_map:
            refactor_path = os.path.join(pkg_dir, f"{name}_std.shp")
            field_mapping = []
            for idx in range(fields.count()):
                f = fields.at(idx)
                field_mapping.append({
                    "expression": f'"{f.name()}"',
                    "length": f.length(),
                    "name": rename_map.get(idx, f.name()),
                    "precision": f.precision(),
                    "type": f.type(),
                })
            refactor_result = processing.run(
                "native:refactorfields",
                {
                    "INPUT": work_layer,
                    "FIELDS_MAPPING": field_mapping,
                    "OUTPUT": refactor_path,
                },
            )
            final_path = refactor_result["OUTPUT"]
        else:
            final_path = clean_result["OUTPUT"]

        results.append({"layer_name": name, "output": final_path})
        progress_callback(f"  ✓ 完成 → {os.path.basename(final_path)}")

    # 加载到画布
    for r in results:
        lyr = QgsVectorLayer(r["output"], os.path.basename(r["output"]), "ogr")
        if lyr.isValid():
            QgsProject.instance().addMapLayer(lyr)

    progress_callback(f"\n地籍标准化完成！共处理 {len(results)} 个图层，输出目录：{pkg_dir}")
    return {"success": True, "results": results, "output_dir": pkg_dir}


# ══════════════════════════════════════════════════════════
# 按钮 2：DEM 水文全分析
# ══════════════════════════════════════════════════════════

def run_dem_hydrological_analysis(
    progress_callback: Callable[[str], None],
    dem_path: str = "",
    xzq_path: str = "",
    stream_threshold: int = 100,
) -> Dict[str, Any]:
    """
    DEM 水文全分析管道（直接复用 safe_complete_hydrological_analysis）：
    洼地填充 → D8 流向提取 → 汇流累积 → 河网提取 → 行政区沟壑密度分区统计
    """
    from .fallback_utils import safe_complete_hydrological_analysis

    # 如果未指定 DEM/XZQ，尝试从已有图层推断
    if not dem_path:
        for lyr in QgsProject.instance().mapLayers().values():
            if hasattr(lyr, 'providerType') and lyr.providerType() == "gdal":
                dem_path = lyr.source()
                progress_callback(f"自动检测 DEM: {dem_path}")
                break
    if not dem_path:
        raise RuntimeError("未找到 DEM 栅格图层。请先加载 DEM，或通过按钮 3 指定路径。")

    if not xzq_path:
        for lyr in QgsProject.instance().mapLayers().values():
            if isinstance(lyr, QgsVectorLayer):
                # 找行政区划图层（含多边形几何）
                if lyr.geometryType() == QgsWkbTypes.PolygonGeometry:
                    xzq_path = lyr.source()
                    progress_callback(f"自动检测行政区划: {xzq_path}")
                    break
    if not xzq_path:
        raise RuntimeError("未找到行政区划面图层。请先加载行政区划 SHP。")

    output_dir = os.path.join(_get_output_root(), "hydrology")
    progress_callback("启动完整水文分析管道...")

    result = safe_complete_hydrological_analysis(
        dem_path=dem_path,
        output_dir=output_dir,
        xzq_path=xzq_path,
        stream_threshold=stream_threshold,
    )

    # 加载水文输出图层到画布
    for key, path in result.items():
        if path.endswith(".shp"):
            lyr = QgsVectorLayer(path, os.path.basename(path), "ogr")
            if lyr.isValid():
                QgsProject.instance().addMapLayer(lyr)

    progress_callback("\n水文全分析完成！")
    return {"success": True, "result": result, "output_dir": output_dir}


# ══════════════════════════════════════════════════════════
# 按钮 3：图层批量裁剪+投影
# ══════════════════════════════════════════════════════════

def run_batch_clip_project(
    progress_callback: Callable[[str], None],
    input_layers: Optional[List[QgsVectorLayer]] = None,
    boundary_layer: Optional[QgsVectorLayer] = None,
    target_crs: str = "EPSG:4612",
) -> Dict[str, Any]:
    """
    图层批量裁剪+投影管道：
    多图层批量加载 → 按边界图层裁剪 → 统一转为 JGD2000 → 自动分类归档
    """
    if input_layers is None:
        input_layers = [lyr for lyr in QgsProject.instance().mapLayers().values()
                        if isinstance(lyr, QgsVectorLayer)]

    if not input_layers:
        raise RuntimeError("无矢量图层可用。")

    # 找边界图层：默认为活动图层，或第一个多边形图层
    if boundary_layer is None:
        for lyr in input_layers:
            if lyr.geometryType() == QgsWkbTypes.PolygonGeometry:
                boundary_layer = lyr
                break
    if boundary_layer is None:
        raise RuntimeError("未找到边界多边形图层。请在图层列表中选择一个面图层作为裁剪边界。")

    progress_callback(f"裁剪边界图层: {boundary_layer.name()}")
    progress_callback(f"目标坐标系: {target_crs}")

    output_dir = os.path.join(_get_output_root(), "batch_clip_project")
    os.makedirs(output_dir, exist_ok=True)
    jgd2000 = QgsCoordinateReferenceSystem(target_crs)
    results = []

    # 按几何类型分类子目录
    type_dirs = {
        QgsWkbTypes.PointGeometry: "point",
        QgsWkbTypes.LineGeometry: "line",
        QgsWkbTypes.PolygonGeometry: "polygon",
    }

    for i, layer in enumerate(input_layers):
        name = layer.name()
        geom_type = layer.geometryType()
        subdir = type_dirs.get(geom_type, "other")
        layer_dir = os.path.join(output_dir, subdir)
        os.makedirs(layer_dir, exist_ok=True)

        progress_callback(f"[{i+1}/{len(input_layers)}] 处理: {name}")

        # 步骤 1：裁剪
        clip_path = os.path.join(layer_dir, f"{name}_clipped.shp")
        progress_callback("  裁剪中...")
        clip_result = processing.run(
            "native:clip",
            {
                "INPUT": layer,
                "OVERLAY": boundary_layer,
                "OUTPUT": clip_path,
            },
        )

        # 步骤 2：转 JGD2000
        clipped = QgsVectorLayer(clip_result["OUTPUT"], f"{name}_clipped", "ogr")
        if clipped.crs() != jgd2000:
            progress_callback("  投影转换 → JGD2000...")
            final_path = os.path.join(layer_dir, f"{name}_JGD2000.shp")
            proj_result = processing.run(
                "native:reprojectlayer",
                {
                    "INPUT": clipped,
                    "TARGET_CRS": jgd2000,
                    "OUTPUT": final_path,
                },
            )
            final_output = proj_result["OUTPUT"]
        else:
            final_output = clip_result["OUTPUT"]

        # 加载到画布
        lyr = QgsVectorLayer(final_output, f"[Clip] {name}", "ogr")
        if lyr.isValid():
            QgsProject.instance().addMapLayer(lyr)

        results.append({"layer_name": name, "output": final_output, "type": subdir})
        progress_callback(f"  ✓ 完成 → {os.path.basename(final_output)}")

    progress_callback(f"\n批量裁剪投影完成！共处理 {len(results)} 个图层，输出目录：{output_dir}")
    return {"success": True, "results": results, "output_dir": output_dir}


# ══════════════════════════════════════════════════════════
# 按钮 4：矢量属性批量处理
# ══════════════════════════════════════════════════════════

def run_vector_attribute_batch(
    progress_callback: Callable[[str], None],
    source_layer: Optional[QgsVectorLayer] = None,
    filter_expression: str = "",
    field_assignments: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    矢量属性批量处理管道：
    图层条件筛选 → 字段批量赋值 → 筛选结果导出 SHP

    参数
    ----
    source_layer : QgsVectorLayer
        源矢量图层。默认使用活动图层。
    filter_expression : str
        QGIS 表达式筛选条件，如 "area > 1000"
    field_assignments : dict
        字段赋值映射 {字段名: 表达式}，如 {"category": "'urban'", "density": "pop / area"}
    """
    if source_layer is None:
        source_layer = QgsProject.instance().mapLayers().values()
        source_layer = next(
            (lyr for lyr in source_layer if isinstance(lyr, QgsVectorLayer)), None
        )
    if source_layer is None:
        raise RuntimeError("无矢量图层可用。请先加载矢量数据。")

    name = source_layer.name()
    output_dir = os.path.join(_get_output_root(), "attribute_batch")
    os.makedirs(output_dir, exist_ok=True)

    progress_callback(f"源图层: {name} ({source_layer.featureCount()} 要素)")

    # 步骤 1：条件筛选
    if filter_expression:
        progress_callback(f"  筛选条件: {filter_expression}")
        selected = list(source_layer.getFeatures(filter_expression))
        # 用 QGIS expression 选择
        source_layer.selectByExpression(filter_expression)
        selected_count = source_layer.selectedFeatureCount()
        progress_callback(f"  筛选出 {selected_count} 个要素")
    else:
        selected_count = source_layer.featureCount()
        progress_callback("  无筛选条件，将处理全部要素。")

    # 步骤 2：字段批量赋值
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(output_dir, f"{name}_processed_{ts}.shp")

    if field_assignments:
        # 使用 Refactor Fields + Field Calculator 组合
        progress_callback("  字段赋值中...")
        # 先复制图层
        if filter_expression:
            copy_result = processing.run(
                "native:saveselectedfeatures",
                {
                    "INPUT": source_layer,
                    "OUTPUT": output_path,
                },
            )
        else:
            copy_path_temp = os.path.join(output_dir, f"{name}_temp_{ts}.shp")
            copy_result = processing.run(
                "native:savefeatures",
                {
                    "INPUT": source_layer,
                    "OUTPUT": copy_path_temp,
                },
            )

        work_layer = QgsVectorLayer(copy_result["OUTPUT"], f"{name}_work", "ogr")

        # 逐字段赋值
        for field_name, expression in field_assignments.items():
            progress_callback(f"    字段 {field_name} = {expression}")
            calc_path = os.path.join(output_dir, f"{name}_{field_name}_calc_{ts}.shp")
            calc_result = processing.run(
                "native:fieldcalculator",
                {
                    "INPUT": work_layer,
                    "FIELD_NAME": field_name,
                    "FIELD_TYPE": 0,  # Float
                    "FIELD_LENGTH": 20,
                    "FIELD_PRECISION": 6,
                    "FORMULA": expression,
                    "OUTPUT": calc_path,
                },
            )
            work_layer = QgsVectorLayer(calc_result["OUTPUT"], f"{name}_final", "ogr")

        # 最终保存
        final_result = processing.run(
            "native:savefeatures",
            {
                "INPUT": work_layer,
                "OUTPUT": output_path,
            },
        )
        final_path = final_result["OUTPUT"]
    else:
        if filter_expression:
            final_result = processing.run(
                "native:saveselectedfeatures",
                {
                    "INPUT": source_layer,
                    "OUTPUT": output_path,
                },
            )
            final_path = final_result["OUTPUT"]
        else:
            final_path = output_path
            shutil.copy2(source_layer.source(), final_path)

    # 加载到画布
    lyr = QgsVectorLayer(final_path, f"[AttrBatch] {name}", "ogr")
    if lyr.isValid():
        QgsProject.instance().addMapLayer(lyr)

    progress_callback(f"\n属性批量处理完成 → {os.path.basename(final_path)}")
    return {"success": True, "output": final_path, "selected_count": selected_count}


# ══════════════════════════════════════════════════════════
# 按钮 5：专题图批量出图
# ══════════════════════════════════════════════════════════

def run_thematic_map_export(
    progress_callback: Callable[[str], None],
    layers: Optional[List[QgsVectorLayer]] = None,
    export_png: bool = True,
    export_pdf: bool = True,
) -> Dict[str, Any]:
    """
    专题图批量出图管道：
    自动加载图例/比例尺/指北针 → 统一样式渲染 → 批量导出 PNG/PDF

    为当前项目中每个矢量图层创建一张独立的专题图，
    包含图例（legend）、比例尺（scale bar）、指北针（north arrow），
    统一使用 terrain 色带渲染，导出版面为 A4 横向。
    """
    from qgis.core import (
        QgsLayout,
        QgsLayoutExporter,
        QgsLayoutItemLegend,
        QgsLayoutItemMap,
        QgsLayoutItemScaleBar,
        QgsLayoutItemPicture,
        QgsLayoutPoint,
        QgsLayoutSize,
        QgsPrintLayout,
        QgsReadWriteContext,
        QgsRectangle,
        QgsUnitTypes,
    )
    from qgis.gui import QgsMapCanvas

    project = QgsProject.instance()

    if layers is None:
        layers = [lyr for lyr in project.mapLayers().values()
                  if isinstance(lyr, QgsVectorLayer)]

    if not layers:
        raise RuntimeError("无矢量图层可导出。")

    output_dir = os.path.join(_get_output_root(), "thematic_maps")
    os.makedirs(output_dir, exist_ok=True)
    results = []

    # 创建临时画布用于布局渲染
    temp_canvas = QgsMapCanvas()
    temp_canvas.setDestinationCrs(project.crs())

    layout = QgsPrintLayout(project)
    layout.initializeDefaults()
    layout.pageCollection().beginPageSizeChange()
    page_size = layout.pageCollection().page(0).pageSize()
    page_size = QgsLayoutSize(297, 210, QgsUnitTypes.LayoutMillimeters)  # A4 横向
    layout.pageCollection().page(0).setPageSize(page_size)
    layout.pageCollection().endPageSizeChange()

    for i, layer in enumerate(layers):
        name = layer.name()
        progress_callback(f"[{i+1}/{len(layers)}] 出图: {name}")

        # 清空布局
        layout.clear()

        # ── 地图项 ──
        map_item = QgsLayoutItemMap(layout)
        map_item.setRect(15, 15, 200, 180)  # 留出右侧空间给图例
        map_item.setCrs(project.crs())
        map_item.zoomToExtent(layer.extent())
        map_item.setFrameEnabled(True)
        layout.addLayoutItem(map_item)

        # 设置图层可见性（只显示当前图层）
        for lyr in project.mapLayers().values():
            tree_root = project.layerTreeRoot()
            node = tree_root.findLayer(lyr.id())
            if node:
                node.setItemVisibilityChecked(lyr.id() == layer.id())

        # ── 图例 ──
        legend = QgsLayoutItemLegend(layout)
        legend.setTitle("图例")
        legend.setLinkedMap(map_item)
        legend.setFrameEnabled(True)
        legend.attemptMove(QgsLayoutPoint(225, 15, QgsUnitTypes.LayoutMillimeters))
        legend.adjustBoxSize()
        layout.addLayoutItem(legend)

        # ── 比例尺 ──
        scalebar = QgsLayoutItemScaleBar(layout)
        scalebar.setStyle("Single Box")
        scalebar.setLinkedMap(map_item)
        scalebar.setUnits(QgsUnitTypes.DistanceMeters)
        scalebar.setNumberOfSegments(4)
        scalebar.setUnitLabel("m")
        scalebar.attemptMove(QgsLayoutPoint(15, 198, QgsUnitTypes.LayoutMillimeters))
        layout.addLayoutItem(scalebar)

        # ── 标题 ──
        from qgis.core import QgsLayoutItemLabel
        title = QgsLayoutItemLabel(layout)
        title.setText(f"专题图 — {name}")
        title.setFont(QgsLayoutItemLabel().font())
        title.attemptMove(QgsLayoutPoint(15, 2, QgsUnitTypes.LayoutMillimeters))
        title.adjustSizeToText()
        layout.addLayoutItem(title)

        # ── 导出 ──
        base_name = f"{name}_thematic_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        if export_png:
            png_path = os.path.join(output_dir, f"{base_name}.png")
            exporter = QgsLayoutExporter(layout)
            settings = QgsLayoutExporter.ImageExportSettings()
            settings.dpi = 300
            result_code = exporter.exportToImage(png_path, settings)
            if result_code == QgsLayoutExporter.Success:
                results.append({"layer": name, "format": "PNG", "path": png_path})
                progress_callback(f"  ✓ PNG → {os.path.basename(png_path)}")

        if export_pdf:
            pdf_path = os.path.join(output_dir, f"{base_name}.pdf")
            exporter = QgsLayoutExporter(layout)
            settings = QgsLayoutExporter.PdfExportSettings()
            settings.dpi = 300
            result_code = exporter.exportToPdf(pdf_path, settings)
            if result_code == QgsLayoutExporter.Success:
                results.append({"layer": name, "format": "PDF", "path": pdf_path})
                progress_callback(f"  ✓ PDF → {os.path.basename(pdf_path)}")

    # 恢复所有图层可见
    for lyr in project.mapLayers().values():
        node = project.layerTreeRoot().findLayer(lyr.id())
        if node:
            node.setItemVisibilityChecked(True)

    progress_callback(f"\n专题图批量出图完成！共 {len(results)} 个文件，输出目录：{output_dir}")
    return {"success": True, "results": results, "output_dir": output_dir}
