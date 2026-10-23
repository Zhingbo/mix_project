import requests

# 设置请求的 URL 和参数
url = "http://8.141.19.136:8080/generate_industry_chain"
headers = {"Content-Type": "application/json"}
data = {"user_id": "user_24", "industry_name": "智慧养老"}

# 发送 POST 请求
response = requests.post(url, json=data, stream=True)

# 检查响应状态码
if response.status_code == 200:
    # 逐行读取流式响应
    for line in response.iter_lines():
        if line:
            decoded_line = line.decode('utf-8')
            # 去掉可能的前缀 "data: "
            if decoded_line.startswith("data: "):
                decoded_line = decoded_line[6:]
            print(decoded_line)
else:
    print(f"Error: {response.status_code}")