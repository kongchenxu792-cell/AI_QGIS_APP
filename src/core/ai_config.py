"""OpenAI 兼容接口的 AI 端点配置。

需在此填写 API 密钥、接口地址和模型名称。
"""

#: API 密钥（从服务商控制台获取）, 修改为你的 DeepSeek API Key 即可。
#: 获取地址: https://platform.deepseek.com/api_keys
API_KEY = "sk-8867df84a0a544d9abff32a124a79184"

#: 兼容 OpenAI 格式的接口基础 URL。
BASE_URL = "https://api.deepseek.com/v1"

#: 模型名称标识符。
MODEL_NAME = "deepseek-chat"