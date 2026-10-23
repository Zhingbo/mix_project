import os
import time
from datetime import datetime
import json
import yaml
from multiprocessing import Pool
from concurrent.futures import ThreadPoolExecutor
import networkx as nx
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from GoogleSearcher import GoogleSearcher
from Crawler import Crawler
from langchain_openai import ChatOpenAI
from functions import *
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import HumanMessage, SystemMessage
from langchain.agents import initialize_agent
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from zhipuai import ZhipuAI
from openai import OpenAI


# 定义日志记录函数
def log_message(user_id, message, log_type="INFO"):
    # 获取当前进程的PID
    pid = os.getpid()
    user_folder = f"user_{user_id}_pid_{pid}"
    os.makedirs(f"logs/{user_folder}", exist_ok=True)
    
    # 创建日志文件路径
    log_file = f"logs/{user_folder}/log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    
    # 格式化日志内容
    log_content = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][{log_type}] {message}\n"
    
    # 写入日志文件
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(log_content)
    
    # 同时打印到控制台（可选）
    print(log_content.strip())

# 读取项目配置文件
with open("settings.yaml", "r") as file:
    settings = yaml.load(file, Loader=yaml.FullLoader)

headers = settings['system_settings']['headers']
google_api_url = settings['system_settings']['google_api_url']
deepseek_api_key = settings['system_settings']['deepseek_api_key']
deepseek_url = settings['system_settings']['deepseek_url']
input_clean_prompts = settings['prompts']['input_clean']['content']
clean_info_prompts = settings['prompts']['clean_info']['content']
clean_node_info_prompts = settings['prompts']['clean_node_info']['content']
words_from_ocr_prompts = settings['prompts']['words_from_ocr']['content']
get_entity_prompts = settings['prompts']['get_entity']['content']
jina_api_url = settings['system_settings']['jina_api_url']
jina_api_headers = settings['system_settings']['jina_api_headers']
data_source_excel = settings['system_settings']['data_source_excel']
get_triples_prompts = settings['prompts']['get_triples']['content']
check_triples_prompts = settings['prompts']['check_triples']['content']
modify_triples_prompts = settings['prompts']['modify_triples']['content']


# 初始化火山引擎客户端
client = OpenAI(
    api_key=os.getenv("VOLCENGINE_ARK_API_KEY"),
    base_url='https://ark.cn-beijing.volces.com/api/v3',
)

def process_industry_data(clean_info_prompts, raw_content, user_id):
    try:
        # 如果输入内容过长，进行截断
        max_length = 65536
        if len(raw_content) > max_length:
            raw_content = raw_content[:max_length]
            log_message(user_id, "输入内容过长，已截断", log_type="WARNING")

        # 构造消息
        messages = [
            {"role": "system", "content": clean_info_prompts},
            {"role": "user", "content": raw_content}
        ]
        # 异步调用火山引擎模型
        response = client.chat.completions.create(
            model="ep-20250217153421-8lrxj",
            messages=messages,
            temperature=0.6,
            response_format={"type": "json_object"}
        )
        # 获取模型的输出内容和思维链内容
        reasoning_content = response.choices[0].message.reasoning_content
        content = response.choices[0].message.content

        # 记录思维链内容到日志
        log_message(user_id, f"Reasoning Content: {reasoning_content}", log_type="DEBUG")
        return content
    except Exception as e:
        log_message(user_id, f"Error in process_industry_data: {e}", log_type="ERROR")
        return None


def tool_search(industry_name, isNode=False, node="", isAux=True, user_id=None):
    try:
        clean_prompts = clean_node_info_prompts.format(industry=industry_name, node=node) if isNode else clean_info_prompts.format(industry=industry_name)
        google_searcher = GoogleSearcher(google_api_url, headers, industry_name)
        limit = 2 if isNode else 3
        try:
            raw_content = google_searcher.google_search(limit=limit, isNode=isNode, node=node)
        except Exception as e:
            log_message(user_id, f"Error in google_search: {e}", log_type="ERROR")
            return '无内容'
        urls = []
        querys = ""
        if raw_content is not None:
            urls = [r['url'] for r in raw_content['results']]
            querys = raw_content['search_term']
            log_message(user_id, f"Search query: {querys}")
            log_message(user_id, f"URLs: {urls}")

        url_file_path = f"materials/url_list_{industry_name}.txt"
        with open(url_file_path, 'a') as file:
            file.write(querys + '\n')
            for url in urls:
                file.write(url + '\n')
            file.write('\n')
        log_message(user_id, "数据源链接url已存入txt文件")

        total_info = []
        for url in urls:
            result = Crawler.crawl_url_data(url)
            if result is not None and result != '无内容':
                total_info.append(str(result))
        if not total_info:
            return '无内容'
        web_content = '\n'.join(total_info)
        html_knowledge = process_industry_data(clean_prompts, web_content, user_id)

        if isAux:
            try:
                aux_content = Crawler.crawl_data(industry_name, data_source_excel)
                aux_knowledge = process_industry_data(clean_prompts, aux_content, user_id)
                full_knowledge = (html_knowledge or "") + '\n' + (aux_knowledge or "")
                total_knowledge = process_industry_data(clean_prompts, full_knowledge, user_id)
            except Exception as e:
                log_message(user_id, f"Error in auxiliary data processing: {e}", log_type="ERROR")
                return '无内容'
        else:
            total_knowledge = html_knowledge
        return total_knowledge
    except BrokenPipeError:
        log_message(user_id, "BrokenPipeError occurred in tool_search", log_type="ERROR")
        return '无内容'


def tool_total_search(industry_name, user_id=None):
    center_node_info = tool_search(industry_name, user_id=user_id)
    log_message(user_id, f"搜索结果为: {center_node_info}")
    if center_node_info in ['无内容', '']:
        log_message(user_id, "未获取到有效内容，调用普通搜索逻辑")
        center_node_info = tool_search(industry_name, isNode=False, user_id=user_id)

    nodes = process_industry_data(get_entity_prompts.format(industry=industry_name), center_node_info, user_id)
    log_message(user_id, f"节点有: {nodes}")
    while True:
        try:
            nodes = json.loads(nodes.replace("```", "").replace("json", ""))
        except Exception as e:
            log_message(user_id, f"nodes解析失败，重新尝试: {e}", log_type="ERROR")
            nodes = process_industry_data(get_entity_prompts.format(industry=industry_name), center_node_info, user_id)
        else:
            break

    try:
        with open(f'materials/white_list_{industry_name}.txt', 'r', encoding='utf-8') as file:
            white_list = file.read().splitlines()
            for item in white_list:
                if item not in nodes:
                    nodes.append(item)
            log_message(user_id, f"加入白名单后的节点有: {nodes}")
    except FileNotFoundError:
        log_message(user_id, f"文件 materials/white_list_{industry_name}.txt 不存在。", log_type="WARNING")

    total_info = []
    with Pool(3) as pool:
        nodes_params = [(industry_name, True, node, False, user_id) for node in nodes]
        results = pool.starmap(tool_search, nodes_params)
        total_info = [result for result in results if result is not None]
    total_info = '\n'.join(total_info)

    final = f'# 1 {industry_name}整体产业链知识\n{center_node_info}\n' + f'# 2 有关{industry_name}中其他节点的产业链知识\n{total_info}'
    return final, nodes


def clean_and_parse(triples_raw, user_id=None):
    try:
        if triples_raw is None:
            log_message(user_id, "Error: triples_raw is None", log_type="ERROR")
            return None
        cleaned_triples_raw = triples_raw.replace("```", "").replace("json", "")
        log_message(user_id, f"清理后的字符串: {cleaned_triples_raw}")
        return json.loads(cleaned_triples_raw)
    except json.JSONDecodeError as e:
        log_message(user_id, f"解析 triples_raw 时出错: {e}", log_type="ERROR")
        return None


def process_industry(industry_name, user_id):
    # 获取当前进程的PID
    pid = os.getpid()
    user_folder = f"user_{user_id}_pid_{pid}"
    os.makedirs(f"resultTxt/{user_folder}", exist_ok=True)
    os.makedirs(f"resultImg/{user_folder}", exist_ok=True)

    industry_name = process_industry_data(input_clean_prompts, industry_name, user_id)
    print(f"处理后的产业链描述（调试）: {repr(industry_name)}")
    
    # 如果 industry_name 处理结果为空，直接返回
    if not industry_name.strip() or industry_name.strip() == '""':
        print("industry_name 为空，直接返回")
        return '无内容'
   
    final_info, nodes = tool_total_search(industry_name, user_id=user_id)

    with open(f"resultTxt/{user_folder}/{industry_name}_total_info.txt", "w", encoding='utf-8') as f:
        f.write(final_info)

    with open(f"resultTxt/{user_folder}/{industry_name}_total_info.txt", "r", encoding='utf-8') as f:
        final_info = f.read()

    # 初始化 white_list 为一个空集合
    white_list = set()

    # 尝试读取白名单文件
    try:
        with open(f'materials/white_list_{industry_name}.txt', 'r', encoding='utf-8') as f:
            white_list = set(line.strip() for line in f.readlines())
    except FileNotFoundError:
        log_message(user_id, f"文件 materials/white_list_{industry_name}.txt 不存在。", log_type="WARNING")

    max_attempts = 5
    attempts = 0

    while attempts < max_attempts:
        triples_raw = process_industry_data(get_triples_prompts.format(industry=industry_name) + "。需要特别注意：不要无限循环输出，不要有重复。", final_info + "。需要特别注意：不要无限循环输出，不要有重复。", user_id)
        triples_raw_dict = clean_and_parse(triples_raw, user_id)
        if triples_raw_dict is None:
            attempts += 1
            log_message(user_id, f"解析失败，第 {attempts} 次尝试...")
            if attempts >= max_attempts:
                log_message(user_id, "达到最大尝试次数，退出循环。", log_type="ERROR")
                break
            continue

        relations = triples_raw_dict['relations']
        nodes = triples_raw_dict['nodes']

        nodes_set = set(nodes)
        try:
            nodes_set.update(white_list)
        except Exception as e:
            log_message(user_id, f"更新节点时出错: {e}", log_type="ERROR")
            continue

        nodes = list(nodes_set)

        relations_str = '\n'.join(relations)
        nodes_str = '\n'.join(nodes)

        with open(f'resultTxt/{user_folder}/nodes_{industry_name}.txt', 'w', encoding='utf-8') as f:
            f.write(nodes_str)

        with open(f'resultTxt/{user_folder}/relations_{industry_name}.txt', 'w', encoding='utf-8') as f:
            f.write(relations_str)

        break


if __name__ == "__main__":
    start_time = time.time()
    user_id = "user_417"  # 示例用户ID，实际使用时需要动态获取

    industry_names = [
        # "电气设备", "电子器件", "医疗器械", "消费电子","无人驾驶", 
        # "集成电路", "元宇宙", "新能源汽车", "电子信息", "机械设备与零件",
        # "3D打印", "卫星导航", "无人机", "大飞机", "激光",
        # "汽车", "眼镜", "工业母机", "工业软件", "人工智能",
        # "光伏", "合成生物", "5G", "检验检测", "储能",
        # "芯片", "氢能", "低碳经济","低空经济", "能源环保", 
        # "仪器仪表","装备制造", "通信设备", "半导体", "新材料", 
        # "医疗美容", "大健康", "机器人", "生命健康", "生物医药",
        # "风电","轨道交通装备",
        # "智能家居","物联网","云计算","服装","绿色建筑",
        # "可再生能源","环保技术","生物科技","数字媒体","电子商务",
        # "食品科技","海洋经济","航空航天","数字安全","纳米技术",
        # "量子计算","精细化工","金属加工","超导材料","船舶制造",
        # "生物经济","直播电商","在线教育","AI智能体","家具制造",
        # "家电设备","端侧AI","人形机器人","未来显示","算力",
        # "新能源", "首发经济","未来信息" ,"虚拟现实","碳中和",
        # "远程医疗","智能交通","智能电网","智能金融","智能农业",
        # "AI大模型","装配式建筑","跨境电商","银发经济","情绪价值",
        # "量子科技","空天信息","电竞","5G-A","固态电池",
        # "商业航天","AI眼镜","北斗产业","碳纤维","智能穿戴",
        # "智能传感器","预制菜产业","高端装备制造","宠物经济","露营经济",
        # "数字创意产业","数字医疗","脑机接口","deepseek","超导",
        # "AI制药","冰雪经济","AI基础设施","特斯拉","供应链服务",
        # "地方特色食品","特钢材料","疗愈经济","本地化运营","智能算力",
        # "风电装备","铝镁精深加工","具身智能"

        "生命健康","集成电路","机器人","检验检测"
        ,"工业软件","卫星导航","无人机","大飞机","仪表仪器"
        ,"工业母机","3D打印","人工智能","激光","合成生物"
        ,"光伏","5G","低空经济","储能","跨境电商"
        ,"船舶海工","人形机器人"
        # "新能源汽车",
    ]

    for industry_name in industry_names:
        log_message(user_id, f"Processing {industry_name}")
        process_industry(industry_name, user_id)

    end_time = time.time()
    log_message(user_id, f"代码运行总时间：{end_time - start_time}")