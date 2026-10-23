#!/bin/bash

# 定义变量
PORT=8001
LOG_FILE="gunicorn.log"
APP_COMMAND="gunicorn -n cyl_mix_project -c gunicorn_config.py main:app"
WORK_DIR="/root/mix_project"
PROC_NAME="cyl_mix_project"  # 进程名称标识

# 停止 FastAPI 程序
stop_fastapi() {
    echo "Stopping FastAPI ($PROC_NAME) running on port $PORT..."

    # 切换到工作目录
    cd "$WORK_DIR" || exit 1

    # 使用 lsof 查找监听指定端口的进程
    echo "Finding processes listening on port $PORT..."

    if command -v lsof > /dev/null 2>&1; then
        PIDS=$(lsof -t -i :$PORT 2>/dev/null)
        if [ -n "$PIDS" ]; then
            echo "Found processes using port $PORT: $PIDS"
            for PID in $PIDS; do
                # 检查进程是否是我们的项目进程（通过 cyl_mix_project 标识）
                CMDLINE=$(ps -p $PID -o command= 2>/dev/null | tr '\0' ' ')
                if echo "$CMDLINE" | grep -q "cyl_mix_project"; then
                    echo "Killing process $PID ($PROC_NAME)"
                    kill -9 $PID 2>/dev/null || true
                elif echo "$CMDLINE" | grep -q "$WORK_DIR"; then
                    echo "Killing process $PID from our project"
                    kill -9 $PID 2>/dev/null || true
                else
                    echo "Process $PID is not from our project, skipping"
                fi
            done
        fi
    fi

    # 等待一下
    sleep 2

    # 二次检查：如果端口还被占用，再次尝试清理
    if command -v lsof > /dev/null 2>&1; then
        PIDS=$(lsof -t -i :$PORT 2>/dev/null)
        if [ -n "$PIDS" ]; then
            echo "Found processes still using port $PORT: $PIDS"
            for PID in $PIDS; do
                # 检查进程是否是我们的项目进程（通过 cyl_mix_project 标识）
                CMDLINE=$(ps -p $PID -o command= 2>/dev/null | tr '\0' ' ')
                if echo "$CMDLINE" | grep -q "cyl_mix_project"; then
                    echo "Killing process $PID ($PROC_NAME)"
                    kill -9 $PID 2>/dev/null || true
                elif echo "$CMDLINE" | grep -q "$WORK_DIR"; then
                    echo "Killing process $PID from our project"
                    kill -9 $PID 2>/dev/null || true
                else
                    echo "Process $PID is not from our project, skipping"
                fi
            done
            sleep 1
        fi
    fi

    # 最终确认
    if command -v lsof > /dev/null 2>&1; then
        if lsof -t -i :$PORT >/dev/null 2>&1; then
            echo "WARNING: Port $PORT is still in use!"
            echo "Current processes using port $PORT:"
            lsof -i :$PORT
            return 1
        fi
    fi

    echo "FastAPI stopped successfully."
    return 0
}

# 启动 FastAPI 程序
start_fastapi() {
    echo "Starting FastAPI on port $PORT..."
    nohup $APP_COMMAND > $LOG_FILE 2>&1 &
    echo "FastAPI started. Logs are being written to $LOG_FILE."
}

# 重启 FastAPI 程序
restart_fastapi() {
    stop_fastapi || exit 1
    start_fastapi
}

# 根据参数执行操作
case "$1" in
    start)
        start_fastapi
        ;;
    stop)
        stop_fastapi
        ;;
    restart)
        restart_fastapi
        ;;
    *)
        echo "Usage: $0 {start|stop|restart}"
        exit 1
        ;;
esac