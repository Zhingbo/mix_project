import os
import mysql.connector
from transformers import BertTokenizer, BertModel
import torch
import faiss
import numpy as np
import json
from openai import OpenAI
import time
import pandas as pd

# 加载预训练模型和分词器
tokenizer = BertTokenizer.from_pretrained('/data/ASRProject/Industry_chain/bert-base-chinese')
model = BertModel.from_pretrained('/data/ASRProject/Industry_chain/bert-base-chinese')

zlc_api_key = os.getenv('DEEPSEEK_API_KEY_LC')
sandro_api_key = os.getenv('DEEPSEEK_API_KEY')
mh_api_key = os.getenv('DEEPSEEK_API_KEY_MH')
gy_api_key = os.getenv('DEEPSEEK_API_KEY_GY')


client = OpenAI(
            api_key=sandro_api_key,
            base_url="https://api.deepseek.com",
    )



prompts = '''
    你是一个商业分析专家。以下是A公司名称(company_name_A)，A公司简介(company_intro_A)，经营范围(business_scope_A)，A公司主营产品(major_product_A)和A公司的产品应用领域(company_field_A)，以及行业(gm_third_A)。
    还有一些候选公司的信息，在candidates_companies_info中给出。这些候选公司的信息用“|”隔开，每个候选公司中包括公司名称、公司简介、产品应用领域和公司主营产品。
    我会以Json形式给出：
    {
        "company_name_A":"",
        "company_intro_A":"",
        "business_scope_A":"",
        "major_product_A":"",
        "company_field_A":"",
        "gm_third_A":"",
        "candidates_companies_info":""
    }

    请你根据我上边提供的信息以及你自身的知识储备，在候选公司（candidates_companies_info）中匹配出A公司的所有潜在生意伙伴。
    匹配规则：
    1. 产品供需匹配：
        - A公司产品应用领域 ∈ 候选公司产品应用领域
        - 候选公司主营产品 ∈ A公司经营范围（原材料/服务需求）
    2. 行业协同匹配：
        - 行业相同：直接匹配
    3. 业务场景匹配：
        - 通过公司简介分析核心业务场景
        - 验证候选公司产品能否解决A公司业务场景中的需求
    4. 你必须要逐条阅读候选公司的信息，逐条进行匹配，有可能一家公司会匹配出多家潜在生意伙伴。

    结果包括：公司名称，经营范围，公司主营产品，产品应用领域，行业和匹配公司名单。
    匹配公司名单中要包括候选公司的名称company_name，候选公司的经营范围business_scope，候选公司的主营产品major_product，候选公司的行业industry和匹配原因reason。
    如果没有匹配上任何企业，那么请在结果中的"匹配公司名单"里的"reason"中说明没有匹配上企业的原因是什么，"匹配公司名单"里的其余内容都返回"无"即可。

    请以Json的方式返回答案，示例如下：
    {
        "公司名称":"广州赛宝计量检测中心服务有限公司",
        "经营范围":"电气设备",
        "公司主营产品":"产品1，产品2，产品3",
        "产品应用领域":"应用领域1，应用领域2，应用领域3",
        "行业":"电子制造",
        "匹配公司名单":[
            {
                "company_name":"匹配公司1",
                "business_scope":"经营范围1",
                "major_product":"主营产品1，主营产品2",
                "industry":"行业1",
                "reason":"匹配原因1"
            },
            {
                "company_name":"匹配公司2",
                "business_scope":"经营范围2",
                "major_product":"主营产品1，主营产品2",
                "industry":"行业2",
                "reason":"匹配原因2"
            },...
        ]
    }
    
    注意：
    1.对于匹配上的公司，匹配原因"reason"请说明的具体些，落实在公司具体的产品和应用场景上，不要太过笼统，输出示例："根据公司A的产品在某某应用领域，分析出候选公司B生产的某某产品可以应用到A公司的这个领域内，所以匹配上"。
    2.不论是匹配出企业还是没匹配出企业都请严格按照上面的规则和输出格式返回结果，只返回JSON即可，不需要其他内容。   
    3.如果匹配上的企业有多家，那么需要你按照上边的"匹配公司名单"格式以列表中的每个元素都是一个字典的格式返回结果。


'''

def get_embedding(text):
    inputs = tokenizer(text, return_tensors='pt', truncation=True, padding=True, max_length=512)
    with torch.no_grad():
        outputs = model(**inputs)
    return outputs.last_hidden_state.mean(dim=1).squeeze().numpy()



def execute_mysql_query(query):
    """
    执行 MySQL 查询，支持 SELECT 和建表类操作。
    
    Args:
        query (str): SQL 查询字符串。
        
    Returns:
        list or None: 对于 SELECT 查询，返回查询结果列表；对于其他操作，返回 None。
    """
    # 数据库连接配置
    cnx = mysql.connector.connect(
        user='remote_user',
        password=os.getenv('DB_PASSWORD_REMOTE'),
        host='8.141.23.4',
        database='business_data'
    )
    cursor = cnx.cursor()
    try:
        # 执行查询
        cursor.execute(query)

        # 判断是否为 SELECT 查询
        if query.strip().lower().startswith("select"):
            rows = cursor.fetchall()  # 获取查询结果
            return rows 
        else:
            cnx.commit()  # 提交事务
        
    except mysql.connector.Error as err:
        print("Something went wrong: {}".format(err))
        return None
    finally:
        # 确保关闭游标和连接
        cursor.close()
        cnx.close()
    
def insert_data_to_mysql(table,data):
    cnx = mysql.connector.connect(
        user='remote_user',
        password=os.getenv('DB_PASSWORD_REMOTE'),
        host='8.141.23.4',
        database='business_data'
    )
    cursor = cnx.cursor()
    placeholders = ', '.join(['%s'] * len(data[0]))  # 根据每条数据的长度生成占位符
    insert_query = f"INSERT INTO {table} VALUES ({placeholders})"
    try:
        # 执行批量插入
        cursor.executemany(insert_query, data)
        # 提交事务
        cnx.commit()
        cursor.close()
        cnx.close()
        print(f"{cursor.rowcount} rows inserted successfully into {table}.")
    except mysql.connector.Error as err:
        print(f"Error: {err}")
        cnx.rollback()
        cursor.close()
        cnx.close()



def search(query, index,k=20):
    query_embedding = get_embedding(query).reshape(1, -1).astype('float32')
    distances, indices = index.search(query_embedding, k)
    return indices, distances


def clean_str(inputStr):
    return inputStr.replace('"','').replace("{","").replace("}","").replace(":","")


def get_faiss():
    '''
        将知识写入向量数据库
    '''
    query = '''
        SELECT company_name,
        company_profile,
        business_scope,
        product_application_area,
        major_product,
        gm_third
    FROM inner_company_match0609
    '''
    rows = execute_mysql_query(query)
    infos = [str({"公司名称":clean_str(str(r[0])),"公司简介":clean_str(str(r[1])),"经营范围":clean_str(str(r[2])),"产品应用领域":clean_str(str(r[3])),"公司主营产品":clean_str(str(r[4])),"行业":clean_str(str(r[5]))}) for r in rows]
    file_path = 'company_info_total0609.txt'
    with open(file_path,'w') as f:
        f.write("\n".join(infos))
        f.close()
    with open(file_path, 'r', encoding='utf-8') as file:
        documents = file.readlines()
    # 将文档转换为向量
    embeddings = [get_embedding(doc) for doc in documents]
    # 将嵌入向量转换为 NumPy 数组
    embedding_matrix = np.array(embeddings).astype('float32')
    # 获取向量的维度
    d = embedding_matrix.shape[1]
    # 创建 FAISS 索引
    index = faiss.IndexFlatL2(d)
    # 添加向量到索引
    index.add(embedding_matrix)
    faiss.write_index(index, 'company_info0609.index')

def get_matching_companies():
    query = '''
        SELECT company_name,
        company_profile,
        business_scope,
        product_application_area,
        major_product,
        gm_third
    FROM inner_company_match0609
    '''
    rows = execute_mysql_query(query)
    infos = [str({"公司名称":clean_str(str(r[0])),"公司简介":clean_str(str(r[1])),"经营范围":clean_str(str(r[2])),"产品应用领域":clean_str(str(r[3])),"公司主营产品":clean_str(str(r[4])),"行业":clean_str(str(r[5]))}) for r in rows]
    file_path = "company_info_total0609.txt"  # 确保文件路径正确
    index = faiss.read_index('company_info0609.index')
    with open(file_path, 'r', encoding='utf-8') as file:
        documents = file.readlines()
    matched_companies = []
    errors = []

    for info in infos:
        query =  f'{info}'
        indices, distances = search(query,index)
        # 输出最相似的文档
        results = []
        info = eval(info)
        for i, idx in enumerate(indices[0]):
            company_info = eval(documents[idx].replace("：",":"))
            if company_info['公司名称'] != info['公司名称']:
                results.append(company_info['公司名称'])
        print(info['公司名称'],'|'.join(results))
        matched_companies.append(info['公司名称']+','+'|'.join(results))
    
    with open('matched_companies.txt','w') as f:
        f.write("\n".join(matched_companies))
        f.close()

    with open('matching_errors.txt','w') as f:
        f.write("\n".join(errors))
        f.close()

def into_database():
    with open('matched_companies.txt','r') as f:
        companies = f.readlines()
        f.close()
    
    companies =[(c.split(",")[0],c.split(",")[1]) for c in companies]
    # 结果列表
    data = []

    # 遍历数据
    for item in companies:
        # 获取元组中的第一个元素（ID）和第二个元素（'a|b|c' 或 'b|c|d'）
        id, values = item
        
        # 将 'a|b|c' 拆分为 ['a', 'b', 'c']
        values_list = values.split('|')
        
        # 遍历拆分后的值，创建新的元组并添加到结果列表
        for value in values_list:
            data.append((id, value))


    insert_data_to_mysql('company_matching_0609',data)



if __name__ == '__main__':
    start_time = time.time()

    print('----1. 建立向量数据库，建立索引')
    get_faiss()
    print('----2. 粗筛')
    get_matching_companies()
    into_database()
    print('----3. 建表，汇总')
    drop_query = '''
        drop table if exists company_matching_all0609
    '''
    execute_mysql_query(drop_query)

    calculate_query = '''

        create table company_matching_all0609 as 
        select a.company_name,a.candidate,c.company_profile compnany_profile_major,c.business_scope business_scope_major,c.product_application_area product_application_area_major,
        c.major_product major_product_major,c.gm_third gm_third_major,
        b.company_profile candidate_company_profile,b.business_scope candidate_business_scope, b.product_application_area candidate_product_application_area,
        b.major_product candidate_major_product,b.gm_third candidate_gm_third
        from company_matching_0609 a 
        join (select company_name,company_profile,business_scope,product_application_area,major_product,gm_third from inner_company_match0609) b 
        on a.candidate = b.company_name
        join  (select company_name,company_profile,business_scope,product_application_area,major_product,gm_third from inner_company_match0609) c 
        on a.company_name = c.company_name;
    '''
    execute_mysql_query(calculate_query)
    print('----4. 开始匹配任务')

    query = '''     
        SELECT 
            company_name, max(compnany_profile_major) compnany_profile_major,max(business_scope_major) business_scope_major,
            max(product_application_area_major) product_application_area_major,
            max(major_product_major) major_product_major,max(gm_third_major) gm_third_major,
            GROUP_CONCAT(
                CONCAT(
                    '公司名称:', candidate, 
                    ',公司简介:', candidate_company_profile,
                    ',经营范围:', candidate_business_scope,
                    ',公司主营产品:', candidate_major_product,
                    ',行业:', candidate_gm_third
                ) 
                SEPARATOR '|'
            ) AS aggregated_info
        FROM 
            company_matching_all0609
        GROUP BY 
            company_name;
    '''
    rows = execute_mysql_query(query)
    print(rows)

    final = []
    errors = []
    total = len(rows)
    i = 1

    # 初始化DataFrame
    df = pd.DataFrame(columns=['company_name_major', 'major_company_product', 'major_business_scope', 'major_field', 'major_industry','matching_company_name', 'matching_company_product','matching_business_scope','matching_industry', 'reason'])

    # 初始化空列表，用于存储每行数据的字典
    data = []

    for row in rows:
        question = json.dumps({'company_name_A': str(row[0]), 'company_intro_A': str(row[1]), 'business_scope_A': str(row[2]),'major_product_A': str(row[3]), 'company_field_A': str(row[4]),'gm_third_A': str(row[5]),'candidates_companies_info': str(row[6])}, ensure_ascii=False)
        try:
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {'role': 'system', 'content': prompts},
                    {'role': 'user', 'content': question}
                ],
                temperature=0.6,
                response_format={"type": "json_object"}
            )
            result = response.choices[0].message.content
            result = json.loads(result)
            company_name = result['公司名称']
            major_business_scope = result['经营范围']
            major_company_product = result['公司主营产品']
            major_field = result['产品应用领域']
            major_industry = result['行业']
            matching_company_info = result['匹配公司名单']

            # 将基本信息添加到列表
            basic_info = {
                'company_name_major': company_name,
                'major_company_product': major_company_product,
                'major_business_scope': major_business_scope,
                'major_field': major_field,
                'major_industry': major_industry,
                'matching_company_name': None,  # 初始化为None
                'matching_company_product': None,  # 初始化为None
                'matching_business_scope': None,  # 初始化为None
                'matching_industry': None,  # 初始化为None
                'reason': None  # 初始化为None
            }
            data.append(basic_info)
            

            # 确保matching_company_info是列表，并且每个元素都是字典
            if isinstance(matching_company_info, list) and all(isinstance(item, dict) for item in matching_company_info):
                
                # 遍历匹配公司名单，提取每家公司的信息
                for company_info in matching_company_info:
                    matching_info = {
                        'company_name_major': company_name,
                        'major_company_product': major_company_product,
                        'major_business_scope': major_business_scope,
                        'major_field': major_field,
                        'major_industry': major_industry,
                        'matching_company_name': company_info["company_name"],
                        'matching_company_product': company_info["major_product"],
                        'matching_business_scope': company_info["business_scope"],
                        'matching_industry': company_info["industry"],
                        'reason': company_info["reason"]
                    }
                    data.append(matching_info)
                    print(f'当前第{i}条，共{total}条：{result}')
                    df = pd.DataFrame(data)
                    print(f"Total rows in DataFrame: {len(df)}")
                    df.to_excel('company_corp_results_0609.xlsx', index=False)
                    print("数据已成功保存")

            else:
                print("Error: matching_company_info is not a list of dictionaries")
            
        except Exception as e:
            errors.append(question)
            print(f"Error processing row: {e}")  # 打印错误信息
            continue
        finally:
            i = i + 1

    # # 使用列表创建DataFrame
    # df = pd.DataFrame(data)          
            
    # print(f"Total rows in DataFrame: {len(df)}")

    # # 保存DataFrame到Excel文件
    # df.to_excel('company_corp_results_0609.xlsx', index=False)
    # print("数据已成功保存")

    end_time = time.time()
    print(f"代码运行总时间：{end_time - start_time}")