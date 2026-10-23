import os

import pymysql


DB_CONFIG_INDUSTRIAL_CHAIN = {
    "host": os.getenv("DB_HOST", "8.141.5.67"),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME_CHAIN", "industrial_chain"),
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor
}

# 获取数据库连接
def get_db_connection():
    return pymysql.connect(**DB_CONFIG_INDUSTRIAL_CHAIN)

# 异步获取数据库连接（实际上是同步函数的包装，因为pymysql不支持原生异步）
async def get_connection():
    """
    异步获取数据库连接
    
    Returns:
        数据库连接对象
    """
    return get_db_connection()