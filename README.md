# AIQGIS v0.4 — Portable Edition

AI 驱动桌面 GIS 应用。QGIS 引擎已随包封装，**无需独立安装 QGIS**。

## 首次使用

1. 打开 `src\core\ai_config.py`，将 `API_KEY` 修改为你的 [DeepSeek API Key](https://platform.deepseek.com/api_keys)
2. 双击 `启动.bat` 运行

## 运行前提

- Windows 10/11 64-bit
- 无需安装 QGIS（已在 `qgis-portable\` 中封装）

## 功能

| 功能 | 说明 |
|------|------|
| 图层加载 | 拖放 SHP / GeoJSON / TIF / GPKG |
| AI 空间分析 | 自然语言→生成 PyQGIS 代码→执行→结果可视化 |
| 属性表 | 查看图层属性数据 |
| 图层样式 | AI 生成渲染样式（颜色/线宽/分类） |
| 地图导出 | PNG / JPG / PDF，支持 DPI 控制 |

## 目录结构

```
AIQGIS_APP/
├── 启动.bat            # 启动脚本
├── README.md
├── qgis-portable/      # QGIS 3.44.9 便携版（2.18 GB）
├── src/
│   ├── main.py         # 程序入口
│   ├── core/           # AI 配置、QGIS 环境适配
│   ├── skills/         # Skill-based Agent 技能
│   └── ui/             # PyQt5 界面
└── temp/
```