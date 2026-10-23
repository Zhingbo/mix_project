import requests
import json

def call_service(user_id, industry_name, custom_urls=None):
    # 构造请求的 URL
    url = "http://8.141.19.136:8080/process_industry"
    
    # 构造请求的 JSON 数据
    payload = {
        "user_id": user_id,
        "industry_name": industry_name
    }
    
    # 如果 custom_urls 不为空，则将其添加到 payload 中
    if custom_urls:
        payload["custom_urls"] = custom_urls
    
    # 设置请求头
    headers = {
        "Content-Type": "application/json"
    }
    
    # 发送 POST 请求，并设置 stream=True 以支持流式处理
    response = requests.post(url, json=payload, headers=headers, stream=True)
    
    if response.status_code == 200:
        # 如果响应状态码为 200，逐行处理流式响应
        for line in response.iter_lines():
            if line:
                decoded_line = line.decode('utf-8')
                # 检查是否是心跳信号
                if decoded_line.startswith("type: "):
                    parts = decoded_line.split("\n")
                    message_type = parts[0].split(": ", 1)[1]
                    message_content = parts[1].split(": ", 1)[1]
                    # 忽略心跳信号
                    if message_type.lower() == "ping":
                        continue
                    print(f"Type: {message_type}, Content: {message_content}")
                else:
                    print(f"Received raw message: {decoded_line}")
    else:
        # 如果响应状态码不是 200，打印错误信息
        print(f"Failed to call service. Status code: {response.status_code}, Response: {response.text}")

if __name__ == "__main__":
    user_id = "user_66"
    industry_name = "具身智能"
    custom_urls = [
        "https://www.163.com/dy/article/JI112GS705198SOQ.html",
        "https://www.sgpjbg.com/baogao/614359.html"
    ]  # 可以为空
    call_service(user_id, industry_name, custom_urls)