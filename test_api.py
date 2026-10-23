"""
测试产业链自动化处理 API
"""

import requests
import json
import time
import websocket

API_BASE_URL = "http://localhost:8000"
WS_BASE_URL = "ws://localhost:8000"


def test_get_industries():
    """测试获取产业链列表"""
    print("\n=== 测试: 获取产业链列表 ===")
    response = requests.get(f"{API_BASE_URL}/api/industries")
    print(f"状态码: {response.status_code}")
    print(f"响应: {json.dumps(response.json(), ensure_ascii=False, indent=2)}")
    return response.json()


def test_get_industry_info(industry_name):
    """测试获取产业链信息"""
    print(f"\n=== 测试: 获取产业链信息 ({industry_name}) ===")
    response = requests.get(f"{API_BASE_URL}/api/industry/{industry_name}/info")
    print(f"状态码: {response.status_code}")
    print(f"响应: {json.dumps(response.json(), ensure_ascii=False, indent=2)}")
    return response.json()


def test_start_process(industry_name):
    """测试启动处理流程"""
    print(f"\n=== 测试: 启动处理流程 ({industry_name}) ===")
    data = {"industry_name": industry_name}
    response = requests.post(f"{API_BASE_URL}/api/process", json=data)
    print(f"状态码: {response.status_code}")
    print(f"响应: {json.dumps(response.json(), ensure_ascii=False, indent=2)}")
    return response.json()


def test_get_task_status(task_id):
    """测试查询任务状态"""
    print(f"\n=== 测试: 查询任务状态 ({task_id}) ===")
    response = requests.get(f"{API_BASE_URL}/api/task/{task_id}")
    print(f"状态码: {response.status_code}")
    print(f"响应: {json.dumps(response.json(), ensure_ascii=False, indent=2)}")
    return response.json()


def test_websocket(task_id):
    """测试 WebSocket 连接"""
    print(f"\n=== 测试: WebSocket 连接 ({task_id}) ===")

    def on_message(ws, message):
        data = json.loads(message)
        msg_type = data.get('type', 'unknown')
        print(f"[WS] {msg_type}: {data.get('message', '')}")

    def on_error(ws, error):
        print(f"[WS] 错误: {error}")

    def on_close(ws, close_status_code, close_msg):
        print("[WS] 连接关闭")

    def on_open(ws):
        print("[WS] 连接已建立")

    ws = websocket.WebSocketApp(
        f"{WS_BASE_URL}/ws/{task_id}",
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )

    # 运行 WebSocket（阻塞）
    ws.run_forever()


def test_full_workflow(industry_name="氢能产业"):
    """测试完整工作流程"""
    print("\n" + "="*60)
    print("产业链自动化处理 API - 完整测试")
    print("="*60)

    # 1. 获取产业链列表
    industries = test_get_industries()

    # 2. 获取产业链信息
    info = test_get_industry_info(industry_name)

    if not info.get('exists'):
        print(f"\n错误: 产业链 '{industry_name}' 不存在")
        return

    # 3. 启动处理流程
    result = test_start_process(industry_name)
    task_id = result.get('task_id')

    if not task_id:
        print("\n错误: 未获取到 task_id")
        return

    print(f"\n任务 ID: {task_id}")
    print("等待处理完成...")

    # 4. 轮询查询任务状态
    max_wait = 600  # 最多等待 10 分钟
    start_time = time.time()

    while time.time() - start_time < max_wait:
        time.sleep(5)  # 每 5 秒查询一次

        task_status = test_get_task_status(task_id)
        status = task_status.get('status')

        if status == 'completed':
            print("\n✓ 处理完成!")
            break
        elif status == 'failed':
            print(f"\n✗ 处理失败: {task_status.get('error')}")
            break
        else:
            current_step = task_status.get('current_step', 0)
            completed = len(task_status.get('completed_steps', []))
            total = task_status.get('total_steps', 9)
            print(f"  进度: {completed}/{total} (当前步骤: {current_step})")

    # 5. 获取最终结果
    if status == 'completed':
        result = test_get_task_result(task_id)
        print("\n=== 最终结果 ===")
        print(f"产业链: {result.get('industry_name')}")
        print(f"完成步骤: {result.get('completed')}/{result.get('total_steps')}")


if __name__ == "__main__":
    import sys

    # 检查命令行参数
    if len(sys.argv) > 1:
        industry_name = sys.argv[1]
    else:
        industry_name = "氢能产业"

    try:
        # 测试 API 是否运行
        response = requests.get(f"{API_BASE_URL}/")
        if response.status_code == 200:
            print("✓ API 服务正常运行")
            test_full_workflow(industry_name)
        else:
            print(f"✗ API 服务响应异常: {response.status_code}")
    except requests.exceptions.ConnectionError:
        print("✗ 无法连接到 API 服务，请先启动服务:")
        print("  ./start_api.sh")
        print("或")
        print("  python3 -m uvicorn api.app:app --host 0.0.0.0 --port 8000")
    except Exception as e:
        print(f"✗ 错误: {e}")
