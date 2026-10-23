"""
第五步：

这个脚本的核心功能是将公司匹配到产业链节点。                                                                                                                                                     
                                                                                                                                                                                                 
  数据来源：                                                                                                                                                                                       
  - ent_industry_class_old：公司及其行业分类信息
  - nodes_industry_mapping_0421：节点与行业的映射关系（上一步的输出）                                                                                                                              
                                                                                                                                                                                                 
  核心逻辑（第 49-85 行）：                                                                                                                                                                        
  公司 → 行业分类 → 节点映射 → 产业链节点                                                                                                                                                          
                                                                                                                                                                                                   
  匹配规则：                                                                                                                                                                                       
  1. 解析公司的 industry_class_third 字段（格式：{"行业A": "强", "行业B": "弱"}）                                                                                                                  
  2. 只匹配 "强" 相关的行业                                                                                                                                                                        
  3. 用正则表达式模糊匹配：full_name 是否包含在公司行业分类中                                                                                                                                      
  4. 匹配成功则记录：公司 → 节点的映射关系                                                                                                                                                         
                                                                                                                                                                                                   
  示例流程：                                                                                                                                                                                       
  公司A的行业分类: {"新能源汽车零部件制造": "强", "食品加工": "弱"}                                                                                                                                
                                                                                                                                                                                                   
  节点映射表中有:                                                                                                                                                                                  
    - "动力电池" → "新能源电池制造"                                                                                                                                                                
                                                                                                                                                                                                   
  匹配: "新能源电池制造" ≈ "新能源汽车零部件制造" ✓                                                                                                                                                
                                                                                                                                                                                                   
  结果: 公司A → "动力电池"节点  
"""
import os

import pandas as pd
from sqlalchemy import create_engine, text
import ast  # 用于将字符串解析为字典
import re  # 用于转义特殊字符

# 数据库连接信息
host = "8.141.5.67"
user = "root"
password = os.getenv("DB_PASSWORD")
database = "business_data"
port = 3306

# 目标表名配置
TARGET_TABLE = "company_nodes_mapping0421"

# 创建数据库连接引擎
engine = create_engine(f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}")

# 自动创建目标表（如果不存在）
def create_table_if_not_exists():
    create_table_sql = f"""
    CREATE TABLE IF NOT EXISTS {database}.{TARGET_TABLE} (
        company_name TEXT,
        credit_code TEXT,
        certainty TEXT,
        industry_name TEXT,
        nodes TEXT,
        name TEXT,
        level TEXT,
        full_name TEXT,
        reason TEXT
    )
    """
    try:
        with engine.connect() as conn:
            conn.execute(text(create_table_sql))
        print(f"表 {TARGET_TABLE} 检查完成，已确保存在")
    except Exception as e:
        print(f"创建表失败：{e}")

# 执行表创建
create_table_if_not_exists()

# 分批次处理 ent_industry_class_old 表
batch_size = 1000  # 每次处理 1000 条数据
query_a = "SELECT company_name, credit_code, certainty, industry_class_third FROM ent_industry_class_old"
query_b = "SELECT industry_name, nodes, name, level, full_name, reason FROM nodes_industry_mapping_0421"#换上一步的结果表

# 获取 ent_industry_class_old 表的总行数
total_rows_a = pd.read_sql("SELECT COUNT(*) AS total FROM ent_industry_class_old", engine)['total'][0]

# 加载 nodes_industry_mapping_0819 表数据到内存
df_b = pd.read_sql(query_b, engine)

# 确保 full_name 是字符串类型
df_b['full_name'] = df_b['full_name'].astype(str)

# 分批次处理 ent_industry_class_old 表
total_batches = (total_rows_a + batch_size - 1) // batch_size

for batch_index in range(total_batches):
    start_row = batch_index * batch_size
    end_row = start_row + batch_size

    # 查询当前批次的 ent_industry_class_old 数据
    batch_query_a = f"{query_a} LIMIT {start_row}, {batch_size}"
    print(batch_query_a)
    df_a_batch = pd.read_sql(batch_query_a, engine)

    # 确保 industry_class_third 是字符串类型
    df_a_batch['industry_class_third'] = df_a_batch['industry_class_third'].astype(str)

    # 初始化一个空的列表来存储匹配结果
    matched_results = []

    # 遍历 df_b 中的每一行
    for index_b, row_b in df_b.iterrows():
        full_name = row_b['full_name']

        # 对 full_name 中的特殊字符进行转义
        escaped_full_name = re.escape(full_name)

        # 遍历当前批次的 df_a_batch 中的每一行
        for index_a, row_a in df_a_batch.iterrows():
            try:
                # 将 industry_class_third 解析为字典
                industry_dict = ast.literal_eval(row_a['industry_class_third'])
            except (ValueError, SyntaxError):
                # 如果解析失败，跳过当前行
                continue

            # 如果解析结果是 None 或空字典，跳过
            if not industry_dict:
                continue

            # 检查 full_name 是否存在于字典的键中，且只匹配"强"相关的行业
            for key, strength in industry_dict.items():
                if re.search(escaped_full_name, key) and strength == '强':
                    # 如果匹配成功且为强相关，将结果添加到匹配列表中
                    combined_row = {
                        'company_name': row_a['company_name'],
                        'credit_code': row_a['credit_code'],
                        'certainty': row_a['certainty'],
                        'industry_name': row_b['industry_name'],
                        'nodes': row_b['nodes'],
                        'name': row_b['name'],
                        'level': row_b['level'],
                        'full_name': row_b['full_name'],
                        'reason': row_b['reason']
                    }
                    print(combined_row)
                    matched_results.append(combined_row)
                    break  # 匹配成功后，不再检查其他键

    # 将当前批次的匹配结果转换为 DataFrame
    if matched_results:
        result_df_batch = pd.DataFrame(matched_results)
        try:
            table_name = TARGET_TABLE
            result_df_batch.to_sql(table_name, engine, index=False, if_exists='append', chunksize=1000)
            print(f"第 {batch_index + 1}/{total_batches} 批次处理完成，插入 {len(result_df_batch)} 条记录")
        except Exception as e:
            print(f"插入失败，错误信息：{e}")

print(f"所有数据已处理完毕并插入到表 {TARGET_TABLE} 中")