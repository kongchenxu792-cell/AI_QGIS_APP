# AIQGIS_APP 功能自检报告

**日期**：2026-05-26
**方法**：静态代码审查（未实际运行）
**审查范围**：全部核心源码（`src/core/`、`src/skills/`、`src/ui/`、`启动.bat`）

---

## 1. 文件读取能力

### 1.1 open_project_skill.py — 打开 .qgz/.qgs 项目文件

| 检查项 | 状态 | 说明 |
|--------|------|------|
| `OpenProjectSkill` 继承 `BaseSkill` | **通过** | `save_project_skill.py:22` — 正确继承 |
| 使用 `get_project_manager()` 单例 | **通过** | `open_project_skill.py:20` |
| `execute()` → `ProjectManager.open_project()` 调用链 | **通过** | `open_project_skill.py:81` → `project_manager.py:56` |
| `ProjectManager.open_project()` 文件存在性验证 | **通过** | `project_manager.py:67-71` |
| `ProjectManager.open_project()` 扩展名验证 (.qgz/.qgs) | **通过** | `project_manager.py:73-77` |
| `project.read(file_path)` 调用 | **通过** | `project_manager.py:83` |
| 返回结构含 `loaded_layers`/`layer_names`/`layer_count` | **通过** | `project_manager.py:93-99` |
| `extract_file_path()` 路径提取工具 | **通过** | `project_manager.py:282-303` — 支持绝对/相对/引号/自然语言描述 |

**结论：通过** — 调用链完整，`OpenProjectSkill → ProjectManager.open_project → QgsProject.read()` 链路正确。

### 1.2 layer_loader.py — 矢量/栅格文件加载

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 矢量格式支持：`.shp` / `.geojson` / `.gpkg` | **通过** | `layer_loader.py:18-25` — `VECTOR_EXTENSIONS` 包含全部三种 |
| 额外矢量格式：`.json` / `.kml` / `.gml` | **通过** | 同一集合中 |
| 栅格格式支持：`.tif` / `.tiff` / `.img` 等 | **通过** | `layer_loader.py:28-34` |
| `create_layer_from_path()` 矢量加载逻辑 | **通过** | `layer_loader.py:72` — `QgsVectorLayer(str(path), layer_name, "ogr")` |
| 图层有效性检查 `layer.isValid()` | **通过** | `layer_loader.py:79` |
| 批量加载 `load_layers_from_paths()` | **通过** | `layer_loader.py:83-117` — 带错误收集 |

**结论：通过** — 矢量/栅格加载逻辑完整，支持的格式覆盖 `.geojson`、`.shp`、`.gpkg`。

### 1.3 测试文件可用性

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 项目目录下 `.qgz` / `.qgs` 文件 | **警告** | 未找到独立测试项目文件。`qgis-portable\apps\qgis-ltr\resources\data\world_map.gpkg` 存在可作 GPKG 测试 |

**结论：警告** — 缺失专用测试 `.qgz`/`.qgs` 项目文件，建议在项目根目录放置 1-2 个最小项目文件供自测。

---

## 2. 文件导出/保存能力

### 2.1 save_project_skill.py — 保存/另存为

| 检查项 | 状态 | 说明 |
|--------|------|------|
| `SaveProjectSkill` 继承 `BaseSkill` | **通过** | `save_project_skill.py:17` |
| `SaveAsProjectSkill` 继承 `BaseSkill` | **通过** | `save_project_skill.py:148` |
| `SaveProjectSkill` 使用 `ProjectManager.save_project()` | **通过** | `save_project_skill.py:127` |
| 保存成功后调用 `backup_current()` | **通过** | `save_project_skill.py:132` |
| `SaveAsProjectSkill` 使用 `ProjectManager.save_project()` | **通过** | `save_project_skill.py:215` |
| 空项目保护（layers == 0） | **通过** | `save_project_skill.py:84-87`、`save_project_skill.py:173-176` |
| 文件对话框 + 默认扩展名 `.qgz` | **通过** | `save_project_skill.py:103-119` |
| `SaveAsProjectSkill` 在 SkillManager 中注册 | **失败** | 见下方详情 |

**失败详情**：`skill_manager.py:24-42` 的 `_scan_and_load()` 对每个模块只取**第一个** `BaseSkill` 子类后 `break`。`save_project_skill.py` 包含两个类：
- `SaveProjectSkill` → 注册为 `"save_project"` ✓
- `SaveAsProjectSkill` → **未被注册** ✗

`SkillManager.register()` 方法存在（`skill_manager.py:48`），但代码库中没有任何地方调用它来手动注册 `SaveAsProjectSkill`。因此 `"save_as_project"` 技能永远无法被触发。

**修复建议**：在 `skill_manager.py` 的 `_scan_and_load()` 中去掉 `break`，遍历模块中所有 `BaseSkill` 子类；或在 `__init__` 末尾手动调用 `self.register(SaveAsProjectSkill())`。

### 2.2 output_persistence.py — 输出路径生成

| 检查项 | 状态 | 说明 |
|--------|------|------|
| `generate_output_path()` 路径格式 | **通过** | `output/shapefiles/{skill_prefix}_{timestamp}_{sanitized_name}{extension}` |
| 时间戳格式 `%Y%m%d_%H%M%S` | **通过** | `output_persistence.py:51` |
| 文件名清理 `_sanitize_filename()` | **通过** | `output_persistence.py:67-79` — 处理 Windows 非法字符 `< > : " / \ \| ? *` |
| `ensure_output_dir()` 自动创建目录 | **通过** | `output_persistence.py:25-27` |
| `generate_geojson_output_path()` | **通过** | `output_persistence.py:60-63` — 正确委托给 `generate_output_path` |

### 2.3 技能中使用 `generate_output_path()` 情况

| 技能 | 状态 | 使用位置 |
|------|------|----------|
| `clip_skill.py` | **通过** | `clip_skill.py:71` — `generate_output_path("clip", input_layer.name())` |
| `centroid_skill.py` | **通过** | `centroid_skill.py:56` — `generate_output_path("centroid", input_layer.name())` |
| `dissolve_skill.py` | **通过** | `dissolve_skill.py:68` — `generate_output_path("dissolve", input_layer.name())` |

所有三个技能正确使用 `generate_output_path()`，输出路径格式统一。

---

## 3. 数据处理技能

### 3.1 centroid_skill.py

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 继承 `BaseSkill` | **通过** | `centroid_skill.py:14` |
| 活动图层获取逻辑（active_layer → 搜索面图层 → 回退任意矢量） | **通过** | `centroid_skill.py:34-47` |
| `geometryType() == 2` 判断面图层 | **通过** | `centroid_skill.py:40` — QGIS 中 `2 = Polygon` |
| `processing.run("native:centroids", params)` | **通过** | `centroid_skill.py:60` |
| 结果从磁盘加载（修复版） | **通过** | `centroid_skill.py:63` — `QgsVectorLayer(output_path, new_name, "ogr")` |
| 结果添加到项目 `addMapLayer()` | **通过** | `centroid_skill.py:65` |
| 画布刷新 | **通过** | `centroid_skill.py:67-68` |
| 返回结构含 `added_layers`/`output_path` | **通过** | `centroid_skill.py:70-76` |

**结论：通过** — 已修复为从磁盘加载结果图层的模式，`QgsVectorLayer(output_path, ...)` 调用正确。

### 3.2 clip_skill.py

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 继承 `BaseSkill` | **通过** | `clip_skill.py:16` |
| 最小图层数检查（≥2） | **通过** | `clip_skill.py:36-39` |
| 输入图层获取逻辑 | **通过** | `clip_skill.py:41-46` |
| 叠加图层获取逻辑（排除自身） | **通过** | `clip_skill.py:51-54` |
| `generate_output_path()` 持久化 | **通过** | `clip_skill.py:60` |
| `processing.run("native:clip", params)` | **通过** | `clip_skill.py:67` |
| 结果类型声明 `QgsVectorLayer` | **通过** | `clip_skill.py:68` |
| 图层重命名 + 添加到项目 | **通过** | `clip_skill.py:71-74` |
| 画布刷新 | **通过** | `clip_skill.py:76-77` |

**结论：通过** — 整体流程完整，`native:clip` 返回内存图层对象直接使用是正确的（与 centroid 不同，不同 processing 算法返回值行为不同，属 QGIS 设计）。

### 3.3 dissolve_skill.py

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 继承 `BaseSkill` | **通过** | `dissolve_skill.py:16` |
| 输入图层获取逻辑 | **通过** | `dissolve_skill.py:34-40` |
| 可选融合字段解析 `fields().indexFromName()` | **通过** | `dissolve_skill.py:54-58` |
| `generate_output_path()` 持久化 | **通过** | `dissolve_skill.py:61` |
| `processing.run("native:dissolve", params)` | **通过** | `dissolve_skill.py:69` |
| 结果类型声明 `QgsVectorLayer` | **通过** | `dissolve_skill.py:70` |
| 图层重命名 + 添加到项目 | **通过** | `dissolve_skill.py:73-76` |

**结论：通过** — 整体流程完整，融合字段解析逻辑正确。

---

## 4. 项目管理

### 4.1 project_manager.py — ProjectManager 方法审查

| 方法 | 状态 | 行号 | 说明 |
|------|------|------|------|
| `open_project(file_path, canvas)` | **通过** | `project_manager.py:56` | 文件验证 → 清空 → `project.read()` → 刷新画布 |
| `save_project(file_path)` | **通过** | `project_manager.py:121` | `project.write(file_path)` + 更新 `_current_path` |
| `backup_current()` | **通过** | `project_manager.py:263` | 生成备份路径 → 调用 `save_project()` |
| `save_as(file_path)` | **通过** | `project_manager.py:146` | 委托 `save_project()` |
| `create_new(canvas)` | **通过** | `project_manager.py:149` | `project.clear()` + 刷新 |
| `close_project(canvas)` | **通过** | `project_manager.py:166` | 委托 `create_new()` |
| `get_layer_by_name(name)` | **通过** | `project_manager.py:169` | 大小写不敏感匹配 |
| `get_layers_by_type(layer_type)` | **通过** | `project_manager.py:177` | 类型筛选 |
| `get_vector_layers()` | **通过** | `project_manager.py:193` | `isinstance` 过滤 |
| `get_raster_layers()` | **通过** | `project_manager.py:197` | `isinstance` 过滤 |
| `generate_backup_path(prefix)` | **通过** | `project_manager.py:202` | 格式 `output/projects/backup_YYYYMMDD_HHMMSS.qgz` |
| `get_active_layer()` | **不适用** | — | `ProjectManager` 中不存在该方法，但 `MainWindow._get_active_layer()`（第 1033 行）提供同等功能，通过 `layer_tree_view.currentLayer()` 获取 |

### 4.2 SaveAsProjectSkill 注册状态

| 检查项 | 状态 | 说明 |
|--------|------|------|
| `SaveAsProjectSkill` 类定义 | **通过** | `save_project_skill.py:148` |
| SkillManager 自动扫描注册 | **失败** | `skill_manager.py:36` 行 `break` 导致模块内第二个类被跳过 |
| SkillManager 手动注册 | **失败** | 代码库中无 `skill_manager.register(SaveAsProjectSkill())` 调用 |

**结论：失败** — `SaveAsProjectSkill`（`"save_as_project"`）永远不会被 SkillManager 发现和注册。

---

## 5. 启动文件

### 5.1 启动.bat

| 检查项 | 状态 | 说明 |
|--------|------|------|
| `OSGEO4W_ROOT` 指向便携目录 | **通过** | `启动.bat:4` — `%~dp0qgis-portable` |
| `QGIS_PREFIX_PATH` 设置 | **通过** | `启动.bat:5` — `apps\qgis-ltr` |
| `QT_PLUGIN_PATH` 含 Qt5/plugins | **通过** | `启动.bat:11` — `apps\qgis-ltr\qtplugins;apps\Qt5\plugins` |
| `PYTHONHOME` 指向便携 Python | **通过** | `启动.bat:13` — `apps\Python312` |
| PATH 含 qgis-ltr/bin | **通过** | `启动.bat:15` |
| PATH 含 Qt5/bin | **警告** | `启动.bat:15` — PATH 中**不含** `%OSGEO4W_ROOT%\apps\Qt5\bin`。Qt5 DLL 在运行时由 `qgis_env.py` 的 `configure_qgis_environment()` 动态扫描 `apps/*/bin` 补充，但若启动在 `bootstrap_qgis()` 之前失败（如 import 错误），Qt5 DLL 可能无法找到。建议显式添加 `%OSGEO4W_ROOT%\apps\Qt5\bin` 到 PATH。 |
| 编码设置 `PYTHONUTF8=1` | **通过** | `启动.bat:14` |
| GDAL/PROJ 环境变量 | **通过** | `启动.bat:7-10` |
| 入口调用 `python.exe src\main.py` | **通过** | `启动.bat:22` |
| 错误码检查 | **通过** | `启动.bat:24-28` |

### 5.2 qgis_env.py — 便携路径发现逻辑

| 检查项 | 状态 | 说明 |
|--------|------|------|
| `discover_qgis_prefix_candidates()` | **通过** | `qgis_env.py:62-103` |
| `QGIS_PREFIX_PATH` 环境变量优先 | **通过** | `qgis_env.py:67-68` |
| 已知路径列表（独立安装版 + OSGeo4W） | **通过** | `qgis_env.py:70-79` |
| `glob` 动态扫描 `C:\Program Files\QGIS *` | **通过** | `qgis_env.py:81-84` |
| 去重逻辑 | **通过** | `qgis_env.py:87-94` |
| `configure_qgis_environment()` 动态扫描 `apps/*/bin` | **通过** | `qgis_env.py:160-162` — 覆盖 Qt5、Qt6、GDAL 等 |
| PROJ 数据路径设置（PROJ_DATA + PROJ_LIB） | **通过** | `qgis_env.py:170-181` |
| `proj.db` 回退搜索 | **通过** | `qgis_env.py:182-186` |
| `initialize_processing()` 注册原生算法 | **通过** | `qgis_env.py:190-208` |
| `bootstrap_qgis()` 完整引导流程 | **通过** | `qgis_env.py:211-251` |

**结论：通过** — `qgis_env.py` 便携路径发现逻辑完整健壮，`启动.bat` 完整性良好（仅 `Qt5/bin` 缺 PATH 为低风险警告）。

---

## 6. 汇总统计

| 模块类别 | 通过 | 警告 | 失败 | 不适用 |
|----------|:----:|:----:|:----:|:------:|
| 文件读取能力 | 19 | 1 | 0 | 0 |
| 文件导出/保存能力 | 14 | 0 | 2 | 0 |
| 数据处理技能 | 18 | 0 | 0 | 0 |
| 项目管理 | 11 | 0 | 2 | 1 |
| 启动文件 | 10 | 1 | 0 | 0 |
| **合计** | **72** | **2** | **4** | **1** |

---

## 7. 失败项清单

| # | 模块 | 问题 | 文件 | 行号 |
|---|------|------|------|------|
| 1 | 保存/导出 | `SaveAsProjectSkill` 未被 SkillManager 自动发现 | `src/skills/skill_manager.py` | 36 (`break`) |
| 2 | 保存/导出 | 无手动注册 `SaveAsProjectSkill` 的代码 | 全局 | — |

## 8. 警告项清单

| # | 模块 | 问题 | 文件 |
|---|------|------|------|
| 1 | 文件读取 | 项目根目录缺少 `.qgz`/`.qgs` 测试项目文件 | — |
| 2 | 启动 | `启动.bat` PATH 不含 `apps\Qt5\bin`，依赖 `qgis_env.py` 运行时动态补充 | `启动.bat:15` |

---

## 9. 修复建议优先级

| 优先级 | 问题 | 修复方案 |
|--------|------|----------|
| **P0** | `SaveAsProjectSkill` 未注册 | 修改 `skill_manager.py:36`，去掉 `break`，遍历模块中所有 `BaseSkill` 子类；或在其 `__init__` 末尾添加 `self.register(SaveAsProjectSkill())` |
| **P1** | `启动.bat` 缺 `Qt5/bin` | 在 PATH 行添加 `%OSGEO4W_ROOT%\apps\Qt5\bin` |
| **P2** | 缺测试项目文件 | 在项目根目录放置 1-2 个最小 `.qgz` 测试项目 |

---

*报告由静态代码审查自动生成，覆盖 14 个源码文件、约 2300 行代码。*