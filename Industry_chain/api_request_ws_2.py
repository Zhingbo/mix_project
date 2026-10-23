import asyncio
import websockets
import json

async def connect_to_server():
    try:
        async with websockets.connect("ws://localhost:40000/generate_industry_chain") as websocket:
            data = {
                "user_id": "user_29",
                "industry_name": "智慧养老"
            }
            await websocket.send(json.dumps(data))

            while True:
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=60)
                    if message == '{"type":"ping"}':
                        print("收到心跳包，继续等待数据...")
                        await websocket.send(json.dumps({"type": "pong"}))
                        continue
                    print(f"收到数据: {message}")
                except asyncio.TimeoutError:
                    print("WebSocket 接收超时，发送心跳包...")
                    await websocket.send(json.dumps({"type": "pong"}))
                except websockets.exceptions.ConnectionClosed:
                    print("WebSocket 连接已关闭")
                    break

    except websockets.exceptions.WebSocketException as e:
        print(f"WebSocket 连接失败: {e}")
    except Exception as e:
        print(f"发生错误: {e}")

asyncio.run(connect_to_server())