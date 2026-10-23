"""
测试新模型是否可用
1. DeepSeek v4-pro
2. 阿里云 qwen-plus 3.2
"""
from openai import OpenAI
import os

# ==================== 配置 ====================
# DeepSeek 配置
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"  # 或者是兼容的base_url

# 阿里云配置
ALI_API_KEY = os.getenv("DASHSCOPE_API_KEY")
ALI_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

def test_deepseek_v4_pro():
    """测试 DeepSeek v4-pro"""
    print("\n" + "="*50)
    print("测试 DeepSeek v4-pro")
    print("="*50)
    
    try:
        # 尝试不同的 base_url
        base_urls = [
            "https://api.deepseek.com",
            "https://api.deepseek.com/v1",
        ]
        
        for base_url in base_urls:
            print(f"\n尝试 base_url: {base_url}")
            client = OpenAI(
                api_key=DEEPSEEK_API_KEY,
                base_url=base_url
            )
            
            response = client.chat.completions.create(
                model="deepseek-v4-pro",  # 或者是 deepseek-chat
                messages=[
                    {"role": "user", "content": "你好，请用一句话介绍你自己"}
                ],
                max_tokens=50
            )
            
            print(f"✅ 成功! 回复: {response.choices[0].message.content}")
            return True, base_url
            
    except Exception as e:
        print(f"❌ 失败: {str(e)}")
        
    # 尝试其他可能的模型名称
    print("\n尝试其他模型名称...")
    model_names = ["deepseek-v4-pro", "deepseek-v4", "deepseek-chat", "deepseek-reasoner"]
    
    for model in model_names:
        try:
            client = OpenAI(api_key=DEEPSEEK_API_KEY)
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=10
            )
            print(f"✅ 模型 '{model}' 可用!")
            return True, model
        except Exception as e:
            print(f"❌ 模型 '{model}': {str(e)[:100]}")
    
    return False, None

def test_ali_qwen_32():
    """测试阿里云 qwen-plus 3.2"""
    print("\n" + "="*50)
    print("测试阿里云 Qwen 3.2")
    print("="*50)
    
    # 可能的模型名称
    model_names = [
        "qwen-plus-3.2",
        "qwen-plus-32",
        "qwen-plus-v3.2",
        "qwen-plus-4.0",
        "qwen-max-2025-01-25",
        "qwen-max-latest",
        "qwen-plus-latest",
        "qwen-turbo-latest",
        "qwen-omni-4.0",
    ]
    
    client = OpenAI(
        api_key=ALI_API_KEY,
        base_url=ALI_BASE_URL
    )
    
    for model in model_names:
        try:
            print(f"\n尝试模型: {model}")
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "user", "content": "你好，请用一句话介绍你自己"}
                ],
                max_tokens=50
            )
            print(f"✅ 成功! 回复: {response.choices[0].message.content}")
            return True, model
        except Exception as e:
            print(f"❌ 失败: {str(e)[:150]}")
    
    return False, None

def list_available_models():
    """列出可用的模型列表（如果API支持）"""
    print("\n" + "="*50)
    print("尝试列出可用模型")
    print("="*50)
    
    # 阿里云
    try:
        client = OpenAI(api_key=ALI_API_KEY, base_url=ALI_BASE_URL)
        models = client.models.list()
        print("\n阿里云可用模型:")
        for m in models.data[:20]:  # 只显示前20个
            print(f"  - {m.id}")
    except Exception as e:
        print(f"阿里云模型列表获取失败: {str(e)[:100]}")
    
    # DeepSeek
    try:
        client = OpenAI(api_key=DEEPSEEK_API_KEY)
        models = client.models.list()
        print("\nDeepSeek可用模型:")
        for m in models.data[:20]:
            print(f"  - {m.id}")
    except Exception as e:
        print(f"DeepSeek模型列表获取失败: {str(e)[:100]}")

if __name__ == "__main__":
    print("🧪 开始测试新模型...")
    
    # 首先尝试列出可用模型
    list_available_models()
    
    # 测试 DeepSeek
    deepseek_ok, deepseek_model = test_deepseek_v4_pro()
    
    # 测试阿里云
    ali_ok, ali_model = test_ali_qwen_32()
    
    # 总结
    print("\n" + "="*50)
    print("📊 测试总结")
    print("="*50)
    print(f"DeepSeek: {'✅ 可用' if deepseek_ok else '❌ 不可用'} - {deepseek_model}")
    print(f"阿里云Qwen: {'✅ 可用' if ali_ok else '❌ 不可用'} - {ali_model}")
    
    if deepseek_ok or ali_ok:
        print("\n建议配置:")
        if deepseek_ok:
            print(f"  DEEPSEEK_MODEL = \"{deepseek_model}\"")
        if ali_ok:
            print(f"  ALI_MODEL = \"{ali_model}\"")
