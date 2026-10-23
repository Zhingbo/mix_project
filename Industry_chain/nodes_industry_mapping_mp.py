"""
第四步：
  1. 获取数据                                                                                                                                            
    - 从 chain_needcomp0421 表读取"氢能产业"的所有节点                                                                                                 
    - 从 mapping_industry_info_new 表读取标准行业分类库                                                                                                  
  2. AI 匹配（核心逻辑，第 165-196 行）                                                                                                                  
    - 使用通义千问分析节点与行业的关系                                                                                                                   
    - 匹配关系类型：                                                                                                                                     
        - 包含关系：节点是行业的一部分（如：伺服器 → 伺服器生产制造）                                                                                    
      - 组成关系：节点是行业的组成部分（如：伺服器 → 机器人零部件制造）                                                                                  
      - 相似关系：语义相似（如：原材料 → 新材料）                                                                                                        
      - 同类关系：同一类别（如：锂电池 → 新能源电池制造）                                                                                                
  3. 保存结果                                                                                                                                            
    - 匹配结果写入 nodes_industry_mapping_0421 表                                                                                                        
    - 包含字段：节点名称、行业名称、行业层级、全称、所属产业链、匹配原因
"""
import os

import json
from openai import OpenAI
import pandas as pd
import time
import mysql.connector
from mysql.connector import Error
from zhipuai import ZhipuAI
from multiprocessing import Process, Pool

# 配置行业名称和文件路径
industry_names = [
        # "3D打印","低空经济","仪器仪表","机器人","船舶",
        # "人形机器人","集成电路","卫星导航","无人机","生命健康",
        # "合成生物","光伏","储能","跨境电商","工业软件""新能源汽车","检验检测","仪表仪器"
        "氢能产业"
]

# OpenAI API配置
sandro_api_key = os.getenv('DEEPSEEK_API_KEY')
zhipukey = '82be19c96af3da40cdf125044e349811.16lEnft5oNRMIeOb'

# 初始化OpenAI客户端
client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

# 数据库连接配置
def connect_to_mysql():
    try:
        cnx = mysql.connector.connect(
            user='root',
            password=os.getenv('DB_PASSWORD'),
            host='8.141.5.67',
            database='business_data'
        )
        return cnx
    except Error as err:
        print(f"无法连接到数据库：{err}")
        return None

# 从数据库获取数据
def get_data_from_mysql(query):
    cnx = connect_to_mysql()
    if not cnx:
        return None
    cursor = cnx.cursor()
    try:
        cursor.execute(query)
        columns = [col[0] for col in cursor.description]  # 获取列名
        data = cursor.fetchall()
        df = pd.DataFrame(data, columns=columns)
        return df
    except Error as err:
        print(f"查询数据时出错：{err}")
    finally:
        cursor.close()
        cnx.close()
    return None

# 创建表
def create_table(cnx):
    cursor = cnx.cursor()
    create_table_query = """
    CREATE TABLE IF NOT EXISTS nodes_industry_mapping_0421 (
        id INT AUTO_INCREMENT PRIMARY KEY,
        nodes VARCHAR(255),
        name VARCHAR(255),
        level VARCHAR(255),
        full_name VARCHAR(255),
        industry_name VARCHAR(255), 
        reason TEXT
    )
    """
    try:
        cursor.execute(create_table_query)
        cnx.commit()
        print("表 nodes_industry_mapping_0421 创建成功或已存在。")
    except Error as err:
        print(f"创建表时出错：{err}")
    finally:
        cursor.close()

# 插入数据
def insert_data(cnx, data):
    cursor = cnx.cursor()
    insert_query = """
    INSERT INTO nodes_industry_mapping_0421 (nodes, name, level, full_name, industry_name, reason)
    VALUES (%s, %s, %s, %s, %s, %s)
    """
    try:
        cursor.executemany(insert_query, data)
        cnx.commit()
        print(f"成功插入 {cursor.rowcount} 条数据。")
    except Error as err:
        print(f"插入数据时出错：{err}")
    finally:
        cursor.close()

# 匹配节点到行业
def match_node_to_industry(client, system_prompt_new, node):
    response = client.chat.completions.create(
        model="deepseek-v4-pro",
        messages=[
            {'role': 'system', 'content': system_prompt_new},
            {'role': 'user', 'content': node}
        ],
        response_format={"type": "json_object"}
    )    
    return response.choices[0].message.content

def process_industry(industry_name):
    print(f"开始处理行业：{industry_name}")

    # 连接到数据库
    cnx = connect_to_mysql()
    if not cnx:
        print(f"无法连接到数据库，程序将退出。")
        return

    # 确保表已创建
    create_table(cnx)

    # 初始化查询语句
    query_nodes = f"""
    SELECT DISTINCT nodes FROM chain_needcomp0421
    WHERE chain_name = '{industry_name}'
    """

    # 用于标记是否是第一次执行
    first_run = True

    while True:
        # 如果不是第一次执行，添加额外的条件
        if not first_run:
            query_nodes = f"""
            SELECT DISTINCT nodes FROM chain_needcomp0421
            WHERE chain_name = '{industry_name}'
            AND nodes IN (SELECT nodes FROM nodes_industry_mapping_0421 WHERE full_name IS NULL AND industry_name = '{industry_name}')
            """
        first_run = False  # 更新标记

        df_nodes = get_data_from_mysql(query_nodes)
        if df_nodes is None or df_nodes.empty:
            print(f"行业 {industry_name} 没有更多未处理的产业链节点，退出循环。")
            break

        nodes = df_nodes['nodes'].tolist()
        print(f"行业 {industry_name} 的未处理产业链节点：", nodes)

        # 从MySQL数据库获取行业打标结构化的数据
        query = """
        SELECT DISTINCT name, level, full_name FROM mapping_industry_info_new
        """
        df = get_data_from_mysql(query)
        if df is None:
            print("未成功获取数据，程序将退出。")
            return

        # 构建名字信息字典
        name_info = {row['name']: (row['level'], row['full_name']) for _, row in df.iterrows()}

        # 构建匹配逻辑的系统提示
        names = df['name'].tolist()
        system_prompt_new = f'''你是一个行业分析专家，也是一个产业链知识专家。
        我会给你需要匹配的产业链节点名称{nodes}，你的任务是为每个节点在已有的行业名称库{names}中找到与{industry_name}相关的1个最匹配的行业名称，并给出你的匹配原因。

        具体匹配逻辑为：
        - 节点与行业名称之间可能是以下关系之一：包含关系、组成关系、相似关系、同类关系。你需要根据这些关系找到与节点最为相关的行业名称。
        - 下面是每种关系的具体含义：
        - **包含关系**：节点是行业名称的一部分。例如，节点“伺服器”包含于行业名称“伺服器生产制造”。
        - **组成关系**：节点是行业的组成部分。例如，节点“伺服器”是“机器人零部件制造”的组成部分。
        - **相似关系**：节点与行业名称在语义或功能用途上相似。例如，节点“原材料”与行业名称“新材料”语义相似。
        - **同类关系**：节点与行业名称属于同一类别。例如，节点“锂电池”与行业名称“新能源电池制造”属于同一类别。

        示例：
        - 有一个节点名称是“伺服器”，你分析出伺服器是机器人的核心零部件之一，你在行业名称库{names}中根据组成关系找到“机器人零部件制造”是最匹配最相关的行业名称。

        注意：
        - 如果存在多个行业名称与节点相关，优先选择更具体、更直接相关的行业名称（例如"机器人零部件制造"优于"机械制造"）。
        - 在匹配过程中，还需要考虑节点在产业链中的位置，例如上游原材料、中游零部件、下游终端产品等，以确保匹配的合理性。
        - **重要：你只能在行业名称库{names}中选择行业名称，严禁创造或使用不在库中的行业名称。即使找不到完美匹配，也必须从库中选择最接近的一个。**

        最后请你以JSON格式返回结果，例如：
        {{
            "节点名称": "伺服器",
            "行业名称": "机器人零部件制造",
            "匹配原因": "伺服器是机器人的核心零部件之一，与机器人零部件制造这个行业名称最相关。"
        }}

        注意：
        1.返回结果中的属性名一定要用双引号括起来！如 "节点名称".
        2.返回结果中的属性值也一定要用双引号括起来！如 "伺服器".

        现在，请根据上述要求开始匹配：
        '''

        # 执行匹配逻辑
        results = []
        failed_nodes = []  # 用于记录匹配失败的节点
        invalid_results = []  # 用于记录行业名称不在库中的结果
        for node in nodes:
            if node not in [industry_name, '上游', '中游', '下游']:
                try:
                    result = match_node_to_industry(client, system_prompt_new, node)
                    # 确保返回的字符串是有效的 JSON 格式
                    try:
                        result = json.loads(result.replace("```", "").replace("json", ""))
                        # 验证行业名称是否在库中
                        if result['行业名称'] in name_info:
                            results.append(result)
                            print(result)
                        else:
                            print(f"警告：AI返回的行业名称 '{result['行业名称']}' 不在行业名称库中，节点：{node}")
                            invalid_results.append((node, result))
                            failed_nodes.append((node, f"返回的行业名称不在库中：{result['行业名称']}"))
                    except json.JSONDecodeError as e:
                        print(f"JSON解析错误：{e}，节点：{node}")
                        failed_nodes.append((node, f"JSON解析错误：{e}"))
                except Exception as e:
                    print(f"匹配节点时发生异常：{e}，节点：{node}")
                    failed_nodes.append((node, f"异常：{e}"))

        print(f"行业 {industry_name} 的匹配结果：", results)

        # 保存匹配失败的节点到文件
        failed_nodes_file_path = f'resultTxt/failed_nodes_{industry_name}.txt'
        with open(failed_nodes_file_path, 'w', encoding='utf-8') as file:
            for node, reason in failed_nodes:
                file.write(f"节点：{node}, 原因：{reason}\n")
        print(f"行业 {industry_name} 匹配失败的节点已保存到文件：{failed_nodes_file_path}")

        # 准备插入的数据
        data_to_insert = [
            (
                item['节点名称'],
                item['行业名称'],
                name_info.get(item['行业名称'], (None, None))[0],  # level
                name_info.get(item['行业名称'], (None, None))[1],  # full_name
                industry_name,
                item['匹配原因']
            )
            for item in results
        ]

        # 插入数据
        insert_data(cnx, data_to_insert)
        print(f"行业 {industry_name} 的数据已成功插入数据库。")

    # 数据去重处理
    print(f"开始对行业 {industry_name} 进行数据去重...")
    cursor = cnx.cursor()
    try:
        target_table = "nodes_industry_mapping_0421"
        final_table = f"{target_table}_final"

        # 1. 创建去重后的临时表
        dedupe_sql = f"""
        CREATE TABLE {final_table} AS
        WITH RankedData AS (
            SELECT nodes, name, level, full_name, industry_name, reason,
                   ROW_NUMBER() OVER (PARTITION BY nodes, industry_name ORDER BY full_name DESC) AS rn
            FROM {target_table}
            WHERE industry_name = '{industry_name}'
        )
        SELECT nodes, name, level, full_name, industry_name, reason
        FROM RankedData
        WHERE rn = 1
        """
        cursor.execute(dedupe_sql)
        cnx.commit()
        print(f"创建去重临时表 {final_table} 成功")

        # 2. 删除原表中该行业的数据
        delete_sql = f"DELETE FROM {target_table} WHERE industry_name = %s"
        cursor.execute(delete_sql, (industry_name,))
        cnx.commit()
        print(f"删除原表中的 {industry_name} 数据成功")

        # 3. 将去重后的数据插回原表
        insert_back_sql = f"""
        INSERT INTO {target_table} (nodes, name, level, full_name, industry_name, reason)
        SELECT nodes, name, level, full_name, industry_name, reason FROM {final_table}
        """
        cursor.execute(insert_back_sql)
        cnx.commit()
        print(f"去重后数据插回原表成功")

        # 4. 删除临时表
        cursor.execute(f"DROP TABLE IF EXISTS {final_table}")
        cnx.commit()
        print(f"删除临时表 {final_table} 成功")

        # 验证去重结果
        cursor.execute(f"SELECT COUNT(*) FROM {target_table} WHERE industry_name = %s", (industry_name,))
        final_count = cursor.fetchone()[0]
        print(f"行业 {industry_name} 去重后记录数: {final_count}")

    except Error as err:
        print(f"去重处理时出错：{err}")
        cnx.rollback()
    finally:
        cursor.close()

    # 关闭数据库连接
    cnx.close()

def worker(industry_name):
    process_industry(industry_name)

if __name__ == '__main__':
    start_time = time.time()

    # 创建进程池
    pool = Pool(processes=50)

    # 使用进程池处理每个行业名称
    pool.map(worker, industry_names)

    # 关闭进程池
    pool.close()
    pool.join()

    end_time = time.time()
    print(f"代码运行总时间：{end_time - start_time}")
