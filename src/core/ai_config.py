"""OpenAI 兼容接口的 AI 端点配置。

全离线便携环境加固 (P0 任务2)：
- OFFLINE_MODE 控制是否允许发起网络请求
- API_KEY 置空后所有 AI 功能优雅降级，不弹窗不崩溃
- 需联网功能时由用户自行填入有效 API_KEY 并关闭 OFFLINE_MODE
"""

import os

#: 离线模式开关。True = 禁止所有网络请求，AI 功能优雅降级。
OFFLINE_MODE: bool = os.environ.get("AIQGIS_OFFLINE", "1") == "1"

#: API 密钥（从服务商控制台获取）。
#: 离线环境下留空即可，AI 功能将自动降级。
API_KEY = ""

#: 兼容 OpenAI 格式的接口基础 URL。
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

#: 模型名称标识符。
MODEL_NAME = "qwen-plus"