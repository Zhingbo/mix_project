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

# 产业链名称（可修改）
industry_name = '自动驾驶'

try:
    # 连接数据库
    connection = mysql.connector.connect(**db_config)
    print("数据库连接成功")

    # 查询最终结果
    query = f"""
    SELECT DISTINCT a.company_name, industry_name, nodes, node_level, parent_node, score
    FROM business_data.company_nodes_finallist1230 a
    WHERE industry_name = '{industry_name}'
    ORDER BY score DESC
    """
    
    # 读取数据
    df = pd.read_sql_query(query, connection)
    
    print(f"查询到 {len(df)} 条记录")
    
    # 生成文件名（包含产业链名称和时间戳）
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_file = f'C:\\Users\\13123\\Desktop\\daima\\产业链\\{industry_name}_企业节点最终结果_{timestamp}.xlsx'
    
    # 导出到Excel
    df.to_excel(output_file, index=False, engine='openpyxl')
    
    print(f"数据已成功导出到: {output_file}")
    print(f"总共导出 {len(df)} 条记录")
    
    # 显示前5条数据预览
    print("\n数据预览（前5条）：")
    print(df.head())

except mysql.connector.Error as e:
    print(f"数据库操作失败: {e}")
except Exception as e:
    print(f"导出失败: {e}")
finally:
    if 'connection' in locals() and connection.is_connected():
        connection.close()
        print("\n数据库连接已关闭")
