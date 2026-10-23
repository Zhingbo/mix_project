"""
Celery应用配置

使用Redis作为broker和backend
"""

from celery import Celery
import os

# Redis配置
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = os.getenv('REDIS_PORT', 6379)
REDIS_DB = os.getenv('REDIS_DB', 0)

BROKER_URL = f'redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}'
BACKEND_URL = f'redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}'

# 创建Celery应用
app = Celery(
    'mix_project',
    broker=BROKER_URL,
    backend=BACKEND_URL,
    include=['tasks.pipeline_tasks']
)

# Celery配置
app.conf.update(
    # 任务配置
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Asia/Shanghai',
    enable_utc=True,

    # 任务执行配置
    task_acks_late=True,  # 任务执行后才确认
    worker_prefetch_multiplier=1,  # 每次只预取一个任务
    task_time_limit=14400,  # 任务最长执行时间4小时
    task_soft_time_limit=13800,  # 软超时3.75小时，触发异常
    task_track_started=True,  # 跟踪任务开始时间

    # 重试配置
    task_autoretry_for=(Exception,),  # 所有异常自动重试
    task_retry_max_retry_delay=300,  # 最大重试延迟5分钟
    task_retry_backoff=True,  # 指数退避
    task_retry_backoff_max=600,  # 最大退避10分钟
    task_retry_max=3,  # 最大重试次数

    # 结果配置
    result_expires=86400,  # 结果保留1天
    result_extended=True,  # 扩展结果信息

    # Worker配置
    worker_concurrency=16,  # 16个并发worker
    worker_max_tasks_per_child=100,  # 每个worker执行100个任务后重启
)

# 任务路由配置（可选，用于将特定任务发到特定队列）
app.conf.task_routes = {
    'tasks.pipeline_tasks.run_pipeline_task': {'queue': 'pipeline'},
    'tasks.pipeline_tasks.cancel_pipeline_task': {'queue': 'pipeline_control'},
}

if __name__ == '__main__':
    app.start()
