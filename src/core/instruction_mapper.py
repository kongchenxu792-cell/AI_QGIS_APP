"""
instruction_mapper.py — 多语言 GIS 指令映射层

将本地大模型解析出的自然语言指令对接底层 QGIS/GDAL 接口。
支持中/日/英三语指令模板匹配，提升小模型准确率。
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

_log = logging.getLogger("instruction_mapper")

# ── 指令模板定义 ────────────────────────────────────────
# 格式: { "action": str, "zh": [...], "ja": [...], "en": [...], "handler": str, "params": {} }

_INSTRUCTION_TEMPLATES: List[Dict[str, Any]] = [
    # ── 文件操作 ──
    {
        "action": "load_layer",
        "zh": ["加载图层", "打开文件", "导入图层", "添加图层", "加载.*文件"],
        "ja": ["レイヤを読み込む", "ファイルを開く", "レイヤをインポート", "レイヤを追加"],
        "en": ["load layer", "open file", "import layer", "add layer", "load.*file"],
        "handler": "_handle_load_layer",
        "params": {"file_path": ""},
    },
    {
        "action": "save_project",
        "zh": ["保存项目", "保存工程"],
        "ja": ["プロジェクトを保存", "プロジェクト保存"],
        "en": ["save project"],
        "handler": "_handle_save_project",
        "params": {},
    },
    {
        "action": "export_map",
        "zh": ["导出地图", "导出为图片", "保存为图片", "截图"],
        "ja": ["地図をエクスポート", "画像として保存", "マップをエクスポート"],
        "en": ["export map", "save as image", "export as image", "screenshot"],
        "handler": "_handle_export_map",
        "params": {"format": "png"},
    },
    # ── 视图操作 ──
    {
        "action": "zoom_to_layer",
        "zh": ["缩放到图层", "缩放到.*层", "全图显示"],
        "ja": ["レイヤにズーム", "全体表示", "ズーム.*レイヤ"],
        "en": ["zoom to layer", "zoom to full extent", "zoom full"],
        "handler": "_handle_zoom_to_layer",
        "params": {"layer_name": ""},
    },
    {
        "action": "zoom_in",
        "zh": ["放大", "拉近"],
        "ja": ["拡大", "ズームイン"],
        "en": ["zoom in"],
        "handler": "_handle_zoom_in",
        "params": {},
    },
    {
        "action": "zoom_out",
        "zh": ["缩小", "拉远"],
        "ja": ["縮小", "ズームアウト"],
        "en": ["zoom out"],
        "handler": "_handle_zoom_out",
        "params": {},
    },
    # ── 图层操作 ──
    {
        "action": "remove_layer",
        "zh": ["删除图层", "移除图层", "去掉.*层"],
        "ja": ["レイヤを削除", "レイヤを除去"],
        "en": ["remove layer", "delete layer"],
        "handler": "_handle_remove_layer",
        "params": {"layer_name": ""},
    },
    {
        "action": "list_layers",
        "zh": ["列出图层", "显示图层", "有哪些图层", "图层列表"],
        "ja": ["レイヤ一覧", "レイヤを表示", "レイヤリスト"],
        "en": ["list layers", "show layers", "what layers"],
        "handler": "_handle_list_layers",
        "params": {},
    },
    # ── 查询操作 ──
    {
        "action": "identify_feature",
        "zh": ["识别要素", "点击查询", "要素信息", "查询.*属性"],
        "ja": ["地物を識別", "クリック照会", "属性を照会"],
        "en": ["identify feature", "query feature", "feature info"],
        "handler": "_handle_identify_feature",
        "params": {},
    },
    # ── 坐标系 ──
    {
        "action": "set_crs",
        "zh": ["设置坐标系", "切换投影", "坐标系.*EPSG", "CRS.*4326"],
        "ja": ["座標系を設定", "投影法を変更", "CRS.*EPSG"],
        "en": ["set CRS", "set projection", "change coordinate system"],
        "handler": "_handle_set_crs",
        "params": {"epsg": 4326},
    },
    {
        "action": "show_crs",
        "zh": ["查看坐标系", "当前投影", "是什么坐标系"],
        "ja": ["座標系を確認", "現在の投影法"],
        "en": ["show CRS", "what projection", "current CRS"],
        "handler": "_handle_show_crs",
        "params": {},
    },
    # ── P0 新增：编辑/选择/视图 ──
    {
        "action": "toggle_editing",
        "zh": ["切换编辑", "开启编辑", "关闭编辑", "停止编辑", "编辑状态", "开始编辑"],
        "ja": ["編集切替", "編集開始", "編集停止", "編集状態"],
        "en": ["toggle editing", "start editing", "stop editing", "edit state"],
        "handler": "_handle_toggle_editing",
        "params": {"layer_name": ""},
    },
    {
        "action": "select_feature",
        "zh": ["选择要素", "框选要素", "点选要素", "条件选择", "清除选择", "选中要素"],
        "ja": ["地物選択", "矩形選択", "ポイント選択", "条件選択", "選択解除"],
        "en": ["select feature", "select by rectangle", "select by point", "select by expression", "clear selection"],
        "handler": "_handle_select_feature",
        "params": {"method": "rect"},
    },
    {
        "action": "reset_view",
        "zh": ["重置视图", "全图显示", "显示全部", "回到全图", "全景"],
        "ja": ["ビューをリセット", "全体表示", "全図表示", "全景"],
        "en": ["reset view", "zoom to full", "show all", "full extent", "panorama"],
        "handler": "_handle_reset_view",
        "params": {},
    },
    # ── P1 新增：样式/过滤/导出 ──
    {
        "action": "set_layer_style",
        "zh": ["设置样式", "图层样式", "渲染样式", "单一样式", "分类样式", "分级样式"],
        "ja": ["スタイル設定", "レイヤスタイル", "単一スタイル", "分類スタイル", "段階スタイル"],
        "en": ["set style", "layer style", "render style", "single style", "categorized style", "graduated style"],
        "handler": "_handle_set_layer_style",
        "params": {"layer_name": "", "render_type": "single", "color": "#FF0000"},
    },
    {
        "action": "load_layer_style",
        "zh": ["加载样式", "导入样式", "QML样式", "样式文件"],
        "ja": ["スタイル読込", "QMLスタイル", "スタイルファイル"],
        "en": ["load style", "import style", "QML style", "style file"],
        "handler": "_handle_load_layer_style",
        "params": {"layer_name": "", "qml_path": ""},
    },
    {
        "action": "filter_layer",
        "zh": ["过滤图层", "属性过滤", "条件筛选", "设置过滤", "清除过滤"],
        "ja": ["レイヤフィルタ", "属性フィルタ", "条件抽出", "フィルタ解除"],
        "en": ["filter layer", "attribute filter", "set filter", "clear filter", "filter by expression"],
        "handler": "_handle_filter_layer",
        "params": {"layer_name": "", "expression": ""},
    },
    {
        "action": "export_attribute",
        "zh": ["导出属性表", "导出表格", "导出CSV", "属性导出", "导出属性"],
        "ja": ["属性テーブルエクスポート", "CSV出力", "属性エクスポート"],
        "en": ["export attribute table", "export table", "export CSV", "attribute export"],
        "handler": "_handle_export_attribute",
        "params": {"layer_name": "", "output_path": ""},
    },
    # ── P2 新增：标注/字段/统计/缓冲区 ──
    {
        "action": "add_label",
        "zh": ["添加标注", "显示标注", "关闭标注", "要素标注", "标注字段"],
        "ja": ["ラベル追加", "ラベル表示", "ラベル非表示", "ラベルフィールド"],
        "en": ["add label", "show label", "hide label", "feature label", "label field"],
        "handler": "_handle_add_label",
        "params": {"layer_name": "", "field": ""},
    },
    {
        "action": "open_field_manager",
        "zh": ["字段管理", "打开字段管理器", "管理字段", "属性字段"],
        "ja": ["フィールド管理", "フィールドマネージャ", "属性フィールド"],
        "en": ["field manager", "open field manager", "manage fields", "attribute fields"],
        "handler": "_handle_open_field_manager",
        "params": {"layer_name": ""},
    },
    {
        "action": "layer_statistic",
        "zh": ["图层统计", "数据统计", "要素统计", "字段统计", "最大值", "最小值", "平均值", "求和"],
        "ja": ["レイヤ統計", "データ統計", "最大値", "最小値", "平均値", "合計"],
        "en": ["layer statistic", "data statistics", "feature count", "field statistics", "max", "min", "mean", "sum"],
        "handler": "_handle_layer_statistic",
        "params": {"layer_name": "", "method": "count"},
    },
    {
        "action": "create_buffer",
        "zh": ["缓冲区分析", "创建缓冲区", "缓冲距离", "缓冲区"],
        "ja": ["バッファ分析", "バッファ作成", "バッファ距離"],
        "en": ["buffer analysis", "create buffer", "buffer distance"],
        "handler": "_handle_create_buffer",
        "params": {"layer_name": "", "distance": 100.0},
    },
]

# ── 系统提示词（离线模式用）─────────────────────────────

_SYSTEM_PROMPT_ZH = """你是一个 GIS 桌面助手，运行在离线模式下。你必须严格遵循以下规则：

【硬性规则】
- 你只能输出 JSON，不要输出任何解释、分析、步骤描述或 Markdown 格式。
- 即使你认为指令无法执行，也必须用 JSON 回复，不要用自然语言解释原因。
- 不要输出 ```json 代码块，直接输出纯 JSON。

【输出格式】
- 能匹配到操作时：{"action": "<action_name>", "params": {"<key>": "<value>"}}
- 无法匹配时：{"action": "unknown", "message": "<简短原因，不超过30字>"}
- 回答 GIS 知识问题时：{"action": "answer", "message": "<回答内容>"}

【可用操作列表（严格从以下选择，不能自创）】

load_layer       — 加载图层文件 {"file_path": "文件完整路径"}
save_project     — 保存当前项目（无参数）
export_map       — 导出地图为图片 {"format": "png"}
zoom_to_layer    — 缩放到指定图层 {"layer_name": "图层名称"}
zoom_in          — 放大（无参数）
zoom_out         — 缩小（无参数）
remove_layer     — 删除图层 {"layer_name": "图层名称"}
list_layers      — 列出所有图层（无参数）
identify_feature — 识别要素属性（无参数）
set_crs          — 设置坐标系 {"epsg": 4326}
show_crs         — 查看当前坐标系（无参数）
toggle_editing   — 切换矢量图层编辑状态 {"layer_name": "图层名称", "target": "all(可选，关闭所有)"}
select_feature   — 要素选择 {"method": "point/rect/expression/clear", "layer_name": "图层名称(可选)", "expression": "SQL表达式(method=expression时)"}
reset_view       — 重置视图为全图范围（无参数）
set_layer_style  — 设置图层样式 {"layer_name": "图层名称", "render_type": "single/categorized/graduated", "color": "#FF0000", "field_name": "字段名"}
load_layer_style — 加载QML样式文件 {"layer_name": "图层名称", "qml_path": "QML文件路径"}
filter_layer     — 图层属性过滤 {"layer_name": "图层名称", "expression": "SQL表达式（空字符串清除过滤）"}
export_attribute — 导出属性表为CSV {"layer_name": "图层名称", "output_path": "CSV输出路径"}
add_label        — 添加/隐藏要素标注 {"layer_name": "图层名称", "field": "标注字段名（不传或空关闭）"}
open_field_manager — 打开字段管理器 {"layer_name": "图层名称"}
layer_statistic  — 图层数据统计 {"layer_name": "图层名称", "method": "count/min/max/sum/mean/all", "field": "字段名(可选)"}
create_buffer    — 缓冲区分析 {"layer_name": "图层名称", "distance": 100.0, "selected_only": false}

【示例】
用户："加载 D:/data/roads.shp"
你：{"action": "load_layer", "params": {"file_path": "D:/data/roads.shp"}}

用户："删除名为'临时图层'的图层"
你：{"action": "remove_layer", "params": {"layer_name": "临时图层"}}

用户："什么是空间索引"
你：{"action": "answer", "message": "空间索引是一种用于加速空间查询的数据结构，常用 R-tree 实现。"}

用户："帮我做个缓冲区分析"
你：{"action": "unknown", "message": "当前不支持缓冲区分析操作"}

记住：无论什么情况，只输出 JSON。"""

_SYSTEM_PROMPT_JA = """あなたは GIS デスクトップアシスタントで、オフラインモードで動作しています。以下のことができます：
1. GIS 関連の質問に回答
2. GIS 操作コマンドの実行

操作指示がある場合は、次の JSON 形式で返信してください：
{"action": "操作名", "params": {"パラメータ名": "値"}}

対応操作：load_layer, save_project, export_map, zoom_to_layer, zoom_in, zoom_out,
remove_layer, list_layers, identify_feature, set_crs, show_crs,
toggle_editing, select_feature, reset_view, set_layer_style, load_layer_style,
filter_layer, export_attribute, add_label, open_field_manager, layer_statistic, create_buffer

不明な場合は次を返信：
{"action": "unknown", "message": "指示を認識できませんでした。より明確な説明をお試しください。"}"""

_SYSTEM_PROMPT_EN = """You are a GIS desktop assistant running in offline mode. You can:
1. Answer GIS-related questions
2. Execute GIS operation commands

When the user issues an operation command, reply with a JSON object:
{"action": "operation_name", "params": {"param_name": "value"}}

Supported actions: load_layer, save_project, export_map, zoom_to_layer, zoom_in, zoom_out,
remove_layer, list_layers, identify_feature, set_crs, show_crs,
toggle_editing, select_feature, reset_view, set_layer_style, load_layer_style,
filter_layer, export_attribute, add_label, open_field_manager, layer_statistic, create_buffer

If unrecognized, reply:
{"action": "unknown", "message": "Unable to recognize the instruction. Please try a clearer description."}"""


class InstructionMapper:
    """多语言 GIS 指令映射器。

    将大模型输出的自然语言指令匹配到预定义操作模板，并调用对应 QGIS API。
    """

    def __init__(self, iface: Any = None) -> None:
        self._iface = iface  # QgisInterface 引用（可选）
        self._templates = _INSTRUCTION_TEMPLATES

    @staticmethod
    def get_system_prompt(lang: str = "zh") -> str:
        """获取离线模式系统提示词。"""
        prompts = {"zh": _SYSTEM_PROMPT_ZH, "ja": _SYSTEM_PROMPT_JA, "en": _SYSTEM_PROMPT_EN}
        return prompts.get(lang, _SYSTEM_PROMPT_EN)

    def match_and_execute(
        self,
        llm_response: str,
        canvas: Any = None,
        project: Any = None,
    ) -> Dict[str, Any]:
        """解析 LLM 响应并执行匹配的指令。

        Parameters
        ----------
        llm_response : str
            本地大模型的原始响应文本。
        canvas : QgsMapCanvas or None
            当前地图画布。
        project : QgsProject or None
            当前 QGIS 项目。

        Returns
        -------
        dict
            {"success": bool, "message": str, "action": str or None}
        """
        # 1. 尝试从 LLM 响应中提取 JSON
        instruction = self._extract_json(llm_response)
        if instruction is None:
            return {"success": False, "message": llm_response.strip()[:500], "action": None}

        action = instruction.get("action", "")
        if action == "unknown":
            return {"success": False, "message": instruction.get("message", "无法识别指令"), "action": "unknown"}
        if action == "answer":
            return {"success": True, "message": instruction.get("message", ""), "action": "answer"}

        params = instruction.get("params", {})

        # 2. 匹配模板
        template = self._find_template(action)
        if template is None:
            return {"success": False, "message": f"不支持的操作：{action}", "action": action}

        # 3. 执行处理函数
        handler_name = template["handler"]
        handler = getattr(self, handler_name, None)
        if handler is None:
            return {"success": False, "message": f"处理函数未实现：{handler_name}", "action": action}

        try:
            result = handler(canvas=canvas, project=project, **params)
            result["action"] = action
            return result
        except Exception as e:
            _log.exception(f"执行指令 {action} 失败")
            return {"success": False, "message": f"执行失败：{e}", "action": action}

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """从文本中提取 JSON 对象。增强 7B 模型输出容错。"""
        text = text.strip()

        # 1. 直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 2. Markdown 代码块
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # 3. 找到第一个 { 到最后一个 }，尝试解析（容错兜底）
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            candidate = text[start:end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        return None

    def _find_template(self, action: str) -> Optional[Dict[str, Any]]:
        """按 action 名称查找模板。"""
        for t in self._templates:
            if t["action"] == action:
                return t
        return None

    # ── 操作处理函数 ────────────────────────────────────

    def _handle_load_layer(self, canvas=None, project=None, file_path: str = "", **kwargs) -> Dict[str, Any]:
        from qgis.core import QgsVectorLayer, QgsRasterLayer, QgsProject
        proj = project or QgsProject.instance()

        if not file_path or not os.path.exists(file_path):
            return {"success": False, "message": f"文件不存在：{file_path}"}

        name = os.path.splitext(os.path.basename(file_path))[0]
        ext = os.path.splitext(file_path)[1].lower()
        raster_exts = {'.tif', '.tiff', '.png', '.jpg', '.jpeg', '.bmp'}

        if ext in raster_exts:
            layer = QgsRasterLayer(file_path, name)
        else:
            layer = QgsVectorLayer(file_path, name, "ogr")

        if not layer.isValid():
            return {"success": False, "message": f"无法加载图层：{file_path}"}

        proj.addMapLayer(layer)
        if canvas:
            canvas.setExtent(layer.extent())
            canvas.refresh()
        return {"success": True, "message": f"已加载图层：{name}"}

    def _handle_save_project(self, canvas=None, project=None, **kwargs) -> Dict[str, Any]:
        from qgis.core import QgsProject
        proj = project or QgsProject.instance()
        path = proj.fileName()
        if not path:
            return {"success": False, "message": "项目尚未保存。请使用「文件 → 另存为」先指定路径。"}
        if proj.write():
            return {"success": True, "message": f"项目已保存：{path}"}
        return {"success": False, "message": "保存失败"}

    def _handle_export_map(self, canvas=None, project=None, format: str = "png", **kwargs) -> Dict[str, Any]:
        if canvas is None:
            return {"success": False, "message": "地图画布未初始化"}

        from PyQt5.QtGui import QImage, QPainter
        from PyQt5.QtCore import Qt
        from qgis.core import QgsMapRendererCustomPainterJob

        import tempfile, time
        path = os.path.join(tempfile.gettempdir(), f"aiqgis_export_{int(time.time())}.{format}")

        settings = canvas.mapSettings()
        size = settings.outputSize()
        image = QImage(size, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)

        painter = QPainter(image)
        job = QgsMapRendererCustomPainterJob(settings, painter)
        job.start()
        job.waitForFinished()
        painter.end()

        if image.save(path):
            return {"success": True, "message": f"地图已导出：{path}", "output_path": path}
        return {"success": False, "message": "导出失败"}

    def _handle_zoom_to_layer(self, canvas=None, project=None, layer_name: str = "", **kwargs) -> Dict[str, Any]:
        if canvas is None:
            return {"success": False, "message": "地图画布未初始化"}

        from qgis.core import QgsProject
        proj = project or QgsProject.instance()

        # 查找匹配图层
        for layer_id, layer in proj.mapLayers().items():
            if layer_name.lower() in layer.name().lower():
                canvas.setExtent(layer.extent())
                canvas.refresh()
                return {"success": True, "message": f"已缩放至图层：{layer.name()}"}

        # 未找到指定图层 → 缩放到全部
        if not layer_name:
            canvas.zoomToFullExtent()
            canvas.refresh()
            return {"success": True, "message": "已缩放至全图范围"}

        return {"success": False, "message": f"未找到图层：{layer_name}"}

    def _handle_zoom_in(self, canvas=None, project=None, **kwargs) -> Dict[str, Any]:
        if canvas is None:
            return {"success": False, "message": "地图画布未初始化"}
        canvas.zoomIn()
        canvas.refresh()
        return {"success": True, "message": "已放大"}

    def _handle_zoom_out(self, canvas=None, project=None, **kwargs) -> Dict[str, Any]:
        if canvas is None:
            return {"success": False, "message": "地图画布未初始化"}
        canvas.zoomOut()
        canvas.refresh()
        return {"success": True, "message": "已缩小"}

    def _handle_remove_layer(self, canvas=None, project=None, layer_name: str = "", **kwargs) -> Dict[str, Any]:
        from qgis.core import QgsProject
        proj = project or QgsProject.instance()

        for layer_id, layer in list(proj.mapLayers().items()):
            if layer_name.lower() in layer.name().lower():
                proj.removeMapLayer(layer_id)
                if canvas:
                    canvas.refresh()
                return {"success": True, "message": f"已移除图层：{layer.name()}"}

        return {"success": False, "message": f"未找到图层：{layer_name}"}

    def _handle_list_layers(self, canvas=None, project=None, **kwargs) -> Dict[str, Any]:
        from qgis.core import QgsProject, QgsVectorLayer
        proj = project or QgsProject.instance()
        layers = []
        for layer in proj.mapLayers().values():
            ltype = "矢量" if isinstance(layer, QgsVectorLayer) else "栅格"
            layers.append(f"  - [{ltype}] {layer.name()}")

        if not layers:
            return {"success": True, "message": "当前项目没有图层。", "layers": []}

        return {"success": True, "message": "当前图层：\n" + "\n".join(layers), "layers": layers}

    def _handle_identify_feature(self, canvas=None, project=None, **kwargs) -> Dict[str, Any]:
        """激活 QGIS 要素识别工具（如果 iface 可用）。"""
        try:
            from qgis.utils import iface
            if iface:
                iface.actionIdentify().trigger()
                return {"success": True, "message": "已激活要素识别工具，请点击地图上的要素查看属性。", "action": "identify_feature"}
        except Exception:
            pass
        return {"success": False, "message": "离线模式下要素识别请使用工具栏的「识别」工具点击地图。", "action": "identify_feature"}

    def _handle_set_crs(self, canvas=None, project=None, epsg: int = 4326, **kwargs) -> Dict[str, Any]:
        from qgis.core import QgsCoordinateReferenceSystem, QgsProject
        proj = project or QgsProject.instance()

        crs = QgsCoordinateReferenceSystem(f"EPSG:{epsg}")
        if not crs.isValid():
            return {"success": False, "message": f"无效的坐标系：EPSG:{epsg}"}

        proj.setCrs(crs)
        if canvas:
            canvas.refresh()
        return {"success": True, "message": f"项目坐标系已设置为 EPSG:{epsg} — {crs.description()}"}

    def _handle_show_crs(self, canvas=None, project=None, **kwargs) -> Dict[str, Any]:
        from qgis.core import QgsProject
        proj = project or QgsProject.instance()
        crs = proj.crs()
        return {"success": True, "message": f"当前坐标系：{crs.authid()} — {crs.description()}"}

    # ── 共享工具函数 ─────────────────────────────────────

    @staticmethod
    def _find_layer(project, layer_name: str) -> Optional[Any]:
        """按名称模糊匹配图层。"""
        from qgis.core import QgsProject
        proj = project or QgsProject.instance()
        for _lid, layer in proj.mapLayers().items():
            if layer_name.lower() in layer.name().lower():
                return layer
        return None

    @staticmethod
    def _check_vector(layer) -> Optional[Dict[str, Any]]:
        """检查图层是否为矢量图层，不是则返回错误字典。"""
        from qgis.core import QgsVectorLayer
        if not isinstance(layer, QgsVectorLayer):
            return {"success": False, "message": "编辑操作仅支持矢量图层"}
        return None

    @staticmethod
    def _export_attribute_table(layer, output_path: str) -> Dict[str, Any]:
        """导出矢量图层属性表为 CSV（共享工具函数）。"""
        from qgis.core import QgsVectorFileWriter
        import os
        error = QgsVectorFileWriter.writeAsVectorFormat(
            layer, output_path, "UTF-8", layer.crs(), "CSV",
            layerOptions=["GEOMETRY=AS_WKT"]
        )
        if error[0] == QgsVectorFileWriter.NoError:
            size_kb = os.path.getsize(output_path) / 1024 if os.path.exists(output_path) else 0
            return {"success": True, "message": f"属性表已导出：{output_path}（{size_kb:.1f} KB）"}
        return {"success": False, "message": f"导出失败：{error}"}

    # ── P0 新增 handler ──────────────────────────────────

    def _handle_toggle_editing(self, canvas=None, project=None, layer_name: str = "",
                                target: str = "", **kwargs) -> Dict[str, Any]:
        from qgis.core import QgsProject, QgsVectorLayer
        proj = project or QgsProject.instance()

        if target == "all":
            closed = []
            for _lid, layer in proj.mapLayers().items():
                if isinstance(layer, QgsVectorLayer) and layer.isEditable():
                    try:
                        layer.commitChanges()
                        closed.append(layer.name())
                    except Exception:
                        layer.rollBack()
            msg = f"已关闭所有编辑图层：{', '.join(closed)}" if closed else "当前没有正在编辑的图层"
            return {"success": True, "message": msg, "action": "toggle_editing", "closed": closed}

        layer = self._find_layer(project, layer_name) if layer_name else None
        if layer is None:
            return {"success": False, "message": f"未找到图层：{layer_name}"}

        err = self._check_vector(layer)
        if err:
            return err

        try:
            if layer.isEditable():
                layer.commitChanges()
                return {"success": True, "message": f"已保存编辑并关闭：{layer.name()}", "action": "toggle_editing"}
            else:
                layer.startEditing()
                return {"success": True, "message": f"已开启编辑：{layer.name()}", "action": "toggle_editing"}
        except Exception as e:
            try:
                layer.rollBack()
            except Exception:
                pass
            return {"success": False, "message": f"编辑切换失败：{e}", "action": "toggle_editing"}

    def _handle_select_feature(self, canvas=None, project=None, method: str = "rect",
                                layer_name: str = "", expression: str = "", **kwargs) -> Dict[str, Any]:
        from qgis.core import QgsProject, QgsVectorLayer
        proj = project or QgsProject.instance()

        if method == "clear":
            for _lid, layer in proj.mapLayers().items():
                if isinstance(layer, QgsVectorLayer):
                    layer.removeSelection()
            if canvas:
                canvas.refresh()
            return {"success": True, "message": "已清除所有图层选择", "action": "select_feature"}

        if method == "point":
            try:
                from qgis.utils import iface
                if iface:
                    iface.actionSelect().trigger()
                    return {"success": True, "message": "已激活点选工具，请在地图上点击要素", "action": "select_feature"}
            except Exception:
                pass
            return {"success": False, "message": "点选工具仅在 QGIS 桌面环境下可用"}

        if method == "rect":
            try:
                from qgis.utils import iface
                if iface:
                    iface.actionSelectRectangle().trigger()
                    return {"success": True, "message": "已激活框选工具，请在地图上拖拽矩形区域", "action": "select_feature"}
            except Exception:
                pass
            return {"success": False, "message": "框选工具仅在 QGIS 桌面环境下可用"}

        if method == "expression":
            layer = self._find_layer(project, layer_name) if layer_name else None
            if layer is None:
                return {"success": False, "message": f"未找到图层：{layer_name}"}
            err = self._check_vector(layer)
            if err:
                return err
            if not expression:
                return {"success": False, "message": "expression 模式下必须提供 SQL 表达式"}
            layer.selectByExpression(expression)
            count = layer.selectedFeatureCount()
            return {"success": True, "message": f"已选中 {count} 个要素", "selected_count": count, "action": "select_feature"}

        return {"success": False, "message": f"不支持的选择方式：{method}"}

    def _handle_reset_view(self, canvas=None, project=None, **kwargs) -> Dict[str, Any]:
        if canvas is None:
            return {"success": False, "message": "地图画布未初始化"}
        canvas.zoomToFullExtent()
        canvas.refresh()
        return {"success": True, "message": "已重置为全图范围", "action": "reset_view"}

    # ── P1 新增 handler ──────────────────────────────────

    def _handle_set_layer_style(self, canvas=None, project=None, layer_name: str = "",
                                 render_type: str = "single", color: str = "#FF0000",
                                 field_name: str = "", **kwargs) -> Dict[str, Any]:
        from qgis.core import (
            QgsProject, QgsVectorLayer, QgsRasterLayer,
            QgsSingleSymbolRenderer, QgsCategorizedSymbolRenderer,
            QgsGraduatedSymbolRenderer, QgsRendererCategory,
            QgsFillSymbol, QgsLineSymbol, QgsMarkerSymbol,
            QgsSingleBandPseudoColorRenderer, QgsColorRampShader,
            QgsRasterShader, QgsStyle, QgsGraduatedSymbolRenderer,
        )
        from qgis.PyQt.QtGui import QColor
        from qgis.utils import iface as qgis_iface
        import random

        proj = project or QgsProject.instance()
        layer = self._find_layer(project, layer_name)
        if layer is None:
            return {"success": False, "message": f"未找到图层：{layer_name}"}

        # 栅格图层处理
        if isinstance(layer, QgsRasterLayer):
            if render_type != "single":
                return {"success": False, "message": "栅格图层仅支持 single 样式"}
            try:
                shader_func = QgsColorRampShader(0, 255)
                import numpy as np
                stats = layer.dataProvider().bandStatistics(1)
                vmin = stats.minimumValue
                vmax = stats.maximumValue
                color_ramp_items = [
                    QgsColorRampShader.ColorRampItem(vmin, QColor("#808080")),
                    QgsColorRampShader.ColorRampItem(vmax, QColor("#FF0000")),
                ]
                shader_func.setColorRampItemList(color_ramp_items)
                shader_func.setColorRampType(QgsColorRampShader.Interpolated)
                raster_shader = QgsRasterShader()
                raster_shader.setRasterShaderFunction(shader_func)
                renderer = QgsSingleBandPseudoColorRenderer(
                    layer.dataProvider(), 1, raster_shader
                )
                layer.setRenderer(renderer)
                layer.triggerRepaint()
                return {"success": True, "message": f"栅格图层 {layer.name()} 样式已设置"}
            except Exception as e:
                return {"success": False, "message": f"栅格样式设置失败：{e}"}

        # 矢量图层处理
        err = self._check_vector(layer)
        if err:
            return err

        qcolor = QColor(color)

        try:
            if render_type == "single":
                geom_type = layer.geometryType()
                if geom_type == 0:  # Point
                    symbol = QgsMarkerSymbol.createSimple({})
                elif geom_type == 1:  # Line
                    symbol = QgsLineSymbol.createSimple({})
                else:  # Polygon
                    symbol = QgsFillSymbol.createSimple({})
                symbol.setColor(qcolor)
                renderer = QgsSingleSymbolRenderer(symbol)

            elif render_type == "categorized":
                if not field_name:
                    field_name = layer.fields().at(0).name() if layer.fields().count() > 0 else ""
                if not field_name:
                    return {"success": False, "message": "分类样式需要指定 field_name 参数"}
                idx = layer.fields().indexOf(field_name)
                unique_values = list(layer.uniqueValues(idx))
                categories = []
                for i, val in enumerate(unique_values):
                    hue = (i * 137) % 360
                    cat_color = QColor.fromHsv(hue, 200, 220)
                    cat_symbol = QgsFillSymbol.createSimple({})
                    cat_symbol.setColor(cat_color)
                    category = QgsRendererCategory(val, cat_symbol, str(val))
                    categories.append(category)
                renderer = QgsCategorizedSymbolRenderer(field_name, categories)

            elif render_type == "graduated":
                if not field_name:
                    field_name = layer.fields().at(0).name() if layer.fields().count() > 0 else ""
                if not field_name:
                    return {"success": False, "message": "分级样式需要指定 field_name 参数"}
                idx = layer.fields().indexOf(field_name)
                values = []
                for feat in layer.getFeatures():
                    val = feat.attribute(field_name)
                    if val is not None:
                        values.append(float(val))
                if not values:
                    return {"success": False, "message": f"字段 {field_name} 没有有效数值"}
                vmin, vmax = min(values), max(values)
                if vmin == vmax:
                    vmax = vmin + 1
                step = (vmax - vmin) / 5
                ranges = []
                for i in range(5):
                    lo = vmin + i * step
                    hi = vmin + (i + 1) * step
                    r = int(255 * i / 4)
                    g = int(255 * (4 - i) / 4)
                    rcolor = QColor(r, g, 128)
                    rsymbol = QgsFillSymbol.createSimple({})
                    rsymbol.setColor(rcolor)
                    rrange = QgsRendererRange(lo, hi, rsymbol, f"{lo:.1f} - {hi:.1f}")
                    ranges.append(rrange)
                renderer = QgsGraduatedSymbolRenderer(field_name, ranges)
            else:
                return {"success": False, "message": f"不支持的渲染类型：{render_type}"}

            layer.setRenderer(renderer)
            layer.triggerRepaint()
            return {"success": True, "message": f"图层 {layer.name()} 样式已设置为 {render_type}"}

        except Exception as e:
            _log.exception("set_layer_style 失败")
            return {"success": False, "message": f"样式设置失败：{e}"}

    def _handle_load_layer_style(self, canvas=None, project=None, layer_name: str = "",
                                  qml_path: str = "", **kwargs) -> Dict[str, Any]:
        import os
        from qgis.core import QgsProject

        layer = self._find_layer(project, layer_name)
        if layer is None:
            return {"success": False, "message": f"未找到图层：{layer_name}"}

        if not qml_path or not os.path.exists(qml_path):
            return {"success": False, "message": f"QML 文件不存在：{qml_path}"}

        result = layer.loadNamedStyle(qml_path)
        if result[0]:
            layer.triggerRepaint()
            return {"success": True, "message": f"已加载样式：{os.path.basename(qml_path)}"}
        return {"success": False, "message": f"样式加载失败：{result[1]}"}

    def _handle_filter_layer(self, canvas=None, project=None, layer_name: str = "",
                              expression: str = "", **kwargs) -> Dict[str, Any]:
        from qgis.core import QgsProject

        layer = self._find_layer(project, layer_name)
        if layer is None:
            return {"success": False, "message": f"未找到图层：{layer_name}"}

        err = self._check_vector(layer)
        if err:
            return err

        if expression.strip() == "":
            layer.setSubsetString("")
            return {"success": True, "message": f"图层 {layer.name()} 过滤已清除，共 {layer.featureCount()} 个要素"}

        layer.setSubsetString(expression)
        return {"success": True, "message": f"图层 {layer.name()} 过滤已应用，当前显示 {layer.featureCount()} 个要素"}

    def _handle_export_attribute(self, canvas=None, project=None, layer_name: str = "",
                                  output_path: str = "", **kwargs) -> Dict[str, Any]:
        layer = self._find_layer(project, layer_name)
        if layer is None:
            return {"success": False, "message": f"未找到图层：{layer_name}"}
        err = self._check_vector(layer)
        if err:
            return err
        return self._export_attribute_table(layer, output_path)

    # ── P2 新增 handler ──────────────────────────────────

    def _handle_add_label(self, canvas=None, project=None, layer_name: str = "",
                           field: str = "", **kwargs) -> Dict[str, Any]:
        from qgis.core import (
            QgsProject, QgsPalLayerSettings, QgsVectorLayerSimpleLabeling,
            QgsTextFormat,
        )

        layer = self._find_layer(project, layer_name)
        if layer is None:
            return {"success": False, "message": f"未找到图层：{layer_name}"}
        err = self._check_vector(layer)
        if err:
            return err

        if not field:
            layer.setLabeling(None)
            layer.triggerRepaint()
            return {"success": True, "message": f"已关闭图层 {layer.name()} 的标注"}

        settings = QgsPalLayerSettings()
        settings.fieldName = field
        settings.isExpression = False
        fmt = QgsTextFormat()
        fmt.setSize(10)
        settings.setFormat(fmt)
        labeling = QgsVectorLayerSimpleLabeling(settings)
        layer.setLabeling(labeling)
        layer.triggerRepaint()
        return {"success": True, "message": f"已为图层 {layer.name()} 开启标注，字段：{field}"}

    def _handle_open_field_manager(self, canvas=None, project=None, layer_name: str = "",
                                    **kwargs) -> Dict[str, Any]:
        from qgis.core import QgsProject

        layer = self._find_layer(project, layer_name)
        if layer is None:
            return {"success": False, "message": f"未找到图层：{layer_name}"}

        err = self._check_vector(layer)
        if err:
            return err

        try:
            from qgis.utils import iface
            if iface:
                iface.setActiveLayer(layer)
                iface.actionManageFields().trigger()
                return {"success": True, "message": f"已打开字段管理器：{layer.name()}"}
        except Exception:
            pass
        return {"success": False, "message": f"请在 QGIS 桌面环境中手动打开 {layer.name()} 的字段管理器"}

    def _handle_layer_statistic(self, canvas=None, project=None, layer_name: str = "",
                                 method: str = "count", field: str = "", **kwargs) -> Dict[str, Any]:
        from qgis.core import QgsStatisticalSummary

        layer = self._find_layer(project, layer_name)
        if layer is None:
            return {"success": False, "message": f"未找到图层：{layer_name}"}
        err = self._check_vector(layer)
        if err:
            return err

        if method == "count":
            return {"success": True, "message": f"图层 {layer.name()} 共 {layer.featureCount()} 个要素",
                    "count": layer.featureCount()}

        if method == "all" and not field:
            return {"success": True, "message": f"图层 {layer.name()} 共 {layer.featureCount()} 个要素",
                    "count": layer.featureCount()}

        if not field and method in ("min", "max", "sum", "mean", "all"):
            return {"success": False, "message": f"{method} 统计需要指定 field 参数"}

        idx = layer.fields().indexOf(field)
        if idx < 0:
            return {"success": False, "message": f"字段不存在：{field}"}

        values = []
        for feat in layer.getFeatures():
            val = feat.attribute(field)
            if val is not None:
                try:
                    values.append(float(val))
                except (ValueError, TypeError):
                    pass

        if not values:
            return {"success": False, "message": f"字段 {field} 没有有效数值"}

        if method == "min":
            result = min(values)
            return {"success": True, "message": f"{field} 最小值：{result}", "value": result}
        elif method == "max":
            result = max(values)
            return {"success": True, "message": f"{field} 最大值：{result}", "value": result}
        elif method == "sum":
            result = sum(values)
            return {"success": True, "message": f"{field} 合计：{result}", "value": result}
        elif method == "mean":
            result = sum(values) / len(values)
            return {"success": True, "message": f"{field} 平均值：{result:.4f}", "value": result}
        elif method == "all":
            cnt = len(values)
            mn = min(values)
            mx = max(values)
            sm = sum(values)
            avg = sm / cnt
            return {"success": True,
                    "message": f"{field} 统计：count={cnt}, min={mn}, max={mx}, sum={sm}, mean={avg:.4f}",
                    "count": cnt, "min": mn, "max": mx, "sum": sm, "mean": avg}

        return {"success": False, "message": f"不支持的统计方法：{method}"}

    def _handle_create_buffer(self, canvas=None, project=None, layer_name: str = "",
                               distance: float = 100.0, selected_only: bool = False,
                               **kwargs) -> Dict[str, Any]:
        from qgis.core import (
            QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry,
            QgsField, QgsFields,
        )
        from qgis.PyQt.QtCore import QVariant

        layer = self._find_layer(project, layer_name)
        if layer is None:
            return {"success": False, "message": f"未找到图层：{layer_name}"}
        err = self._check_vector(layer)
        if err:
            return err

        if layer.featureCount() > 10000 and not selected_only:
            return {"success": False,
                    "message": f"图层要素数量（{layer.featureCount()}）超过 10000，请使用 selected_only=true 或先筛选数据"}

        crs = layer.crs().authid()
        geom_type_str = "Polygon"
        uri = f"{geom_type_str}?crs={crs}"
        buff_layer = QgsVectorLayer(uri, f"{layer.name()}_buffer_{distance}m", "memory")
        provider = buff_layer.dataProvider()

        fields = QgsFields()
        fields.append(QgsField("original_id", QVariant.Int))
        provider.addAttributes(fields)
        buff_layer.updateFields()

        if selected_only:
            features = layer.selectedFeatures()
        else:
            features = layer.getFeatures()

        new_features = []
        for feat in features:
            geom = feat.geometry()
            if geom and not geom.isNull():
                buff_geom = geom.buffer(distance, 5)
                if buff_geom and not buff_geom.isNull():
                    new_feat = QgsFeature()
                    new_feat.setGeometry(buff_geom)
                    new_feat.setAttributes([feat.id()])
                    new_features.append(new_feat)

        if not new_features:
            return {"success": False, "message": "没有要素可用于缓冲区分析"}

        provider.addFeatures(new_features)
        buff_layer.updateExtents()

        proj = project or QgsProject.instance()
        proj.addMapLayer(buff_layer)

        if canvas:
            canvas.setExtent(buff_layer.extent())
            canvas.refresh()

        return {"success": True,
                "message": f"缓冲区分析完成，新增图层：{buff_layer.name()}（{len(new_features)} 个要素）"}
