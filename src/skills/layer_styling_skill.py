"""
图层样式与符号化技能 - AI 驱动的矢量/栅格图层可视化样式修改。

继承 BaseSkill，由 SkillManager 自动发现注册。
通过 AI 生成 PyQGIS 样式代码并安全执行。
"""

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List

from qgis.core import (
    QgsProject,
    QgsMapLayer,
    QgsVectorLayer,
    QgsRasterLayer,
)

from skills.base_skill import BaseSkill


# ── 样式代码生成的系统提示词 ─────────────────────────────────
def _build_styling_prompt() -> str:
    """构建图层样式生成的系统提示词。"""
    return (
        "你是 QGIS 图层样式与符号化代码生成专家。\n"
        "你的输出必须严格满足以下要求：\n"
        "1. 仅输出一个 ```python ... ``` 代码块。\n"
        "2. 除代码块外，不允许输出任何解释。\n"
        "3. 代码必须围绕 QGIS 样式 API 完成可视化修改。\n"
        "4. 变量 `layer` 是当前活动图层，直接使用它。\n"
        "5. 必须把执行结果赋给变量 `result`，"
        "result = {\"success\": True, \"message\": \"描述\"}。\n"
        "6. 可用 API 示例：\n"
        "   - 修改符号颜色：\n"
        "     from qgis.core import QgsSingleSymbolRenderer, QgsFillSymbol\n"
        "     sym = QgsFillSymbol.createSimple({'color': 'blue', 'outline_color': 'black'})\n"
        "     layer.setRenderer(QgsSingleSymbolRenderer(sym))\n"
        "   - 修改线宽：\n"
        "     from qgis.core import QgsSingleSymbolRenderer, QgsLineSymbol\n"
        "     sym = QgsLineSymbol.createSimple({'color': 'red', 'line_width': '2'})\n"
        "     layer.setRenderer(QgsSingleSymbolRenderer(sym))\n"
        "   - 按字段分类渲染：\n"
        "     from qgis.core import QgsCategorizedSymbolRenderer, QgsRendererCategory\n"
        "     renderer = QgsCategorizedSymbolRenderer('字段名', [])\n"
        "     for val, color in [('值1','#ff0000'), ('值2','#00ff00')]:\n"
        "         sym = QgsFillSymbol.createSimple({'color': color})\n"
        "         renderer.addCategory(QgsRendererCategory(val, sym, str(val)))\n"
        "     layer.setRenderer(renderer)\n"
        "   - 渐变渲染：\n"
        "     from qgis.core import QgsGraduatedSymbolRenderer\n"
        "     renderer = QgsGraduatedSymbolRenderer.createRenderer(\n"
        "         layer, '字段名', 5, QgsGraduatedSymbolRenderer.Jenks, QgsFillSymbol())\n"
        "     layer.setRenderer(renderer)\n"
        "7. 必须调用 layer.triggerRepaint() 和 result = {'success': True, 'message': '...'}\n"
        "8. 禁止调用 print、input、sys、subprocess、eval、exec、open、__import__。\n"
        "9. 如果无法生成代码，返回抛出 RuntimeError 的最短代码。"
    )


def _request_styling_code(user_text: str, layer_name: str, layer_fields: List[str]) -> str:
    """向 AI 请求图层样式代码。"""
    from core.ai_config import API_KEY, BASE_URL, MODEL_NAME

    body = {
        "model": MODEL_NAME,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": _build_styling_prompt()},
            {"role": "user", "content": json.dumps({
                "user_request": user_text,
                "layer_name": layer_name,
                "layer_fields": layer_fields,
            }, ensure_ascii=False, indent=2)},
        ],
    }

    url = BASE_URL.rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"AI 接口请求失败，HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"AI 接口连接失败：{exc.reason}") from exc


class LayerStylingSkill(BaseSkill):
    """图层样式与符号化技能：AI 驱动的地图可视化样式修改。"""

    def get_name(self) -> str:
        return "layer_styling"

    def get_description(self) -> str:
        return (
            "- 用途：图层可视化样式修改（颜色、线宽、符号、标注、分类渲染、渐变渲染等）\n"
            "- 触发词：颜色、样式、符号、线宽、渲染、标注、标签、分类、渐变、\n"
            "  变成红色、改成蓝色、粗细、透明度、填充、边框、显示标签\n"
            "- 注意：此技能通过 AI 生成 QGIS 样式代码并执行，arguments 为客户原始指令正文\n"
            "- 优先级：当用户意图是修改地图外观/可视化/样式时路由到此技能"
        )

    def execute(
        self,
        canvas=None,
        layer_tree=None,
        arguments: str = "",
        active_layer=None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        执行图层样式修改。

        Parameters
        ----------
        canvas : QgsMapCanvas, optional
            地图画布（执行后刷新用）。
        arguments : str
            用户的样式修改指令。
        active_layer : QgsMapLayer, optional
            当前活动图层。

        Returns
        -------
        dict
            {"success": bool, "message": str}
        """
        if not arguments:
            return {"success": False, "message": "请提供样式修改指令，例如「把图层变成蓝色」"}

        # 获取图层
        layer = active_layer
        if layer is None:
            for l in QgsProject.instance().mapLayers().values():
                if l.type() == QgsMapLayer.VectorLayer:
                    layer = l
                    break
        if layer is None:
            return {"success": False, "message": "当前没有可渲染的图层"}

        # 获取字段列表
        fields = []
        if isinstance(layer, QgsVectorLayer):
            fields = [f.name() for f in layer.fields()]

        # 请求 AI 生成样式代码
        try:
            response = _request_styling_code(arguments, layer.name(), fields)
        except Exception as e:
            return {"success": False, "message": f"AI 请求失败：{e}"}

        # 提取代码
        import re
        match = re.search(r"```(?:python)?\s*([\s\S]*?)```", response, re.IGNORECASE)
        if not match:
            return {"success": False, "message": "AI 未返回合法代码块"}

        code = match.group(1).strip()

        # 安全执行
        safe_builtins = {
            "len": len, "min": min, "max": max, "sum": sum,
            "str": str, "int": int, "float": float, "bool": bool,
            "list": list, "dict": dict, "tuple": tuple, "set": set,
            "range": range, "enumerate": enumerate, "zip": zip, "sorted": sorted,
            "RuntimeError": RuntimeError, "ValueError": ValueError,
            "__import__": __import__, "isinstance": isinstance, "type": type,
            "super": super, "hasattr": hasattr, "getattr": getattr,
        }
        exec_globals = {
            "__builtins__": safe_builtins,
            "layer": layer,
            "canvas": canvas,
        }
        exec_locals: Dict[str, Any] = {}
        exec(code, exec_globals, exec_locals)

        # 刷新渲染
        if hasattr(layer, 'triggerRepaint'):
            layer.triggerRepaint()
        if canvas and hasattr(canvas, 'refresh'):
            canvas.refresh()

        result = exec_locals.get("result", {})
        if not isinstance(result, dict):
            return {"success": True, "message": "样式已应用"}

        return result