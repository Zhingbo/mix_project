"""
后台任务执行脚本

独立进程运行产业链自动化处理，进度写入数据库或文件
"""
import sys
import os
import json
import pymysql
import asyncio
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

INDUSTRY_NAME = sys.argv[1] if len(sys.argv) > 1 else "测试产业"

# 数据库配置
DB_CONFIG = {
    'host': '8.141.5.67',
    'user': 'root',
    'password': os.getenv('DB_PASSWORD'),
    'database': 'business_data'
}

# 进度表
PROGRESS_TABLE = 'pipeline_task_progress'

def init_progress_table():
    """创建进度表"""
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()

    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {PROGRESS_TABLE} (
        id INT AUTO_INCREMENT PRIMARY KEY,
        industry_name VARCHAR(100) NOT NULL,
        status VARCHAR(50) DEFAULT 'running',
        current_step INT DEFAULT 0,
        current_step_name VARCHAR(100),
        progress INT DEFAULT 0,
        message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_industry_name (industry_name)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    conn.commit()
    cursor.close()
    conn.close()

def update_progress(industry_name, status=None, current_step=None, current_step_name=None, progress=None, message=None):
    """更新进度"""
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()

    updates = []
    params = []

    if status is not None:
        updates.append("status = %s")
        params.append(status)
    if current_step is not None:
        updates.append("current_step = %s")
        params.append(current_step)
    if current_step_name is not None:
        updates.append("current_step_name = %s")
        params.append(current_step_name)
    if progress is not None:
        updates.append("progress = %s")
        params.append(progress)
    if message is not None:
        updates.append("message = %s")
        params.append(message)

    params.append(industry_name)

    if updates:
        query = f"UPDATE {PROGRESS_TABLE} SET {', '.join(updates)} WHERE industry_name = %s"
        cursor.execute(query, params)
        conn.commit()

    cursor.close()
    conn.close()

def get_progress(industry_name):
    """获取进度"""
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()

    cursor.execute(f"SELECT * FROM {PROGRESS_TABLE} WHERE industry_name = %s", (industry_name,))
    result = cursor.fetchone()
    cursor.close()
    conn.close()

    if result:
        return {
            'id': result[0],
            'industry_name': result[1],
            'status': result[2],
            'current_step': result[3],
            'current_step_name': result[4],
            'progress': result[5],
            'message': result[6]
        }
    return None


if __name__ == "__main__":
    print(f"后台任务开始处理: {INDUSTRY_NAME}")
    # 这里可以调用原有的处理逻辑
    print("任务完成")
