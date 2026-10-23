import json
import mysql.connector
from mysql.connector import Error
from openai import OpenAI
import os
from datetime import datetime
from multiprocessing import Pool, cpu_count
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
client = OpenAI(
    api_key=sandro_api_key,
    base_url="https://api.deepseek.com",
)

# 总共需要处理的数据条数
total_records_to_process = 20000
# 每次的数据处理条数
records_per_batch = 500
# 已处理的数据条数
processed_records = 7500

# 产业链名称列表
industry_names = [
    "电气设备", "电子器件", "医疗器械", "消费电子","无人驾驶", 
    "集成电路", "元宇宙", "新能源汽车", "电子信息", "机械设备与零件",
    "3D打印", "卫星导航", "无人机", "大飞机", "激光",
    "汽车", "眼镜", "工业母机", "工业软件", "人工智能",
    "光伏", "合成生物", "5G", "检验检测", "储能",
    "芯片", "氢能", "低碳经济","低空经济", "能源环保", 
    "仪器仪表","装备制造", "通信设备", "半导体", "新材料", 
    "医疗美容", "大健康", "机器人", "生命健康", "生物医药",
    "风电","轨道交通装备","脑机接口",
    "智能家居","物联网","云计算","服装","绿色建筑",
    "可再生能源","环保技术","生物科技","数字媒体","电子商务",
    "食品科技","海洋经济","航空航天","数字安全","纳米技术",
    "量子计算","精细化工","金属加工","超导材料","船舶制造",
    "生物经济","直播电商","在线教育","AI智能体","家具制造",
    "家电设备","端侧AI","人形机器人","未来显示","算力",
    "新能源", "首发经济","未来信息" ,"虚拟现实","碳中和",
    "远程医疗","智能交通","智能电网","智能金融","智能农业"
]

# 提示词
system_prompt_filter = '''你是一个产业链分析专家。以下是公司名称(company_name)，公司简介(company_intro)，和公司主营产品(major_product)，我会以Json形式给出：
    {{
        "company_name":"{company_name}",
        "company_intro":"{company_intro}",
        "major_product":"{major_product}"
    }}

以下是产业链列表：{industry_names}，其中包含了多个字符串元素，每个字符串代表一个产业链名称，每个元素之间用逗号分隔。

请你利用你的分析能力，结合公司名称，公司简介以及公司主营产品，在上边给出的产业链列表中匹配出与该公司可能相关的产业链。
如果在上边给出的产业链列表中没有找到能够匹配上的，那么可以给出其他适合的产业链。
请以JSON的格式返回结果，例如：
{{
    "公司名称":"广州宇曦电子科技有限公司",
    "产业链列表":["电气设备","电子器件","新能源汽车","电子信息","机械设备与零件"]
}}

注意：
1.返回结果中键的名字必须是"公司名称"，"产业链列表"，不可以是别的！
2.返回结果中的"产业链列表"中的内容只能从{industry_names}列表中进行匹配。
'''

def create_new_table():
    """创建新表"""
    try:
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        
        create_table_query = """
        CREATE TABLE IF NOT EXISTS company_industry_matches (
            id INT AUTO_INCREMENT PRIMARY KEY,
            company_name VARCHAR(500),
            company_intro TEXT,
            major_product TEXT,
            matched_industries JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
        cursor.execute(create_table_query)
        connection.commit()
        print("新表 company_industry_matches 创建成功")
    except Error as e:
        print(f"创建新表时出错: {e}")
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

def fetch_batch_data(batch_size, offset):
    try:
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        query = f"""
        select entity_name company_name, NULL website, business_scope company_intro, product_name AS major_product, NULL certainty, gm_third trd_industry 
        from inner_company0604
        where entity_name<>'未获取'
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

def insert_match_data(data):
    """插入匹配结果到新表"""
    try:
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        query = """
        INSERT INTO company_industry_matches (company_name, company_intro, major_product, matched_industries)
        VALUES (%s, %s, %s, %s)
        """
        cursor.executemany(query, data)
        connection.commit()
        print(f"成功插入 {len(data)} 条匹配记录")
    except Error as e:
        print(f"Error inserting data into database: {e}")
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

def process_company(company_info, industry_names):
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

        filter_response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {'role': 'system', 'content': filter_prompt},
                {'role': 'user', 'content': json.dumps(company_info, ensure_ascii=False)}
            ],
            temperature=0.6,
            response_format={"type": "json_object"}              
        )
        filter_result = filter_response.choices[0].message.content
        potential_industries = json.loads(filter_result)['产业链列表']
        print(f"Potential industries for {company_info['company_name']}: {potential_industries}")

        # 返回匹配结果
        return {
            'company_name': company_info['company_name'],
            'company_intro': company_info['company_intro'],
            'major_product': company_info['major_product'],
            'matched_industries': json.dumps(potential_industries, ensure_ascii=False)
        }

    except Exception as e:
        print(f"Error processing company {company_info['company_name']}: {e}")
        return None

def process_batch(batch_data, industry_names):
    """处理单个批次的数据"""
    all_results = []
    for row in batch_data:
        company_info = {
            'company_name': row['company_name'],
            'company_intro': row['company_intro'],
            'major_product': row['major_product'],
            'certainty': row['certainty'],
            'trd_industry': row['trd_industry']
        }
        
        result = process_company(company_info, industry_names)
        if result:
            all_results.append((
                result['company_name'],
                result['company_intro'],
                result['major_product'],
                result['matched_industries']
            ))
    return all_results

def main():
    global processed_records
    
    # 创建新表
    create_new_table()
    
    # 设置进程池大小
    num_processes = 20
    
    while processed_records < total_records_to_process:
        try:
            offset = processed_records
            batch_data = fetch_batch_data(records_per_batch, offset)
            if not batch_data:
                print("No more data to process.")
                break

            # 将批次数据分成多个子批次
            chunk_size = max(1, len(batch_data) // num_processes)
            chunks = [batch_data[i:i + chunk_size] for i in range(0, len(batch_data), chunk_size)]

            # 使用进程池处理数据
            with Pool(processes=num_processes) as pool:
                results = pool.starmap(process_batch, [(chunk, industry_names) for chunk in chunks])

            # 合并结果
            all_results = []
            for result in results:
                all_results.extend(result)

            if all_results:
                insert_match_data(all_results)
            
            processed_records += len(batch_data)
            print(f"Processed {processed_records} records so far.")
            
            # 添加短暂延迟避免API限流
            time.sleep(1)
            
        except Exception as e:
            print(f"Error processing batch at offset {offset}: {e}")
            processed_records += len(batch_data)  # 确保进度不会丢失
            continue

if __name__ == "__main__":
    main()