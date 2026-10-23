#!/usr/bin/env python3
"""
生产环境启动脚本
多进程模式，高性能运行
"""

import os
import sys
import multiprocessing
import uvicorn
from utils.logger import get_logger

# 设置环境变量
os.environ["ENVIRONMENT"] = "production"

# 获取日志记录器
logger = get_logger(__name__)

def main():
    """启动生产服务器"""
    workers = multiprocessing.cpu_count()
    
    logger.info("🚀 启动生产环境服务器")
    logger.info(f"🔄 使用 {workers} 个工作进程")
    logger.info("🌐 服务地址: http://localhost:8001")
    logger.info("📚 API文档: http://localhost:8001/docs")
    logger.info("🔧 停止服务: Ctrl+C")
    
    try:
        uvicorn.run(
            "main:app",
            host="0.0.0.0",
            port=8001,
            workers=workers,  # 多进程模式
            log_level="info",
            access_log=True,
        )
    except KeyboardInterrupt:
        logger.info("👋 服务已停止")
    except Exception as e:
        logger.error(f"❌ 启动失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 