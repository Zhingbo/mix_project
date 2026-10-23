import subprocess

def get_public_ip():
    try:
        # 调用 curl 命令
        result = subprocess.run(['curl', 'ifconfig.me'], capture_output=True, text=True, check=True)
        # 获取输出
        public_ip = result.stdout.strip()
        return public_ip
    except subprocess.CalledProcessError as e:
        print(f"Error: {e}")
        return None

# 测试
public_ip = get_public_ip()
if public_ip:
    print(f"Public IP: {public_ip}")
else:
    print("Failed to get public IP")