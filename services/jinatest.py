import os
import asyncio
import aiohttp
import json
from urllib.parse import quote

async def test_jina_api():
    """测试Jina API的直接调用"""
    
    # 使用您配置文件中的API密钥
    # 更新API密钥为新密钥
    api_key = os.getenv("JINA_API_KEY_TEST")
    base_url = "https://s.jina.ai/"
    
    # 测试查询
    test_queries = [
        "人工智能",  # 普通搜索
        "人工智能 site:baidu.com",  # 指定网站搜索
        "人工智能 site:zhihu.com",  # 另一个网站
    ]
    
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Accept': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    async with aiohttp.ClientSession() as session:
        for query in test_queries:
            print(f"\n=== 测试查询: {query} ===")
            
            try:
                encoded_query = quote(query)
                search_url = f"{base_url}{encoded_query}"
                print(f"请求URL: {search_url}")
                
                async with session.get(search_url, headers=headers, timeout=30) as response:
                    print(f"响应状态码: {response.status}")
                    
                    response_text = await response.text()
                    print(f"响应长度: {len(response_text)} 字符")
                    
                    # 打印前1000个字符
                    print(f"响应内容预览: {response_text[:1000]}")
                    
                    # 尝试解析JSON
                    try:
                        data = json.loads(response_text)
                        print(f"JSON解析成功，类型: {type(data)}")
                        if isinstance(data, dict):
                            print(f"JSON键: {list(data.keys())}")
                        elif isinstance(data, list):
                            print(f"JSON列表长度: {len(data)}")
                    except json.JSONDecodeError:
                        print("响应不是有效的JSON格式")
                        
            except Exception as e:
                print(f"请求失败: {e}")
            
            print("-" * 50)

if __name__ == "__main__":
    asyncio.run(test_jina_api())


# 添加错误处理和重试机制
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def test_jina_api_with_retry():
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        status_forcelist=[429, 500, 502, 503, 504],
        method_whitelist=["HEAD", "GET", "OPTIONS"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    # 使用正确的 Jina API 端点
    base_url = "https://r.jina.ai/"  # 或者使用配置文件中的URL
    
    try:
        response = session.get(base_url + query, timeout=30)
        return response
    except Exception as e:
        print(f"请求失败: {e}")
        return None