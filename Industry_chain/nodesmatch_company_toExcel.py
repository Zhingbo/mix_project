import json
from openai import OpenAI
from sympy import false
import pandas as pd
from multiprocessing import Pool
from multiprocessing import set_start_method
from concurrent.futures import ProcessPoolExecutor
import time
import mysql.connector
import os

industry_names = [
    "电气设备", "电子器件", "医疗器械", "消费电子","无人驾驶", 
    "集成电路", "元宇宙", "新能源汽车", "电子信息", "机械设备与零件",
    "3D打印", "卫星导航", "无人机", "大飞机", "激光",
    "汽车", "眼镜", "工业母机", "工业软件", "人工智能",
    "光伏", "合成生物", "5G", "检验检测", "储能",
    "芯片", "氢能", "低碳经济","低空经济", "能源环保", 
    "仪器仪表","装备制造", "通信设备", "半导体", "新材料", 
    "医疗美容", "大健康", "机器人", "生命健康", "生物医药",
    "风电","轨道交通装备","智能家居","物联网","云计算",
    "服装","绿色建筑","可再生能源","环保技术","生物科技",
    "数字媒体","电子商务","食品科技","海洋经济","航空航天",
    "数字安全","纳米技术","量子计算","精细化工","金属加工",
    "超导材料","船舶制造"
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


system_prompt = '''你是一个擅于归纳总结的专家。
以下是一些公司网站的抓取内容(crawl_content)，请你总结概括出每一家公司的公司简介，并以JSON的格式返回到结果中，输出示例如下：
{
    "crawl_content":"广东顺德和壹设计咨询有限公司主要属于工业设计行业，专注于产品设计、工业设计等领域。"
}

注意：
1.返回结果中键的名字一定是"crawl_content"，不可以是别的！
2.总结出来的公司简介中只需要有与公司业务相关的内容，公司是干什么的，公司的产品以及公司的产品应用场景领域就可以，不要有公司成立时间，公司地址，注册地这些.

'''

system_prompt_filter = f'''你是一个产业链分析专家。以下是公司名称(company_name)，公司简介(company_intro)，和公司主营产品(major_product)，我会以Json形式给出：
    {{
        "company_name":"",
        "company_intro":"",
        "major_product":""
    }}

以下是产业链列表:{industry_names}，其中包含了多个字符串元素，每个字符串代表一个产业链名称，每个元素之间用逗号分隔。

请你利用你的分析能力，结合公司名称，公司简介以及公司主营产品，在上边给出的{industry_names}列表中匹配出该公司可能涉及到的产业链。
请以JSON的格式返回结果，例如：
{{
    "公司名称":"广州宇曦电子科技有限公司",
    "产业链列表":["电气设备","电子器件","新能源汽车","电子信息","机械设备与零件"]
}}

注意：
1.返回结果中键的名字必须是"公司名称"，"产业链列表"，不可以是别的！
2.返回结果中的"产业链列表"中的内容只能从{industry_names}列表中进行匹配。

'''


client = OpenAI(
            api_key=sandro_api_key,
            base_url="https://api.deepseek.com/beta",
    )


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

def summarize_crawl_content(crawl_content):
    if crawl_content:  
        words_json = {
            'crawl_content': crawl_content
        }
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': json.dumps(words_json, ensure_ascii=False)}
            ],
            temperature=1.0,
            response_format={"type": "json_object"}
        )
        try:
            return response.choices[0].message.content
        except:
            return None
    else:
        print("crawl_content列不存在或为空。")
        return None

def chain_filter(row):
    abstract = summarize_crawl_content(row[4]) ## row是以tuple形式传递的，需要用index而不是列名
    print(abstract)
    if abstract is not None:
        try:
            result_json = json.loads(abstract)
        except json.JSONDecodeError as e:
            print(f"JSON解析错误：{e}")
            return None  # 返回 None 表示解析失败

        words_json = {
            'company_name': row[0],
            'company_intro': result_json['crawl_content'],
            'major_product': row[3]
        }
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {'role': 'system', 'content': system_prompt_filter},
                {'role': 'user', 'content': json.dumps(words_json, ensure_ascii=False)}
            ],
            temperature=1.0,
            response_format={"type": "json_object"}
        )
        try:
            print(response.choices[0].message.content)
            return response.choices[0].message.content
        except:
            print("process_row_new出错")
            return None
    else:
        return None
    
def process_row_new(row, nodes,rules,system_prompt_new):        
    abstract = summarize_crawl_content(row[4]) ## row是以tuple形式传递的，需要用index而不是列名
    if abstract is not None:
        try:
            result_json = json.loads(abstract)
        except json.JSONDecodeError as e:
            print(f"JSON解析错误：{e}")
            return None  # 返回 None 表示解析失败

        words_json = {
            'nodes': nodes,
            'company_name': row[0],
            'company_intro': result_json['crawl_content'],
            'website': row[1],
            'major_product': row[3],
            'rules': rules,
            'certainty': str(row[5])
        }
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {'role': 'system', 'content': system_prompt_new},
                {'role': 'user', 'content': json.dumps(words_json, ensure_ascii=False)}
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        try:
            print(response.choices[0].message.content)
            return response.choices[0].message.content
        except:
            print("process_row_new出错")
            return None
    else:
        return None

def get_data_from_mysql_in_batches(query):
    return get_data_from_mysql(query)
    # results = []
    # offset = 0
    # has_more = True
    # while has_more:
    #     batch_query = f"{query} LIMIT {batch_size} OFFSET {offset}"
    #     print(batch_query)
    #     batch_df = get_data_from_mysql(batch_query)
    #     if batch_df is not None and not batch_df.empty:
    #         results.append(batch_df)
    #         offset += batch_size
    #         print(f"Processed {len(batch_df)} rows")
    #     else:
    #         has_more = False
    # return pd.concat(results, ignore_index=True)

    
if __name__ == '__main__':
    set_start_method('spawn')
    start_time = time.time()

    query = """
    select b.company_name,a.website,b.other_website,a.major_product,b.crawl_content,
    certainty
    from company_result_info1220 a
    inner JOIN ent_website_info1220 b ON a.website = b.offcial_website
    where a.major_product like '%新能源汽车%'
    LIMIT 50 OFFSET 0
    """

    df = get_data_from_mysql_in_batches(query)
    print(df.head())

    if df.empty:
        print("No data found. Exiting.")
        exit()  # 如果没有数据，退出程序

    df.columns = ['company_name', 'website', 'other_website', 'major_product', 'crawl_content', 'certainty']
    print(df.columns)

    company_industry_list = []  # 存储公司及其产业链列表

    for row in df.itertuples(index=False, name=None):
        chain_filter_output = chain_filter(row)
        if chain_filter_output:  # 确保chain_filter_output不为空
            try:
                chain_filter_output_dict = json.loads(chain_filter_output)
                company_industry_list.append({
                    '公司名称': chain_filter_output_dict.get('公司名称', []),
                    '产业链列表': chain_filter_output_dict.get('产业链列表', [])
                })
            except json.JSONDecodeError as e:
                print(f"JSON解析错误：{e}")

    print(company_industry_list)


    # 使用Pool来并行处理数据
    with ProcessPoolExecutor(max_workers=50) as executor:
        results = {}
        for i, company_info in enumerate(company_industry_list):
            company_name = company_info['公司名称']
            industry_list = company_info['产业链列表']
            # 根据公司名称从df中获取对应的行数据
            row = df[df['company_name'] == company_name].iloc[0]  
            for industry_name in industry_list:
                # 读取规则和节点
                rules = get_rules(industry_name)
                nodes = get_nodes(industry_name)

                system_prompt_new = f'''你是一个产业链分析专家,也是一个构建产业链知识图谱的专家。

                以下是公司名称(company_name)，公司简介(company_intro)，公司网站(website)，公司主营产品(major_product)，置信度(certainty)，我会以Json形式给出：
                {{
                    "company_name":"",
                    "company_intro":"",
                    "website":"",
                    "major_product":"",
                    "certainty":""
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

                    - 请你严格遵守我提供的硬规则{rules}中的内容。

                请你以JSON格式返回结果，例如：

                {{
                    "企业名称": "广州宇曦电子科技有限公司",
                    "主营产品": "锂电池充电器",
                    "企业网站": "http://www.ytechate.com/",
                    "公司简介": "广州宇曦电子科技有限公司是国内一家专业定制化电源及测试系统的高新技术企业，公司集研发、生产、销售、服务于一体。",
                    "匹配节点": "充电设施;销售与服务",
                    "匹配原因": "匹配上节点充电设施的原因为主营产品中的锂电池充电器是充电设施中的一个重要组成部分;匹配上节点销售与服务的原因为公司简介中提到公司集研发、生产、销售、服务于一体。",
                    "certainty":"1",
                    "score": "96;99"
                }}

                特别注意：
                1.结果中的"匹配节点"只返回我提供的产业链节点中存在的节点{nodes}，不要出现主营产品中提到的但是我提供的产业链节点中{nodes}不存在的，也不要出现公司简介中提到的但是我提供的产业链节点{nodes}中不存在的。
                2.你要严格遵循我提供的产业链节点{nodes}去匹配，不要自行总结或推断新的节点，导致匹配节点不在我提供的产业链节点{nodes}中。
                3.如果公司简介或者主营产品与{industry_name}无关或者没有在{nodes}中找到合适的匹配节点，那么结果中的"匹配节点"以及"节点定义"都返回"无"不要返回"其他"，并且在结果中的"匹配原因"中说明原因.
                4.结果中的"certainty"是我上边给你的信息中的置信度(certainty)，值为1,2,3,4其中一个。
                5.结果中的"匹配节点"不要有重复的节点，不要无限输出。
                6.结果中的"公司简介"不要无限输出！
                7.结果中的"匹配原因"不要无限输出！
                
                需要再次强调的是，绝对不能出现匹配节点{nodes}以外的节点！下面开始：
                '''

                args = (row, nodes, rules, system_prompt_new)
                if industry_name not in results:
                    results[industry_name] = []
                results[industry_name].append(executor.submit(process_row_new, *args))


            # 每100条数据写入一次Excel
            if (i + 1) % 100 == 0 or i == len(company_industry_list) - 1:
                industry_data = {}
                for industry_name, futures in results.items():
                    industry_results = []
                    for future in futures:
                        result = future.result()
                        if result is not None:
                            try:
                                result_json = json.loads(result.replace("```", "").replace("json", ""))
                                industry_results.append(result_json)
                            except Exception as e:
                                print("result_json格式有问题", result, e)
                    if industry_results:
                        industry_data[industry_name] = industry_results

                # 为每个产业链创建一个Excel文件
                for industry_name, data in industry_data.items():
                    output_file_path = f'outputFiles/company_nodesV5_{industry_name}.xlsx'
                    industry_df = pd.DataFrame(data)
                    with pd.ExcelWriter(output_file_path, engine='xlsxwriter') as writer:
                        industry_df.to_excel(writer, sheet_name=f'company_nodes_{industry_name}', index=False)
                    print(f"数据已写入文件: company_nodesV4_{industry_name}.xlsx")

                # 打印当前进度
                print(f"已处理 {i + 1} 条数据")

                # 清空results以便下一次写入
                results = {}

    end_time = time.time()
    print(f"代码运行总时间：{end_time - start_time}")
