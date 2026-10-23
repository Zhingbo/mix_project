"""
测试产业链自动化处理 API

用法:
    python test_pipeline.py <产业链名称>

示例:
    python test_pipeline.py 氢能产业
"""

import requests
import json
import sys
import time

# API 配置
BASE_URL = "http://localhost:8001"
USERNAME = "admin"
PASSWORD = "admin123"

def login():
    """登录获取 token"""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": USERNAME, "password": PASSWORD}
    )
    if response.status_code == 200:
        data = response.json()
        if data.get("status") == "success":
            return data["data"].get("access_token")
    print(f"登录失败: {response.text}")
    return None

def get_industries(token):
    """获取产业链列表"""
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"{BASE_URL}/api/pipeline/industries", headers=headers)
    return response.json()

def get_industry_info(token, industry_name):
    """获取产业链信息"""
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"{BASE_URL}/api/pipeline/industry/{industry_name}/info", headers=headers)
    return response.json()

def start_process(token, industry_name):
    """启动处理流程并接收 SSE 消息"""
    headers = {"Authorization": f"Bearer {token}"}

    print(f"\n启动产业链处理: {industry_name}")
    print("="*60)

    response = requests.post(
        f"{BASE_URL}/api/pipeline/process",
        headers=headers,
        json={"industry_name": industry_name},
        stream=True
    )

    if response.status_code != 200:
        print(f"启动失败: {response.text}")
        return

    print("开始接收处理进度...\n")

    for line in response.iter_lines():
        if line:
            line = line.decode('utf-8')
            if line.startswith('data: '):
                data = line[6:]  # 移除 'data: ' 前缀
                try:
                    message = json.loads(data)
                    msg_type = message.get('type', 'unknown')
                    content = message.get('content', '')

                    # 根据类型格式化输出
                    if msg_type == 'start':
                        print(f"🚀 {content}")
                    elif msg_type == 'progress':
                        step_info = json.loads(content) if isinstance(content, str) else content
                        print(f"  [步骤 {step_info.get('step', '?')}] {step_info.get('step_name', '')}")
                        print(f"    {step_info.get('message', '')}")
                    elif msg_type == 'step_completed':
                        step_info = json.loads(content) if isinstance(content, str) else content
                        print(f"  ✓ 完成: {step_info.get('step_name', '')}")
                    elif msg_type == 'completed':
                        print(f"\n✅ {content}")
                        result = message.get('result', {})
                        if result:
                            print(f"   总步骤: {result.get('total_steps', 0)}")
                            print(f"   完成步骤: {result.get('completed', 0)}")
                        break
                    elif msg_type == 'error':
                        print(f"  ❌ 错误: {content}")
                        break
                    elif msg_type == 'heartbeat':
                        pass  # 忽略心跳
                    else:
                        print(f"  [{msg_type}] {content}")
                except json.JSONDecodeError:
                    print(f"  {data}")

def main():
    if len(sys.argv) < 2:
        print("用法: python test_pipeline.py <产业链名称>")
        print("\n示例:")
        print("  python test_pipeline.py 氢能产业")
        print("  python test_pipeline.py 生物医药产业")
        sys.exit(1)

    industry_name = sys.argv[1]

    print("="*60)
    print("产业链自动化处理 API 测试")
    print("="*60)

    # 登录
    print("\n1. 登录...")
    token = login()
    if not token:
        print("登录失败，退出")
        sys.exit(1)
    print("✓ 登录成功")

    # 获取产业链列表
    print("\n2. 获取产业链列表...")
    industries = get_industries(token)
    if industries.get("status") == "success":
        print(f"✓ 共 {len(industries.get('data', []))} 个产业链:")
        for ind in industries.get('data', [])[:10]:
            print(f"  - {ind}")
        if len(industries.get('data', [])) > 10:
            print(f"  ... 还有 {len(industries.get('data', [])) - 10} 个")

    # 获取产业链信息
    print(f"\n3. 获取产业链信息: {industry_name}...")
    info = get_industry_info(token, industry_name)
    if info.get("status") == "success":
        data = info.get('data', {})
        print(f"✓ 节点数量: {data.get('node_count', 0)}")
        print(f"✓ 白名单数量: {data.get('whitelist_count', 0)}")
        print(f"✓ 处理步骤: {data.get('steps', 0)}")
    else:
        print(f"✗ 获取失败: {info.get('message', '未知错误')}")
        sys.exit(1)

    # 启动处理流程
    start_process(token, industry_name)

    print("\n" + "="*60)
    print("测试完成")
    print("="*60)

if __name__ == "__main__":
    main()
