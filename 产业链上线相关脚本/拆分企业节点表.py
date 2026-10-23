"""
第八步：这个脚本的功能是拆分企业节点匹配结果。 
---                                                                                                                                                    
  代码逻辑
                                                                                                                                                         
  输入： company_nodes_info_result_0421（上一步的结果）                                                                                                
                                                                                                                                                         
  ┌──────────────┬───────────────────┬───────────────────┬──────────┐                                                                                    
  │ company_name │   matched_nodes   │   match_reason    │  score   │                                                                                    
  ├──────────────┼───────────────────┼───────────────────┼──────────┤                                                                                    
  │ 某公司       │ 节点A;节点B;节点C │ 原因A;原因B;原因C │ 90;85;80 │                                                                                  
  └──────────────┴───────────────────┴───────────────────┴──────────┘                                                                                    
                                                                                                                                                         
  处理： 按 ; 分号拆分                                                                                                                                   
                                                                                                                                                         
  输出： company_nodes_info_result_0421_split                                                                                                            
                                                                                                                                                       
  ┌──────────────┬──────────────┬──────────────┬───────┐                                                                                                 
  │ company_name │ matched_node │ match_reason │ score │                                                                                               
  ├──────────────┼──────────────┼──────────────┼───────┤                                                                                                 
  │ 某公司       │ 节点A        │ 原因A        │ 90    │                                                                                               
  ├──────────────┼──────────────┼──────────────┼───────┤                                                                                                 
  │ 某公司       │ 节点B        │ 原因B        │ 85    │                                                                                                 
  ├──────────────┼──────────────┼──────────────┼───────┤                                                                                                 
  │ 某公司       │ 节点C        │ 原因C        │ 80    │                                                                                                 
  └──────────────┴──────────────┴──────────────┴───────┘                                                                                                 
                                                                                                                                                       
  ---                                                                                                                                                    
  最后一步                                                                                                                                             
                                                                                                                                                         
  UPDATE company_nodes_info_result_0421_split SET score=9999
                                                                                                                                                         
  将所有记录的 score 设置为 9999（可能是标记用途）                                                                                                       
                                                                                                                                                         
  ---                                                                                                                                                    
  作用                                                                                                                                                 
                                                                                                                                                         
  将一行多节点的数据展开为多��，每个节点一行，便于后续分析和统计。 
"""
import os


import pandas as pd
from sqlalchemy import create_engine, text
import mysql.connector
from mysql.connector import Error

# 表名配置
SOURCE_TABLE = "company_nodes_info_result_0421"  #上一步的表
TARGET_TABLE = "company_nodes_info_result_0421_split"  #要更新备份的表

# 数据库连接配置
db_config = {
    'host': '8.141.5.67',
    'user': 'root',
    'password': os.getenv('DB_PASSWORD'),
    'database': 'business_data',
    'port': 3306
}

# 创建SQLAlchemy引擎
engine = create_engine(f"mysql+mysqlconnector://{db_config['user']}:{db_config['password']}@"
                       f"{db_config['host']}:{db_config['port']}/{db_config['database']}")

# 连接到数据库
try:
    connection = mysql.connector.connect(**db_config)
    print("数据库连接成功")

    # 查询数据
    query = f"""
    SELECT company_name, industry_name, matched_nodes, match_reason, score
    FROM {SOURCE_TABLE};
    """
    df = pd.read_sql_query(query, connection)

    # 替换双引号
    df['matched_nodes'] = df['matched_nodes'].str.replace('"', '')
    df['match_reason'] = df['match_reason'].str.replace('"', '')
    df['score'] = df['score'].str.replace('"', '')

    # 按分号或逗号加空格拆分字段，同时处理中文分号和英文分号
    def split_columns(row):
        # 先将 ", " 替换为分号 ";"
        matched_nodes = row['matched_nodes'].replace(", ", ";").replace('；', ';').split(';') if row['matched_nodes'] else []
        match_reason = row['match_reason'].replace(", ", ";").replace('；', ';').split(';') if row['match_reason'] else []
        score = row['score'].replace(", ", ";").replace('；', ';').split(';') if row['score'] else []

        # 按顺序对齐，如果长度不对等，取最后一个分号后的值补齐
        max_length = max(len(matched_nodes), len(match_reason), len(score))
        if len(matched_nodes) < max_length:
            matched_nodes += [matched_nodes[-1] if matched_nodes else ''] * (max_length - len(matched_nodes))
        if len(match_reason) < max_length:
            match_reason += [match_reason[-1] if match_reason else ''] * (max_length - len(match_reason))
        if len(score) < max_length:
            score += [score[-1] if score else ''] * (max_length - len(score))

        rows = []
        for i in range(max_length):
            rows.append({
                'company_name': row['company_name'],
                'industry_name': row['industry_name'],
                'matched_node': matched_nodes[i].strip(),
                'match_reason': match_reason[i].strip(),
                'score': score[i].strip()
            })
        return rows

    # 应用拆分逻辑
    all_rows = []
    for _, row in df.iterrows():
        all_rows.extend(split_columns(row))

    # 将结果转换为DataFrame
    result_df = pd.DataFrame(all_rows)

    # 创建目标表（如果不存在）
    cursor = connection.cursor()
    create_table_query = f"""
    CREATE TABLE IF NOT EXISTS {TARGET_TABLE} (
        company_name VARCHAR(255),
        industry_name VARCHAR(255),
        matched_node VARCHAR(255),
        match_reason TEXT,
        score VARCHAR(255)
    );
    """
    cursor.execute(create_table_query)
    connection.commit()
    cursor.close()

    # 将数据写入目标表（批量插入）
    insert_query = f"""
    INSERT INTO {TARGET_TABLE}
    (company_name, industry_name, matched_node, match_reason, score)
    VALUES (%s, %s, %s, %s, %s)
    """
    cursor = connection.cursor()
    data_to_insert = [tuple(row) for row in result_df.values]
    cursor.executemany(insert_query, data_to_insert)
    connection.commit()
    cursor.close()

    print("数据处理完成并写入目标表")

    # 执行 score 更新命令
    cursor = connection.cursor()
    update_sql = f"UPDATE {TARGET_TABLE} SET score=9999"
    cursor.execute(update_sql)
    connection.commit()
    cursor.close()
    print(f"已执行 UPDATE {TARGET_TABLE} SET score=9999")

except Exception as e:
    print(f"数据库连接或操作失败: {e}")

finally:
    print("数据库连接已关闭")