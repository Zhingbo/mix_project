#!/bin/bash
# Celery worker启动脚本

cd /root/mix_project

# 配置
WORKER_CONCURRENCY=16
LOG_LEVEL=info

# 启动Celery worker
celery -A celery_app worker \
    --loglevel=$LOG_LEVEL \
    --concurrency=$WORKER_CONCURRENCY \
    --pidfile=/tmp/celery_worker.pid \
    --logfile=celery_worker.log \
    --without-gossip \
    --without-mingle \
    --without-heartbeat \
    -Q pipeline,pipeline_control
