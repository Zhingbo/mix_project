"""
第7步：

这个脚本的核心功能是将头部企业（AI搜索出的龙头企业）匹配到产业链节点。                                                                                 
                                                                                                                                                       
  ---                                                                                                                                                    
  完整工作流程
                                                                                                                                                         
  ┌─────────────────────────────────────────────────────────────┐                                                                                      
  │  第一步：数据预处理 (preprocess_data)                         │                                                                                      
  │  1. 清理换行符 (industry_chain_topcompanies0421)            │                                                                                        
  │  2. 创建过滤表 (排除已匹配的公司)                            │                                                                                       
  └─────────────────────────────────────────────────────────────┘                                                                                        
                            ↓                                                                                                                            
  ┌─────────────────────────────────────────────────────────────┐                                                                                        
  │  第二步：获取企业信息                                        │                                                                                       
  │  数据来源：                                                  │                                                                                       
  │  - topcompany_filtered_0421 (头部企业名单)                  │                                                                                        
  │  - company_product_detail_info (企业详细信息库)             │                                                                                        
  │  缺失信息 → Jina API 搜索获取                               │                                                                                        
  └─────────────────────────────────────────────────────────────┘                                                                                        
                            ↓                                                                                                                            
  ┌─────────────────────────────────────────────────────────────┐                                                                                        
  │  第三步：AI 节点匹配 (deepseek-v4-pro)                             │ 
  │  输入：公司名称 + 简介 + 主营产品 + 节点定义                 │                                                                                       
  │  输出：匹配的节点（最多20个）+ 匹配原因 + 分数               │                                                                                       
  └─────────────────────────────────────────────────────────────┘                                                                                        
                            ↓                                                                                                                            
  ┌─────────────────────────────────────────────────────────────┐                                                                                        
  │  第四步：保存结果                                            │                                                                                       
  │  保存到：company_nodes_info_result_0421                     │                                                                                        
  └─────────────────────────────────────────────────────────────┘                                                                                        
                                                                                                                                                         
  ---                                                                                                                                                    
  关键字段说明                                                                                                                                           
                                                                                                                                                         
  ┌───────────┬──────────────────────────────────────────────────┐
  │   字段    │                       说明                       │                                                                                       
  ├───────────┼──────────────────────────────────────────────────┤                                                                                       
  │ certainty │ 置信度：1(最高) → 4(最低)                        │                                                                                       
  ├───────────┼──────────────────────────────────────────────────┤                                                                                       
  │ 分数区间  │ certainty=1: 75-100, 2: 51-74, 3: 26-50, 4: 0-25 │                                                                                       
  ├───────────┼──────────────────────────────────────────────────┤                                                                                       
  │ 匹配节点  │ 最多 20 个，用";"分隔                            │                                                                                       
  ├───────────┼──────────────────────────────────────────────────┤                                                                                       
  │ 匹配原因  │ 每个节点的匹配原因，用";"分隔                    │                                                                                     
  └───────────┴──────────────────────────────────────────────────┘
"""

import json
from openai import OpenAI
import pandas as pd
from multiprocessing import set_start_method
from concurrent.futures import ProcessPoolExecutor, as_completed
import time
import mysql.connector
import math
import os
import requests
from bs4 import BeautifulSoup

# API 密钥
zlc_api_key = os.getenv('DEEPSEEK_API_KEY_LC')
sandro_api_key = os.getenv('DEEPSEEK_API_KEY')
mh_api_key = os.getenv('DEEPSEEK_API_KEY_MH')
gy_api_key = os.getenv('DEEPSEEK_API_KEY_GY')

# Jina API配置
jina_api_key = os.getenv("JINA_API_KEY_B")

# 行业名称
industry_names = [
        "氢能产业"
        ]  # 可以更换行业名称

# 表名配置
TOPCOMPANY_TABLE = "industry_chain_topcompanies0421"
FILTERED_TABLE = "topcompany_filtered_0421"
MAPPING_TABLE = "company_nodes_mapping0421"
RESULT_TABLE = "company_nodes_info_result_0421"
CHAIN_TABLE = "chain_needcomp0421"

# 数据库连接配置
db_config = {
    "host": "8.141.5.67",
    "user": "root",
    "password": os.getenv("DB_PASSWORD"),
    "database": "business_data",
    "port": 3306
}

def fetch_company_info_from_jina(company_name: str, industry_name: str) -> dict:
    """
    使用Jina API搜索公司信息，获取公司简介和主营产品
    """
    try:
        # 搜索该公司信息
        search_url = "https://s.jina.ai/"
        headers = {
            'Authorization': f'Bearer {jina_api_key}',
            'X-Respond-With': 'no-content',
            'Accept': 'application/json; charset=utf-8'
        }
        search_query = f"{company_name} 官网 公司简介 主营产品"

        response = requests.get(
            search_url,
            headers=headers,
            params={'q': search_query},
            proxies={'https': 'socks5://127.0.0.1:7891', 'http': 'socks5://127.0.0.1:7891'},
            timeout=30
        )

        if response.status_code == 200:
            response.encoding = 'utf-8'

            # 解析搜索结果，提取公司信息
            search_results = []
            current_result = {}

            for line in response.text.split('\n'):
                line = line.strip()
                if not line:
                    if current_result:
                        search_results.append(current_result)
                        current_result = {}
                    continue

                if 'URL Source:' in line:
                    current_result['URL Source'] = line.split('URL Source:')[1].strip()
                elif 'Description:' in line:
                    current_result['Description'] = line.split('Description:')[1].strip()
                elif 'Title:' in line:
                    current_result['Title'] = line.split('Title:')[1].strip()

            if current_result:
                search_results.append(current_result)

            # 使用AI模型从搜索结果中提取结构化信息
            if search_results:
                # 构建上下文信息
                context_parts = []
                for result in search_results[:3]:  # 只使用前3个结果
                    if 'Description' in result:
                        context_parts.append(f"搜索描述: {result['Description']}")
                    if 'Title' in result:
                        context_parts.append(f"标题: {result['Title']}")

                context = "\n".join(context_parts)

                # 使用AI模型提取公司信息
                client = OpenAI(
                    api_key=os.getenv("DASHSCOPE_API_KEY"),
                    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
                )

                prompt = f"""根据以下搜索结果，提取公司"{company_name}"的详细信息：

{context}

请以JSON格式返回：
{{
    "company_intro": "公司简介（100-200字）",
    "major_product": "主营产品或业务（50-100字）"
}}

注意：
1. 如果搜索结果中没有足够信息，请基于公司名称和行业"{industry_name}"给出合理的描述
2. company_intro应该描述公司的基本情况、成立时间、规模等
3. major_product应该列出公司的主要产品或服务
4. 确保返回的是纯JSON格式，不要有其他文字"""

                try:
                    ai_response = client.chat.completions.create(
                        model="deepseek-v4-pro",
                        messages=[
                            {'role': 'system', 'content': '你是一个专业的企业信息提取专家。'},
                            {'role': 'user', 'content': prompt}
                        ],
                        temperature=0.3,
                        response_format={"type": "json_object"}
                    )

                    result_text = ai_response.choices[0].message.content
                    result_text = result_text.replace("```json", "").replace("```", "").strip()
                    extracted_info = json.loads(result_text)

                    return {
                        'company_intro': extracted_info.get('company_intro', '暂无简介'),
                        'major_product': extracted_info.get('major_product', '暂无主营产品信息'),
                        'certainty': '2'  # 从网络搜索获取的，默认置信度为2
                    }
                except Exception as e:
                    print(f"AI提取失败 ({company_name}): {str(e)}")

            # 如果AI提取失败，返回基本描述
            return {
                'company_intro': f"{company_name}是{industry_name}行业的企业。",
                'major_product': f"从事{industry_name}相关业务",
                'certainty': '3'
            }
        else:
            print(f"Jina搜索失败: {response.status_code}")
            return {
                'company_intro': "暂无简介",
                'major_product': "暂无主营产品信息",
                'certainty': '4'
            }

    except Exception as e:
        print(f"获取公司信息时出错 ({company_name}): {str(e)}")
        return {
            'company_intro': "暂无简介",
            'major_product': "暂无主营产品信息",
            'certainty': '4'
        }

def get_data_from_mysql(query):
    try:
        cnx = mysql.connector.connect(**db_config)
        cursor = cnx.cursor(dictionary=True)
        cursor.execute(query)
        result = cursor.fetchall()
        cursor.close()
        cnx.close()
        return result
    except mysql.connector.Error as err:
        print("Something went wrong: {}".format(err))
        return None

def get_nodes_and_definitions(industry_name):
    query = f"""
    SELECT nodes, nodes_definition
    FROM {CHAIN_TABLE}
    WHERE chain_name = '{industry_name}'
    """
    result = get_data_from_mysql(query)
    if result:
        # 初始化节点列表和节点定义字典
        nodes = []
        nodes_definitions = {}
        
        # 遍历查询结果，提取所有节点及其定义
        for row in result:
            node_list = row.get('nodes', '').split(',')
            definition = row.get('nodes_definition', '').strip()
            for node in node_list:
                node = node.strip()  # 去除可能的空格
                if node:
                    nodes.append(node)
                    nodes_definitions[node] = definition
        
        # 去除重复的节点
        nodes = list(set(nodes))
        
        return nodes, nodes_definitions
    else:
        # 如果没有找到匹配的记录，返回空列表和空字典
        print(f"未找到行业名称为 '{industry_name}' 的节点和定义信息。")
        return [], {}
    
def preprocess_data():
    """
    预处理数据：执行 SQL 命令
    1. 清理 industry_chain_topcompanies 表中 company_name 的换行符
    2. 创建过滤表，排除已匹配的企业
    """
    try:
        cnx = mysql.connector.connect(**db_config)
        cursor = cnx.cursor()

        print("=" * 60)
        print("开始数据预处理...")
        print("=" * 60)

        # 步骤1: 清理换行符
        print(f"\n[1/2] 清理 {TOPCOMPANY_TABLE} 表中的换行符...")
        update_sql = f"""
        UPDATE {TOPCOMPANY_TABLE}
        SET company_name = REPLACE(REPLACE(company_name, '\n', ''), '\r', '')
        WHERE company_name LIKE '%\n%' OR company_name LIKE '%\r%'
        """
        cursor.execute(update_sql)
        cleaned_count = cursor.rowcount
        cnx.commit()
        print(f"    清理完成，影响行数: {cleaned_count}")

        # 验证是否清理干净
        check_sql = f"""
        SELECT COUNT(*) FROM {TOPCOMPANY_TABLE}
        WHERE company_name LIKE '%\n%' OR company_name LIKE '%\r%'
        """
        cursor.execute(check_sql)
        remaining = cursor.fetchone()[0]
        if remaining > 0:
            print(f"    警告: 仍有 {remaining} 行包含换行符")
        else:
            print(f"    验证通过: 无换行符残留")

        # 步骤2: 创建过滤表
        print(f"\n[2/2] 创建过滤表 {FILTERED_TABLE}...")
        drop_sql = f"DROP TABLE IF EXISTS {FILTERED_TABLE}"
        cursor.execute(drop_sql)

        create_sql = f"""
        CREATE TABLE {FILTERED_TABLE} AS
        SELECT industry_chain, company_name
        FROM {TOPCOMPANY_TABLE} a
        WHERE NOT EXISTS(
            SELECT 1
            FROM {MAPPING_TABLE} b
            WHERE a.company_name = b.company_name COLLATE utf8mb4_unicode_ci
              AND b.industry_name = a.industry_chain COLLATE utf8mb4_unicode_ci
        )
        """
        cursor.execute(create_sql)
        cnx.commit()

        # 统计过滤后的数据量
        count_sql = f"SELECT COUNT(*) FROM {FILTERED_TABLE}"
        cursor.execute(count_sql)
        filtered_count = cursor.fetchone()[0]
        print(f"    过滤表创建成功，共 {filtered_count} 家企业待处理")

        print("\n" + "=" * 60)
        print("数据预处理完成！")
        print("=" * 60 + "\n")

    except mysql.connector.Error as err:
        print(f"预处理出错: {err}")
    finally:
        cursor.close()
        cnx.close()

def get_rules(industry_name):
    rules_file_path = f'materials/rules_list_{industry_name}.txt'
    if os.path.exists(rules_file_path):
        with open(rules_file_path, 'r', encoding='utf-8') as file:
            return file.read().splitlines()
    return []

def validate_matching_nodes(matching_nodes, nodes):
    valid_nodes = [node for node in matching_nodes if node in nodes]
    return valid_nodes

def create_table_if_not_exists():
    try:
        cnx = mysql.connector.connect(**db_config)
        cursor = cnx.cursor()
        create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS {RESULT_TABLE} (
            company_name    TEXT NULL,
            ai_company_name TEXT NULL,
            major_product   LONGTEXT NULL,
            company_intro   LONGTEXT NULL,
            matched_nodes   TEXT NULL,
            match_reason    LONGTEXT NULL,
            certainty       TEXT NULL,
            score           TEXT NULL,
            industry_name   TEXT NULL
        );
        """
        cursor.execute(create_table_sql)
        print(f"表 {RESULT_TABLE} 已创建或已存在。")
    except mysql.connector.Error as err:
        print(f"创建表时出错: {err}")
    finally:
        cursor.close()
        cnx.close()

def insert_into_database(data_list):
    try:
        cnx = mysql.connector.connect(**db_config)
        cursor = cnx.cursor()
        sql = f"""
        INSERT INTO {RESULT_TABLE} (company_name, ai_company_name, major_product, company_intro, matched_nodes, match_reason, certainty, score, industry_name)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        for data in data_list:
            company_name = data.get('原始公司名', '未知') or '未知'
            ai_company_name = data.get('企业名称', '未知') or '未知'
            major_product = json.dumps(data.get('主营产品', '未知'), ensure_ascii=False) if data.get('主营产品') else '未知'
            company_intro = json.dumps(data.get('公司简介', '未知'), ensure_ascii=False) if data.get('公司简介') else '未知'
            matched_nodes = json.dumps(data.get('匹配节点', '未知'), ensure_ascii=False) if data.get('匹配节点') else '未知'
            match_reason = json.dumps(data.get('匹配原因', '未知'), ensure_ascii=False) if data.get('匹配原因') else '未知'
            certainty = data.get('置信度', '未知') or '未知'
            score = data.get('分数', '未知') or '未知'
            industry_name = data.get('产业链名称', '未知') or '未知'
            values = (company_name, ai_company_name, major_product, company_intro, matched_nodes, match_reason, certainty, score, industry_name)
            cursor.execute(sql, values)
        cnx.commit()
        print("Data inserted successfully")
    except Exception as e:
        print(f"插入数据库时出错: {e}")
    finally:
        cursor.close()
        cnx.close()
        print("MySQL connection is closed")

def process_row_new(row, nodes, rules, system_prompt_new, industry_name, nodes_definition):
    words_json = {
        'nodes': nodes,
        'company_name': row['company_name'],
        'company_intro': row['company_intro'],
        'major_product': row['major_product'],
        'rules': rules,
        'certainty': str(row['certainty']),
        'trd_industry': row['trd_industry'],
        'industry_name': industry_name,
        'nodes_definition': nodes_definition
    }
    client = OpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    response = client.chat.completions.create(
        model="deepseek-v4-pro",
        messages=[
            {'role': 'system', 'content': system_prompt_new},
            {'role': 'user', 'content': json.dumps(words_json, ensure_ascii=False)}
        ],
        temperature=0.6,
        response_format={"type": "json_object"}
    )
    try:
        result = response.choices[0].message.content
        # print(f"模型返回结果: {result}")  # 打印模型返回的结果
        return result
    except Exception as e:
        print(f"Error processing row: {e}")
        return None

def process_data_batch(data_batch, industry_name, nodes,rules, nodes_definitions):
    results = []
    # 确保提示词中包含所有节点及其定义
    nodes_str = ", ".join(nodes)  # 将所有节点以逗号分隔的形式拼接成字符串
    print(f"传入提示词的节点: {nodes_str}")
    nodes_definitions_str = "; ".join([f"{node}: {nodes_definitions[node]}" for node in nodes])  # 将所有节点及其定义拼接成字符串
    print(f"传入提示词的节点定义: {nodes_definitions_str}")
    system_prompt_new = f'''你是一个产业链分析专家，也是一个构建产业链知识图谱的专家。
                    以下是公司名称(company_name)，公司简介(company_intro)，公司主营产品(major_product)，置信度(certainty)，产业链名称(industry_name)，行业分类(trd_industry)，节点二级名称(nodes_referlv2)和节点三级名称(nodes_referlv3)，我会以Json形式给出：
                    {{
                        "company_name":"{data_batch['company_name'].iloc[0]}",
                        "company_intro":"{data_batch['company_intro'].iloc[0]}",
                        "major_product":"{data_batch['major_product'].iloc[0]}",
                        "certainty":"{data_batch['certainty'].iloc[0]}",
                        "industry_name":"{industry_name}",
                        "trd_industry":"{data_batch['trd_industry'].iloc[0]}",
                        "nodes_referlv2":"{data_batch.get('nodes_referlv2', '').iloc[0] if 'nodes_referlv2' in data_batch.columns else ''}",
                        "nodes_referlv3":"{data_batch.get('nodes_referlv3', '').iloc[0] if 'nodes_referlv3' in data_batch.columns else ''}"                        
                    }}
                    你的任务是根据公司简介(company_intro)，公司主营产品(major_product)，节点二级名称(nodes_referlv2)和节点三级名称(nodes_referlv3)，并结合上节点({nodes_str})的定义({nodes_definitions_str})在已有的产业链节点({nodes_str})中找到至少1个最匹配的节点并对每个匹配上的节点都分别给出你的匹配原因，如果匹配上多个节点用";"分隔开，每个节点的匹配原因也用";"分隔开。
                    **重要限制：最多只能匹配20个节点！请选择分数最高、最相关的前20个节点即可。**
                    然后你还需要为每个匹配上的节点打出一个分数，即这个企业匹配上该节点的准确度分数。打这个分数的时候你需要参考下我上边给你的置信度(certainty)，置信度1的准确性最高，往后依次是2，3，4。所以对于置信度为1的，你给的分数区间在75-100，对于置信度为2的，你给的分数区间在51-74，对于置信度为3的，你给的分数区间在26-50，对于置信度为4的，你给的分数区间在0-25。每个节点的分数用";"分隔开。
                    节点具体匹配逻辑为：
                        - 首先，你先去主营产品中找与"{industry_name}"相关的产品描述，结合节点定义({nodes_definitions_str})再去已有的产业链节点({nodes_str})中找能匹配上的节点，匹配规则是产品描述和已有的产业链节点({nodes_str})之间可能是包含关系，组成关系或者关联关系。
                        - 如果你发现主营产品中与"{industry_name}"相关的产品描述太过于宽泛不具体，比如主营产品就只有"{industry_name}"，那么你需要去公司简介(company_intro)中找到这家公司是做什么的，根据这家公司是做什么的，公司的业务，产品描述，结合节点定义({nodes_definitions_str})再去已有的产业链节点({nodes_str})中找能匹配上的节点，匹配规则是公司简介描述的内容和已有的产业链节点({nodes_str})之间可能是包含关系，组成关系或者关联关系。
                        - 如果节点二级名称(nodes_referlv2)或者节点三级名称(nodes_referlv3)有内容，那么对比他们和节点({nodes_str})哪一个或哪几个有相关性，在已有的产业链节点({nodes_str})中找到能匹配上的节点，匹配规则为语义相近。注意：要从({nodes_str})中选择节点返回到输出结果中，而不能将节点二级名称(nodes_referlv2)或者节点三级名称(nodes_referlv3)返回到结果中。
                        - 如果公司简介(company_intro)和公司主营产品(major_product)中都没有内容，那么你需要根据公司名称(company_name)和你的分析技能，并结合节点定义({nodes_definitions_str})去已有的产业链节点({nodes_str})中找能匹配上的节点。
                        - 不要匹配"上游","中游","下游"以及"{industry_name}"这四个节点。
                        - 请你严格遵守我提供的硬规则{rules}中的内容。
                        - 每一个公司一定能匹配上节点({nodes_str})中至少一个节点。如果你没有匹配上那么重新进行分析直到匹配上至少一个节点为止。
                        - 匹配节点一定不能是产业链名称"{industry_name}"，也不要是“上游”，“中游”，“下游”任何一个。
                        - 匹配节点不可以为空，不可以为null，不可以为None，不可以为“无”，一定会有匹配上的节点。
                    请你以JSON格式返回结果，例如：
                    {{
                        "企业名称": "广州宇曦电子科技有限公司",
                        "主营产品": "锂电池充电器",
                        "公司简介": "广州宇曦电子科技有限公司是国内一家专业定制化电源及测试系统的高新技术企业，公司集研发、生产、销售、服务于一体。",
                        "匹配节点": "充电设施;销售与服务",
                        "匹配原因": "匹配上节点充电设施的原因为主营产品中的锂电池充电器是充电设施中的一个重要组成部分;匹配上节点销售与服务的原因为公司简介中提到公司集研发、生产、销售、服务于一体。",
                        "置信度":"1",
                        "分数": "96;99",
                        "产业链名称": "新能源汽车"
                    }}
                    特别注意：
                    1.结果中的"匹配节点"只返回我提供的产业链节点中存在的节点({nodes_str})，不要出现主营产品中提到的但是我提供的产业链节点中({nodes_str})不存在的，也不要出现公司简介中提到的但是我提供的产业链节点({nodes_str})中不存在的。
                    2.你要严格在我提供的产业链节点({nodes_str})中去匹配，不要自行总结或推断新的节点，导致匹配节点不在我提供的产业链节点中。
                    4.结果中的"certainty"是我上边给你的信息中的置信度(certainty)，值为1,2,3,4这四个整数其中一个，不要出现小数的格式比如1.0。
                    5.结果中的"匹配节点"不要有重复的节点，不要无限输出。**最多只返回20个最相关的节点！**
                    6.结果中的"公司简介"不要无限输出，控制在200字以内！
                    7.结果中的"匹配原因"不要无限输出，每个节点的匹配原因控制在50字以内！
                    8.返回结果中的键的名字只能是"企业名称"，"主营产品"，"公司简介"，"匹配节点"，"匹配原因"，"置信度"，"分数"，"产业链名称",不可以是别的！
                    9.返回结果中的"产业链名称"是我上边给你的信息中的产业链名称"{industry_name}"。
                    10.匹配节点一定不能是产业链名称"{industry_name}"，也不要是“上游”，“中游”，“下游”任何一个.
                    11.匹配节点不可以为空，不可以为null，不可以为None，不可以为“无”，一定会有匹配上的节点.
                    12.不能将节点二级名称(nodes_referlv2)或者节点三级名称(nodes_referlv3)返回到结果中，除非是({nodes_str})中有完全一样的节点名称，否则要在({nodes_str})中找到一个近似匹配节点.
                    需要再次强调的是，绝对不能出现匹配节点({nodes_str})以外的节点！下面开始：
        '''
    for index, row in data_batch.iterrows():
        print(f"正在处理公司: {row['company_name']}")  # 打印正在处理的公司名称
        result = process_row_new(row, nodes, rules, system_prompt_new, industry_name, nodes_definitions)
        if result is not None:
            # 将原始公司名和结果一起返回
            results.append((row['company_name'], result))
    return results

if __name__ == '__main__':
    set_start_method('spawn')
    start_time = time.time()

    # 执行数据预处理（清理换行符 + 创建过滤表）
    preprocess_data()

    # 创建表（如果不存在）
    create_table_if_not_exists()

    # 遍历所有行业名称
    for industry_name in industry_names:
        print(f'Processing {industry_name}')
        
        # 获取行业相关的nodes和rules
        nodes, nodes_definition = get_nodes_and_definitions(industry_name)
        rules = get_rules(industry_name)
        print(f'强规则信息： {rules}')

        # 数据处理循环
        while True:
            # 数据库查询
            query = f"""
            SELECT b.company_name AS company_name, NULL AS nodes_referlv2, NULL AS nodes_referlv3, a.website, a.company_intro, a.product_detail AS major_product, a.certainty, a.trd_industry
            FROM company_product_detail_info a
            RIGHT JOIN {FILTERED_TABLE} b ON TRIM(a.company_name) = TRIM(b.company_name) COLLATE utf8mb4_unicode_ci
            WHERE NOT EXISTS (
                SELECT 1
                FROM {RESULT_TABLE} c
                WHERE TRIM(b.company_name) COLLATE utf8mb4_unicode_ci = TRIM(c.company_name) COLLATE utf8mb4_unicode_ci
                AND b.industry_chain COLLATE utf8mb4_unicode_ci = c.industry_name COLLATE utf8mb4_unicode_ci
            )
            AND b.industry_chain COLLATE utf8mb4_unicode_ci = '{industry_name}' COLLATE utf8mb4_unicode_ci
            """
            # print(query)
            df = get_data_from_mysql(query)

            if not df:  # 如果没有数据，退出循环
                print(f"没有更多的数据可以处理。")
                break

            df = pd.DataFrame(df)
            df.columns = ['company_name', 'nodes_referlv2', 'nodes_referlv3', 'website', 'company_intro', 'major_product', 'certainty', 'trd_industry']

            # 为缺少公司信息的��司使用Jina API获取信息
            print(f"\n正在为 {len(df)} 家公司获取详细信息...")
            for idx, row in df.iterrows():
                # 如果company_intro或major_product为空，使用Jina搜索
                if pd.isna(row['company_intro']) or pd.isna(row['major_product']) or row['company_intro'] == '' or row['major_product'] == '':
                    print(f"正在搜索公司信息: {row['company_name']}")
                    company_info = fetch_company_info_from_jina(row['company_name'], industry_name)

                    # 更新DataFrame
                    df.at[idx, 'company_intro'] = company_info['company_intro']
                    df.at[idx, 'major_product'] = company_info['major_product']
                    df.at[idx, 'certainty'] = company_info['certainty']

                    # 避免请求过快
                    time.sleep(1)

            print(f"公司信息获取完成，开始处理节点匹配...")
            
            # 使用ProcessPoolExecutor创建进程池，并指定最大工作进程数为10
            with ProcessPoolExecutor(max_workers=10) as executor:
                # 计算每个批次的大小
                batch_size = math.ceil(len(df) / 10)
                
                # 为每个批次提交一个处理任务
                futures = []
                for i in range(0, len(df), batch_size):
                    data_batch = df[i:i+batch_size]
                    futures.append(executor.submit(process_data_batch, data_batch, industry_name, nodes, rules, nodes_definition))

                # 收集结果
                all_validated_results = []  # 用于存储所有验证后的结果
                for i, future in enumerate(as_completed(futures)):
                    try:
                        batch_results = future.result()
                        if isinstance(batch_results, list):  # 确保结果是列表
                            for item in batch_results:
                                if item is not None:
                                    # item 现在是 (original_company_name, result) 元组
                                    original_company_name, result = item
                                    result = result.replace("```json", "").replace("```", "").strip()
                                    print(f"模型返回的修正后内容: {result}")
                                    try:
                                        # 尝试解析 JSON
                                        result_json = json.loads(result)
                                        # 添加原始公司名到结果中
                                        result_json['原始公司名'] = original_company_name
                                        all_validated_results.append(result_json)
                                    except json.JSONDecodeError as e:
                                        # 如果解析失败，打印错误信息
                                        print(f"JSON 解析失败: {e}")
                                        print(f"错误位置: 行 {e.lineno}, 列 {e.colno}")
                                        print("错误原因: 请检查模型返回的内容是否为合法的 JSON 格式。")
                        else:
                            print(f"预期列表，但获取了：{type(batch_results)}")
                    except Exception as e:
                        print(f"第 {i + 1} 批次处理失败: {e}")

                # 将所有验证后的结果批量插入数据库
                if all_validated_results:
                    insert_into_database(all_validated_results)  # 插入JSON字符串列表
                    print(f"数据已经成功插入数据库。")
                else:
                    print(f"没有更多的数据可以处理。")
                    break  # 如果没有验证后的结果，也退出循环

    end_time = time.time()
    print(f"代码运行总时间：{end_time - start_time}秒")