#!/bin/bash

# Mix Project 服务管理脚本
# 使用 systemd + gunicorn 管理产业链智能体服务

SERVICE_NAME="mix-project"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
WORK_DIR="/root/mix_project"
LOG_FILE="$WORK_DIR/industrial.log"
ERROR_LOG="$WORK_DIR/industrial_error.log"
ACCESS_LOG="$WORK_DIR/industrial_access.log"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查服务是否安装
check_service_installed() {
    if [ ! -f "$SERVICE_FILE" ]; then
        print_error "Systemd 服务文件不存在: $SERVICE_FILE"
        echo "请先运行安装脚本安装服务"
        return 1
    fi
    return 0
}

# 启动服务
start_service() {
    print_info "启动 $SERVICE_NAME 服务..."

    if ! check_service_installed; then
        return 1
    fi

    # 重新加载 systemd 配置
    systemctl daemon-reload

    # 启动服务
    systemctl start $SERVICE_NAME

    # 等待服务启动
    sleep 3

    # 检查服务状态
    if systemctl is-active --quiet $SERVICE_NAME; then
        print_info "服务启动成功！"
        print_info "服务状态:"
        systemctl status $SERVICE_NAME --no-pager -l
        return 0
    else
        print_error "服务启动失败！"
        print_error "查看错误日志: journalctl -u $SERVICE_NAME -n 50"
        return 1
    fi
}

# 停止服务
stop_service() {
    print_info "停止 $SERVICE_NAME 服务..."

    if ! check_service_installed; then
        return 1
    fi

    # 检查服务是否在运行
    if ! systemctl is-active --quiet $SERVICE_NAME; then
        print_warn "服务未在运行"
        return 0
    fi

    # 停止服务
    systemctl stop $SERVICE_NAME

    # 等待服务停止
    sleep 2

    # 检查是否已停止
    if systemctl is-active --quiet $SERVICE_NAME; then
        print_error "服务停止失败！"
        return 1
    else
        print_info "服务已停止"
        return 0
    fi
}

# 重启服务
restart_service() {
    print_info "重启 $SERVICE_NAME 服务..."

    if ! check_service_installed; then
        return 1
    fi

    # 重新加载 systemd 配置
    systemctl daemon-reload

    # 重启服务
    systemctl restart $SERVICE_NAME

    # 等待服务重启
    sleep 5

    # 检查服务状态
    if systemctl is-active --quiet $SERVICE_NAME; then
        print_info "服务重启成功！"
        return 0
    else
        print_error "服务重启失败！"
        print_error "查看错误日志: journalctl -u $SERVICE_NAME -n 50"
        return 1
    fi
}

# 查看服务状态
status_service() {
    if ! check_service_installed; then
        return 1
    fi

    systemctl status $SERVICE_NAME --no-pager -l
}

# 查看日志
logs_service() {
    local lines=${1:-50}

    if ! check_service_installed; then
        return 1
    fi

    echo "=== 最近 $lines 行 systemd 日志 ==="
    journalctl -u $SERVICE_NAME -n $lines --no-pager

    echo ""
    echo "=== 应用访问日志 (最后20行) ==="
    if [ -f "$ACCESS_LOG" ]; then
        tail -20 "$ACCESS_LOG"
    else
        print_warn "访问日志文件不存在: $ACCESS_LOG"
    fi
}

# 实时查看日志
logs_follow() {
    if ! check_service_installed; then
        return 1
    fi

    print_info "实时查看日志 (Ctrl+C 退出)..."
    journalctl -u $SERVICE_NAME -f
}

# 检查服务健康状态
health_check() {
    print_info "检查服务健康状态..."

    # 检查 systemd 服务状态
    if systemctl is-active --quiet $SERVICE_NAME; then
        print_info "✓ Systemd 服务运行中"
    else
        print_error "✗ Systemd 服务未运行"
        return 1
    fi

    # 检查端口监听
    if command -v lsof >/dev/null 2>&1; then
        if lsof -i :8001 >/dev/null 2>&1; then
            print_info "✓ 端口 8001 监听中"
        else
            print_error "✗ 端口 8001 未监听"
            return 1
        fi
    fi

    # 检查 HTTP 响应
    if command -v curl >/dev/null 2>&1; then
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8001/health || echo "000")
        if [ "$HTTP_CODE" = "200" ]; then
            print_info "✓ HTTP 健康检查通过 (200)"
        else
            print_warn "HTTP 健康检查返回: $HTTP_CODE"
        fi
    fi

    # 检查进程数
    WORKER_COUNT=$(pgrep -f "gunicorn.*main:app" | wc -l)
    print_info "当前工作进程数: $WORKER_COUNT"

    return 0
}

# 启用开机自启
enable_service() {
    print_info "启用开机自启..."

    if ! check_service_installed; then
        return 1
    fi

    systemctl enable $SERVICE_NAME
    print_info "已设置开机自启"
}

# 禁用开机自启
disable_service() {
    print_info "禁用开机自启..."

    if ! check_service_installed; then
        return 1
    fi

    systemctl disable $SERVICE_NAME
    print_info "已取消开机自启"
}

# 安装/重新安装服务
install_service() {
    print_info "安装/更新 systemd 服务..."

    # 检查服务文件
    if [ ! -f "$SERVICE_FILE" ]; then
        print_error "服务文件不存在: $SERVICE_FILE"
        print_info "请确保服务文件已正确创建"
        return 1
    fi

    # 重新加载 systemd
    systemctl daemon-reload

    # 重启服务
    restart_service

    # 启用开机自启
    enable_service

    print_info "服务安装完成！"
}

# 显示帮助信息
show_help() {
    cat << EOF
Mix Project 服务管理脚本

用法: $0 {start|stop|restart|status|logs|logsf|health|enable|disable|install|help}

命令:
    start       启动服务
    stop        停止服务
    restart     重启服务
    status      查看服务状态
    logs [N]    查看最近 N 行日志 (默认50行)
    logsf       实时查看日志
    health      健康检查
    enable      启用开机自启
    disable     禁用开机自启
    install     安装/重新安装服务
    help        显示此帮助信息

服务信息:
    服务名称: $SERVICE_NAME
    工作目录: $WORK_DIR
    日志文件: $LOG_FILE
    错误日志: $ERROR_LOG

EOF
}

# 主程序
case "$1" in
    start)
        start_service
        ;;
    stop)
        stop_service
        ;;
    restart)
        restart_service
        ;;
    status)
        status_service
        ;;
    logs)
        logs_service "${2:-50}"
        ;;
    logsf)
        logs_follow
        ;;
    health)
        health_check
        ;;
    enable)
        enable_service
        ;;
    disable)
        disable_service
        ;;
    install)
        install_service
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        echo "用法: $0 {start|stop|restart|status|logs|logsf|health|enable|disable|install|help}"
        exit 1
        ;;
esac

exit $?
