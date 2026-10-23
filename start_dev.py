#!/usr/bin/env python3
"""
开发环境启动脚本
自动重载模式，修改代码即时生效
"""

import os
import sys
import uvicorn
from utils.logger import get_logger

# 设置环境变量
os.environ["ENVIRONMENT"] = "development"

# 获取日志记录器
logger = get_logger(__name__)

def main():
    """启动开发服务器"""
    logger.info("🚀 启动开发环境服务器")
    logger.info("📝 自动重载已启用 - 修改代码将自动重启服务")
    logger.info("🌐 服务地址: http://localhost:8001")
    logger.info("📚 API文档: http://localhost:8001/docs")
    logger.info("🔧 停止服务: Ctrl+C")
    
    try:
        uvicorn.run(
            "main:app",
            host="0.0.0.0",
            port=8001,
            reload=True,  # 开发模式：自动重载
            reload_dirs=["./"],  # 监控当前目录的所有文件
            reload_includes=["*.py"],  # 只监控Python文件
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