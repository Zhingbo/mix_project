import os

from GoogleSearcher import GoogleSearcher 
from Crawler import Crawler
import yaml
from langchain_openai import ChatOpenAI
from functions import * 
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent
from langchain.tools import tool
from langchain.agents import AgentExecutor
from langchain.tools import Tool
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from langchain.agents import initialize_agent
from multiprocessing import Pool
from concurrent.futures import ThreadPoolExecutor
import networkx as nx
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import json
import time
import ast
import csv
import logging
from neo4j import GraphDatabase


# 读取项目配置文件
with open("settings.yaml", "r") as file:
    settings = yaml.load(file, Loader=yaml.FullLoader)


headers = settings['system_settings']['headers']
google_api_url = settings['system_settings']['google_api_url']
deepseek_api_key = settings['system_settings']['deepseek_api_key']
deepseek_url = settings['system_settings']['deepseek_url']
clean_info_prompts = settings['prompts']['clean_info']['content']
clean_node_info_prompts =  settings['prompts']['clean_node_info']['content']

words_from_ocr_prompts = settings['prompts']['words_from_ocr']['content']
get_entity_prompts = settings['prompts']['get_entity']['content']
jina_api_url = settings['system_settings']['jina_api_url']
jina_api_headers = settings['system_settings']['jina_api_headers']
data_source_excel = settings['system_settings']['data_source_excel']
get_triples_prompts = settings['prompts']['get_triples']['content']
check_triples_prompts = settings['prompts']['check_triples']['content']
modify_triples_prompts = settings['prompts']['modify_triples']['content']

# llm = ChatOpenAI(
#     model='deepseek-chat',  # DeepSeek模型名称
#     openai_api_key=deepseek_api_key,  # API Key
#     openai_api_base=deepseek_url,
#     temperature = 1.0, # DeepSeek API的基础URL
#     max_tokens= 8000
# )   

dbflash_api_key=os.getenv('VOLCENGINE_ARK_API_KEY')
llm = ChatOpenAI(
    model='ep-20250217153421-8lrxj', #R1
    # ep-20250205154622-7gm5g
    # model="ep-20250217153205-d7px5", #V3
    openai_api_key=dbflash_api_key, 
    openai_api_base='https://ark.cn-beijing.volces.com/api/v3'
) 

parser = StrOutputParser()
memory = MemorySaver()


# 检查三元组的完整性

def check_triples(triples,output,draw_graph=True):
    """
    检查三元组图的连通性，并验证非叶子节点的度是否大于 10，并绘制图网络。

    参数：
    triples (list of tuples): 三元组列表，格式为 [(entity1, entity2, relation), ...]
    draw_graph (bool): 是否绘制图网络并保存图片。

    返回：
    - 是否有断点 (bool)
    - 不满足度要求的节点 (list)
    """
    # 创建无向图
    G = nx.Graph()

    # 添加三元组中的节点和边
    for entity1, entity2, relation in triples:
        G.add_edge(entity1, entity2, label=relation)

    # 检查是否有断点（不连通部分）
    if not nx.is_connected(G):
        print("图中存在断点！")
        disconnected_components = list(nx.connected_components(G))
        print(f"不连通的部分：{disconnected_components}")
        has_breakpoint = True
    else:
        print("图是连通的。")
        has_breakpoint = False

    # 检查非叶子节点的度是否大于thresh
    invalid_nodes = []
    for node in G.nodes:
        degree = G.degree(node)
        # 叶子节点的度为 1，跳过
        if degree == 1:
            invalid_nodes.append(node)



    # 绘制图网络并保存图片
    if draw_graph:
        font_path = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
        font_prop = FontProperties(fname=font_path)
        plt.rcParams['axes.unicode_minus'] = False
        plt.figure(figsize=(36, 24))
        # 使用 kamada_kawai 布局
        pos = nx.kamada_kawai_layout(G)
        nx.draw(G, pos, with_labels=True, node_color='skyblue', node_size=3000, font_size=16, font_color='black', edge_color='gray')
        edge_labels = nx.get_edge_attributes(G, 'label')
        nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_color='red')
        for text in plt.gca().texts:
            text.set_fontproperties(font_prop)
        plt.title("三元组图网络",font_properties=font_prop)
        plt.savefig(f"{output}")
        plt.show()
        print(f"图网络已保存为{output}")

    return has_breakpoint, invalid_nodes


def process_industry_data(clean_info_prompts,raw_content,llm, parser):

    try:
        # 创建系统消息和用户消息
        system_message = SystemMessage(content=clean_info_prompts)
        human_message = HumanMessage(content=raw_content)
        
        # 构造消息列表
        messages = [system_message, human_message]
        
        # 获取 LLM 输出（假设 llm.invoke 已经封装）
        html_knowledge = llm.invoke(messages)
        
        # 解析输出的 HTML
        parsed_knowledge = parser.invoke(html_knowledge)
        
        return parsed_knowledge
    except:
        return None

# def url_crawl(url):
#     crawler = Crawler(jina_api_url, jina_api_headers,url)
#     try:
#         temp_html = crawler.crawl_url_data()
#         return '无内容' if temp_html is None else temp_html
#     except:
#         return '无内容'



# def tool_search(industry_name,isNode=False,node="",isAux=True):
#     try:
#         clean_prompts = clean_node_info_prompts.format(industry=industry_name,node=node) if isNode else clean_info_prompts.format(industry=industry_name)
#         google_searcher = GoogleSearcher(google_api_url,headers,industry_name)
#         limit = 2 if isNode else 3
#         try:
#             raw_content = google_searcher.google_search(limit=limit, isNode=isNode, node=node)
#         except Exception as e:
#             print(f"Error in google_search: {e}")
#             return '无内容'
#         urls = []  # 初始化 urls 为空列表
#         if raw_content is not None:
#             urls = [r['url'] for r in raw_content['results']]
#             print(urls)
#         web_content = ''
#         images = []
#         industry = node if isNode else industry_name

#         ## 下面的部分多线程完成，否则太慢了
#         total_info = []
#         for url in urls:
#             result = Crawler.crawl_url_data(url)
#             if result is not None and result != '无内容':
#                 total_info.append(str(result))  # 确保结果是字符串
#         if not total_info:
#             return '无内容'
#         web_content = '\n'.join(total_info)
#         # 处理图片
#         # image_content = ''
#         # for image in images:
#         #     image_data = get_image_content(image)
#         #     if image_data is not None:
#         #         # 将图片转化为结构化文字
#         #         tempresult = process_industry_data(words_from_ocr_prompts,industry,str(image_data),llm,parser)
#         #         image_content = image_content + tempresult + '\n'
#         # 整理所有的图片文字
#         # image_knowledge = process_industry_data(clean_info_prompts,industry, image_content, llm, parser)
#         # 整理html知识
#         html_knowledge = process_industry_data(clean_prompts, web_content, llm,parser)
    
#         # 整理外部知识
#         if isAux:
#             try:
#                 aux_content = Crawler.crawl_data(industry, data_source_excel)
#                 aux_knowledge = process_industry_data(clean_prompts, aux_content, llm, parser)
#                 # 整体的整合
#                 full_knowledge = html_knowledge + '\n' + aux_knowledge
#                 total_knowledge = process_industry_data(clean_prompts, full_knowledge, llm, parser)
#             except Exception as e:
#                 print(f"Error in auxiliary data processing: {e}")
#                 return '无内容'
#         else:
#             total_knowledge = html_knowledge
#         return total_knowledge
#     except BrokenPipeError:
#         print(f"BrokenPipeError occurred in tool_search")
#         return '无内容'
    
# def tool_total_search(industry_name):
#     center_node_info = tool_search(industry_name)
#     ## 总结节点
#     nodes = process_industry_data(get_entity_prompts.format(industry=industry_name),center_node_info,llm,parser)
#     print("节点有",nodes)
#     while True:
#         try:
#             nodes = json.loads(nodes.replace("```","").replace("json",""))
#         except:
#             print("nodes有问题")
#             nodes = process_industry_data(get_entity_prompts.format(industry=industry_name),center_node_info,llm,parser)
#         else:
#             break
#     # 读取白名单文件
#     try:
#         with open(f'materials/white_list_{industry_name}.txt', 'r', encoding='utf-8') as file:
#             white_list = file.read().splitlines()
#             # 将白名单中的节点添加到nodes中，如果它们还不在列表中
#             for item in white_list:
#                 if item not in nodes:
#                     nodes.append(item)
#             print("加入白名单后的节点有",nodes)                
#     except FileNotFoundError:
#         print(f"文件 materials/white_list_{industry_name}.txt 不存在。") 
    

#     total_info = []
#     with Pool(3) as pool:
#         nodes_params = [(industry_name,True,node,False) for node in nodes]
#         results = pool.starmap(tool_search, nodes_params)
#         total_info = [result for result in results if result is not None]
#     total_info = '\n'.join(total_info)

#     final = f'# 1 {industry_name}整体产业链知识\n{center_node_info}\n' + f'# 2 有关{industry_name}中其他节点的产业链知识\n{total_info}'
#     return final,nodes 

# def tool_invalid_nodes_search(industry_name, invalid_nodes):
#     try:
#         total_info = []
#         with Pool(3) as pool:
#             nodes_params = [(industry_name, True, node, False) for node in invalid_nodes]
#             results = pool.starmap(tool_search, nodes_params)
            
#             # 过滤掉None值，并确保所有元素都是字符串
#             total_info = [str(result) for result in results if result is not None]
        
#         # 将非None的元素连接成一个字符串
#         total_info_str = '\n'.join(total_info)
#         return total_info_str
#     except BrokenPipeError:
#         print(f"BrokenPipeError occurred in tool_invalid_nodes_search")
#         return '无内容'

def clean_and_parse(triples_raw):
    try:
        # 尝试清理字符串并解析为JSON
        cleaned_triples_raw = triples_raw.replace("```", "").replace("json", "")
        print("清理后的字符串：", cleaned_triples_raw)  # 打印清理后的字符串以供调试

        # # 检查并补全缺失的引号
        # if not cleaned_triples_raw.endswith('"') and cleaned_triples_raw.count('"') % 2 != 0:
        #     cleaned_triples_raw += '"'
        # if not cleaned_triples_raw.endswith("'") and cleaned_triples_raw.count("'") % 2 != 0:
        #     cleaned_triples_raw += "'"

        # # 移除尾部的逗号
        # if cleaned_triples_raw.endswith(','):
        #     cleaned_triples_raw = cleaned_triples_raw.rstrip(',')

        # # 检查并补全缺失的方括号
        # if cleaned_triples_raw.startswith('[') and not cleaned_triples_raw.endswith(']'):
        #     cleaned_triples_raw += ']'

        # print("补全后的字符串：", cleaned_triples_raw)  # 打印补全后的字符串以供调试

        # 使用 json.loads 而不是 ast.literal_eval
        return json.loads(cleaned_triples_raw)
    except json.JSONDecodeError as e:
        print(f"解析 triples_raw 时出错：{e}")
        return None
    
def process_industry(industry_name, llm, parser):
    # final_info, nodes = tool_total_search(industry_name)  # 在这里搜索资料

    # with open(f"resultTxt/{industry_name}_total_info.txt", "w", encoding='utf-8') as f:
    #     f.write(final_info)
    
    with open(f"resultTxt/{industry_name}_total_info.txt", "r", encoding='utf-8') as f:
        final_info = f.read()

    # 读取白名单文件
    white_list_file = f'materials/white_list_{industry_name}.txt'
    white_list = set()
    try:
        with open(white_list_file, 'r', encoding='utf-8') as f:
            white_list = set(line.strip() for line in f.readlines())
    except FileNotFoundError:
        print(f"文件 {white_list_file} 不存在。")            

    max_attempts = 5  # 设置最大尝试次数
    attempts = 0  # 初始化尝试次数

    while attempts < max_attempts:
        triples_raw = process_industry_data(get_triples_prompts.format(industry=industry_name)+"。需要特别注意：不要无限循环输出；节点和三元组都不要有重复；总结出的三元组不要有三元组关系的缺失也就是说除了中心节点外，其他节点一定要有结束节点；一个节点只能有一个固定的结束节点，比如：假如你总结出 陪护机器人,原材料供应,part-of 这个三元组，那么起始节点 陪护机器人 就不能再有除了 原材料供应 以外的结束节点。", final_info+"。需要特别注意：不要无限循环输出，不要有重复。", llm, parser)
        triples_raw_dict = clean_and_parse(triples_raw)
        if triples_raw_dict is None:
            attempts += 1  # 如果解析失败，增加尝试次数
            print(f"解析失败，第 {attempts} 次尝试...")
            if attempts >= max_attempts:
                print("达到最大尝试次数，退出循环。")
                break  # 达到最大尝试次数，退出循环
            continue  # 继续下一次循环

        relations = triples_raw_dict['relations']
        nodes = triples_raw_dict['nodes']

        # 合并模型生成的节点和白名单中的节点，并去除重复项
        nodes_set = set(nodes)
        try: 
            nodes_set.update(white_list)
        except FileNotFoundError:
            print(f"文件 {white_list_file} 不存在。")
            continue  # 如果白名单文件不存在，跳过当前循环

        nodes = list(nodes_set)
        
        relations_str = '\n'.join(relations)
        nodes_str = '\n'.join(nodes)

        # 写入 nodes 文件
        with open(f'resultTxt/nodes_{industry_name}.txt', 'w', encoding='utf-8') as f:
            f.write(nodes_str)

        # 写入 relations 文件
        with open(f'resultTxt/relations_{industry_name}.txt', 'w', encoding='utf-8') as f:
            f.write(relations_str)

        break  # 当relations文件写入完成后，退出循环

    # while True:
    #     try:
    #         # 确保invalid_nodes是字符串
    #         if isinstance(invalid_nodes, list):
    #             invalid_nodes_str = json.dumps(invalid_nodes)  # 将列表转换为JSON字符串
    #         else:
    #             invalid_nodes_str = invalid_nodes  # 如果已经是字符串，直接使用

    #         # 尝试清理字符串并解析为Python字面量
    #         cleaned_invalid_nodes = invalid_nodes_str.replace("```", "").replace("```json", "")
    #         invalid_nodes = json.loads(cleaned_invalid_nodes)
    #         print(invalid_nodes)
    #     except (ValueError, SyntaxError) as e:
    #         print(f"解析 invalid_nodes 时出错：{e}")
    #         # 假设process_industry_data返回的是一个字符串
    #         invalid_nodes = process_industry_data(check_triples_prompts.format(nodes=str(invalid_nodes)), '', llm, parser)
    #     else:
    #         break

    # if invalid_nodes is not None:
    #     # 现在对invalid_nodes进行搜索资料，并且生成新的三元组
    #     invalid_nodes_info = tool_invalid_nodes_search(industry_name, invalid_nodes)
    #     with open('resultTxt/invalid_nodes_info.txt', 'w', encoding='utf-8') as f:
    #         f.write(invalid_nodes_info)
        
    #     invalid_nodes_info_json = {'triples_already': relations, 'node_need_expand': invalid_nodes, 'material': invalid_nodes_info}
    #     invalid_nodes_info_json_str = json.dumps(invalid_nodes_info_json, ensure_ascii=False)
    #     while True:
    #         new_triples_raw = process_industry_data(modify_triples_prompts.format(industry=industry_name), invalid_nodes_info_json_str, llm, parser)
    #         print("新三元组原始数据：", new_triples_raw)
    #         try:
    #             # 尝试清理字符串并解析为Python字面量
    #             if new_triples_raw is not None:
    #                 cleaned_new_triples_raw = new_triples_raw.replace("```", "").replace("json", "")
    #                 print("清理后的JSON字符串：", cleaned_new_triples_raw)
    #                 # 尝试解析JSON，捕获并处理可能的异常
    #                 try:
    #                     new_triples_raw = json.loads(cleaned_new_triples_raw)
    #                     new_relations = new_triples_raw['relations']
    #                     new_nodes = new_triples_raw['nodes']
    #                 except json.JSONDecodeError as e:
    #                     print(f"JSON解析错误：{e}")
    #                     print(f"错误位置：{e.pos}")
    #                     continue  # 如果JSON解析失败，继续下一次循环

    #             # 合并新生成的节点和白名单中的节点，并去除重复项
    #             new_nodes_set = set(new_nodes)
    #             try:
    #                 new_nodes_set.update(white_list)
    #             except FileNotFoundError:
    #                 print(f"文件 {white_list_file} 不存在。")    
    #             new_nodes = list(new_nodes_set)
                
    #             new_relations_str = '\n'.join(new_relations)
    #             new_nodes_str = '\n'.join(new_nodes)
                
    #             with open(f'resultTxt/new_nodes_{industry_name}.txt', 'w', encoding='utf-8') as f:
    #                 f.write(new_nodes_str)
                
    #             with open(f'resultTxt/new_relations_{industry_name}.txt', 'w', encoding='utf-8') as f:
    #                 f.write(new_relations_str)

    #             # 作图
    #             new_relations = [(r.split(",")[0],r.split(",")[1],r.split(",")[2]) for r in new_relations]
    #             has_break_points, invalid_nodes = check_triples(new_relations, f"resultImg/{industry_name}_graph.png")
    #             if not has_break_points:
    #                 print(has_break_points, invalid_nodes)        
    #                 break
        
    #         except (ValueError, SyntaxError) as e:
    #             print(f"解析 new_triples_raw 时出错：{e}")

if __name__ == "__main__":
    start_time = time.time()
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
        # "数字创意产业","数字医疗","脑机接口","deepseek","超导"

        "碳中和"         
    ]  # 可以更换行业名称

    for industry_name in industry_names:
        print(f"Processing {industry_name}")
        process_industry(industry_name, llm, parser)

    end_time = time.time()
    print(f"代码运行总时间：{end_time - start_time}")