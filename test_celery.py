"""
测试Celery Pipeline任务
"""

from celery_app import app
from tasks.pipeline_tasks import run_pipeline_task

# 直接提交测试任务
print("提交测试任务到Celery...")
task = run_pipeline_task.delay("风力发电", start_step=2)

print(f"任务ID: {task.id}")
print(f"任务状态: {task.status}")

# 等待几秒看状态变化
import time
time.sleep(3)

print(f"3秒后状态: {task.status}")

if task.state == 'PENDING':
    print("任务可能在等待worker处理...")
elif task.state == 'STARTED':
    print("任务已开始执行...")
elif task.state == 'PROGRESS':
    print(f"任务执行中: {task.info}")
elif task.state == 'SUCCESS':
    print(f"任务完成: {task.result}")
elif task.state == 'FAILURE':
    print(f"任务失败: {task.info}")
