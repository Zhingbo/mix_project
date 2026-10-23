import json
import pandas as pd
from multiprocessing import Pool, set_start_method
import time
import mysql.connector
import os
import multiprocessing
from openai import OpenAI

# 配置API密钥和系统提示
zlc_api_key = os.getenv('DEEPSEEK_API_KEY_LC')
sandro_api_key = os.getenv('DEEPSEEK_API_KEY')
mh_api_key = os.getenv('DEEPSEEK_API_KEY_MH')
gy_api_key = os.getenv('DEEPSEEK_API_KEY_GY')

system_prompt = '''你是一个擅于归纳总结的专家。
以下是一些公司网站的抓取内容(crawl_content)，请你总结概括出每一家公司的公司简介,以及公司产品的应用领域，最后以JSON的格式返回到结果中。
结果中应该包含两部分：
    1.公司简介
    2.产品应用领域

输出示例如下：
{
    "公司简介":"广东顺德和壹设计咨询有限公司经营范围包括工业产品设计、动画设计、平面设计及上述项目的咨询服务；家电产品、电子产品、美容产品研发；企业品牌策划及咨询服务；制造、销售：家用电器、电子产品、文化用品；经营和代理各类商品及技术的进出口业务。",
    "产品应用领域":"工业产品设计,动画设计,平面设计"
}

注意：
1.返回结果中键的名字一定是"公司简介"和"产品应用领域"，不可以是别的！！
2.总结出来的公司简介中只需要有与公司业务相关的内容，公司是干什么的，公司的产品以及公司的产品应用场景领域就可以，不要有公司成立时间，注册地这些。
'''

client = OpenAI(
    api_key=os.getenv("VOLCENGINE_ARK_API_KEY"),
    base_url="https://ark.cn-beijing.volces.com/api/v3"
)

# 数据库连接配置
db_config = {
    'user': 'remote_user',
    'password': os.getenv('DB_PASSWORD_REMOTE'),
    'host': '8.141.23.4',
    'database': 'business_data'
}

def get_data_from_mysql(query, offset, limit):
    try:
        cnx = mysql.connector.connect(**db_config)
        cursor = cnx.cursor()
        cursor.execute(query, (limit, offset))
        df = pd.DataFrame(cursor.fetchall(), columns=[i[0] for i in cursor.description])
        cursor.close()
        cnx.close()
        return df
    except mysql.connector.Error as err:
        print("Something went wrong: {}".format(err))
        return None

def summarize_crawl_content(crawl_content):
    if crawl_content:
        words_json = {
            'crawl_content': crawl_content
        }
        try:
            response = client.chat.completions.create(
                model="ep-20250205154622-7gm5g",
                messages=[
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': json.dumps(words_json, ensure_ascii=False)}
                ],
                response_format={"type": "json_object"}
            )
            if response.choices and response.choices[0].message.content:
                raw_response = response.choices[0].message.content
                print(f"API response: {raw_response}")
                return raw_response
            else:
                print("API response is empty or invalid.")
                return None
        except Exception as e:
            print(f"Error occurred while calling API: {e}")
            return None
    else:
        print("crawl_content列不存在或为空。")
        return None

def process_row(row, cursor):
    summary_result = summarize_crawl_content(row['crawl_content'])
    if summary_result:
        try:
            summary = json.loads(summary_result)
            company_profile = summary.get('公司简介', '')
            product_application_area = summary.get('产品应用领域', '')

            insert_query = """
            INSERT INTO company_info_summary (company_name, website, other_website, major_product, crawl_content, certainty, company_profile, product_application_area)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(insert_query, (
                row['company_name'], row['website'], row['other_website'], row['major_product'], row['crawl_content'],
                row['certainty'], company_profile, product_application_area))
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}. Summary result: {summary_result}")
        except Exception as e:
            print(f"Error occurred while processing row: {e}")
    else:
        print(f"Summary result is empty for company: {row['company_name']}")

def worker(args):
    df_chunk, cursor_config = args
    try:
        cnx = mysql.connector.connect(**cursor_config)
        cursor = cnx.cursor()

        for index, row in df_chunk.iterrows():
            process_row(row, cursor)

        cnx.commit()
    except mysql.connector.Error as err:
        print(f"Database error: {err}")
    except Exception as e:
        print(f"Error occurred in worker: {e}")
    finally:
        if 'cursor' in locals() and cursor:
            cursor.close()
        if 'cnx' in locals() and cnx:
            cnx.close()

if __name__ == '__main__':
    set_start_method('spawn')
    start_time = time.time()

    query = """
    SELECT company_name,
        offcial_website AS website,
        other_website,
        NULL AS major_product,
        crawl_content,
        999 AS certainty
    FROM ent_website_info a
    where not exists (select 1 from company_product_detail_info b where a.company_name=b.company_name)
    and not exists (select 1 from company_info_summary c where a.company_name = c.company_name)
    AND crawl_content IS NOT NULL
    LIMIT %s OFFSET %s
    """

    batch_size = 300
    offset = 0

    while True:
        print(f"Fetching data with offset {offset} and limit {batch_size}")
        df = get_data_from_mysql(query, offset, batch_size)
        if df is None or df.empty:
            print(f"No more data to process at offset {offset}.")
            break

        print(f"Processing batch starting at offset {offset} with {len(df)} rows.")

        df.columns = ['company_name', 'website', 'other_website', 'major_product', 'crawl_content', 'certainty']

        chunksize = len(df) // 30 + 1
        chunks = [df[i:i + chunksize] for i in range(0, len(df), chunksize)]

        with Pool(processes=30) as pool:
            pool.map(worker, [(chunk, db_config) for chunk in chunks])

        offset += batch_size

    print("Data insertion completed.")
    end_time = time.time()
    print(f"代码运行总时间：{end_time - start_time}")