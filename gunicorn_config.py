"""
Gunicorn 配置文件
用于生产环境的产业链智能体服务
"""
import multiprocessing
import os

# 服务器绑定
bind = "0.0.0.0:8001"

# 工作进程数 - 限制为4个，避免过多worker导致后台任务重复执行
workers = 4

# 工作进程类型
worker_class = "uvicorn.workers.UvicornWorker"

# 工作进程连接数
worker_connections = 1000

# 最大请求数，防止内存泄漏
max_requests = 10000
max_requests_jitter = 1000

# 超时设置
timeout = 300
keepalive = 65

# 预加载应用
preload_app = True

# 日志配置 - 禁用多余日志文件
accesslog = None
errorlog = "-"
loglevel = "warning"

# 进程名称 - 添加 cyl 标识避免误杀
proc_name = "cyl_mix_project"

# 守护进程
daemon = False  # 由 systemd 管理，不需要 daemon 模式

# PID 文件
pidfile = "/root/mix_project/mix_project.pid"

# 工作目录
chdir = "/root/mix_project"

# 环境变量
raw_env = [
    "PYTHONUNBUFFERED=1",
    "LANG=en_US.UTF-8",
]

# 优雅重启超时
graceful_timeout = 30

# 目录权限（用于上传文件等）
# umask = 0

# 启动钩子
def on_starting(server):
    """服务器启动时执行"""
    print("Gunicorn server starting...")

def when_ready(server):
    """服务器准备就绪时执行"""
    print("Gunicorn server ready.")

def on_exit(server):
    """服务器退出时执行"""
    print("Gunicorn server exiting...")
