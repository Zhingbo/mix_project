import os
from langchain.agents import initialize_agent, AgentType
from langchain_openai import ChatOpenAI
import yaml
from GoogleSearcher import GoogleSearcher 
from Crawler import Crawler
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langgraph.checkpoint.memory import MemorySaver
import ast
from multiprocessing import Pool
from langchain.tools import Tool
import networkx as nx
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import json
import concurrent.futures


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
    temperature = 0.1 # DeepSeek API的基础URL
) 

# llm = ChatOpenAI(
#     model='gpt-4o',  # DeepSeek模型名称
#     openai_api_key=os.getenv('GPTSAPI_API_KEY'),  # API Key
#     openai_api_base='https://api.gptsapi.net/v1',
#     temperature = 0.1 # DeepSeek API的基础URL
# ) 


llm_agent = ChatOpenAI(
    model='gpt-4o',  # DeepSeek模型名称
    openai_api_key=os.getenv('GPTSAPI_API_KEY'),  # API Key
    openai_api_base='https://api.gptsapi.net/v1',
    temperature = 0.1 # DeepSeek API的基础URL
) 

parser = StrOutputParser()
memory = MemorySaver()


def check_triples(triples):
    """
    检查三元组图的连通性，并验证非叶子节点的度是否大于 10，并绘制图网络。

    参数：
    triples_json：用json的形式给出三元组元组列表，例如[(entity_a,entity_b,entity_c),...]
    返回：
    - 是否有断点 (bool)
    - 不满足度要求的节点 (list)
    """
    if isinstance(triples, str):
        try:
            triples = eval(triples)
        except Exception as e:
            print("输入信息为",triples)
            print("输入转换为列表失败，错误信息：", e)
            return None

    #创建无向图
    G = nx.Graph()





    for t in triples:
        entity1,entity2,relation = t[0],t[1],t[2]
        G.add_edge(entity1, entity2, label=relation)

    disconnected_components  = []

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



    return has_breakpoint, disconnected_components,invalid_nodes

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

def url_crawl(url):
    crawler = Crawler(jina_api_url, jina_api_headers,url)
    try:
        temp_html = crawler.crawl_url_data()
        return '无内容' if temp_html is None else temp_html
    except:
        return '无内容'




def tool_search(industry_name,isNode=False,node="",isAux=True):
    clean_prompts = clean_node_info_prompts.format(industry=industry_name,node=node) if isNode else clean_info_prompts.format(industry=industry_name)
    google_searcher = GoogleSearcher(google_api_url,headers,industry_name)
    limit = 3 if isNode else 5
    raw_content = google_searcher.google_search(limit=limit,isNode=isNode,node=node)
    urls = [r['url']for r in raw_content['results']]
    print(urls)
    web_content = ''
    images = []
    industry = node if isNode else industry_name

    total_info = []
    # with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
    #     # 使用 map 来并行处理数据
    #     total_info = executor.map(url_crawl, urls)

    for url in urls:
        total_info.append(url_crawl(url))

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
            # 爬取外部数据
        aux_content = Crawler.crawl_data(industry,data_source_excel)
        aux_knowledge = process_industry_data(clean_prompts, aux_content,llm,parser)
        # 整体的整合
        #full_knowledge = image_knowledge + '\n' + html_knowledge + '\n' + aux_knowledge
        full_knowledge = html_knowledge + '\n' + '' if aux_knowledge is None else aux_knowledge
        total_knowledge = process_industry_data(clean_prompts, full_knowledge, llm,parser)
    else:
        total_knowledge = html_knowledge
    return total_knowledge



def tool_total_search(industry_name):
    """
    查询整个产业链的知识，并返回中心节点和其他节点的信息。
    """
    # 获取中心节点信息
    center_node_info = tool_search(industry_name)

    # 生成并解析节点三元组
    nodes = process_industry_data(get_entity_prompts.format(industry=industry_name), center_node_info, llm, parser)
    print("节点有", nodes)
    nodes = ast.literal_eval(nodes.replace("```", "").replace("json", ""))

    # 使用多进程查询每个节点的信息
    total_info = []
    with Pool(4) as pool:
        nodes_params = [(industry_name, True, node, False) for node in nodes]
        total_info = pool.starmap(tool_search, nodes_params)
    total_info = '\n'.join(total_info)

    # 构建最终结果
    final = f'# 1 {industry_name}整体产业链知识\n{center_node_info}\n' + \
            f'# 2 有关{industry_name}中其他节点的产业链知识\n{total_info}'

    return final, nodes


def get_triples(final_info):
    triples_raw = process_industry_data(get_triples_prompts.format(industry=industry_name),final_info,llm,parser)
    triples_raw = triples_raw.replace("```","").replace("json","")
    triples_raw = ast.literal_eval(triples_raw)
    return triples_raw

def tool_invalid_nodes_search(input_dict):
    total_info = []
    industry_name = input_dict['industry_name']
    invalid_nodes = input_dict['invalid_nodes']
    with Pool(4) as pool:
        nodes_params  = [(industry_name,True,node,False) for node in invalid_nodes]
        total_info = pool.starmap(tool_search,nodes_params)
    total_info = '\n'.join(total_info)
    return total_info

def modify_triples(invalid_nodes_info_json):
    process_industry_data(modify_triples_prompts.format(industry=industry_name),invalid_nodes_info_json,llm,parser)
    new_triples_raw = new_triples_raw.replace("```","").replace("json","")
    new_triples_raw = ast.literal_eval(new_triples_raw)
    return new_triples_raw

industry_name = '新能源汽车'

total_search_tool = Tool(
    name="产业链查询工具",
    func=tool_total_search,
    description='''
        该工具用于查询一个产业的整体产业链信息。输入产业名称，返回产业链的详细信息和所有相关节点。
        输入：
            - industry_name (str): 产业名称
        输出：
            - Tuple: 
                - 第一个元素为产业链的详细信息 (str)
                - 第二个元素为产业链中的所有节点 (list of str)
    '''
)
check_triples_tool = Tool(
    name="三元组检查工具",
    func=check_triples,
    description='''
        用于检查三元组图的连通性，验证三元组图是否存在断点。注意，输入是三元组列表，不是dict。
        输入：
            - triples(list of tuple)：三元组列表
        输出：
            - Tuple:
                - has_breakpoint (bool): 图是否有断点
                - disconnected_components (list of set): 不连通的组件
                - invalid_nodes (list of str): 需要展开的节点列表
    '''
)

get_triples_tool = Tool(
    name="三元组生成工具",
    func=get_triples,
    description='''
        该工具根据提供的产业链节点及资料生成三元组知识图谱。
        输入：
            - final_info (str): 包含节点和材料的完整资料，用于生成三元组
        输出：
            - dict: 
                - "nodes" (list of str): 节点列表
                - "relations" (list of str): 生成的三元组列表 ["entity1,entity2,relation", ...]
    '''
)

search_invalid_nodes_tool = Tool(
    name="可展开节点信息查询工具",
    func=tool_invalid_nodes_search,
    description='''
        该工具用于搜索可展开节点的详细信息。输入产业链名称和无效节点，返回节点的详细资料。输入是字典，举例：{"industry_name":"新能源","invalid_nodes":[xx,xxx,xx]}
        输入：
            - dict:
                - "industry_name"(str):产业名称
                - "invalid_nodes"(list of str):需要查询的无效节点列表,[entity1,entity2,...]
        输出：
            - str: 所有无效节点的详细信息
    '''
)

modify_triples_tool = Tool(
    name="三元组补充工具",
    func=modify_triples,
    description='''
        该工具用于将新的节点信息补充到现有的三元组中，并生成更新后的三元组。
        输入：
            - invalid_nodes_info_json (dict): 新节点信息，包括已有三元组和需要展开的节点信息。示例如下：
              ```json
              {
                  "triples_already": [
                      ["entity1, entity2, relation"],
                      ...
                  ],
                  "nodes_need_expand": ["node1", "node2", ...],
                  "material": "补充节点的详细信息"
              }
              ```
        输出：
            - list of str: 新的三元组列表 ["entity1, entity2, relation", ...]
    '''
)


tools = [
    total_search_tool,check_triples_tool,get_triples_tool
]

react_agent = initialize_agent(
    tools=tools,
    llm=llm_agent,
    agent_type=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
    verbose=True
)

mission = f'''
    你是一个产业链专家，也是知识图谱专家。现在需要你帮我建立有关{industry_name}的知识图谱。
    我给了你很多工具，包括产业链查询工具、三元组检查工具、三元组生成工具、可展开节点信息查询工具以及三元组补充工具。
    你一定要阅读工具的描述文字，要清楚在使用工具的时候到底应该传什么样的参数。
    整体方法是：
    1. 你先使用产业链查询工具搜索有关{industry_name}的产业链资料，得到产业链资料和节点。
    2. 将得到的产业资料保存好，然后将产业资料给到三元组生成工具，使用三元组生成工具去生成三元组；
    3. 使用三元组检查工具去判断三元组是否存在断点、以及是否存在可以展开的其他节点。
    4. 如果三元组存在断点，需要你重新调用三元组生成工具重新生成三元组，你可以一直重复这个过程，直到三元组没有断点。
    5. 三元组没有断点之后，你根据你自己的行业感觉参考check_triples_tool给出的invalid_nodes，挑选出可以继续展开的行业节点；
    6. 之后你可以利用"可展开节点信息查询工具"，搜索有关这些节点的信息，然后使用三元组补充工具对已有的三元组进行补充。注意，这个地方给出的参数是字典。
    7. 补充完毕后需要再次检查，确保三元组没有断点。
    8. 注意，因为这些过程紧密相连，你必须按照我上面给出的顺序做，因为一个步骤的结果一定是下个步骤所需的条件。所以你必须保存好每个工具的输出结果。
    9. 你可以自由使用工具，只要保证最后能生成所有的节点与正确的三元组关系即可。
    10. 最后你需要输出所有整理好的节点以及三元组。格式为：
    ```json
    {{
        "nodes":["entity1","entity2",...],
        "triples":["entity1,entity2,relation",...]
    }}
    需要特别注意的是：
    1. 需要搜索信息的时候，一定要用给你提供的搜索工具；
    2. 有两个搜索工具，一个是产业链查询工具，另一个是可展开节点信息查询工具。两个工具的作用是不一样的：
    - 产业链查询工具：这个工具是用来搜索整个产业链的信息的，在刚开始的时候会用到；
    - 可展开节点信息查询工具：这个工具是用来搜索那些可以进一步展开的节点工具，在需要展开更多节点的需要。
    这两个工具的使用千万不能混淆！
    3. 你一定要保存好搜索出来的资料，因为我们需要使用这些资料来生成知识图谱三元组；
    4. 一定要补充一次节点，因为必然可以有进一步展开的节点；
    5. 最后直接返回json结果即可，不需要其他内容；
    ```
'''

response = react_agent.invoke({"input":mission})
print(response)