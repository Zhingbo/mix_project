import os
import json
from openai import OpenAI
import pandas as pd
import time
import mysql.connector
from mysql.connector import Error
from zhipuai import ZhipuAI

# 配置行业名称和文件路径
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
    ]

# OpenAI API配置
sandro_api_key = os.getenv('DEEPSEEK_API_KEY')
zhipukey = '82be19c96af3da40cdf125044e349811.16lEnft5oNRMIeOb'

# 初始化OpenAI客户端
client = OpenAI(
    api_key=os.getenv("VOLCENGINE_ARK_API_KEY"),
    base_url="https://ark.cn-beijing.volces.com/api/v3",
)

# 数据库连接配置
def connect_to_mysql():
    try:
        cnx = mysql.connector.connect(
            user='remote_user',
            password=os.getenv('DB_PASSWORD_REMOTE'),
            host='8.141.23.4',
            database='business_data'
        )
        return cnx
    except Error as err:
        print(f"无法连接到数据库：{err}")
        return None

# 从数据库获取数据
def get_data_from_mysql(query):
    cnx = connect_to_mysql()
    if not cnx:
        return None
    cursor = cnx.cursor()
    try:
        cursor.execute(query)
        columns = [col[0] for col in cursor.description]  # 获取列名
        data = cursor.fetchall()
        df = pd.DataFrame(data, columns=columns)
        return df
    except Error as err:
        print(f"查询数据时出错：{err}")
    finally:
        cursor.close()
        cnx.close()
    return None

# 创建表
def create_table(cnx):
    cursor = cnx.cursor()
    create_table_query = """
    CREATE TABLE IF NOT EXISTS nodes_industry_mapping_new (
        id INT AUTO_INCREMENT PRIMARY KEY,
        nodes VARCHAR(255),
        name VARCHAR(255),
        level VARCHAR(255),
        full_name VARCHAR(255),
        industry_name VARCHAR(255), 
        reason TEXT
    )
    """
    try:
        cursor.execute(create_table_query)
        cnx.commit()
        print("表 nodes_industry_mapping_new 创建成功或已存在。")
    except Error as err:
        print(f"创建表时出错：{err}")
    finally:
        cursor.close()

# 插入数据
def insert_data(cnx, data):
    cursor = cnx.cursor()
    insert_query = """
    INSERT INTO nodes_industry_mapping_new (nodes, name, level, full_name, industry_name, reason)
    VALUES (%s, %s, %s, %s, %s, %s)
    """
    try:
        cursor.executemany(insert_query, data)
        cnx.commit()
        print(f"成功插入 {cursor.rowcount} 条数据。")
    except Error as err:
        print(f"插入数据时出错：{err}")
    finally:
        cursor.close()

# 匹配节点到行业
def match_node_to_industry(client, system_prompt_new, node):
    response = client.chat.completions.create(
        model="ep-20250217153205-d7px5",
        messages=[
            {'role': 'system', 'content': system_prompt_new},
            {'role': 'user', 'content': node}
        ],
        response_format={"type": "json_object"}
    )    
    # print(response.choices[0].message.content)
    return response.choices[0].message.content

def process_industry(industry_name):
    print(f"开始处理行业：{industry_name}")

    # 读取产业链节点
    nodes_file_path = f'resultTxt/nodes_{industry_name}.txt'
    with open(nodes_file_path, 'r', encoding='utf-8') as file:
        nodes = file.read().splitlines()
    print("产业链节点：", nodes)

    # 从MySQL数据库获取数据
    query = """
    SELECT DISTINCT name, level, full_name FROM mapping_industry_info_new
    """
    df = get_data_from_mysql(query)
    if df is None:
        print("未成功获取数据，程序将退出。")
        return

    # print("从数据库中获取的数据：")
    # print(df)

    # 构建名字信息字典
    name_info = {row['name']: (row['level'], row['full_name']) for _, row in df.iterrows()}

    # 构建匹配逻辑的系统提示
    names = df['name'].tolist()
    system_prompt_new = f'''你是一个行业分析专家，也是一个产业链知识专家。
    我会给你需要匹配的产业链节点名称{nodes}，你的任务是为每个节点在已有的行业名称库{names}中找到与{industry_name}相关的1个最匹配的行业名称，并给出你的匹配原因。

    具体匹配逻辑为：
    - 节点与行业名称之间可能是以下关系之一：包含关系、组成关系、相似关系、同类关系。你需要根据这些关系找到与节点最为相关的行业名称。
    - 下面是每种关系的具体含义：
    - **包含关系**：节点是行业名称的一部分。例如，节点“伺服器”包含于行业名称“伺服器生产制造”。
    - **组成关系**：节点是行业的组成部分。例如，节点“伺服器”是“机器人零部件制造”的组成部分。
    - **相似关系**：节点与行业名称在语义或功能用途上相似。例如，节点“原材料”与行业名称“新材料”语义相似。
    - **同类关系**：节点与行业名称属于同一类别。例如，节点“锂电池”与行业名称“新能源电池制造”属于同一类别。

    示例：
    - 有一个节点名称是“伺服器”，你分析出伺服器是机器人的核心零部件之一，你在行业名称库{names}中根据组成关系找到“机器人零部件制造”是最匹配最相关的行业名称。

    注意：
    - 如果存在多个行业名称与节点相关，优先选择更具体、更直接相关的行业名称（例如“机器人零部件制造”优于“机械制造”）。
    - 在匹配过程中，还需要考虑节点在产业链中的位置，例如上游原材料、中游零部件、下游终端产品等，以确保匹配的合理性。
    - 如果行业名称库{names}中没有能匹配上该节点的行业名称，那么请你给出一个能匹配该节点的行业名称并返回到结果"行业名称"中并给出匹配原因。

    最后请你以JSON格式返回结果，例如：
    {{
        "节点名称": "伺服器",
        "行业名称": "机器人零部件制造",
        "匹配原因": "伺服器是机器人的核心零部件之一，与机器人零部件制造这个行业名称最相关。"
    }}

    现在，请根据上述要求开始匹配：
    '''

    # 执行匹配逻辑
    results = []
    failed_nodes = []  # 用于记录匹配失败的节点
    for node in nodes:
        if node not in [industry_name, '上游', '中游', '下游']:
            try:
                result = match_node_to_industry(client, system_prompt_new, node)
                # 确保返回的字符串是有效的 JSON 格式
                try:
                    result = json.loads(result.replace("```", "").replace("json", ""))
                    results.append(result)
                    print(result)
                except json.JSONDecodeError as e:
                    print(f"JSON解析错误：{e}，节点：{node}")
                    failed_nodes.append((node, f"JSON解析错误：{e}"))
            except Exception as e:
                print(f"匹配节点时发生异常：{e}，节点：{node}")
                failed_nodes.append((node, f"异常：{e}"))

    print(f"行业 {industry_name} 的匹配结果：", results)

    # 保存匹配失败的节点到文件
    failed_nodes_file_path = f'resultTxt/failed_nodes_{industry_name}.txt'
    with open(failed_nodes_file_path, 'w', encoding='utf-8') as file:
        for node, reason in failed_nodes:
            file.write(f"节点：{node}, 原因：{reason}\n")
    print(f"行业 {industry_name} 匹配失败的节点已保存到文件：{failed_nodes_file_path}")

    # 连接到数据库
    cnx = connect_to_mysql()
    if cnx:
        # 创建表
        create_table(cnx)

        # 准备插入的数据
        data_to_insert = [
            (
                item['节点名称'],
                item['行业名称'],
                name_info.get(item['行业名称'], (None, None))[0],  # level
                name_info.get(item['行业名称'], (None, None))[1],  # full_name
                industry_name,
                item['匹配原因']
            )
            for item in results
        ]

        # 插入数据
        insert_data(cnx, data_to_insert)
        print(f"行业 {industry_name} 的数据已成功插入数据库。")

        # 关闭数据库连接
        cnx.close()


if __name__ == '__main__':
    start_time = time.time()

    # 逐个处理每个行业名称
    for industry_name in industry_names:
        process_industry(industry_name)

    end_time = time.time()
    print(f"代码运行总时间：{end_time - start_time}")