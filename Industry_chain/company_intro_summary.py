import os
import json
from openai import OpenAI
import pandas as pd
import time
import mysql.connector


zlc_api_key = os.getenv('DEEPSEEK_API_KEY_LC')
sandro_api_key = os.getenv('DEEPSEEK_API_KEY')
mh_api_key = os.getenv('DEEPSEEK_API_KEY_MH')
gy_api_key = os.getenv('DEEPSEEK_API_KEY_GY')


system_prompt = '''你是一个擅于归纳总结的专家。
以下是一些公司网站的抓取内容(crawl_content)，请你总结概括出每一家公司的公司简介,以及公司主营业务，最后以JSON的格式返回到结果中。
结果中应该包含两部分：
    1.公司简介
    2.公司主营业务

输出示例如下：
{
    "公司简介":"广东顺德和壹设计咨询有限公司成立于2012年07月20日，注册地位于佛山市顺德区北滘镇设计城居委会广东工业设计城二期东座1楼101，法定代表人为邓浩景。经营范围包括工业产品设计、动画设计、平面设计及上述项目的咨询服务；家电产品、电子产品、美容产品研发；企业品牌策划及咨询服务；制造、销售：家用电器、电子产品、文化用品；经营和代理各类商品及技术的进出口业务。",
    "公司主营业务":"工业产品设计,动画设计,平面设计"
}

注意：
1.返回结果中键的名字一定是"公司简介"，"公司主营业务"，不可以是别的！！
2.总结出来的公司简介中只需要有与公司业务相关的内容，公司是干什么的，公司的产品以及公司的产品应用场景领域就可以，不要有公司成立时间，注册地这些。

'''


# client = OpenAI(
#             api_key=mh_api_key,
#             base_url="https://api.deepseek.com",
#     )

client = OpenAI(
    api_key=os.getenv("VOLCENGINE_ARK_API_KEY"),
    base_url="https://ark.cn-beijing.volces.com/api/v3",
)

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
    
def summarize_crawl_content(crawl_content, max_length=65536):
    if crawl_content:  
        # 检查crawl_content的长度并进行截断
        if len(crawl_content) > max_length:
            print("crawl_content超出最大长度限制，将进行截断。")
            crawl_content = crawl_content[:max_length]
        
        try:
            words_json = {
                'crawl_content': crawl_content
            }
            # response = client.chat.completions.create(
            #     model="deepseek-chat",
            #     messages=[
            #         {'role': 'system', 'content': system_prompt},
            #         {'role': 'user', 'content': json.dumps(words_json, ensure_ascii=False)}
            #     ],
            #     temperature=1.0,
            #     response_format={"type": "json_object"},
            #     max_tokens=8000
            # )
            response = client.chat.completions.create(
                # model="ep-20250205103212-g9ql9",
                model="ep-20250217153205-d7px5",
                temperature=0.6,
                messages=[
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': json.dumps(words_json, ensure_ascii=False)}],
                response_format={
                    "type": "json_object"
                }
                )
            return response.choices[0].message.content
        except Exception as e:
            print(f"处理过程中发生错误：{e}，跳过当前内容。")
            return None
    else:
        print("crawl_content列不存在或为空。")
        return None


def get_data_from_mysql_in_batches(query):
    return get_data_from_mysql(query)


def process_row(row, cursor):
    # 处理每一行数据
    summary_result = summarize_crawl_content(row['crawl_content'])
    if summary_result:
        try:
            summary = json.loads(summary_result)
            print(summary)
            company_profile = summary.get('公司简介', '')
            product_application_area = summary.get('公司主营业务', '')

            # 插入新表
            insert_query = """
            INSERT INTO company_info_summary (company_name, website, other_website, major_product, crawl_content, certainty, company_profile, product_application_area)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(insert_query, (row['company_name'], row['website'], row['other_website'], row['major_product'], row['crawl_content'], row['certainty'], company_profile, product_application_area))
        except json.JSONDecodeError as e:
            print(f"JSONDecodeError: {e}")
            print("Invalid JSON content:", summary_result)
    else:
        print("summary_result is empty or None")

def main():
    start_time = time.time()

    query = """
    SELECT distinct company_name,
        offcial_website website,
        other_website,
        NULL major_product,
        crawl_content,
        NULL certainty
    FROM need_company_intro0321
    LIMIT 9890, 18446744073709551615
    """

    df = get_data_from_mysql(query)
    if df.empty:
        print("No data found. Exiting.")
        return

    df.columns = ['company_name', 'website', 'other_website', 'major_product', 'crawl_content', 'certainty']

    # 数据库连接配置
    cnx = mysql.connector.connect(
        user='remote_user',
        password=os.getenv('DB_PASSWORD_REMOTE'),
        host='8.141.23.4',
        database='business_data'
    )
    cursor = cnx.cursor()

    total_rows = len(df)  # 获取总行数
    for index, row in df.iterrows():
        process_row(row, cursor)
        # 打印进度信息
        print(f"Processed {index + 1}/{total_rows} rows. Company: {row['company_name']}")

    # 提交事务
    cnx.commit()

    # 关闭游标和连接
    cursor.close()
    cnx.close()

    print("Data insertion completed.")

    end_time = time.time()
    print(f"代码运行总时间：{end_time - start_time}")

if __name__ == '__main__':
    start_time = time.time()

    main()

    end_time = time.time()
    print(f"代码运行总时间：{end_time - start_time}")    
