import os
import pandas as pd
import mysql.connector
from datetime import datetime

# 数据库连接配置
db_config = {
    'host': '8.141.5.67',
    'user': 'root',
    'password': os.getenv('DB_PASSWORD'),
    'database': 'business_data',
    'port': 3306
}

# 读取审核后的Excel文件
excel_path = "/root/mix_project/产业链上线相关脚本/result_20260225.xlsx"
df = pd.read_excel(excel_path)

print(f"读取数据: {len(df)} 行")
print(f"列名: {df.columns.tolist()}")

# 生成表名（可根据需要修改）
table_name = "result_0225"  # 对应文档中的result_njjk格式

try:
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()

    # 删除旧表（如果存在）
    cursor.execute(f"DROP TABLE IF EXISTS {table_name}")

    # 创建新表
    create_sql = f"""
    CREATE TABLE {table_name} (
        company_name TEXT,
        industry_name VARCHAR(255),
        nodes VARCHAR(255),
        node_level INT,
        parent_node VARCHAR(255),
        score VARCHAR(255),
        父节点_0 VARCHAR(255),
        父节点_1 VARCHAR(255),
        父节点_2 VARCHAR(255),
        父节点_3 VARCHAR(255),
        父节点_4 VARCHAR(255),
        父节点_5 VARCHAR(255),
        父节点_6 VARCHAR(255)
    )
    """
    cursor.execute(create_sql)
    print(f"创建表 {table_name} 成功")

    # 处理NaN值
    df = df.fillna('')

    # 插入数据
    insert_sql = f"""
    INSERT INTO {table_name}
    (company_name, industry_name, nodes, node_level, parent_node, score,
     父节点_0, 父节点_1, 父节点_2, 父节点_3, 父节点_4, 父节点_5, 父节点_6)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    data = [tuple(row) for row in df.values]
    cursor.executemany(insert_sql, data)
    conn.commit()

    print(f"成功导入 {len(data)} 条数据到表 {table_name}")

    # 创建索引加快后续查询
    cursor.execute(f"ALTER TABLE {table_name} ADD INDEX idx_company_name (company_name(255))")
    cursor.execute(f"ALTER TABLE {table_name} ADD INDEX idx_industry_name (industry_name)")
    cursor.execute(f"ALTER TABLE {table_name} ADD INDEX idx_node_level (node_level)")
    conn.commit()
    print("索引创建完成")

    cursor.close()
    conn.close()
    print("数据库连接已关闭")

except Exception as e:
    print(f"操作失败: {e}")
