import os
import pandas as pd
import mysql.connector

# 数据库连接配置
db_config = {
    'host': '8.141.5.67',
    'user': 'root',
    'password': os.getenv('DB_PASSWORD'),
    'database': 'business_data',
    'port': 3306
}

# 连接到数据库
try:
    connection = mysql.connector.connect(**db_config)
    print("数据库连接成功")

    # 查询数据
    query = """
    SELECT DISTINCT a.company_name, industry_name, nodes, node_level, parent_node, score
    FROM business_data.company_nodes_finallist0211 a
    ORDER BY score DESC;
    """
    df = pd.read_sql_query(query, connection)

    # 导出到Excel
    output_file = 'company_nodes_finallist0211_export.xlsx'
    df.to_excel(output_file, index=False)
    print(f"数据已导出到 {output_file}，共 {len(df)} 条记录")

except Exception as e:
    print(f"操作失败: {e}")

finally:
    if 'connection' in locals() and connection.is_connected():
        connection.close()
        print("数据库连接已关闭")
