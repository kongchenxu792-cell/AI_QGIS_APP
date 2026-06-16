# AIQGIS v2.0-offline-expanded — AI-Powered QGIS Assistant

AI 驱动桌面 GIS 应用。支持在线 API（DeepSeek/DashScope）与离线本地推理（Ollama）双模式，22 个自然语言指令覆盖 GIS 全工作流。QGIS 引擎已随包封装，**无需独立安装 QGIS**。

> 更新日期：2026-06-16

---

## 首次使用

1. 打开 `src\core\ai_config.py`，将 `API_KEY` 修改为你的 API Key（在线模式需配置，离线模式可跳过）
2. 双击 `启动.bat` 运行

---

## 运行前提

- Windows 10/11 64-bit
- 无需安装 QGIS（已在 `qgis-portable\` 中封装）
- 离线模式需额外安装 Ollama（详见下方「离线模式部署」）

---

## 离线模式部署

### 简介

AIQGIS 支持完全离线运行模式，使用本地 Ollama 引擎进行推理，不依赖任何云端 API，所有计算和数据处理均在本地完成。

### 前提条件

- 已安装 [Ollama](https://ollama.com/download/windows)（Windows 版）
- 推荐模型：`qwen2.5:7b`（约 4.5 GB 磁盘占用）

### 部署步骤

**1. 安装 Ollama**

从 [ollama.com](https://ollama.com/download/windows) 下载 Windows 安装包并完成安装。安装后 Ollama 会自动注册为系统服务并启动。

**2. 设置模型存储路径（重要）**

为避免中文路径导致的编码问题，需将模型存储路径指向纯英文目录。推荐 `D:\model`：

```powershell
# PowerShell（管理员）
[Environment]::SetEnvironmentVariable("OLLAMA_MODELS", "D:\model", "User")
```

设置后需**重启 Ollama 服务**（或在系统托盘右键 Ollama 图标 → Quit，再重新打开）。

**3. 拉取模型**

```powershell
ollama pull qwen2.5:7b
```

下载约 4.5 GB，首次拉取需要几分钟。

**4. 验证模型**

```powershell
ollama run qwen2.5:7b
```

输入任意文字，确认能正常回复后输入 `/bye` 退出。

**5. 启动 AIQGIS 并切换到离线模式**

双击 `启动.bat` 启动 AIQGIS，在顶部模式切换栏点击「离线模式」即可。

### 硬件要求

| 项目 | 最低要求 | 推荐配置 |
|------|----------|----------|
| 显存 / 内存 | 8 GB | 16 GB |
| 磁盘空间 | 10 GB（模型 + 项目） | 20 GB |
| GPU | 支持 CUDA（可选） | NVIDIA RTX 3060+ |

> RTX 4060 笔记本实测 `qwen2.5:7b` 显存占用约 4.7 GB，JSON 指令解析首 token 延迟约 1.5-3 秒。

### 注意事项

- **离线模式下以下功能不可用**：
  - 截图分析（多模态视觉）
  - 在线 API 设置
  - 在线地图底图（如 Google Satellite、ESRI 等 XYZ 瓦片服务）
- **首次加载模型有启动延时**：首次发送指令时需加载模型到内存，约 5-10 秒。
- 模型路径 `OLLAMA_MODELS` 必须设为无中文路径（如 `D:\model`），避免编码异常。

---

## 功能

### 自然语言指令（22 个）

全部支持中/日/英三语输入，基于 JSON 指令规范 + 三层容错解析。

#### 基础地图操作

| 指令 | 说明 |
|------|------|
| `zoom_in` | 放大地图 |
| `zoom_out` | 缩小地图 |
| `reset_view` | 重置视图为全图范围 |
| `export_map` | 导出地图为 PNG/JPG/PDF |

#### 图层管理

| 指令 | 说明 |
|------|------|
| `load_layer` | 加载图层文件（SHP/GeoJSON/TIF/GPKG） |
| `remove_layer` | 移除指定图层 |
| `list_layers` | 列出当前所有图层 |
| `zoom_to_layer` | 缩放到指定图层范围 |

#### 坐标系

| 指令 | 说明 |
|------|------|
| `set_crs` | 设置图层/项目坐标系（EPSG 代码） |
| `show_crs` | 查看当前坐标系信息 |

#### 矢量编辑

| 指令 | 说明 |
|------|------|
| `toggle_editing` | 切换矢量图层编辑状态（开启/保存并关闭） |

#### 要素操作

| 指令 | 说明 |
|------|------|
| `select_feature` | 要素选择（点选/框选/SQL 表达式选择/清除选择） |
| `identify_feature` | 识别要素属性（点击查询） |
| `filter_layer` | 按 SQL 表达式过滤图层要素 |

#### 样式美化

| 指令 | 说明 |
|------|------|
| `set_layer_style` | 设置图层渲染样式（单一/分类/分级，自动适配几何类型） |
| `load_layer_style` | 加载 QML 样式文件 |
| `add_label` | 添加/隐藏要素文字标注 |

#### 数据分析

| 指令 | 说明 |
|------|------|
| `export_attribute` | 导出属性表为 CSV |
| `layer_statistic` | 图层数据统计（数量/最大/最小/均值/求和） |
| `create_buffer` | 缓冲区分析（生成新图层） |
| `open_field_manager` | 打开字段管理器 |

#### 知识问答

| 指令 | 说明 |
|------|------|
| `answer` | GIS 知识问答（空间索引、投影、拓扑等） |

### 工具栏（5 个按钮）

| 按钮 | 功能 |
|------|------|
| 平移 | 拖拽平移地图（默认激活） |
| 放大 | 点击或框选放大地图 |
| 缩小 | 点击缩小地图 |
| 选择 | 要素选择（框选 / 点选） |
| 编辑 | 切换当前矢量图层编辑状态 |

### 菜单栏

**文件菜单**：新建项目 / 关闭项目 / 保存项目 / 另存为 / 导入导出（导出地图图片、导出图层、导入图层）/ 导出属性表 / 加载样式文件 / API 设置 / 退出

**视图菜单**：代码预览 / 多模态截图分析 / 重置 AI 上下文 / 全图显示 / 标注开关

**工具菜单**：提示词 Agent / 一键瘦身 / 字段管理器 / 要素统计 / 缓冲区分析 / 批量样式设置

**帮助菜单**：查看日志 / 关于 AIQGIS

### 图层树右键菜单（12 项）

- 查看属性表
- 缩放到图层
- 开启/关闭编辑（矢量图层，状态可跟随）
- 图层样式设置（矢量 & 栅格）
- 显示/隐藏标注（矢量图层，状态可跟随）
- 设置属性过滤
- 字段管理
- 导出属性表
- 要素统计
- 重命名图层
- 复制图层
- 移除图层

### 离线模式专属特性

- 红/绿状态标签指示当前模式
- 进度条指示模型推理状态
- 截图分析 / 多模态 / 在线 API 设置自动禁用
- 快捷流程按钮（地籍、水文、批量裁剪、属性批量、专题图）

### 一键瘦身 & 提示词 Agent

- **一键瘦身**：清理项目中未使用的样式、冗余字段和临时数据
- **提示词 Agent**：独立提示词调试与优化工具，支持多轮对话和上下文管理

### 项目管理

- 新建 / 打开 / 保存 / 另存 QGIS 项目（`.qgz`）
- 导入 / 导出图层数据
- 拖放加载图层文件

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 语言 | Python 3.x |
| GUI 框架 | PyQt5 |
| GIS 引擎 | QGIS Python API (PyQGIS 3.44) |
| 在线推理 | OpenAI 兼容 API（DeepSeek / DashScope Qwen-Plus） |
| 离线推理 | Ollama 本地引擎 + Qwen2.5/Qwen3 7B |
| 指令解析 | JSON 指令规范 + 三层容错（模板匹配 → 正则提取 → 原始 JSON） |
| 国际化 | 中 / 日 / 英三语完整支持 |

---

## 目录结构

```
AIQGIS_APP/
├── 启动.bat                # 启动脚本
├── README.md
├── aiqgis_config.json       # 用户配置（模式/语言/API 密钥）
├── qgis-portable/           # QGIS 3.44.9 便携版（2.18 GB）
├── src/
│   ├── main.py              # 程序入口
│   ├── core/                # 核心模块
│   │   ├── ai_config.py     # AI 端点配置
│   │   ├── ai_worker.py     # AI 推理调度
│   │   ├── config_manager.py # 配置持久化管理
│   │   ├── instruction_mapper.py # 多语言指令映射（22 个 action）
│   │   ├── local_llm.py     # 本地 Ollama 推理引擎
│   │   ├── memory_bridge.py # 上下文记忆管理
│   │   └── multimodal/      # 多模态（截图分析）
│   ├── knowledge/           # GIS 知识库
│   │   └── gis_reference.py # PyQGIS API 参考分片
│   ├── skills/              # Skill-based Agent 技能
│   │   ├── buffer_skill.py
│   │   ├── inspect_skill.py
│   │   ├── intersect_skill.py
│   │   ├── layer_control_skill.py
│   │   ├── map_export_skill.py
│   │   └── style_layer_skill.py
│   ├── prompt_agent/        # 提示词 Agent 工具
│   │   ├── config.py
│   │   ├── refiner.py
│   │   └── widget.py
│   ├── i18n/                # 国际化翻译文件
│   │   ├── zh.json          # 中文
│   │   ├── ja.json          # 日文
│   │   └── en.json          # 英文
│   └── ui/                  # PyQt5 界面
│       ├── main_window.py   # 主窗口（菜单/工具栏/右键菜单）
│       └── api_config_dialog.py # API 配置对话框
├── tests/                   # 单元测试
└── temp/                    # 临时文件
```
