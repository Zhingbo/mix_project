#!/usr/bin/env python3
"""
第二步
数据迁移脚本：将指定产业链数据从 industrial_chain 库迁移到 business_data 库

使用方式：
    python migrate_chain_data.py

说明：
    - 修改下方配置区域的数据库连接信息
    - 修改 source_chain_name 为需要迁移的产业链名称
    - 修改 target_table 为目标表名
"""
import os

import pymysql
from typing import List

# ==================== 配置区域 - 请根据实际情况修改 ====================

# 源数据库配置 (industrial_chain)
SOURCE_DB_CONFIG = {
    "host": "8.141.5.67",           # 例如: "8.141.5.67"
    "user": "root",           # 例如: "root"
    "password": os.getenv("DB_PASSWORD"),   # 见 .env
    "database": "industrial_chain",
    "charset": "utf8mb4"
}

# 目标数据库配置 (business_data)
TARGET_DB_CONFIG = {
    "host": "8.141.5.67",           # 例如: "8.141.5.67"
    "user": "root",           # 例如: "root"
    "password": os.getenv("DB_PASSWORD"),   # 见 .env
    "database": "business_data",
    "charset": "utf8mb4"
}

# 迁移参数
SOURCE_CHAIN_NAME = "氢能产业"      # 要迁移的产业链名称
TARGET_TABLE = "chain_needcomp0421" # 目标表名

# ==================== 脚本逻辑 ====================


def get_source_connection():
    """获取源数据库连接"""
    return pymysql.connect(**SOURCE_DB_CONFIG)


def get_target_connection():
    """获取目标数据库连接"""
    return pymysql.connect(**TARGET_DB_CONFIG)


def check_source_data(chain_name: str) -> int:
    """
    检查源数据库中符合条件的数据量

    Args:
        chain_name: 产业链名称

    Returns:
        符合条件的记录数
    """
    conn = get_source_connection()
    try:
        cursor = conn.cursor()
        sql = "SELECT COUNT(*) FROM industrial_chain_structure WHERE chain_name = %s"
        cursor.execute(sql, (chain_name,))
        count = cursor.fetchone()[0]
        print(f"源数据库中找到 {count} 条 chain_name='{chain_name}' 的记录")
        return count
    finally:
        conn.close()


def get_source_table_columns() -> List[str]:
    """获取源表的所有列名"""
    conn = get_source_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DESCRIBE industrial_chain_structure")
        columns = [row[0] for row in cursor.fetchall()]
        print(f"源表列: {', '.join(columns)}")
        return columns
    finally:
        conn.close()


def migrate_data(chain_name: str, target_table: str, batch_size: int = 1000):
    """
    执行数据迁移

    Args:
        chain_name: 产业链名称
        target_table: 目标表名
        batch_size: 批量插入大小
    """
    # 先检查源数据量
    source_count = check_source_data(chain_name)
    if source_count == 0:
        print("没有需要迁移的数据，退出。")
        return

    # 获取源表结构
    columns = get_source_table_columns()
    columns_str = ', '.join(columns)
    placeholders = ', '.join(['%s'] * len(columns))

    # 检查目标表是否存在，不存在则创建
    target_conn = get_target_connection()
    try:
        cursor = target_conn.cursor()
        cursor.execute(f"SHOW TABLES LIKE %s", (target_table,))
        if cursor.fetchone():
            print(f"目标表 {target_table} 已存在，将向其中插入数据")
        else:
            print(f"目标表 {target_table} 不存在，自动创建表")
            # 使用源数据库连接跨库创建表
            source_conn = get_source_connection()
            try:
                source_cursor = source_conn.cursor()
                create_sql = f"CREATE TABLE {TARGET_DB_CONFIG['database']}.{target_table} AS SELECT * FROM {SOURCE_DB_CONFIG['database']}.industrial_chain_structure WHERE chain_name = %s"
                source_cursor.execute(create_sql, (chain_name,))
                source_conn.commit()
                # 添加 nodes_definition 列
                alter_sql = f"ALTER TABLE {TARGET_DB_CONFIG['database']}.{target_table} ADD COLUMN nodes_definition TEXT"
                source_cursor.execute(alter_sql)
                source_conn.commit()
                print(f"表 {target_table} 创建成功，已添加 nodes_definition 列，数据已从源库复制")
                return
            finally:
                source_conn.close()
    finally:
        target_conn.close()

    # 分批读取源数据并插入目标表
    source_conn = get_source_connection()
    target_conn = get_target_connection()

    try:
        source_cursor = source_conn.cursor(pymysql.cursors.DictCursor)
        target_cursor = target_conn.cursor()

        # 查询源数据
        select_sql = f"SELECT {columns_str} FROM industrial_chain_structure WHERE chain_name = %s"
        source_cursor.execute(select_sql, (chain_name,))

        # 批量插入
        insert_sql = f"INSERT INTO {target_table} ({columns_str}) VALUES ({placeholders})"
        batch = []
        migrated_count = 0

        print(f"开始迁移数据...")

        for row in source_cursor:
            batch.append(tuple(row[col] for col in columns))

            if len(batch) >= batch_size:
                target_cursor.executemany(insert_sql, batch)
                target_conn.commit()
                migrated_count += len(batch)
                print(f"已迁移 {migrated_count}/{source_count} 条记录")
                batch = []

        # 插入剩余数据
        if batch:
            target_cursor.executemany(insert_sql, batch)
            target_conn.commit()
            migrated_count += len(batch)

        print(f"迁移完成！共迁移 {migrated_count} 条记录")

        # 验证迁移结果
        target_cursor.execute(f"SELECT COUNT(*) FROM {target_table} WHERE chain_name = %s", (chain_name,))
        target_count = target_cursor.fetchone()[0]
        print(f"目标表中 chain_name='{chain_name}' 的记录数: {target_count}")

        if source_count == target_count:
            print("验证通过：源数据和目标数据量一致！")
        else:
            print(f"警告：源数据({source_count})与目标数据({target_count})数量不一致")

    except Exception as e:
        print(f"迁移过程中发生错误: {e}")
        if target_conn:
            target_conn.rollback()
        raise
    finally:
        source_conn.close()
        target_conn.close()


if __name__ == "__main__":
    print("=" * 60)
    print("数据迁移脚本")
    print("=" * 60)
    print(f"源数据库: {SOURCE_DB_CONFIG['database']}")
    print(f"目标数据库: {TARGET_DB_CONFIG['database']}")
    print(f"产业链名称: {SOURCE_CHAIN_NAME}")
    print(f"目标表: {TARGET_TABLE}")
    print("=" * 60)

    confirm = input("确认开始迁移？(yes/no): ")
    if confirm.lower() in ['yes', 'y']:
        migrate_data(SOURCE_CHAIN_NAME, TARGET_TABLE)
    else:
        print("取消迁移")
