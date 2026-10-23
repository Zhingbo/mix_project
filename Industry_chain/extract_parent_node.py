import os
import pandas as pd
import mysql.connector
from mysql.connector import Error

# 定义文件夹路径
folder_path = 'resultTxt'

# 数据库连接配置
db_config = {
    'user': 'remote_user',
    'password': os.getenv('DB_PASSWORD_REMOTE'),
    'host': '8.141.23.4',
    'database': 'business_data'
}

# 初始化一个空列表来存储数据
data = []

# 遍历文件夹中的文件
for filename in os.listdir(folder_path):
    if filename.startswith('relations') and filename.endswith('.txt'):
        # 提取产业链名称
        chain_name = filename.split('_')[1].split('.')[0]
        
        # 读取文件内容
        with open(os.path.join(folder_path, filename), 'r', encoding='utf-8') as file:
            lines = file.readlines()
            for line in lines:
                # 处理每一行数据
                parts = line.strip().split(',')
                if len(parts) == 3:
                    node = parts[0]
                    parent_node = parts[1]
                    # 将数据添加到列表
                    data.append({'chain_name': chain_name, 'nodes': node, 'parent_node': parent_node})

# 将列表转换为DataFrame
df = pd.DataFrame(data)

# 连接到MySQL数据库
try:
    connection = mysql.connector.connect(**db_config)
    if connection.is_connected():
        cursor = connection.cursor(dictionary=True)
        
        # 遍历DataFrame中的每一行数据
        for index, row in df.iterrows():
            chain_name = row['chain_name']
            nodes = row['nodes']
            parent_node = row['parent_node']
            
            # 查询parent_node对应的id
            query = """
            SELECT id FROM chain_nodes_info_all_new
            WHERE chain_name = %s AND nodes = %s
            """
            cursor.execute(query, (chain_name, parent_node))
            result = cursor.fetchone()
            
            if result:
                parent_id = result['id']
                
                # 更新chain_nodes_info_all_new表中的parent_node和parent_id字段
                update_query = """
                UPDATE chain_nodes_info_all_new
                SET parent_node = %s, parent_id = %s
                WHERE chain_name = %s AND nodes = %s
                """
                cursor.execute(update_query, (parent_node, parent_id, chain_name, nodes))
        
        # 提交事务
        connection.commit()
        print("Data has been successfully updated in the database.")
except Error as e:
    print(f"Error while connecting to MySQL: {e}")
finally:
    if connection.is_connected():
        cursor.close()
        connection.close()
        print("MySQL connection is closed")