import json
from openai import OpenAI
from sympy import false
import pandas as pd
from multiprocessing import Pool
from multiprocessing import set_start_method
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import mysql.connector
from mysql.connector import Error
import concurrent.futures
import math
import os

industry_names = [
    "新能源汽车"
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
以下是一些公司网站的抓取内容(crawl_content)，请你总结概括出每一家公司的公司简介，字数不要太多，并以JSON的格式返回到结果中，输出示例如下：
{
    "crawl_content":"广东顺德和壹设计咨询有限公司主要属于工业设计行业，专注于产品设计、工业设计等领域。"
}

注意：
1.返回结果中键的名字一定是"crawl_content"，不可以是别的！
2.总结出来的公司简介中只需要有与公司业务相关的内容，公司是干什么的，公司的产品以及公司的产品应用场景领域就可以，不要有公司成立时间，公司地址，注册地这些.

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
            INSERT INTO company_nodes_info_result (company_name, website, major_product, company_intro, matched_nodes, match_reason, certainty,score)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            # 遍历结果列表
            for data in data_list:
                data = json.loads(data)
                # 准备插入的数据
                values = (data['企业名称'], data['企业网站'], data['主营产品'], data['公司简介'], data['匹配节点'], 
                          data['匹配原因'], data['置信度'], data['分数'])
                # 执行插入操作
                cursor.execute(sql, values)
        
        # 提交事务
        connection.commit()
        print("Data inserted successfully")
    finally:
        connection.close()
        print("MySQL connection is closed")
  

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
            response_format={"type": "json_object"},
            max_tokens=8000
        )
        try:
            return response.choices[0].message.content
        except:
            return None
    else:
        print("crawl_content列不存在或为空。")
        return None
    
def process_row_new(row, nodes, rules, system_prompt_new, industry_name):        
    abstract = summarize_crawl_content(row[4])
    if abstract is not None:
        try:
            result_json = json.loads(abstract)
        except json.JSONDecodeError as e:
            print(f"JSON解析错误：{e}")
            return None

        words_json = {
            'nodes': nodes,
            'company_name': row[0],
            'company_intro': result_json['crawl_content'],
            'website': row[1],
            'major_product': row[3],
            'rules': rules,
            'certainty': str(row[5]),
            'industry_name': industry_name  # 添加 industry_name
        }
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {'role': 'system', 'content': system_prompt_new},
                {'role': 'user', 'content': json.dumps(words_json, ensure_ascii=False)}
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
            max_tokens=8000
        )
        try:
            print(response.choices[0].message.content)
            result_content = json.loads(response.choices[0].message.content)
            return json.dumps(result_content, ensure_ascii=False)
        except:
            print("process_row_new出错")
            return None
    else:
        return None

def process_data_batch(data_batch, industry_name):
    results = []
    try:
        nodes = get_nodes(industry_name)
        rules = get_rules(industry_name)
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
                        "置信度":"1",
                        "分数": "96;99"
                    }}

                    特别注意：
                    1.结果中的"匹配节点"只返回我提供的产业链节点中存在的节点{nodes}，不要出现主营产品中提到的但是我提供的产业链节点中{nodes}不存在的，也不要出现公司简介中提到的但是我提供的产业链节点{nodes}中不存在的。
                    2.你要严格遵循我提供的产业链节点{nodes}去匹配，不要自行总结或推断新的节点，导致匹配节点不在我提供的产业链节点{nodes}中。
                    3.如果公司简介或者主营产品与{industry_name}无关或者没有在{nodes}中找到合适的匹配节点，那么结果中的"匹配节点"以及"节点定义"都返回"无"不要返回"其他"，并且在结果中的"匹配原因"中说明原因.
                    4.结果中的"certainty"是我上边给你的信息中的置信度(certainty)，值为1,2,3,4其中一个。
                    5.结果中的"匹配节点"不要有重复的节点，不要无限输出。
                    6.结果中的"公司简介"不要无限输出！
                    7.结果中的"匹配原因"不要无限输出！
                    8.返回结果中的键的名字只能是"企业名称"，"主营产品"，"企业网站"，"公司简介"，"匹配节点"，"匹配原因"，"置信度"，"分数"，不可以是别的！
                    
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

    # 存储所有处理结果的列表
    results = []

    # 数据库查询
    query = f"""
    SELECT b.company_name, a.website, b.other_website, a.major_product, b.crawl_content, a.certainty
    FROM company_result_info1220 a
    INNER JOIN ent_website_info1220 b ON a.website = b.offcial_website
    WHERE a.major_product LIKE '%{industry_names[0]}%'
    LIMIT 4000 OFFSET 1010
    """
    df = get_data_from_mysql(query)
    print(df)
    
    if not df.empty:
        df.columns = ['company_name', 'website', 'other_website', 'major_product', 'crawl_content', 'certainty']
        
        # 使用ProcessPoolExecutor创建进程池，并指定最大工作进程数为20
        with ProcessPoolExecutor(max_workers=50) as executor:
            # 计算每个批次的大小
            batch_size = math.ceil(len(df) / 50)
            
            # 为每个批次提交一个处理任务
            futures = []
            for i in range(0, len(df), batch_size):
                data_batch = df[i:i+batch_size]
                futures.append(executor.submit(process_data_batch, data_batch, industry_names[0]))
            
            # 收集结果
            for future in as_completed(futures):
                try:
                    batch_results = future.result()
                    if isinstance(batch_results, list):  # 确保结果是列表
                        results.extend(batch_results)  # 将批次结果添加到总结果列表中
                    else:
                        print(f"预期列表，但获取了：{type(batch_results)}")
                except Exception as e:
                    print(f"批次处理失败: {e}")

    print(results)
    # 将结果插入数据库
    insert_into_database(results)

    end_time = time.time()
    print(f"代码运行总时间：{end_time - start_time}")