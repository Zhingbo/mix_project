#!/usr/bin/env python3
"""
服务重启和诊断脚本
用于解决后端服务不会重启的问题
"""

import os
import sys
import subprocess
import signal
import time
from pathlib import Path

def find_main_py():
    """查找main.py文件"""
    possible_paths = [
        "/root/mix_project/main.py",
        "/root/mix_project/app/main.py",
        "/root/mix_project/src/main.py",
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            return path
    
    # 递归搜索
    for root, dirs, files in os.walk("/root"):
        if "main.py" in files:
            main_path = os.path.join(root, "main.py")
            # 检查是否是FastAPI应用
            try:
                with open(main_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if 'FastAPI' in content or 'uvicorn' in content:
                        return main_path
            except:
                continue
    
    return None

def kill_existing_services():
    """终止现有的服务进程"""
    print("🔍 检查现有服务进程...")
    
    # 查找uvicorn进程
    try:
        result = subprocess.run(['pgrep', '-f', 'uvicorn'], capture_output=True, text=True)
        if result.returncode == 0:
            pids = result.stdout.strip().split('\n')
            for pid in pids:
                if pid:
                    print(f"终止进程 {pid}")
                    os.kill(int(pid), signal.SIGTERM)
                    time.sleep(1)
                    # 如果还没终止，强制杀死
                    try:
                        os.kill(int(pid), signal.SIGKILL)
                    except:
                        pass
    except Exception as e:
        print(f"终止进程时出错: {e}")
    
    # 查找占用8000端口的进程
    try:
        result = subprocess.run(['lsof', '-ti:8000'], capture_output=True, text=True)
        if result.returncode == 0:
            pids = result.stdout.strip().split('\n')
            for pid in pids:
                if pid:
                    print(f"终止占用8000端口的进程 {pid}")
                    os.kill(int(pid), signal.SIGTERM)
                    time.sleep(1)
    except Exception as e:
        print(f"终止端口进程时出错: {e}")

def start_service(main_path):
    """启动服务"""
    print(f"🚀 启动服务: {main_path}")
    
    # 切换到main.py所在目录
    work_dir = os.path.dirname(main_path)
    os.chdir(work_dir)
    
    # 检查是否有requirements.txt
    if os.path.exists('requirements.txt'):
        print("📦 安装依赖...")
        subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'])
    
    # 启动uvicorn服务
    cmd = [
        sys.executable, '-m', 'uvicorn',
        'main:app',
        '--host', '0.0.0.0',
        '--port', '8000',
        '--reload',  # 启用自动重载
        '--reload-dir', work_dir,  # 监听目录变化
    ]
    
    print(f"执行命令: {' '.join(cmd)}")
    print(f"工作目录: {work_dir}")
    
    # 在后台启动服务
    process = subprocess.Popen(cmd, cwd=work_dir)
    print(f"服务已启动，PID: {process.pid}")
    
    return process

def create_systemd_service(main_path):
    """创建systemd服务文件"""
    work_dir = os.path.dirname(main_path)
    
    service_content = f"""[Unit]
Description=Mix Project FastAPI Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory={work_dir}
ExecStart={sys.executable} -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""
    
    service_file = "/etc/systemd/system/mix-project.service"
    try:
        with open(service_file, 'w') as f:
            f.write(service_content)
        
        # 重载systemd配置
        subprocess.run(['systemctl', 'daemon-reload'])
        subprocess.run(['systemctl', 'enable', 'mix-project.service'])
        
        print(f"✅ 已创建systemd服务: {service_file}")
        print("可以使用以下命令管理服务:")
        print("  systemctl start mix-project")
        print("  systemctl stop mix-project")
        print("  systemctl restart mix-project")
        print("  systemctl status mix-project")
        
    except Exception as e:
        print(f"❌ 创建systemd服务失败: {e}")

def main():
    print("🔧 后端服务重启诊断工具")
    print("=" * 50)
    
    # 1. 查找main.py
    main_path = find_main_py()
    if not main_path:
        print("❌ 未找到main.py文件")
        print("请确保FastAPI应用的main.py文件存在")
        return
    
    print(f"✅ 找到main.py: {main_path}")
    
    # 2. 终止现有服务
    kill_existing_services()
    
    # 3. 询问启动方式
    print("\n选择启动方式:")
    print("1. 直接启动 (前台运行，适合调试)")
    print("2. 后台启动 (使用nohup)")
    print("3. 创建systemd服务 (推荐生产环境)")
    
    choice = input("请选择 (1/2/3): ").strip()
    
    if choice == "1":
        # 直接启动
        work_dir = os.path.dirname(main_path)
        os.chdir(work_dir)
        cmd = [
            sys.executable, '-m', 'uvicorn',
            'main:app',
            '--host', '0.0.0.0',
            '--port', '8000',
            '--reload'
        ]
        print(f"执行命令: {' '.join(cmd)}")
        subprocess.run(cmd)
        
    elif choice == "2":
        # 后台启动
        work_dir = os.path.dirname(main_path)
        os.chdir(work_dir)
        cmd = [
            'nohup',
            sys.executable, '-m', 'uvicorn',
            'main:app',
            '--host', '0.0.0.0',
            '--port', '8000',
            '--reload'
        ]
        
        with open('nohup.out', 'w') as f:
            process = subprocess.Popen(cmd, stdout=f, stderr=f, cwd=work_dir)
        
        print(f"✅ 服务已在后台启动，PID: {process.pid}")
        print("日志文件: nohup.out")
        
    elif choice == "3":
        # 创建systemd服务
        create_systemd_service(main_path)
        
        start_service = input("是否立即启动服务? (y/n): ").strip().lower()
        if start_service == 'y':
            subprocess.run(['systemctl', 'start', 'mix-project'])
            subprocess.run(['systemctl', 'status', 'mix-project'])
    
    else:
        print("❌ 无效选择")
        return
    
    # 4. 验证服务状态
    time.sleep(3)
    try:
        result = subprocess.run(['curl', '-s', 'http://localhost:8000/'], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print("✅ 服务启动成功，可以正常访问")
        else:
            print("⚠️ 服务可能启动了，但无法访问根路径")
    except Exception as e:
        print(f"⚠️ 无法验证服务状态: {e}")
    
    print("\n" + "=" * 50)
    print("🎉 服务重启完成!")
    print("现在修改代码应该会自动重启服务了")

if __name__ == "__main__":
    main() 