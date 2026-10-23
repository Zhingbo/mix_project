import json
import mysql.connector
from mysql.connector import Error
from openai import OpenAI
import os
import multiprocessing
from multiprocessing import Pool
import time

# 数据库配置
db_config = {
    'user': 'remote_user',
    'password': os.getenv('DB_PASSWORD_REMOTE'),
    'host': '8.141.23.4',
    'database': 'business_data'
}

sandro_api_key = os.getenv('DEEPSEEK_API_KEY')
mh_api_key = os.getenv('DEEPSEEK_API_KEY_MH')
gy_api_key = os.getenv('DEEPSEEK_API_KEY_GY')

# OpenAI 客户端配置
def get_client():
    return OpenAI(
        api_key=os.getenv("VOLCENGINE_ARK_API_KEY"),
        base_url="https://ark.cn-beijing.volces.com/api/v3"
    )
    # return OpenAI(
    #     api_key=sandro_api_key,
    #     base_url="https://api.deepseek.com"
    # )

# 总共需要处理的数据条数
total_records_to_process = 200000
# 每次的数据处理条数
records_per_batch = 200
# 已处理的数据条数
# processed_records = 56339

# 产业链名称列表
industry_names = [
    "电气设备", "电子器件", "医疗器械", "消费电子", "无人驾驶", 
    "集成电路", "元宇宙", "新能源汽车", "电子信息", "机械设备与零件",
    "3D打印", "卫星导航", "无人机", "大飞机", "激光",
    "汽车", "眼镜", "工业母机", "工业软件", "人工智能",
    "光伏", "合成生物", "5G", "检验检测", "储能",
    "芯片", "氢能", "低碳经济", "低空经济", "能源环保", 
    "仪器仪表", "装备制造", "通信设备", "半导体", "新材料", 
    "医疗美容", "大健康", "机器人", "生命健康", "生物医药",
    "风电", "轨道交通装备",
    "智能家居", "物联网", "云计算", "服装", "绿色建筑",
    "可再生能源", "环保技术", "生物科技", "数字媒体", "电子商务",
    "食品科技", "海洋经济", "航空航天", "数字安全", "纳米技术",
    "量子计算", "精细化工", "金属加工", "超导材料", "船舶制造",
    "生物经济", "直播电商", "在线教育", "AI智能体", "家具制造",
    "家电设备", "端侧AI", "人形机器人", "未来显示", "算力",
    "新能源", "首发经济", "未来信息", "虚拟现实", "碳中和",
    "远程医疗", "智能交通", "智能电网", "智能金融", "智能农业"
]

def get_nodes(industry_name):
    nodes_file_path = f'resultTxt/nodes_{industry_name}.txt'
    if os.path.exists(nodes_file_path):
        with open(nodes_file_path, 'r', encoding='utf-8') as file:
            return file.read().splitlines()
    else:
        print(f"节点文件不存在：{nodes_file_path}")
        return None

# 提示词
system_prompt_filter = '''你是一个产业链分析专家。以下是公司名称(company_name)，公司简介(company_intro)，和公司主营产品(major_product)，我会以Json形式给出：
{{
    "company_name":"{company_name}",
    "company_intro":"{company_intro}",
    "major_product":"{major_product}"
}}

以下是产业链列表：{industry_names}，其中包含了多个字符串元素，每个字符串代表一个产业链名称，每个元素之间用逗号分隔。

请你利用你的分析能力，结合公司名称，公司简介以及公司主营产品，在上边给出的产业链列表中匹配出与该公司可能相关的产业链。
请以JSON的格式返回结果，例如：
{{
    "公司名称":"广州宇曦电子科技有限公司",
    "产业链列表":["电气设备","电子器件","新能源汽车","电子信息","机械设备与零件"]
}}

注意：
1.返回结果中键的名字必须是"公司名称"，"产业链列表"，不可以是别的！
2.返回结果中的"产业链列表"中的内容只能从{industry_names}列表中进行匹配。
'''

system_prompt_new = '''你是一个产业链分析专家，也是一个构建产业链知识图谱的专家。
以下是公司名称(company_name)，公司简介(company_intro)，公司主营产品(major_product)，置信度(certainty)，产业链名称(industry_name)和行业分类(trd_industry)，我会以Json形式给出：
{{
    "company_name":"{company_name}",
    "company_intro":"{company_intro}",
    "major_product":"{major_product}",
    "certainty":"{certainty}",
    "industry_name":"{industry_name}",
    "trd_industry":"{trd_industry}"
}}

你的任务是根据公司简介(company_intro)和公司主营产品(major_product)在已有的产业链节点中找到至少1个最匹配的节点，并对每个匹配上的节点分别给出匹配原因。如果匹配上多个节点，用";"分隔开，每个节点的匹配原因也用";"分隔开。

然后，你还需要为每个匹配上的节点打出一个分数，即这个企业匹配上该节点的准确度分数。打分时请参考置信度(certainty)：
- 置信度1：分数区间为75-100
- 置信度2：分数区间为51-74
- 置信度3：分数区间为26-50
- 置信度4：分数区间为0-25
每个节点的分数用";"分隔开。

节点匹配逻辑如下：
1. 首先，在主营产品中查找与{industry_name}相关的产品描述，然后在已有的产业链节点{nodes}中查找是否有匹配的节点。匹配规则可以是包含关系、组成关系或关联关系。
2. 如果主营产品中的描述过于宽泛或不具体（例如，主营产品仅为{industry_name}），则需要查看公司简介(company_intro)，根据公司的业务和产品描述，在产业链节点{nodes}中查找匹配的节点。
3. 如果公司简介和主营产品中都没有具体信息，则根据公司名称(company_name)和你的分析技能，在产业链节点{nodes}中查找匹配的节点。
4. 不要匹配“上游”、“中游”、“下游”以及"{industry_name}"这四个节点。
5. 严格遵守我提供的硬规则{rules}。

匹配节点后，需要进一步验证每个节点所属的行业是否与公司所属行业(trd_industry)一致。这需要通过{node_name_mapping}来验证，其中{node_name_mapping}是一个JSON对象，键是节点名称，值是该节点所属的行业名称。如果节点所属行业与公司所属行业一致，则为公司挂接该节点；如果不一致，则需要重新评估匹配节点或说明原因。

请你以JSON格式返回结果，结果中一定要包含以下内容，缺一不可。"产业链名称"千万不要缺失！！！例如：
{{
    "企业名称": "广州宇曦电子科技有限公司",
    "主营产品": "锂电池充电器",
    "公司简介": "广州宇曦电子科技有限公司是国内一家专业定制化电源及测试系统的高新技术企业，公司集研发、生产、销售、服务于一体。",
    "匹配节点": "充电设施;销售与服务",
    "匹配原因": "匹配上节点充电设施的原因为主营产品中的锂电池充电器是充电设施中的一个重要组成部分;匹配上节点销售与服务的原因为公司简介中提到公司集研发、生产、销售、服务于一体。",
    "置信度": "1",
    "分数": "96;99",
    "产业链名称": "新能源汽车"
}}

特别注意：
1. 结果中的“匹配节点”只能是我提供的产业链节点中存在的节点，不要出现不在{nodes}中的节点。
2. 严格使用我提供的产业链节点{nodes}进行匹配，不要自行总结或推断新的节点。
3. 如果公司简介或主营产品与{industry_name}无关，或者没有在{nodes}中找到合适的匹配节点，则“匹配节点”和“匹配原因”返回“无”，并在“匹配原因”中说明原因。
4. “置信度”是我提供的信息中的certainty值，只能是1、2、3、4中的一个整数。
5. “匹配节点”中不要有重复的节点。
6. “公司简介”和“匹配原因”不要重复输出。
7. 结果中的键名必须是“企业名称”、“主营产品”、“公司简介”、“匹配节点”、“匹配原因”、“置信度”、“分数”、“产业链名称”，不能使用其他键名。
8. 返回结果必须包含以下这些内容“企业名称”、“主营产品”、“公司简介”、“匹配节点”、“匹配原因”、“置信度”、“分数”、“产业链名称”，不可以有缺失。
9. 为匹配上的节点打分时，必须结合行业(trd_industry)进行判断。如果节点所属行业与公司所属行业不一致，无论置信度如何，都应给出一个特别低的负数分数。

现在开始分析：
'''

def fetch_batch_data(batch_size, offset):
    try:
        connection = mysql.connector.connect(**db_config, connect_timeout=10)  # 设置连接超时
        cursor = connection.cursor(dictionary=True)
        query = f"""
        SELECT company_name, website, company_intro, product_detail AS major_product, certainty, trd_industry
        FROM company_product_detail_info a
        where not exists (select 1 from company_nodes_info_result_0210 b where a.company_name=b.company_name)
        LIMIT {batch_size} OFFSET {offset}
        """
        cursor.execute(query)
        rows = cursor.fetchall()
        return rows
    except Error as e:
        print(f"Error fetching data from database: {e}")
        return []
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

# def get_total_records():
#     try:
#         connection = mysql.connector.connect(**db_config)
#         cursor = connection.cursor()
#         query = "SELECT COUNT(*) FROM company_product_detail_info"
#         cursor.execute(query)
#         total_records = cursor.fetchone()[0]
#         return total_records
#     except Error as e:
#         print(f"Error fetching total records: {e}")
#         return 0
#     finally:
#         if connection.is_connected():
#             cursor.close()
#             connection.close()

def insert_result_data(data):
    try:
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        query = """
        INSERT INTO company_nodes_info_result_0210 (company_name, major_product, company_intro, matched_nodes, match_reason, certainty, score, industry_name)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.executemany(query, data)
        connection.commit()
    except Error as e:
        print(f"Error inserting data into database: {e}")
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

def get_node_name_mapping(industry_name, nodes):
    try:
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        query = f"""
        SELECT nodes, name FROM nodes_industry_mapping WHERE industry_name = '{industry_name}' AND nodes IN ({','.join(f"'{node}'" for node in nodes.split(';'))})
        """
        cursor.execute(query)
        rows = cursor.fetchall()
        node_name_mapping = {row['nodes']: row['name'] for row in rows}
        return node_name_mapping
    except Error as e:
        print(f"Error fetching node name mapping from database: {e}")
        return {}
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

def process_company(company_info):
    """处理单个公司的主逻辑"""
    client = get_client()  # 创建 OpenAI 客户端
    results = []
    
    try:
        print(f"Processing company: {company_info['company_name']}")

        # Step 1: Filter potential industries for the company
        filter_prompt = system_prompt_filter.format(
            company_name=company_info['company_name'],
            company_intro=company_info['company_intro'],
            major_product=company_info['major_product'],
            industry_names=json.dumps(industry_names, ensure_ascii=False)
        )

        # filter_response = client.chat.completions.create(
        #     model="ep-20250205103212-g9ql9",
        #     messages=[
        #         {'role': 'system', 'content': filter_prompt},
        #         {'role': 'user', 'content': json.dumps(company_info, ensure_ascii=False)}
        #     ],
        #     response_format={"type": "json_object"}
        # )

        filter_response = client.chat.completions.create(
            model="ep-20250217153205-d7px5",
            messages=[
                {'role': 'system', 'content': filter_prompt},
                {'role': 'user', 'content': json.dumps(company_info, ensure_ascii=False)}
            ],
            temperature=0.6,
            response_format={"type": "json_object"}
            # model="deepseek-chat",
            # messages=[
            #     {'role': 'system', 'content': filter_prompt},
            #     {'role': 'user', 'content': json.dumps(company_info, ensure_ascii=False)}
            # ],
            # temperature=0.6,
            # response_format={"type": "json_object"}              
        )        
        filter_result = filter_response.choices[0].message.content
        potential_industries = json.loads(filter_result).get('产业链列表', [])
        print(f"Potential industries for {company_info['company_name']}: {potential_industries}")

        # Step 2: Process each potential industry
        for industry_name in potential_industries:
            print(f"Starting to process industry: {industry_name}")

            nodes = get_nodes(industry_name)
            if nodes is None:
                print(f"未找到 {industry_name} 的节点文件，跳过该产业链")
                continue

            node_name_mapping = get_node_name_mapping(industry_name, ';'.join(nodes))
            nodes_json = json.dumps(nodes, ensure_ascii=False)
            node_name_mapping_json = json.dumps(node_name_mapping, ensure_ascii=False)
            # print(f"节点匹配上的行业是: {node_name_mapping_json}")

            new_prompt = system_prompt_new.format(
                company_name=company_info['company_name'],
                company_intro=company_info['company_intro'],
                major_product=company_info['major_product'],
                certainty=company_info['certainty'],
                industry_name=industry_name,
                trd_industry=company_info['trd_industry'],
                nodes=nodes_json,
                rules="",
                node_name_mapping=node_name_mapping_json
            )

            # new_response = client.chat.completions.create(
            #     model="ep-20250205103212-g9ql9",
            #     messages=[
            #         {'role': 'system', 'content': new_prompt},
            #         {'role': 'user', 'content': json.dumps(company_info, ensure_ascii=False)}
            #     ],
            #     response_format={"type": "json_object"}
            # )
            new_response = client.chat.completions.create(
                # model="deepseek-chat",
                # messages=[
                #     {'role': 'system', 'content': new_prompt},
                #     {'role': 'user', 'content': json.dumps(company_info, ensure_ascii=False)}
                # ],
                # temperature=0.6,
                # response_format={"type": "json_object"}                      
                model="ep-20250217153205-d7px5",
                messages=[
                    {'role': 'system', 'content': new_prompt},
                    {'role': 'user', 'content': json.dumps(company_info, ensure_ascii=False)}
                ],
                temperature=0.6,
                response_format={"type": "json_object"}
            )            
            new_result = new_response.choices[0].message.content

            try:
                match_result = json.loads(new_result)
                print(f"Match result for {industry_name}: {match_result}")
            except json.JSONDecodeError as e:
                print(f"解析 JSON 失败: {e}")
                continue

            # 确保所有必要字段存在
            required_keys = ['匹配节点', '分数','匹配原因', '置信度', '产业链名称']
            for key in required_keys:
                if key not in match_result:
                    match_result[key] = "无"  # 设置默认值

            # 提取匹配节点对应的行业名称
            # matched_nodes = match_result.get('匹配节点', '').split(';')
            # matched_industries = ';'.join([node_name_mapping.get(node.strip(), "未知行业") for node in matched_nodes])
            # match_result['节点所属行业'] = matched_industries
            # print(matched_industries)

            # 构建插入数据时确保所有字段为字符串
            results.append((
                str(match_result.get('企业名称', company_info['company_name'])),
                str(match_result.get('主营产品', company_info['major_product'])),
                str(match_result.get('公司简介', company_info['company_intro'])),
                str(match_result['匹配节点']),
                str(match_result['匹配原因']),
                str(match_result.get('置信度', '')),
                str(match_result['分数']),
                # str(match_result['节点所属行业']),
                str(match_result['产业链名称'])
            ))
            # print(results)
    except Exception as e:
        print(f"处理公司 {company_info['company_name']} 时出错: {e}")
    return results

def main():
    processed_records = 0  # 使用局部变量记录已处理的记录数
    # batch_number = 1  # 添加批次编号

    while processed_records < total_records_to_process:
        print(f"Starting batch processing at offset {processed_records}")
        offset = processed_records
        batch_data = fetch_batch_data(records_per_batch, offset)
        if not batch_data:
            print("No more data to process.")
            break

        # 使用多进程处理数据
        with Pool(processes=20) as pool:  
            results = pool.map(process_company, batch_data) 

        # # 按批次插入数据库
        # for idx, result in enumerate(results, start=1):
        #     if result:  # 如果结果不为空
        #         insert_result_data(result)  # 插入当前批次的结果
        #         print(f"Batch {batch_number}, Sub-batch {idx} inserted into database. "
        #               f"Processed {len(result)} records.")

        # processed_records += len(batch_data)  # 累加已处理的记录数
        # print(f"Processed {processed_records} records so far.")

        # # 如果处理的记录数已经超过总记录数，退出循环
        # if processed_records >= total_records_to_process:
        #     break

        # 将所有子进程的结果合并
        all_results = [item for sublist in results for item in sublist]

        # 插入数据库
        if all_results:
            insert_result_data(all_results)
            print("Data inserted successfully.")

        processed_records += len(batch_data)  # 累加已处理的记录数
        print(f"Processed {processed_records} records so far.")

        # 如果处理的记录数已经超过总记录数，退出循环
        if processed_records >= total_records_to_process:
            break

# def main():
#     processed_records = 0  # 使用局部变量记录已处理的记录数
#     while processed_records < total_records_to_process:
#         print(f"Starting batch processing at offset {processed_records}")
#         offset = processed_records
#         batch_data = fetch_batch_data(records_per_batch, offset)
#         if not batch_data:
#             print("No more data to process.")
#             break

#         results = []
#         for row in batch_data:
#             result = process_company(row)  # 处理单个公司
#             results.extend(result)

#         if results:
#             insert_result_data(results)

#         processed_records += len(batch_data)  # 累加已处理的记录数
#         print(f"Processed {processed_records} records so far.")

#         # 如果处理的记录数已经超过总记录数，退出循环
#         if processed_records >= total_records_to_process:
#             break


if __name__ == "__main__":
    start_time = time.time()
    multiprocessing.set_start_method('spawn')  # 设置多进程启动方式
    main()
    end_time = time.time()
    print(f"代码运行总时间：{end_time - start_time}")