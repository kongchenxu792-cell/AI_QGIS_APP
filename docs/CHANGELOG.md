# AIQGIS 变更日志

## [1.4.1] — 2026-06-06

### 热修复：GC 误杀暂存层导致 C++ 野指针崩溃

盲测触发 `wrapped C/C++ object of type QgsVectorLayer has been deleted` 致命崩溃。

**根因**：Worker 线程退出后，QGIS 内部清理该线程创建的"孤儿" QgsVectorLayer（未挂载到 QgsProject 的图层）。`_deferred_layers` 中的 Python 包装器仍存活，但底层 C++ 对象已被 QGIS 的线程级生命周期管理销毁。主线程随后通过信号收到图层列表并尝试 `lyr.id()` 时触发野指针错误。

**修复（Pain 5：线程退出前注入）**：

| 机制 | 内容 |
|------|------|
| Pain 5 核心 | Worker 的 `finally` 块中，**先**通过 `original_add` 将 `_deferred_layers` 直接注入 QgsProject，**后**恢复 monkey-patch。C++ 对象挂载到 QgsProject 后由其管理生命周期，线程退出不再影响 |
| Pain 3 v1.4.1 | `_gc_cleanup` 引入三级白名单（deferred ID / result ID / 名称兜底），防止 GC 误杀暂存层 |

- `sandbox_worker.py::run()` finally 块 — 新增 Pain 5 注入逻辑
- `sandbox_worker.py::_gc_cleanup(before, result)` — 新增 `result` 参数 + ID 白名单
- `spatial_analysis_skill.py::_collect_garbage` — 参数 `deferred_names` → `deferred_layers` + 同步 ID 白名单

## [1.4.0] — 2026-06-06

### 架构升级：四面防御系统 (Four-Sided Defense)

本次升级对 AI 生成代码执行引擎进行底层重写，引入沙箱隔离线程 + 三层安全网。

#### 新增

- **`SandboxExecutionWorker(QThread)`**：独立工作线程容器，确保 AI 代码执行完全脱离 UI 主线程，根除 GIL 争用导致的界面冻结
- **Monkey-patch 图层拦截**：运行时拦截 `QgsProject.instance().addMapLayer`，将 AI 代码创建的图层暂存入 `_deferred_layers`，通过 `finished` 信号安全传递回主线程加载，解决 PyQt 跨线程图层注册崩溃
- **`SandboxStdoutBridge(io.StringIO)`**：替换 `sys.stdout`，逐行回调 `stdout_line` 信号，实现沙箱内 `print()` 输出到 AI 控制台实时回显
- **三次自愈反思管线**：`fix_needed` 信号携带 `{broken_code, error_line, exception_type, exception_msg, retry_count}`，主线程 `_on_sandbox_fix_needed` 编排最多 3 次 LLM 回炉修正（temperature=0.05），`HeatmapRenderSuccessException` 视为成功直接返回
- **隐式 CRS 防御**：`_crs_defense()` 以 active_layer 坐标系为准，内存中对齐所有传入 `layers_by_name` 的图层 CRS，杜绝因坐标系不对齐导致的 QGIS C++ 层崩溃
- **临时图层快照 GC**：执行前 `_snapshot_map_layers()` 记录快照，执行后 `_gc_cleanup()` 对比卸载中间图层（保护 deferred 和结果图层），GC 异常独立 try-except 不阻断主流程

#### 修改

- **`ai_worker.py`**：新增 `request_code_fix()` 和 `_build_fix_mode_prompt()`，支持自愈重试的 LLM 修正请求
- **`spatial_analysis_skill.py`**：新增 `_enforce_crs_alignment` / `_snapshot_map_layers` / `_collect_garbage` 三个静态方法；`execute()` 改用 `SandboxExecutionWorker` + `QEventLoop` 同步等待
- **`main_window.py`**：新增 `_launch_sandbox_worker()` 和 `_create_and_start_worker()`；新增 5 个信号槽（`_on_sandbox_progress` / `_on_sandbox_stdout` / `_on_sandbox_finished` / `_on_sandbox_error` / `_on_sandbox_fix_needed`）；`_on_spatial_code_response` 和 `_fallback_legacy_execution` 改为异步 Worker 模式

#### 移除

- `_execute_ai_code` 死代码及主线程 `exec()` 调用路径

#### 修复

- Worker 切换时 `_create_and_start_worker` 先断开旧 Worker 全部信号 → `quit()` + `wait(500)` → `deleteLater()`，杜绝后台悬挂 QThread 残留
- `_gc_cleanup` 崩溃不会吞噬 `finished` 信号，`_deferred_layers` 安全送达主线程
