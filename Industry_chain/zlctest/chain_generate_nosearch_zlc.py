
from GoogleSearcher import GoogleSearcher 
from Crawler import Crawler
import yaml
from openai import OpenAI
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
import sys


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


llm = OpenAI(api_key=deepseek_api_key, base_url="https://api.deepseek.com")




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




def process_industry_data(clean_info_prompts,raw_content,llm):
    try:
        response = llm.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content":clean_info_prompts},
                {"role": "user", "content": raw_content}
            ],
            stream=False,
            frequency_penalty = 0.1

        )
        return response.choices[0].message.content
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
    
def process_industry(industry_name, llm):
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

    # 生成三元组信息
    triples_raw = process_industry_data(get_triples_prompts.format(industry=industry_name).replace("attatch","特别注意：除了消费电子这个节点外，每个节点都必须有一个父级节点，特别注意原材料这个节点！"), final_info, llm)
    triples_raw_dict = clean_and_parse(triples_raw)

    relations = triples_raw_dict['relations']
    nodes = triples_raw_dict['nodes']

    # 合并模型生成的节点和白名单中的节点，并去除重复项
    nodes_set = set(nodes)
    try: 
        nodes_set.update(white_list)
    except FileNotFoundError:
        print(f"文件 {white_list_file} 不存在。")
    nodes = list(nodes_set)
    
    relations_str = '\n'.join(relations)
    print(relations_str)
    nodes_str = '\n'.join(nodes)
    print(nodes_str)

    # 写入 nodes 文件
    try:
        with open(f'resultTxt/revise_nodes_{industry_name}.txt', 'w', encoding='utf-8') as f:
            f.write(nodes_str)
            print("节点已写入")
    except Exception as e:
        print(f"写入节点文件失败：{e}")

    # 写入 relations 文件
    try:
        with open(f'resultTxt/revise_relations_{industry_name}.txt', 'w', encoding='utf-8') as f:
            f.write(relations_str)
            print("三元组已写入")
    except Exception as e:
        print(f"写入三元组文件失败：{e}")

    # print(invalid_nodes)
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

def check_triples(industry_name,triples,llm):
    prompts = '''
    下面我会给你一些产业链的三元组。你需要帮我按照如下规则检查这些三元组生成得是否有问题。如果没有问题，则返回"无问题",如果有问题，则返回注意事项。
    三元组格式含义是:起始节点,结束节点,关系类型。
    - 起始节点表示下一级的节点，结束节点表示上一级的节点。比如锂电池是电池的下一级节点，那么他们的关系格式应该表示为“锂电池,电池,is-a”而不是“电池,锂电池,is-a”。
    - 关系类型包括:part-of(表明了一种构成关系,表示起始节点是结束节点的一部分),is-a(说明了一种分类关系,表示起始节点是结束节点的一个种类或实例)。
    - 例如,如果有一个节点是“锂电池”,另一个节点是“电池”,那么它们之间的关系可以表示为“锂电池,电池,is-a”,意味着锂电池是电池的一种。
    - 再例如,如果有一个节点是“电芯”,另一个节点是“电池”,那么它们之间的关系可以表示为“电芯,电池,part-of”,意味着电芯是电池的一部分。
    你需要特别注意检查有没有可以合并的结点，如果有也一并输出，告知我哪些节点可以合并。
    注意事项有：
    1) 具体的节点仅有一次作为起始节点,举个例子，假设你总结出"逆变器"这个节点，并且总结出它对应的三元组为"逆变器,中游,part-of"，那么逆变器这个节点就不能再作为起始节点出现在其他的三元组中。
    2) 输出结果包括两部分,第一部分是所有节点,第二部分是三元组。节点以及三元组都是直接输出结果内容即可,不需要对结果内容标注数字序号。比如节点不要输出"1. 动力电池"而是要输出"动力电池".三元组不要输出"1. 动力电池,电池材料,part-of"而是要输出"动力电池,电池材料,part-of"。
    3) 如果你总结出的节点中有重复或者意思相近的，不要把他们作为单独节点，而是只保留一个节点。比如：节点"车身"以及节点"车身及其附件"，那么只保留"车身及其附件"，舍弃掉"车身"这个节点，并且"车身"这个节点下如果还有其他展开的节点也一并归入"车身及其附件"下。再比如"销售","分销","零售"这三个节点，他们可以合并为"销售"这个节点。
    4) 我给你提供的资料是一篇完整的大文章，总结节点的时候不要将每一部分独立开来，一定要分析出各部分之间的关系并将他们联系起来。
    5) 中心节点只有一个，那就是{industry}，它只能是结束节点。
    6) 除了中心节点外，其他节点一定要有结束节点，否则会出现知识图谱中边的丢失。
    7) 你总结出来的节点一定不要有重复的。
    8) 你总结出来的三元组也一定不要有重复的。
    9) {industry}，上游，中游和下游这四个节点一定要返回到输出结果中，并且上游，中游和下游与中心节点构成三个三元组，即"上游,{industry},part-of","中游,{industry},part-of","下游,{industry},part-of"。
        这是必须要有的三个三元组。
    10) 除了上游，中游和下游其余节点都不能与{industry}这个中心节点建立关系，也就是说其余节点的结束节点都不能是{industry}。
    11) 总结出的节点名字中不要含有"产业链"这三个字。
    12) 总结出的节点不要有类似"供需平衡","重要性","意义","定义","政策","标准制定","决策层","合作","挑战","协同","趋势","应用","优化","动态","发展","改进"等这种非具体的不属于产业链的某个具体部分的内容。
    13) 总结出的节点不要是公司名字，不要是供应商/提供商的名字，不要是制造商名字，不要是品牌名字(中英文品牌都不要).
    14) 总结出的节点名字中不要含有"产业链上游"这五个字.
    15) 总结出的节点名字中不要含有"产业链中游"这五个字.
    16) 总结出的节点名字中不要含有"产业链下游"这五个字.
    17) 不要一直总结节点以致于停不下来，适可而止。
    18) 总结出的节点必须是实际的产业链节点。类似政策信息、未来趋势、重要性、发展战略、市场环境，企业等务虚的内容，都不要总结到节点中.
    19) 总结出的节点名字中不要含有"产业上游"这四个字.
    20) 总结出的节点名字中不要含有"产业中游"这四个字.
    21) 总结出的节点名字中不要含有"产业下游"这四个字.
    22) 你在展开上游，中游，下游节点的时候要遵循以下规则：
        - 上游通常包括原材料供应、基础技术研发、关键零部件制造、基础加工设备制造；
        - 中游指上游提供的原材料,零部件以及基础加工设备转化为更高级的中间产品或最终产品的环节，如：制造，组装，封装，测试等；
        - 下游主要涉及产品的销售以及售后服务，比如：品牌营销、物流配送、应用、培训，附加服务等。
    23) 总结出的节点不要是产品。
    下面开始：
'''
    try:
        response = llm.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content":clean_info_prompts},
                    {"role": "user", "content": triples}
                ],
                stream=False
            )
        return response.choices[0].message.content
    except:
        return None 

if __name__ == "__main__":
    start_time = time.time()

    industry_names = sys.argv[1]
    # 可以更换行业名称
    industry_names = industry_names.split(",")

    for industry_name in industry_names:
        print(f"Processing {industry_name}")
        process_industry(industry_name, llm)

    end_time = time.time()
    print(f"代码运行总时间：{end_time - start_time}")