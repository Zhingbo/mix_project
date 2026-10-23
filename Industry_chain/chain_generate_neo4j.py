'''
    整个产业链的过程
'''
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

llm = ChatOpenAI(
    model='deepseek-chat',  # DeepSeek模型名称
    openai_api_key=deepseek_api_key,  # API Key
    openai_api_base=deepseek_url,
    temperature = 0.1, # DeepSeek API的基础URL
    max_tokens= 8000
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



def tool_search(industry_name,isNode=False,node="",isAux=True):
    try:
        clean_prompts = clean_node_info_prompts.format(industry=industry_name,node=node) if isNode else clean_info_prompts.format(industry=industry_name)
        google_searcher = GoogleSearcher(google_api_url,headers,industry_name)
        limit = 2 if isNode else 3
        try:
            raw_content = google_searcher.google_search(limit=limit, isNode=isNode, node=node)
        except Exception as e:
            print(f"Error in google_search: {e}")
            return '无内容'
        urls = []  # 初始化 urls 为空列表
        if raw_content is not None:
            urls = [r['url'] for r in raw_content['results']]
            print(urls)
        web_content = ''
        images = []
        industry = node if isNode else industry_name

        ## 下面的部分多线程完成，否则太慢了
        total_info = []
        for url in urls:
            result = Crawler.crawl_url_data(url)
            if result is not None and result != '无内容':
                total_info.append(str(result))  # 确保结果是字符串
        if not total_info:
            return '无内容'
        web_content = '\n'.join(total_info)
        # 处理图片
        # image_content = ''
        # for image in images:
        #     image_data = get_image_content(image)
        #     if image_data is not None:
        #         # 将图片转化为结构化文字
        #         tempresult = process_industry_data(words_from_ocr_prompts,industry,str(image_data),llm,parser)
        #         image_content = image_content + tempresult + '\n'
        # 整理所有的图片文字
        # image_knowledge = process_industry_data(clean_info_prompts,industry, image_content, llm, parser)
        # 整理html知识
        html_knowledge = process_industry_data(clean_prompts, web_content, llm,parser)
    
        # 整理外部知识
        if isAux:
            try:
                aux_content = Crawler.crawl_data(industry, data_source_excel)
                aux_knowledge = process_industry_data(clean_prompts, aux_content, llm, parser)
                # 整体的整合
                full_knowledge = html_knowledge + '\n' + aux_knowledge
                total_knowledge = process_industry_data(clean_prompts, full_knowledge, llm, parser)
            except Exception as e:
                print(f"Error in auxiliary data processing: {e}")
                return '无内容'
        else:
            total_knowledge = html_knowledge
        return total_knowledge
    except BrokenPipeError:
        print(f"BrokenPipeError occurred in tool_search")
        return '无内容'
    
def tool_total_search(industry_name):
    center_node_info = tool_search(industry_name)
    ## 总结节点
    nodes = process_industry_data(get_entity_prompts.format(industry=industry_name),center_node_info,llm,parser)
    print("节点有",nodes)
    while True:
        try:
            nodes = json.loads(nodes.replace("```","").replace("json",""))
        except:
            print("nodes有问题")
            nodes = process_industry_data(get_entity_prompts.format(industry=industry_name),center_node_info,llm,parser)
        else:
            break
    # 读取白名单文件
    try:
        with open(f'materials/white_list_{industry_name}.txt', 'r', encoding='utf-8') as file:
            white_list = file.read().splitlines()
            # 将白名单中的节点添加到nodes中，如果它们还不在列表中
            for item in white_list:
                if item not in nodes:
                    nodes.append(item)
            print("加入白名单后的节点有",nodes)                
    except FileNotFoundError:
        print(f"文件 materials/white_list_{industry_name}.txt 不存在。") 
    

    total_info = []
    with Pool(3) as pool:
        nodes_params = [(industry_name,True,node,False) for node in nodes]
        results = pool.starmap(tool_search, nodes_params)
        total_info = [result for result in results if result is not None]
    total_info = '\n'.join(total_info)

    final = f'# 1 {industry_name}整体产业链知识\n{center_node_info}\n' + f'# 2 有关{industry_name}中其他节点的产业链知识\n{total_info}'
    return final,nodes 

def tool_invalid_nodes_search(industry_name, invalid_nodes):
    try:
        total_info = []
        with Pool(3) as pool:
            nodes_params = [(industry_name, True, node, False) for node in invalid_nodes]
            results = pool.starmap(tool_search, nodes_params)
            
            # 过滤掉None值，并确保所有元素都是字符串
            total_info = [str(result) for result in results if result is not None]
        
        # 将非None的元素连接成一个字符串
        total_info_str = '\n'.join(total_info)
        return total_info_str
    except BrokenPipeError:
        print(f"BrokenPipeError occurred in tool_invalid_nodes_search")
        return '无内容'    

# # 包装tool
# search_tool = Tool.from_function(
#     func=tool_total_search,
#     name="IndustrySearchTool",
#     description="This tool searches for information about a specific industry and returns detailed knowledge."
# )

def create_nodes(tx, nodes):
    for node in nodes:
        tx.run("MERGE (n:`%s` {name: $name})"%(industry_name), name=node)

def create_relationships(tx, relationships):
    for rel in relationships:
        source, target, relation_type = rel
        tx.run("""
            MATCH (a:`%s` {name: $source})
            OPTIONAL MATCH (b:`%s` {name: $target})
            MERGE (a)-[:`%s`]->(b)
            """%(industry_name, industry_name, relation_type),
            source=source, target=target)

# def clean_and_parse(triples_raw):
#     try:
#         # 尝试清理字符串并解析为JSON
#         cleaned_triples_raw = triples_raw.replace("```", "").replace("json", "")
#         print("清理后的字符串：", cleaned_triples_raw)  # 打印清理后的字符串以供调试
#         # 使用 json.loads 而不是 ast.literal_eval
#         return json.loads(cleaned_triples_raw)
#     except json.JSONDecodeError as e:
#         print(f"解析 triples_raw 时出错：{e}")
#         return None

def clean_and_parse(triples_raw):
    try:
        # 尝试清理字符串并解析为JSON
        cleaned_triples_raw = triples_raw.replace("```", "").replace("json", "")
        print("清理后的字符串：", cleaned_triples_raw)  # 打印清理后的字符串以供调试

        # 检查并补全缺失的引号
        if not cleaned_triples_raw.endswith('"') and cleaned_triples_raw.count('"') % 2 != 0:
            cleaned_triples_raw += '"'
        if not cleaned_triples_raw.endswith("'") and cleaned_triples_raw.count("'") % 2 != 0:
            cleaned_triples_raw += "'"

        print("补全后的字符串：", cleaned_triples_raw)  # 打印补全后的字符串以供调试

        # 使用 json.loads 而不是 ast.literal_eval
        return json.loads(cleaned_triples_raw)
    except json.JSONDecodeError as e:
        print(f"解析 triples_raw 时出错：{e}")
        return None
    
if __name__ == "__main__":
    start_time = time.time()
    industry_name = '生命健康'   #这个可以更换
    final_info,nodes = tool_total_search(industry_name)  # 这个地方是在搜索资料

    with open(f"resultTxt/{industry_name}_total_info.txt","w",encoding='utf-8') as f:
        f.write(final_info)
    
    with open(f"resultTxt/{industry_name}_total_info.txt","r",encoding='utf-8') as f:
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
    while True:
        triples_raw = process_industry_data(get_triples_prompts.format(industry=industry_name),final_info,llm,parser)
        triples_raw_dict = clean_and_parse(triples_raw)
        if triples_raw_dict is None:
            continue  # 如果解析失败，继续下一次循环

        # # 尝试解析 triples_raw 为 Python 字典
        # triples_raw_dict = ast.literal_eval(triples_raw)
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
        nodes_str = '\n'.join(nodes)

        # 写入 nodes 文件
        with open(f'resultTxt/nodes_{industry_name}.txt', 'w', encoding='utf-8') as f:
            f.write(nodes_str)

        # 写入 relations 文件
        with open(f'resultTxt/relations_{industry_name}.txt', 'w', encoding='utf-8') as f:
            f.write(relations_str)

        relations_ = [(r.split(",")[0],r.split(",")[1],r.split(",")[2]) for r in relations]
        has_break_points, invalid_nodes = check_triples(relations_,f"resultImg/{industry_name}_graph1.png")
        invalid_nodes = process_industry_data(check_triples_prompts.format(nodes=str(invalid_nodes)),'',llm,parser)
        if not has_break_points:
            break
            
    print(invalid_nodes)
    while True:
        try:
            # 尝试清理字符串并解析为Python字面量
            cleaned_invalid_nodes = invalid_nodes.replace("```", "").replace("```json", "")
            invalid_nodes = json.loads(cleaned_invalid_nodes)
            print(invalid_nodes)
        except (ValueError, SyntaxError) as e:
            print(f"解析 invalid_nodes 时出错：{e}")
            # 这里可以添加更多的错误处理逻辑，例如记录日志或者设置一个默认值
            invalid_nodes = process_industry_data(check_triples_prompts.format(nodes=str(invalid_nodes)),'',llm,parser)
        else:
            break

    if invalid_nodes is not None:
        # 现在对invalid_nodes进行搜索资料，并且生成新的三元组
        invalid_nodes_info = tool_invalid_nodes_search(industry_name, invalid_nodes)
        with open('resultTxt/invalid_nodes_info.txt', 'w', encoding='utf-8') as f:
            f.write(invalid_nodes_info)
        
        invalid_nodes_info_json = {'triples_already': relations, 'node_need_expand': invalid_nodes, 'material': invalid_nodes_info}
        invalid_nodes_info_json_str = json.dumps(invalid_nodes_info_json, ensure_ascii=False)
        while True:
            new_triples_raw = process_industry_data(modify_triples_prompts.format(industry=industry_name), invalid_nodes_info_json_str, llm, parser)
            print("新三元组原始数据：", new_triples_raw)
            try:
                # 尝试清理字符串并解析为Python字面量
                if new_triples_raw is not None:
                    cleaned_new_triples_raw = new_triples_raw.replace("```", "").replace("json", "")
                    print("清理后的JSON字符串：", cleaned_new_triples_raw)
                    # 尝试解析JSON，捕获并处理可能的异常
                    try:
                        new_triples_raw = json.loads(cleaned_new_triples_raw)
                        new_relations = new_triples_raw['relations']
                        new_nodes = new_triples_raw['nodes']
                    except json.JSONDecodeError as e:
                        print(f"JSON解析错误：{e}")
                        print(f"错误位置：{e.pos}")
                        continue  # 如果JSON解析失败，继续下一次循环

                # 合并新生成的节点和白名单中的节点，并去除重复项
                new_nodes_set = set(new_nodes)
                try:
                    new_nodes_set.update(white_list)
                except FileNotFoundError:
                    print(f"文件 {white_list_file} 不存在。")    
                new_nodes = list(new_nodes_set)
                
                new_relations_str = '\n'.join(new_relations)
                new_nodes_str = '\n'.join(new_nodes)
                
                with open(f'resultTxt/new_nodes_{industry_name}.txt', 'w', encoding='utf-8') as f:
                    f.write(new_nodes_str)
                
                with open(f'resultTxt/new_relations_{industry_name}.txt', 'w', encoding='utf-8') as f:
                    f.write(new_relations_str)

                # 作图
                new_relations = [(r.split(",")[0],r.split(",")[1],r.split(",")[2]) for r in new_relations]
                has_break_points, invalid_nodes = check_triples(new_relations,f"resultImg/{industry_name}_graph.png")
                if not has_break_points:
                    print(has_break_points,invalid_nodes)        
                    break
        
            except (ValueError, SyntaxError) as e:
                print(f"解析 new_triples_raw 时出错：{e}")


    # 设置日志级别为 ERROR，忽略 WARNING 和 INFO 级别的日志
    logging.basicConfig(level=logging.ERROR)

    # 连接到 Neo4j 数据库
    uri = "neo4j://8.141.23.4:7687"
    user = "neo4j"
    password = os.getenv("NEO4J_PASSWORD")

    driver = GraphDatabase.driver(uri, auth=(user, password))        

    # 只删除标签为industry_name的节点及其关系
    with driver.session() as session:
        session.run(f"MATCH (n:`{industry_name}`) DETACH DELETE n")

    # 读取节点文件
    with open(f'resultTxt/new_nodes_{industry_name}.txt', newline='', encoding='utf-8') as csvfile:
        reader = csv.reader(csvfile)
        nodes = [row[0] for row in reader]

    # 读取关系文件
    with open(f'resultTxt/new_relations_{industry_name}.txt', newline='', encoding='utf-8') as csvfile:
        reader = csv.reader(csvfile)
        relationships = [row for row in reader]

    with driver.session() as session:
        # 创建节点
        session.write_transaction(create_nodes, nodes)
        # 创建关系
        session.write_transaction(create_relationships, relationships)

    print("已生成Neo4j图谱")    

    end_time = time.time()
    print(f"代码运行总时间：{end_time - start_time}")  






    

    # 定义一个搜索agent，专门用来搜索信息

    # agent = initialize_agent(
    #     tools=[search_tool],
    #     llm=llm,
    #     agent_type="zero-shot-react-description"
    # )
    # search_result = agent.invoke(industry_name)
    # with open(f'{industry_name}_info.txt','w',encoding='utf-8') as f:
    #     f.write(search_result)

