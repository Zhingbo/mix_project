"""
通过阿里云测试 DeepSeek v4-pro
"""
import os
from openai import OpenAI

ALI_API_KEY = os.getenv("DASHSCOPE_API_KEY")
ALI_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

print("="*60)
print("📋 通过阿里云测试 DeepSeek 模型")
print("="*60)

client = OpenAI(api_key=ALI_API_KEY, base_url=ALI_BASE_URL)

# 阿里云提供的 DeepSeek 模型
models = [
    "deepseek-v4-pro",
    "deepseek-v4.1-flash",
    "vanchin/deepseek-v3.1-terminus",
    "vanchin/deepseek-r1",
]

for model in models:
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "用一句话介绍你自己"}],
            max_tokens=50
        )
        print(f"\n✅ {model}")
        print(f"   回复: {response.choices[0].message.content}")
    except Exception as e:
        print(f"\n❌ {model}: {str(e)[:100]}")

print("\n" + "="*60)
print("📋 测试阿里云 Qwen 模型")
print("="*60)

# 推荐的 Qwen 模型
qwen_models = [
    "qwen3.5-plus-2026-04-20",
    "qwen3.6-max-preview",
    "qwen-max-2025-01-25",
]

for model in qwen_models:
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "计算 123 + 456 = ?"}],
            max_tokens=20
        )
        print(f"\n✅ {model}")
        print(f"   回复: {response.choices[0].message.content}")
    except Exception as e:
        print(f"\n❌ {model}: {str(e)[:100]}")

print("\n" + "="*60)
print("🎯 最终推荐")
print("="*60)
print("\n方案一 (通过阿里云):")
print("  DeepSeek: 'deepseek-chat' → 'deepseek-v4-pro' (阿里云端点)")
print("  阿里云: 'qwen-plus' → 'qwen3.5-plus-2026-04-20'")
print("\n方案二 (最新最强):")
print("  DeepSeek: 'deepseek-chat' → 'deepseek-v4-pro' (阿里云端点)")
print("  阿里云: 'qwen-plus' → 'qwen3.6-max-preview'")
