import json
from openai import OpenAI
import pandas as pd
from multiprocessing import set_start_method
from concurrent.futures import ProcessPoolExecutor, as_completed
import time
import mysql.connector
import math
import os
from zhipuai import ZhipuAI

# zhipukey = '82be19c96af3da40cdf125044e349811.16lEnft5oNRMIeOb'
# client = ZhipuAI(api_key=zhipukey)

industry_names = [
        "电气设备", "电子器件", "医疗器械", "消费电子","无人驾驶", 
        "集成电路", "元宇宙", "新能源汽车", "电子信息", "机械设备与零件",
        "3D打印", "卫星导航", "无人机", "大飞机", "激光",
        "汽车", "眼镜", "工业母机", "工业软件", "人工智能",
        "光伏", "合成生物", "5G", "检验检测", "储能",
        "芯片", "氢能", "低碳经济","低空经济", "能源环保", 
        "仪器仪表","装备制造", "通信设备", "半导体", "新材料", 
        "医疗美容", "大健康", "机器人", "生命健康", "生物医药",
        "风电","轨道交通装备",
        "智能家居","物联网","云计算","服装","绿色建筑",
        "可再生能源","环保技术","生物科技","数字媒体","电子商务",
        "食品科技","海洋经济","航空航天","数字安全","纳米技术",
        "量子计算","精细化工","金属加工","超导材料","船舶制造",
        "生物经济","直播电商","在线教育","AI智能体","家具制造",
        "家电设备","端侧AI","人形机器人","未来显示","算力",
        "新能源", "首发经济","未来信息" ,"虚拟现实","碳中和",
        "远程医疗","智能交通","智能电网","智能金融","智能农业",
        "AI大模型","装配式建筑","跨境电商","银发经济","情绪价值",
        "量子科技","空天信息","电竞","5G-A","固态电池",
        "商业航天","AI眼镜","北斗产业","碳纤维","智能穿戴",
        "智能传感器","预制菜产业","高端装备制造","宠物经济","露营经济",
        "数字创意产业","数字医疗","脑机接口","deepseek","超导",
        "AI制药","冰雪经济","AI基础设施","特斯拉","供应链服务",
        "地方特色食品","特钢材料","疗愈经济","本地化运营","智能算力",
        "风电装备","铝镁精深加工"
    ]  # 可以更换行业名称

zlc_api_key = os.getenv('DEEPSEEK_API_KEY_LC')
sandro_api_key = os.getenv('DEEPSEEK_API_KEY')
mh_api_key = os.getenv('DEEPSEEK_API_KEY_MH')
gy_api_key = os.getenv('DEEPSEEK_API_KEY_GY')

def get_rules(industry_name):
    rules_file_path = f'materials/rules_list_{industry_name}.txt'
    if os.path.exists(rules_file_path):
        with open(rules_file_path, 'r', encoding='utf-8') as file:
            return file.read().splitlines()
    return None

def get_nodes(industry_name):
    nodes_file_path_2 = f'resultTxt/nodes2_{industry_name}.txt'
    nodes_file_path = f'resultTxt/nodes_{industry_name}.txt'
    
    if os.path.exists(nodes_file_path_2):
        with open(nodes_file_path_2, 'r', encoding='utf-8') as file:
            return file.read().splitlines()
    elif os.path.exists(nodes_file_path):
        with open(nodes_file_path, 'r', encoding='utf-8') as file:
            return file.read().splitlines()
    else:
        print(f"节点文件不存在：{nodes_file_path_2} 或 {nodes_file_path}")
        return []

system_prompt_filter = f'''你是一个产业链分析专家。以下是公司名称(company_name)，公司简介(company_intro)，和公司主营产品(major_product)，我会以Json形式给出：
    {{
        "company_name":"",
        "company_intro":"",
        "major_product":""
    }}

以下是产业链列表:{industry_names}，其中包含了多个字符串元素，每个字符串代表一个产业链名称，每个元素之间用逗号分隔。

请你利用你的分析能力，结合公司名称，公司简介以及公司主营产品，在上边给出的{industry_names}列表中匹配出与该公司可能相关的产业链。
请以JSON的格式返回结果，例如：
{{
    "公司名称":"广州宇曦电子科技有限公司",
    "产业链列表":["电气设备","电子器件","新能源汽车","电子信息","机械设备与零件"]
}}

注意：
1.返回结果中键的名字必须是"公司名称"，"产业链列表"，不可以是别的！
2.返回结果中的"产业链列表"中的内容只能从{industry_names}列表中进行匹配。

'''

# system_prompt = '''你是一个擅于归纳总结的专家。
# 以下是一些公司网站的抓取内容(crawl_content)，请你总结概括出每一家公司的公司简介，字数不要太多，并以JSON的格式返回到结果中，输出示例如下：
# {
#     "crawl_content":"广东顺德和壹设计咨询有限公司主要属于工业设计行业，专注于产品设计、工业设计等领域。"
# }

# 注意：
# 1.返回结果中键的名字一定是"crawl_content"，不可以是别的！
# 2.总结出来的公司简介中只需要有与公司业务相关的内容，公司是干什么的，公司的产品以及公司的产品应用场景领域就可以，不要有公司成立时间，公司地址，注册地这些.

# '''

# client = OpenAI(
#             api_key=sandro_api_key,
#             base_url="https://api.deepseek.com",
#     )

# zhipukey = '82be19c96af3da40cdf125044e349811.16lEnft5oNRMIeOb'
# client = ZhipuAI(api_key=zhipukey)

def validate_matching_nodes(matching_nodes, nodes):
    # 校验匹配节点是否都在nodes列表中，不在则移除
    valid_nodes = [node for node in matching_nodes if node in nodes]
    return valid_nodes

def get_data_from_mysql(query):
    # 数据库连接配置
    cnx = mysql.connector.connect(
        user='remote_user',
        password=os.getenv('DB_PASSWORD_REMOTE'),
        host='8.141.23.4',
        database='business_data'
    )
    cursor = cnx.cursor()
    try:
        cursor.execute(query)
        df = pd.DataFrame(cursor.fetchall())
        cursor.close()
        cnx.close()
        return df
    except mysql.connector.Error as err:
        print("Something went wrong: {}".format(err))
        cursor.close()
        cnx.close()
        return None

def create_table_if_not_exists():
    # 数据库连接配置
    connection = mysql.connector.connect(
        user='remote_user',
        password=os.getenv('DB_PASSWORD_REMOTE'),
        host='8.141.23.4',
        database='business_data'
    )
    
    try:
        with connection.cursor() as cursor:
            # 创建表的SQL语句
            create_table_sql = """
            CREATE TABLE IF NOT EXISTS company_nodes_info_result_0320 (
                company_name    TEXT NULL,
                major_product   LONGTEXT NULL,
                company_intro   LONGTEXT NULL,
                matched_nodes   TEXT NULL,
                match_reason    LONGTEXT NULL,
                certainty       TEXT NULL,
                industry_name   TEXT NULL,
                score           TEXT NULL
            );
            """
            cursor.execute(create_table_sql)
            print("表 company_nodes_info_result_0320 已创建或已存在。")
    except mysql.connector.Error as err:
        print(f"创建表时出错: {err}")
    finally:
        connection.close()

def insert_into_database(data_list):
    # 连接数据库
    connection = mysql.connector.connect(
        user='remote_user',
        password=os.getenv('DB_PASSWORD_REMOTE'),
        host='8.141.23.4',
        database='business_data'
    )
    
    try:
        with connection.cursor() as cursor:
            # SQL 插入语句
            sql = """
            INSERT INTO company_nodes_info_result_0320 (company_name, major_product, company_intro, matched_nodes, match_reason, certainty, score, industry_name)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            # 遍历结果列表
            for data in data_list:
                # 检查并设置默认值
                company_name = data.get('企业名称', '未知')
                major_product = data.get('主营产品', '未知')
                company_intro = data.get('公司简介', '未知')  # 如果不存在，设置默认值
                matched_nodes = json.dumps(data.get('匹配节点', []), ensure_ascii=False)
                match_reason = data.get('匹配原因', '未知')
                certainty = data.get('置信度', '未知')
                score = data.get('分数', '未知')
                industry_name = data.get('产业链名称', '未知')

                # 如果某些字段缺失，记录问题数据
                if '公司简介' not in data:
                    print(f"缺失字段 '公司简介' 的数据: {data}")

                # 准备插入的数据
                values = (company_name, major_product, company_intro, matched_nodes,
                          match_reason, certainty, score, industry_name)
                # 执行插入操作
                cursor.execute(sql, values)
        
        # 提交事务
        connection.commit()
        print("Data inserted successfully")
    except Exception as e:
        print(f"插入数据库时出错: {e}")
    finally:
        connection.close()
        print("MySQL connection is closed")

# def insert_into_database(data_list):
#     # 连接数据库
#     connection = mysql.connector.connect(
#         user='remote_user',
#         password=os.getenv('DB_PASSWORD_REMOTE'),
#         host='8.141.23.4',
#         database='business_data'
#     )
    
#     try:
#         with connection.cursor() as cursor:
#             # SQL 插入语句
#             sql = """
#             INSERT INTO company_nodes_info_result_0320 (company_name, major_product, company_intro, matched_nodes, match_reason, certainty,score,industry_name)
#             VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
#             """
            
#             # 遍历结果列表
#             for data in data_list:
#                 # data = json.loads(data)
#                 matched_nodes = json.dumps(data['匹配节点']) if isinstance(data['匹配节点'], list) else data['匹配节点']

#                 # 准备插入的数据
#                 values = (data['企业名称'], data['主营产品'], data['公司简介'], matched_nodes,
#                           data['匹配原因'], data['置信度'], data['分数'], data['产业链名称'])
#                 # 执行插入操作
#                 cursor.execute(sql, values)
        
#         # 提交事务
#         connection.commit()
#         print("Data inserted successfully")
#     finally:
#         connection.close()
#         print("MySQL connection is closed")
  

# def summarize_crawl_content(crawl_content):
#     if crawl_content:  
#         words_json = {
#             'crawl_content': crawl_content
#         }
#         response = client.chat.completions.create(
#             model="deepseek-chat",
#             messages=[
#                 {'role': 'system', 'content': system_prompt},
#                 {'role': 'user', 'content': json.dumps(words_json, ensure_ascii=False)}
#             ],
#             temperature=1.0,
#             response_format={"type": "json_object"},
#             max_tokens=8000
#         )
#         try:
#             return response.choices[0].message.content
#         except:
#             return None
#     else:
#         print("crawl_content列不存在或为空。")
#         return None

def get_nodes_mapping(industry_name):
    # 查询 nodes_industry_mapping_new 表
    query = f"""
    SELECT nodes, name FROM nodes_industry_mapping_new WHERE industry_name = '{industry_name}'
    """
    df = get_data_from_mysql(query)
    if df is not None and not df.empty:
        df.columns = ['nodes', 'name']
        # 将结果存储为字典，键为节点名称，值为对应的 name
        return dict(zip(df['nodes'], df['name']))
    else:
        print(f"未找到行业 {industry_name} 对应的节点映射信息，跳过该行业处理。")
        return None

def process_row_new(row, nodes, rules, system_prompt_new, industry_name):        
    # abstract = summarize_crawl_content(row[4])
    # if abstract is not None:
    #     try:
    #         result_json = json.loads(abstract)
    #     except json.JSONDecodeError as e:
    #         print(f"JSON解析错误：{e}")
    #         return None

    words_json = {
        'nodes': nodes,
        'company_name': row[0],
        'company_intro': row[2],
        'major_product': row[3],
        'rules': rules,
        'certainty': str(row[4]),
        'trd_industry': row[5],
        'industry_name': industry_name  # 添加 industry_name
    }
    # response = client.chat.completions.create(
    #     model="deepseek-chat",
    #     messages=[
    #         {'role': 'system', 'content': system_prompt_new},
    #         {'role': 'user', 'content': json.dumps(words_json, ensure_ascii=False)}
    #     ],
    #     temperature=0.1,
    #     response_format={"type": "json_object"},
    #     max_tokens=8000
    # )
    # response = client.chat.completions.create(
    #     model="glm-4-flash",
    #     messages=[
    #         {
    #             "role": "system",
    #             "content": system_prompt_new
    #         },
    #         {
    #             "role": "user",
    #             "content": json.dumps(words_json, ensure_ascii=False)
    #         }
    #     ],
    #     top_p=0.8,
    #     temperature=0.2,
    #     max_tokens=100000,
    # )    

    client = OpenAI(
        api_key=os.getenv("VOLCENGINE_ARK_API_KEY"),
        base_url="https://ark.cn-beijing.volces.com/api/v3",
    )

    response = client.chat.completions.create(
        # model="ep-20250205103212-g9ql9",
        model="ep-20250217153205-d7px5",
        messages=[
            {'role': 'system', 'content': system_prompt_new},
            {'role': 'user', 'content': json.dumps(words_json, ensure_ascii=False)}],
        response_format={
            "type": "json_object"
        }
        )  
    try:
        return response.choices[0].message.content
    except:
        return None      
    # try:
    #     print(response.choices[0].message.content)
    #     try:
    #         result_content = json.loads(response.choices[0].message.content)
    #     except json.JSONDecodeError as e:
    #         print(f"JSON解析错误：{e}")
    #         print(f"原始内容：{response.choices[0].message.content}")
    #         return None
    #     return json.dumps(result_content, ensure_ascii=False)
    # except Exception as e:
    #     print(f"process_row_new出错: {e}")
    #     return None
    
    # else:
    #     return None

def process_data_batch(data_batch, industry_name, nodes, rules,name):
    results = []
    try:
        system_prompt_new = f'''你是一个产业链分析专家,也是一个构建产业链知识图谱的专家。

                    以下是公司名称(company_name)，公司简介(company_intro)，公司主营产品(major_product)，置信度(certainty)，产业链名称(industry_name)和行业分类(trd_industry)，我会以Json形式给出：
                    {{
                        "company_name":"",
                        "company_intro":"",
                        "major_product":"",
                        "certainty":"",
                        "industry_name":"",
                        "trd_industry":""
                    }}

                    你的任务是根据公司简介(company_intro)和公司主营产品(major_product)在已有的产业链节点{nodes}中找到至少1个最匹配的节点并对每个匹配上的节点都分别给出你的匹配原因，如果匹配上多个节点用";"分隔开，每个节点的匹配原因也用";"分隔开。
                    然后你还需要为每个匹配上的节点打出一个分数，即这个企业匹配上该节点的准确度分数。打这个分数的时候你需要参考下我上边给你的置信度(certainty)，置信度1的准确性最高，往后依次是2，3，4。所以对于置信度为1的，你给的分数区间在75-100，对于置信度为2的，你给的分数区间在51-74，对于置信度为3的，你给的分数区间在26-50，对于置信度为4的，你给的分数区间在0-25。每个节点的分数用";"分隔开。

                    节点具体匹配逻辑为：
                        - 首先，你先去主营产品中找与{industry_name}相关的产品描述，再去已有的产业链节点{nodes}中找是否有能匹配上的节点，匹配规则是产品描述和已有的产业链节点{nodes}之间可能是包含关系，组成关系或者关联关系。
                        比如：公司主营产品中包括新能源汽车用空压机FRA系列，你分析出这直接关联到新能源汽车的动力系统,你应该去已有的产业链节点{nodes}中找与动力系统意思最为接近的节点，于是你匹配到的节点为"动力系统集成"。
                        再比如：公司主营产品中提到新能源汽车测试方案，你分析出这直接关联到新能源汽车产业链的下游销售与服务环节，你应该去已有的产业链节点{nodes}中找与销售服务环节意思最为接近的节点，于是你匹配到的节点为"销售与服务"。
                        再比如：公司主营产品中包括新能源汽车电附件，汽车零部件及配件制造，你分析出这些都是零部件制造的重要组成部分，你应该去已有的产业链节点{nodes}中找与零部件制造意思最为接近的节点，于是你匹配到的节点为"零部件制造"。

                        - 如果你发现主营产品中与{industry_name}相关的产品描述太过于宽泛不具体，比如主营产品就只有{industry_name}，那么你需要去公司简介(company_intro)中找到这家公司是做什么的，根据这家公司是做什么的，公司的业务，产品描述，再去已有的产业链节点{nodes}中找是否有能匹配上的节点，匹配规则是公司简介描述的内容和已有的产业链节点{nodes}之间可能是包含关系，组成关系或者关联关系。
                        比如：公司的主营产品包括新能源汽车，你不好判断出他具体的业务产品是什么，于是你去公司简介中找到这家公司是提供新能源汽车技术培训和人才培养的，于是你分析出这属于新能源汽车产业链的下游销售与服务环节，根据关联性，你应该去已有的产业链节点{nodes}中找与销售服务环节意思最为接近的节点，于是你匹配到的节点为"销售与服务"。
                        再比如：公司的主营产品包括新能源汽车产品，你不好判断出他具体的产品指的是什么，于是你去公司简介中找到这家公司多年来专注于为新能源汽车零件提供同步开发工艺优化验证制造等多元一体化的制造服务，于是你分析出这些涉及到新能源汽车上游的零部件制造以及下游的销售服务环节，你应该去已有的产业链节点{nodes}中找与零部件制造以及销售服务环节意思最为接近的节点，于是你匹配到的节点为"零部件制造"和"销售与服务"。

                        - 如果公司简介(company_intro)和公司主营产品(major_product)中都没有内容，那么你需要根据公司名称(company_name)和你的分析技能去已有的产业链节点{nodes}中找是否有能匹配上的节点。

                        - 不要匹配"上游","中游","下游"以及"{industry_name}"这四个节点。

                        - 请你严格遵守我提供的硬规则{rules}中的内容。

                        - 在匹配节点后，需进一步验证该节点所属的行业{name}是否与公司所属的行业(trd_industry)一致。如果一致，则为公司挂接该节点；如果不一致，则需重新评估匹配节点或说明原因。

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
                    1.结果中的"匹配节点"只返回我提供的产业链节点中存在的节点{nodes}，不要出现主营产品中提到的但是我提供的产业链节点中{nodes}不存在的，也不要出现公司简介中提到的但是我提供的产业链节点{nodes}中不存在的。
                    2.你要严格在我提供的产业链节点{nodes}中去匹配，不要自行总结或推断新的节点，导致匹配节点不在我提供的产业链节点中。
                    3.如果公司简介或者主营产品与{industry_name}无关或者没有在{nodes}中找到合适的匹配节点，那么结果中的"匹配节点"以及"节点定义"都返回"无"不要返回"其他"，并且在结果中的"匹配原因"中说明原因.
                    4.结果中的"certainty"是我上边给你的信息中的置信度(certainty)，值为1,2,3,4这四个整数其中一个，不要出现小数的格式比如1.0。
                    5.结果中的"匹配节点"不要有重复的节点，不要无限输出。
                    6.结果中的"公司简介"不要无限输出！
                    7.结果中的"匹配原因"不要无限输出！
                    8.返回结果中的键的名字只能是"企业名称"，"主营产品"，"公司简介"，"匹配节点"，"匹配原因"，"置信度"，"分数"，"产业链名称",不可以是别的！
                    9.返回结果中的"产业链名称"是我上边给你的信息中的产业链名称(industry_name).
                    10.为匹配上的节点打分数时一定要结合上行业(trd_industry)，也就是节点所属的行业{name}一定要与公司所属的行业(trd_industry)一致才能给高分数，如果不一致则不管置信度是什么都给一个特别低的负数分数.

                    需要再次强调的是，绝对不能出现匹配节点{nodes}以外的节点！下面开始：
        '''
        for index, row in data_batch.iterrows():
            result = process_row_new(row, nodes, rules, system_prompt_new, industry_name)
            if result is not None:
                results.append(result)
    except Exception as e:
        print(f"批次处理失败: {e}")
    return results 


if __name__ == '__main__':
    set_start_method('spawn')
    start_time = time.time()

    # 创建表（如果不存在）
    create_table_if_not_exists()

    # 遍历所有行业名称
    for industry_name in industry_names:
        print(f'Processing {industry_name}')
        
        # 总共需要处理的数据条数
        total_records_to_process = 5000000
        # 每次处理的数据条数
        records_per_batch = 500
        # 已处理的数据条数
        processed_records = 0        
        # 批次计数器
        batch_count = 0

        # 获取行业相关的nodes和rules
        nodes = get_nodes(industry_name)
        rules = get_rules(industry_name)

        # 获取节点名称与 name 的映射关系
        node_name_mapping = get_nodes_mapping(industry_name)
        if node_name_mapping is None:
            continue

        # 数据库查询
        while processed_records < total_records_to_process:
            query = f"""
            select company_name, website, company_intro, product_detail AS major_product, certainty, trd_industry
            from company_product_detail_info a
            where not exists (select 1 from ent_industry_class_0318 b where a.company_name=b.company_name)
            LIMIT {records_per_batch} OFFSET {processed_records}
            """
            df = get_data_from_mysql(query)
            
            if not df.empty:
                df.columns = ['company_name', 'website', 'company_intro', 'major_product', 'certainty', 'trd_industry']
                
                # 使用ProcessPoolExecutor创建进程池，并指定最大工作进程数为50
                with ProcessPoolExecutor(max_workers=10) as executor:
                    # 计算每个批次的大小
                    batch_size = math.ceil(len(df) / 10)
                    
                    # 为每个批次提交一个处理任务
                    futures = []
                    for i in range(0, len(df), batch_size):
                        data_batch = df[i:i+batch_size]
                        futures.append(executor.submit(process_data_batch, data_batch, industry_name, nodes, rules, node_name_mapping))
                    
                    # 收集结果
                    all_validated_results = []  # 用于存储所有验证后的结果
                    for i, future in enumerate(as_completed(futures)):
                        try:
                            batch_results = future.result()
                            if isinstance(batch_results, list):  # 确保结果是列表
                                for result in batch_results:
                                    if result is not None:
                                        try:
                                            # 确保 result 是字典格式
                                            result_json = json.loads(result.replace("'", '"'))
                                            if '匹配节点' in result_json:
                                                print(result_json)
                                                matching_nodes_list = result_json['匹配节点'].split(';')
                                                result_json['匹配节点'] = validate_matching_nodes(matching_nodes_list, nodes)
                                                result_json['匹配节点'] = ';'.join(result_json['匹配节点'])
                                                all_validated_results.append(result_json)

                                        except Exception as e:
                                            print("result_json格式有问题", result, e)
                            else:
                                print(f"预期列表，但获取了：{type(batch_results)}")
                        except Exception as e:
                            print(f"第 {batch_count + i + 1} 批次处理失败: {e}")

                    # 将所有验证后的结果批量插入数据库
                    if all_validated_results:
                        insert_into_database(all_validated_results)  # 插入JSON字符串列表
                        print(f"第 {batch_count + 1} 批数据已经成功插入数据库。")
                
                # 更新已处理的数据条数和批次计数器
                processed_records += len(df)
                batch_count += 1
            else:
                print(f"没有更多的数据可以处理，已处理 {processed_records} 条记录。")
                break

    end_time = time.time()
    print(f"代码运行总时间：{end_time - start_time}秒")
