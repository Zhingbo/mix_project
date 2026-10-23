import os
import pandas as pd
from sqlalchemy import create_engine

# 指定你的TXT文件所在的目录
directory = 'resultTxt'

# 创建一个空列表，用于存储所有的DataFrame
dfs = []

# 获取所有nodes文件
nodes_files = [f for f in os.listdir(directory) if f.startswith('nodes') and f.endswith('.txt')]

# 处理nodes文件
for filename in nodes_files:
    chain_name = filename.split('_')[1].split('.')[0]
    filepath = os.path.join(directory, filename)
    with open(filepath, 'r', encoding='utf-8') as file:
        nodes = file.read().strip().split('\n')
    # 为每个节点创建一个DataFrame并添加到列表中
    df = pd.DataFrame({'chain_name': [chain_name] * len(nodes), 'nodes': nodes})
    dfs.append(df)

# 使用concat合并所有的DataFrame
df_all = pd.concat(dfs, ignore_index=True)

# MySQL连接信息
mysql_config = {
    'user': 'remote_user',
    'password': os.getenv('DB_PASSWORD_REMOTE'),
    'host': '8.141.23.4',
    'database': 'business_data'
}

# 创建SQLAlchemy引擎
engine = create_engine(f"mysql+pymysql://{mysql_config['user']}:{mysql_config['password']}@{mysql_config['host']}/{mysql_config['database']}")

# 将DataFrame数据插入到MySQL表中
df_all.to_sql('chain_nodes_info_all_new', con=engine, if_exists='append', index=False)

print('Data has been written to MySQL table chain_nodes_info_all_new')