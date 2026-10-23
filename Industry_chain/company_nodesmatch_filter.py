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
industry_names = ["大飞机"]  # 可以更换行业名称

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

def get_rules(industry_name):
    rules_file_path = f'materials/rules_list_{industry_name}.txt'
    if os.path.exists(rules_file_path):
        with open(rules_file_path, 'r', encoding='utf-8') as file:
            return file.read().splitlines()
    return []

def process_row_new(row, rules, system_prompt_new, industry_name):
    words_json = {
        'company_name': row['company_name'],
        'company_intro': row['company_intro'],
        'major_product': row['major_product'],
        'rules': rules,
        'industry_name': industry_name
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
        response_format={"type": "json_object"}
    )
    try:
        result = response.choices[0].message.content
        # print(f"模型返回结果: {result}")  # 打印模型返回的结果
        return result
    except Exception as e:
        print(f"Error processing row: {e}")
        return None

def process_data_batch(data_batch, industry_name, rules):
    results = []
    system_prompt_new = f'''你是一个产业链分析专家，也是一个构建产业链知识图谱的专家。
                    以下是公司名称(company_name)，公司简介(company_intro)，公司主营产品(major_product)，产业链名称(industry_name)，我会以Json形式给出：
                    {{
                        "company_name":"{data_batch['company_name'].iloc[0]}",
                        "company_intro":"{data_batch['company_intro'].iloc[0]}",
                        "major_product":"{data_batch['major_product'].iloc[0]}",
                        "industry_name":"{industry_name}"                    
                    }}
                    你的任务是根据公司简介(company_intro)，公司主营产品(major_product)，硬规则{rules}判断该公司是不是属于"{industry_name}"产业链，并且给出判断依据。

                    请你以JSON格式返回结果，例如：
                    {{
                        "企业名称": "塞斯纳飞机公司",
                        "主营产品": "小型固定翼飞机，如塞斯纳172",
                        "公司简介": "塞斯纳飞机公司专注于通用航空领域",
                        "判断结果": "否",
                        "判断依据": "根据硬规则中的内容小型固定翼飞机如塞斯纳172主要用于飞行训练、私人飞行和短途运输，与大飞机产业链的关联性较弱"
                    }}
                    特别注意：
                    1.结果中的"判断结果"只能返回“是”或者“否”。
                    2.你要严格遵守硬规则({rules})中的内容。
                    3.返回结果中的键的名字只能是"企业名称"，"主营产品"，"公司简介"，"判断结果"，"判断依据",不可以是别的！

        '''
    for index, row in data_batch.iterrows():
        print(f"正在处理公司: {row['company_name']}")  # 打印正在处理的公司名称
        result = process_row_new(row, rules, system_prompt_new, industry_name)
        if result is not None:
            results.append(result)
    return results

if __name__ == '__main__':
    set_start_method('spawn')
    start_time = time.time()

    # 遍历所有行业名称
    for industry_name in industry_names:
        print(f'Processing {industry_name}')
        
        # 获取行业相关的rules
        rules = get_rules(industry_name)
        print(f'强规则信息： {rules}')

        # 数据库查询
        query = f"""
        SELECT distinct b.company_name AS company_name, website, company_intro, product_detail AS major_product
        FROM company_product_detail_info a
        RIGHT JOIN company_nodes_mapping0423 b ON TRIM(a.company_name) = TRIM(b.company_name)
        WHERE b.industry_name = '{industry_name}'
        """
        # print(query)
        df = get_data_from_mysql(query)

        df = pd.DataFrame(df)
        df.columns = ['company_name', 'website', 'company_intro', 'major_product']
        
        # 使用ProcessPoolExecutor创建进程池，并指定最大工作进程数为10
        with ProcessPoolExecutor(max_workers=10) as executor:
            # 计算每个批次的大小
            batch_size = math.ceil(len(df) / 10)
            
            # 为每个批次提交一个处理任务
            futures = []
            for i in range(0, len(df), batch_size):
                data_batch = df[i:i+batch_size]
                futures.append(executor.submit(process_data_batch, data_batch, industry_name, rules))

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

        # 将判断结果为“是”的数据保存到Excel文件中
        positive_results = [result for result in all_validated_results if result.get("判断结果") == "是"]
        if positive_results:
            output_file = f"/data/ASRProject/rawdata/{industry_name}_positive_results.xlsx"
            pd.DataFrame(positive_results).to_excel(output_file, index=False)
            print(f"已将判断结果为'是'的数据保存到文件: {output_file}")
        else:
            print(f"没有找到判断结果为'是'的数据，未生成Excel文件。")

    end_time = time.time()
    print(f"代码运行总时间：{end_time - start_time}秒")