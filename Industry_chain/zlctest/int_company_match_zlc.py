import os
import mysql.connector
from transformers import BertTokenizer, BertModel
import torch
import faiss
import numpy as np
import json
from openai import OpenAI

# 加载预训练模型和分词器
tokenizer = BertTokenizer.from_pretrained('/data/ASRProject/Industry_chain/bert-base-chinese')
model = BertModel.from_pretrained('/data/ASRProject/Industry_chain/bert-base-chinese')

zlc_api_key = os.getenv('DEEPSEEK_API_KEY_LC')
sandro_api_key = os.getenv('DEEPSEEK_API_KEY')
mh_api_key = os.getenv('DEEPSEEK_API_KEY_MH')
gy_api_key = os.getenv('DEEPSEEK_API_KEY_GY')


client = OpenAI(
            api_key=sandro_api_key,
            base_url="https://api.deepseek.com/beta",
    )



prompts = '''
    你是一个产业链分析专家。以下是A公司名称(company_name_A)，A公司简介(company_intro_A)，
    A公司的产品应用领域(company_field_A)。
    还有一些候选公司的信息，在candidates_companies_info中给出。这些候选公司的信息用“|”隔开，每个候选公司中包括公司名称、公司简介和主营产品。
    我会以Json形式给出：
    {
        "company_name_A":"",
        "company_intro_A":"",
        "company_field_A":"",
        "candidates_companies_info":""
    }

    请你根据公司简介，以及公司产品的应用领域，在候选公司（candidates_companies_info）中匹配出company_name_A的多个潜在生意伙伴，具体匹配规则为：
    - 产品应用场景或领域重合：公司A的产品应用领域可能会与其他公司的产品应用领域有重合。比如，如果公司A的产品应用于某个特定场景或领域，而其他公司也有类似的产品，那么这些公司是公司A的潜在生意伙伴。
    - 供应链上的互补性：公司A可能需要某种特定的原材料或服务，而有些公司正好提供这样的产品或服务，那么这些公司是公司A的潜在生意伙伴。
    注意：你必须要一条条阅读候选公司的信息，一条条地匹配，有可能一家公司会匹配出多家潜在生意伙伴。
    结果输出：请以Json的方式返回答案，示例如下：
    {
        "公司名称":"广州赛宝计量检测中心服务有限公司",
        "匹配公司名单":[
            {
                "company_name":"匹配公司1",
                "reason":"匹配原因1"
            },
            {
                "company_name":"匹配公司2",
                "reason":"匹配原因2"
            },...
        ]
    }
    如果没有匹配的，匹配公司名单直接返回[]即可。
    请严格按照上面的要求返回，只返回JSON即可，不需要其他内容，现在开始：   


'''

def get_embedding(text):
    inputs = tokenizer(text, return_tensors='pt', truncation=True, padding='max_length', max_length=512)
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
        product_application_area,
        major_product
    FROM company_info_summary_internal
    '''
    rows = execute_mysql_query(query)
    infos = [str({"公司名称":clean_str(str(r[0])),"公司简介":clean_str(str(r[1])),"产品应用领域":clean_str(str(r[2])),"主营产品":clean_str(str(r[3]))}) for r in rows]
    file_path = 'company_info_zlc.txt'
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
    faiss.write_index(index, 'company_info.index')

def get_matching_companies():
    query = '''
        SELECT company_name,
        company_profile,
        product_application_area 
    FROM company_info_summary_internal LIMIT 500
    '''
    rows = execute_mysql_query(query)
    infos = [str({"公司名称":clean_str(str(r[0])),"公司简介":clean_str(str(r[1])),"主营产品":clean_str(str(r[2]))}) for r in rows]
    file_path = "company_info_zlc.txt"  # 确保文件路径正确
    index = faiss.read_index('company_info.index')
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


    insert_data_to_mysql('company_matching_test',data)



if __name__ == '__main__':
    print('----1. 建立向量数据库，建立索引')
    get_faiss()
    print('----2. 粗筛')
    get_matching_companies()
    into_database()
    print('----3. 建表，汇总')
    drop_query = '''
        drop table if exists company_matching_full_table
    '''
    execute_mysql_query(drop_query)

    calculate_query = '''

        create table company_matching_full_table as 
        select a.company_name,a.candidate,c.company_profile compnany_profile_major,c.product_application_area product_application_area_major,
        b.company_profile,b.product_application_area 
        from company_matching_test a 
        join (select company_name,company_profile,product_application_area from company_info_summary_internal) b 
        on a.candidate = b.company_name
        join  (select company_name,company_profile,product_application_area from company_info_summary_internal) c 
        on a.company_name = c.company_name;
    '''
    execute_mysql_query(calculate_query)
    print('----4. 开始匹配任务')

    query = '''     
        SELECT 
            company_name, max(compnany_profile_major)compnany_profile_major,max(product_application_area)product_application_area,
            GROUP_CONCAT(
                CONCAT(
                    '公司名称:', candidate, 
                    ',公司简介:', company_profile, 
                    ',主营产品:', product_application_area
                ) 
                SEPARATOR '|'
            ) AS aggregated_info
        FROM 
            company_matching_full_table
        GROUP BY 
            company_name;
    '''
    rows = execute_mysql_query(query)

    # {
    #     "company_name_A":"",
    #     "company_intro_A":"",
    #     "company_field_A":"",
    #     "candidates_companies_info":""
    # }
    final = []
    errors = []
    total = len(rows)
    i = 1
    for row in rows:
        question = json.dumps({'company_name_A':str(row[0]),'company_intro_A':str(row[1]),'company_field_A':str(row[2]),'candidates_companies_info':str(row[3])},ensure_ascii= False)           
        try:
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {'role': 'system', 'content': prompts},
                    {'role': 'user', 'content': question}
                ],
                temperature=0.8,
                response_format={"type": "json_object"}
            )
            result = response.choices[0].message.content
            result = json.loads(result)
            final.append(f"{result['公司名称']},{result['匹配公司名单']}")
            print(f'当前第{i}条，共{total}条：{result}')
        except:
            errors.append(question)
            continue
        finally:
            i = i + 1
    
    with open('zlcresult_2.txt','w') as f:
        f.write('\n'.join(final))


