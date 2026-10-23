import json
from openai import OpenAI
import pandas as pd
from multiprocessing import set_start_method
from concurrent.futures import ProcessPoolExecutor, as_completed
import time
import mysql.connector
import math
import os

# API 密钥
zlc_api_key = os.getenv('DEEPSEEK_API_KEY_LC')
sandro_api_key = os.getenv('DEEPSEEK_API_KEY')
mh_api_key = os.getenv('DEEPSEEK_API_KEY_MH')
gy_api_key = os.getenv('DEEPSEEK_API_KEY_GY')

# 行业名称
industry_names = [       
        # "生命健康","集成电路","机器人","新能源汽车","检验检测"
        # ,"工业软件","卫星导航","无人机"
        # # "大飞机","工业母机"
        # "3D打印"
        # # ,"人工智能"
        # ,"激光","合成生物","光伏","5G","低空经济","储能","跨境电商"
        # ,"船舶海工","人形机器人","仪表仪器"
        "跨境电商"
        ]  # 可以更换行业名称 

# 数据库连接配置
db_config = {
    "host": "8.141.23.4",
    "user": "remote_user",
    "password": os.getenv("DB_PASSWORD_REMOTE"),
    "database": "business_data",
    "port": 3306
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
    FROM chain_need_company
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
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS company_nodes_info_result_0519 (
            company_name    TEXT NULL,
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
        print("表 company_nodes_info_result_0519 已创建或已存在。")
    except mysql.connector.Error as err:
        print(f"创建表时出错: {err}")
    finally:
        cursor.close()
        cnx.close()

def insert_into_database(data_list):
    try:
        cnx = mysql.connector.connect(**db_config)
        cursor = cnx.cursor()
        sql = """
        INSERT INTO company_nodes_info_result_0519 (company_name, major_product, company_intro, matched_nodes, match_reason, certainty, score, industry_name)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        for data in data_list:
            company_name = data.get('企业名称', '未知') or '未知'
            major_product = json.dumps(data.get('主营产品', '未知'), ensure_ascii=False) if data.get('主营产品') else '未知'
            company_intro = json.dumps(data.get('公司简介', '未知'), ensure_ascii=False) if data.get('公司简介') else '未知'
            matched_nodes = json.dumps(data.get('匹配节点', '未知'), ensure_ascii=False) if data.get('匹配节点') else '未知'
            match_reason = json.dumps(data.get('匹配原因', '未知'), ensure_ascii=False) if data.get('匹配原因') else '未知'
            certainty = data.get('置信度', '未知') or '未知'
            score = data.get('分数', '未知') or '未知'
            industry_name = data.get('产业链名称', '未知') or '未知'
            values = (company_name, major_product, company_intro, matched_nodes, match_reason, certainty, score, industry_name)
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
        api_key=os.getenv("VOLCENGINE_ARK_API_KEY"),
        base_url="https://ark.cn-beijing.volces.com/api/v3"
    )
    response = client.chat.completions.create(
        # model="ep-20250217153421-8lrxj",
        model="ep-20250217153205-d7px5",
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
                    5.结果中的"匹配节点"不要有重复的节点，不要无限输出。
                    6.结果中的"公司简介"不要无限输出！
                    7.结果中的"匹配原因"不要无限输出！
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
            results.append(result)
    return results

if __name__ == '__main__':
    set_start_method('spawn')
    start_time = time.time()

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
            SELECT b.company_name AS company_name, NULL AS nodes_referlv2, NULL AS nodes_referlv3, website, company_intro, product_detail AS major_product, certainty, trd_industry
            FROM company_product_detail_info a
            RIGHT JOIN topcompany_filtered_05192 b ON TRIM(a.company_name) = TRIM(b.company_name)
            WHERE NOT EXISTS (
                SELECT 1 
                FROM company_nodes_info_result_0519 c 
                WHERE TRIM(b.company_name) = TRIM(c.company_name) AND b.industry_chain = c.industry_name
            )
            AND b.industry_chain = '{industry_name}'
            """
            # print(query)
            df = get_data_from_mysql(query)

            if not df:  # 如果没有数据，退出循环
                print(f"没有更多的数据可以处理。")
                break

            df = pd.DataFrame(df)
            df.columns = ['company_name', 'nodes_referlv2', 'nodes_referlv3', 'website', 'company_intro', 'major_product', 'certainty', 'trd_industry']
            
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
                            for result in batch_results:
                                if result is not None:
                                    # result = result.replace('None', '无')
                                    # result = result.replace('null', '"无"')
                                    # result = result.replace("'", "")
                                    result = result.replace("```json", "").replace("```", "").strip()
                                    print(f"模型返回的修正后内容: {result}")
                                    try:
                                        # 尝试解析 JSON
                                        result_json = json.loads(result)
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