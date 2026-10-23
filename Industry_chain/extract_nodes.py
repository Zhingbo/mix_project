import os
import pandas as pd

# 指定你的TXT文件所在的目录
directory = 'resultTxt'

# 创建一个空列表，用于存储所有的DataFrame
dfs = []

# 获取所有nodes2文件的chain_name
nodes2_files = [f for f in os.listdir(directory) if f.startswith('nodes2') and f.endswith('.txt')]
nodes2_chain_names = {filename.split('_')[1].split('.')[0] for filename in nodes2_files}

# 处理nodes2文件
for filename in nodes2_files:
    chain_name = filename.split('_')[1].split('.')[0]
    filepath = os.path.join(directory, filename)
    with open(filepath, 'r', encoding='utf-8') as file:
        nodes = file.read().strip().split('\n')
    # 为每个节点创建一个DataFrame并添加到列表中
    for node in nodes:
        df = pd.DataFrame({'chain_name': [chain_name], 'nodes': [node]})
        dfs.append(df)

# 处理nodes文件，但只处理那些没有nodes2文件的chain_name
nodes_files = [f for f in os.listdir(directory) if f.startswith('nodes') and f.endswith('.txt')]
for filename in nodes_files:
    chain_name = filename.split('_')[1].split('.')[0]
    if chain_name not in nodes2_chain_names:  # 如果这个chain_name没有对应的nodes2文件
        filepath = os.path.join(directory, filename)
        with open(filepath, 'r', encoding='utf-8') as file:
            nodes = file.read().strip().split('\n')
        # 为每个节点创建一个DataFrame并添加到列表中
        for node in nodes:
            df = pd.DataFrame({'chain_name': [chain_name], 'nodes': [node]})
            dfs.append(df)

# 使用concat合并所有的DataFrame
df_all = pd.concat(dfs, ignore_index=True)

# 将DataFrame保存到Excel文件中
excel_path = 'output3.xlsx'
df_all.to_excel(excel_path, index=False)

print(f'Data has been written to {excel_path}')