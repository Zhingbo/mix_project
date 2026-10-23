"""
精确测试新模型
"""
import os
from openai import OpenAI

# DeepSeek 配置
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# 阿里云配置
ALI_API_KEY = os.getenv("DASHSCOPE_API_KEY")
ALI_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

print("="*60)
print("📋 测试 DeepSeek v4-pro (官方)")
print("="*60)

client = OpenAI(api_key=DEEPSEEK_API_KEY)

# 测试 deepseek-v4-pro
models_to_test = [
    ("deepseek-v4-pro", "DeepSeek V4 Pro (官方)"),
    ("deepseek-chat", "DeepSeek Chat (当前使用)"),
]

for model, desc in models_to_test:
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "用3个词描述AI"}],
            max_tokens=20
        )
        print(f"\n✅ {desc}")
        print(f"   模型: {model}")
        print(f"   回复: {response.choices[0].message.content}")
    except Exception as e:
        print(f"\n❌ {desc}: {str(e)[:100]}")

print("\n" + "="*60)
print("📋 测试阿里云 Qwen 新版本")
print("="*60)

client = OpenAI(api_key=ALI_API_KEY, base_url=ALI_BASE_URL)

# 根据模型列表，测试这些模型
ali_models = [
    ("qwen3.5-plus-2026-04-20", "Qwen 3.5 Plus 最新版"),
    ("qwen3.6-max-preview", "Qwen 3.6 Max Preview"),
    ("qwen3.6-flash", "Qwen 3.6 Flash"),
    ("qwen-max-2025-01-25", "Qwen Max (已验证可用)"),
    ("qwen-plus", "Qwen Plus (当前使用)"),
]

for model, desc in ali_models:
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "用3个词描述AI"}],
            max_tokens=20
        )
        print(f"\n✅ {desc}")
        print(f"   模型: {model}")
        print(f"   回复: {response.choices[0].message.content}")
    except Exception as e:
        print(f"\n❌ {desc}: {str(e)[:80]}")

print("\n" + "="*60)
print("🎯 推荐配置")
print("="*60)
print("\n根据测试结果，建议替换:")
print("  DeepSeek: 'deepseek-chat' → 'deepseek-v4-pro'")
print("  阿里云: 'qwen-plus' → 'qwen3.5-plus-2026-04-20' 或 'qwen-max-2025-01-25'")
