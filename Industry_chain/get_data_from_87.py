import os
import mysql.connector
from mysql.connector import errorcode
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 数据库连接配置
src_config = {
    'host': '10.0.2.87',
    'port': 3506,
    'user': 'root',
    'password': os.getenv('DB_PASSWORD_BI'),
    'database': 'liando_bi'
}

dest_config = {
    'user': 'remote_user',
    'password': os.getenv('DB_PASSWORD_REMOTE'),
    'host': '8.141.23.4',
    'database': 'business_data'
}

# 分批处理的每批次大小
BATCH_SIZE = 100000  # 每次处理10万条数据

def connect_to_db(config):
    """建立数据库连接"""
    try:
        conn = mysql.connector.connect(**config)
        logging.info(f"成功连接到数据库: {config['host']}:{config['port']}/{config['database']}")
        return conn
    except mysql.connector.Error as err:
        logging.error(f"数据库连接失败: {err}")
        raise

def fetch_data_in_batches(src_conn, batch_size):
    """分批从源数据库拉取数据"""
    cursor = src_conn.cursor(dictionary=True)
    offset = 0
    while True:
        query = f"SELECT * FROM tmp_dwd_online_final_all LIMIT {offset}, {batch_size}"
        cursor.execute(query)
        rows = cursor.fetchall()
        if not rows:
            break
        yield rows
        offset += batch_size
    cursor.close()

def insert_data_in_batches(dest_conn, data):
    """将数据批量插入目标数据库"""
    cursor = dest_conn.cursor()
    placeholders = ', '.join(['%s'] * len(data[0]))
    columns = ', '.join(data[0].keys())
    query = f"INSERT INTO tmp_dwd_online_final_all ({columns}) VALUES ({placeholders})"
    try:
        cursor.executemany(query, [tuple(row.values()) for row in data])
        dest_conn.commit()
        logging.info(f"成功插入 {len(data)} 条数据")
    except mysql.connector.Error as err:
        logging.error(f"数据插入失败: {err}")
        dest_conn.rollback()
    finally:
        cursor.close()

def main():
    try:
        # 连接源数据库和目标数据库
        src_conn = connect_to_db(src_config)
        dest_conn = connect_to_db(dest_config)

        # 分批处理数据
        for batch_data in fetch_data_in_batches(src_conn, BATCH_SIZE):
            insert_data_in_batches(dest_conn, batch_data)

    except Exception as e:
        logging.error(f"数据迁移失败: {e}")
    finally:
        src_conn.close()
        dest_conn.close()

if __name__ == "__main__":
    main()