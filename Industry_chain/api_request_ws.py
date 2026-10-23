import asyncio
import websockets
import json

async def connect_to_server():
    try:
        async with websockets.connect("ws://8.141.19.136:8080/generate_industry_chain") as websocket:
            data = {
                "user_id": "user_39",
                "industry_names": ["智慧养老"]  # 注意这里应该是 industry_names 而不是 industry_name
            }
            await websocket.send(json.dumps(data))
            print("消息已发送")

            # 持续接收服务器发送的消息
            while True:
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=10)  # 设置超时时间
                    print(f"收到服务器响应：{response}")
                except asyncio.TimeoutError:
                    print("未收到更多消息，连接可能已关闭")
                    break
                except websockets.exceptions.ConnectionClosed:
                    print("连接已关闭")
                    break
    except websockets.exceptions.WebSocketException as e:
        print(f"WebSocket 连接失败: {e}")
    except Exception as e:
        print(f"发生错误: {e}")

if __name__ == "__main__":
    asyncio.run(connect_to_server())