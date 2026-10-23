import os
import json
from openai import OpenAI
from sympy import false
import pandas as pd
from multiprocessing import Pool
from multiprocessing import set_start_method
import time
import mysql.connector

industry_name='汽车'
nodes_file_path = f'resultTxt/new_nodes_{industry_name}.txt'
output_file_path = f'outputFiles/company_nodes_{industry_name}.xlsx'
rules_file_path = f'materials/rules_list_{industry_name}.txt'

zlc_api_key = os.getenv('DEEPSEEK_API_KEY_LC')
sandro_api_key = os.getenv('DEEPSEEK_API_KEY')

with open(rules_file_path, 'r', encoding='utf-8') as file:
    rules = file.read().splitlines()


# 读取产业链节点
with open(nodes_file_path, 'r', encoding='utf-8') as file:
    nodes = file.read().splitlines()


system_prompt = '''你是一个擅于归纳总结的专家。
以下是一些公司网站的抓取内容(crawl_content)，请你总结概括出每一家公司主要是做什么的，输出一段公司简介，并以JSON的格式返回到结果中，例如：
{
    "crawl_content":"广东顺德和壹设计咨询有限公司主要属于工业设计行业，专注于产品设计、工业设计等领域。"
}

'''

system_prompt_new = f'''你是一个产业链分析专家,也是一个构建产业链知识图谱的专家。

以下是{industry_name}产业链中所有节点(nodes)，公司名称(company_name)，公司简介(company_intro)，公司网站(website)，公司主营产品(major_product)和必须要遵守的硬规则(rules)。我会以Json形式给出：
{{
    "nodes":"",
    "company_name":"",
    "company_intro":"",
    "website":"",
    "major_product":"",
    "rules":""
}}

你的任务是根据公司简介(company_intro)和公司主营产品(major_product)在已有的产业链节点中找到至少1个最匹配的节点并给出你的匹配原因，然后结合{industry_name}产业链对每个节点进行定义说明，多个节点的定义用"|"分隔开。
具体匹配逻辑为：
    - 首先，你先去主营产品中找与{industry_name}相关的产品描述，再去已有的产业链节点中找是否有能匹配上的节点，匹配规则是产品描述和已有的产业链节点之间可能是包含关系，组成关系或者关联关系。
      比如：公司主营产品中包括新能源汽车用空压机FRA系列，你分析出这直接关联到新能源汽车的动力系统,你应该去已有的产业链节点中找与动力系统意思最为接近的节点，于是你匹配到的节点为"动力系统集成"。
      再比如：公司主营产品中提到新能源汽车测试方案，你分析出这直接关联到新能源汽车产业链的下游销售与服务环节，你应该去已有的产业链节点中找与销售服务环节意思最为接近的节点，于是你匹配到的节点为"销售与服务"。
      再比如：公司主营产品中包括新能源汽车电附件，汽车零部件及配件制造，你分析出这些都是零部件制造的重要组成部分，你应该去已有的产业链节点中找与零部件制造意思最为接近的节点，于是你匹配到的节点为"零部件制造"。

    - 如果你发现主营产品中与{industry_name}相关的产品描述太过于宽泛不具体，比如主营产品就只有{industry_name}，那么你需要去公司简介(company_intro)中找到这家公司是做什么的，根据这家公司是做什么的，公司的业务，产品描述，再去已有的产业链节点中找是否有能匹配上的节点，匹配规则是公司简介描述的内容和已有的产业链节点之间可能是包含关系，组成关系或者关联关系。
      比如：公司的主营产品包括新能源汽车，你不好判断出他具体的业务产品是什么，于是你去公司简介中找到这家公司是提供新能源汽车技术培训和人才培养的，于是你分析出这属于新能源汽车产业链的下游销售与服务环节，根据关联性，你应该去已有的产业链节点中找与销售服务环节意思最为接近的节点，于是你匹配到的节点为"销售与服务"。
      再比如：公司的主营产品包括新能源汽车产品，你不好判断出他具体的产品指的是什么，于是你去公司简介中找到这家公司多年来专注于为新能源汽车零件提供同步开发工艺优化验证制造等多元一体化的制造服务，于是你分析出这些涉及到新能源汽车上游的零部件制造以及下游的销售服务环节，你应该去已有的产业链节点中找与零部件制造以及销售服务环节意思最为接近的节点，于是你匹配到的节点为"零部件制造"和"销售与服务"。

    - 请你严格遵守我提供的硬规则(rules)中的内容。

请你以JSON格式返回结果，例如：

{{
    "企业名称": "广州宇曦电子科技有限公司",
    "主营产品": "锂电池充电器",
    "企业网站": "http://www.ytechate.com/",
    "公司简介": "广州宇曦电子科技有限公司是国内一家专业定制化电源及测试系统的高新技术企业，公司集研发、生产、销售、服务于一体。",
    "匹配节点": ["充电设施","销售与服务"],
    "节点定义": "充电设施包括车企主导的充电设施服务和公共充电服务商为主导的充电设施服务.|销售与服务包括整车销售、售后服务、维修保养等.",
    "匹配原因": "从主营产品中可以看到锂电池充电器是充电设施中的一个重要组成部分，所以匹配节点为充电设施；结合公司简介来看，公司集研发、生产、销售、服务于一体，所以匹配节点为销售与服务。"
}}

特别注意：
1.结果中的"匹配节点"只返回上边我提供的产业链节点(nodes)中存在的节点，不要出现主营产品中提到的但是已有产业链节点中不存在的，也不要出现公司简介中提到的但是已有产业链节点中不存在的。
比如，主营产品里有"智能机器人, 工业机器人，新能源汽车"，已有的产业链节点中只有"新能源汽车"这个节点，"工业机器人"和"智能机器人"都不在已有产业链节点中，那么匹配节点结果返回的应该只有新能源汽车。
2.你在结合公司简介和主营产品匹配我提供的产业链节点的时候，要尽可能的全面。也就是说如果主营产品或者公司简介涉及到我提供的产业链中的某个节点，那么不仅要匹配出这个大的节点，还要进一步细化，找出这个节点下与主营产品以及公司简介相关的子节点。
比如：主营产品包括"精密连接器, 精密注塑模具, 精密冲压模具, 精密注塑件, 精密冲压件"，已有产业链的节点包括"连接器,零部件制造"，你首先分析出主营产品包括的这些都属于新能源汽车零部件制造的一部分，所以匹配出节点为"零部件制造"，接下来你要继续对主营产品中的每部分进行匹配，你发现精密连接器可以匹配上"连接器"这个节点，因此匹配到的节点应该有两个，分别是"零部件制造"和"连接器"。
3.所有上边我列举的例子都仅供你参考，与你最终应该输出的结果没有直接联系，你不要直接用我例子中的结果，而是需要按照上边的匹配逻辑和规则自己去匹配。

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

def process_row_new(row, nodes):
    abstract = summarize_crawl_content(row[4]) ## row是以tuple形式传递的，需要用index而不是列名
    if abstract is not None:
        result_json = json.loads(abstract)
        words_json = {
            'nodes': nodes,
            'company_name': row[0],
            'company_intro': result_json['crawl_content'],
            'website': row[1],
            'major_product': row[3],
            'rules': rules
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



if __name__ == '__main__':
    set_start_method('spawn')
    start_time = time.time()

    # 从MySQL数据库获取数据
    query = """
    SELECT DISTINCT 
        a.company_name,
        a.website,
        b.other_website,
        a.major_product,
        b.crawl_content
    FROM 
        company_result_info_info a
    INNER JOIN 
        ent_website_info b ON a.website = b.offcial_website
    WHERE 
        a.website IS NOT NULL AND a.website <> '' AND a.website <> '未提及'
        AND b.crawl_content <> '' AND b.crawl_content <> '未提及' AND b.crawl_content IS NOT NULL
        AND b.crawl_content <> '{\"markdown\": \"\", \"metadata\": {\"title\": \"\", \"keywords\": \"\", \"description\": \"\"}}'
        AND a.company_name IN (SELECT company_name FROM guangfo_company_lists)
        AND a.major_product LIKE '%汽车%'
    """
    df = get_data_from_mysql(query)
    print(df)

    df.columns = ['company_name', 'website', 'other_website', 'major_product', 'crawl_content']
    print(df.columns)

    args = [(row, nodes) for row in df.itertuples(index=False, name=None)]
    
    # results = []
    # for row in  df.itertuples(index=False, name=None):
    #     results.append(process_row_new(row,nodes))
    #     break
    # print(results)

    with Pool(5) as pool:
        # 使用starmap而不是map，因为我们需要传递多个参数给process_row_new
        results = pool.starmap(process_row_new, args)
    # print(results)

    # 校验匹配节点
    validated_results = []
    for result in results:
        if result is not None:
            try:
                result_json = json.loads(result.replace("```", "").replace("json", ""))
                if '匹配节点' in result_json:
                    result_json['匹配节点'] = validate_matching_nodes(result_json['匹配节点'], nodes)
                validated_results.append(result_json)
            except:
                print("result_json格式有问题",result_json)

    new_df = pd.DataFrame(validated_results)
    print(new_df)
    new_df.to_excel(output_file_path, index=False)

    end_time = time.time()
    print(f"代码运行总时间：{end_time - start_time}")
