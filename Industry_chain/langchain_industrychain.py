from langchain_community.chat_models import ChatOpenAI
from langchain.llms.base import LLM
from langchain.chains.base import Chain
from langchain import LLMChain
from langchain.prompts import PromptTemplate
from langchain.chains import SequentialChain
from langchain.agents import AgentExecutor
from neo4j import GraphDatabase
from Crawler import Crawler
from typing import List, Tuple
import csv
import os
from pydantic import BaseModel, Extra
from langchain_core.documents import Document
from langchain_experimental.graph_transformers import LLMGraphTransformer
from GoogleSearcher import GoogleSearcher
from langchain_openai import ChatOpenAI
import yaml
from functions import * 
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent
from langchain.tools import tool
from langchain.agents import AgentExecutor
from langchain.tools import Tool
from langgraph.checkpoint.memory import MemorySaver
from langchain.agents import initialize_agent
from multiprocessing import Pool
import networkx as nx
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties


# 配置Neo4j连接
neo4j_uri = "bolt://8.141.19.136:7801"
neo4j_user = "neo4j"
neo4j_password = os.getenv("NEO4J_PASSWORD")


with open("settings.yaml", "r") as file:
    settings = yaml.safe_load(file)


headers = settings['system_settings']['headers']
google_api_url = settings['system_settings']['google_api_url']
deepseek_api_key = settings['system_settings']['deepseek_api_key']
deepseek_url = settings['system_settings']['deepseek_url']
clean_info_prompts = settings['prompts']['clean_info']['content']
clean_node_info_prompts =  settings['prompts']['clean_node_info']['content']
words_from_ocr_prompts = settings['prompts']['words_from_ocr']['content']
jina_api_url = settings['system_settings']['jina_api_url']
jina_api_headers = settings['system_settings']['jina_api_headers']
data_source_excel = settings['system_settings']['data_source_excel']

get_entity_prompts = '''
        请从这些搜索结果以及你自己的知识中找出与{industry}产业链相关的实体，实体越多越好。通过数组方式返回你找到的所有实体,如：
        ["xx","xxxx","xxxx","xxxx","xxxxx"]"
        注意：
        1.输出结果严格按照上述格式返回，除了这些实体不要返回任何其他内容，比如："以下是眼镜产业链的相关信息","这些信息涵盖了眼镜产业链"等等，这些总结或者阐述方面的内容都不要返回到结果中。
        2.只返回数组即可，不需要返回其他内容。
    '''

get_entity_prompts_dict = {
    "content": """
        请从这些搜索结果以及你自己的知识中找出与{industry}产业链相关的实体，实体越多越好。通过数组方式返回你找到的所有实体,如：
        ["xx","xxxx","xxxx","xxxx","xxxxx"]"
        注意：
        1.输出结果严格按照上述格式返回，除了这些实体不要返回任何其他内容，比如："以下是眼镜产业链的相关信息","这些信息涵盖了眼镜产业链"等等，这些总结或者阐述方面的内容都不要返回到结果中。
        2.只返回数组即可，不需要返回其他内容。
    """
}

get_triples_prompts_dict = {
    "content": """
        你是一个产业链分析专家,也是一个构建产业链知识图谱的专家。用户输入的资料中，最开始为中心节点{industry}产业链的相关资料，之后为{industry}产业链其他相关节点的资料。你需要结合整体资料进行整理。
        你需要总结出以{industry}为中心节点的产业链上中下游的所有节点，首先总结出{industry}，上游，中游，下游这四个节点，然后可以按照从成品到原材料，再到原材料的原材料的逻辑关系，分别总结出其他所有节点,最后总结出这些节点的关系三元组。
        总结节点关系三元组的时候，你按照逐步抽象法去总结，这种方法从宏观的角度出发，逐步细化到微观层面，通过逐层深入的方式构建知识图谱。
        比如新能源汽车产业链，首先总结出"上游,新能源汽车,part-of",然后再总结出"动力电池,上游,part-of"，然后再总结出"正负极材料,动力电池,part-of"，最后总结出"锂矿,正负极材料,is-a"。
        节点的关系三元组格式为:起始节点,结束节点,关系类型。
        起始节点表示下一级的节点，结束节点表示上一级的节点。比如锂电池是电池的下一级节点，那么他们的关系格式应该表示为“锂电池,电池,is-a”而不是“电池,锂电池,is-a”。
        关系类型包括:part-of(表明了一种构成关系,表示起始节点是结束节点的一部分),is-a(说明了一种分类关系,表示起始节点是结束节点的一个种类或实例)。
        例如,如果有一个节点是“锂电池”,另一个节点是“电池”,那么它们之间的关系可以表示为“锂电池,电池,is-a”,意味着锂电池是电池的一种。
        再例如,如果有一个节点是“电芯”,另一个节点是“电池”,那么它们之间的关系可以表示为“电芯,电池,part-of”,意味着电芯是电池的一部分。
        注意:
        1) 具体的节点仅有一次作为起始节点,不能多个起始节点同时指向相同的结束节点。
        2) 输出结果包括两部分,第一部分是所有具体的节点,第二部分是节点的关系三元组。具体节点以及三元组输出结果都是直接输出结果内容即可,不需要对结果内容标注数字序号。比如具体节点不要输出"1. 动力电池"而是要输出"动力电池".三元组不要输出"1. 动力电池,电池材料,part-of"而是要输出"动力电池,电池材料,part-of"。
        3) 如果你总结出的节点中有重复项或者意思相近，不要把他们作为单独节点，而是将他们合并。比如：节点"车身"以及节点"车身及其附件"，那么只保留"车身及其附件"，舍弃掉"车身"这个节点，并且"车身"这个节点下如果还有其他展开的节点也一并归入"车身及其附件"下。
        4) 用户输入的资料是一篇完整的大文章，总结节点的时候不要将每一部分独立开来，一定要分析出各部分之间的关系并将他们联系起来。对于找不到联系的部分直接剔除掉。
        5) 中心节点只有一个，那就是{industry}，它只能是结束节点。
        6) 除了中心节点外，其他节点一定要有结束节点，否则会出现知识图谱中边的丢失。
        7) 你总结出来的节点一定不要有重复的。
        8) 你总结出来的三元组也一定不要有重复的。
        9) {industry}，上游，中游和下游这四个节点一定要返回到输出结果中，并且上游，中游和下游与中心节点构成三个三元组，即"上游,{industry},part-of","中游,{industry},part-of","下游,{industry},part-of"。
            这是必须要有的三个三元组。
        10) 除了上游，中游和下游其余节点都不能与{industry}这个中心节点建立关系，也就是说其余节点的结束节点都不能是{industry}。
        11) 总结出的节点名字中不要含有"产业链"这三个字。
        12) 总结出的节点不要有类似"供需平衡"这种不属于产业链的某个具体部分的。
        13) 总结出的节点不要有公司名字。
        需要特别注意的是：整个产业链节点关系不能有断点，不能有独立的丢失关系的节点。
        以下是⼀个具体例⼦，仅供参考,假设用户输入的资料都是汽车相关的信息,那么以汽车为中心节点的产业链输出结果用Json表示:
        ```json
        {
          "nodes":["汽车","整车制造","蓄电池","锂电池","氢燃料电池","同步电机","异步电机","电池","动⼒系统","电机"],
          "relations":["电池,上游,part-of", ...]
        }
        ```
        下面给你资料，你需要尽可能地展开所有的节点，你展开的节点越多你做的就越好！！请你认真分析下面的资料，并按要求整理出节点和三元组：
    """
}

get_triples_prompts = '''
        你是一个产业链分析专家,也是一个构建产业链知识图谱的专家。用户输入的资料中，最开始为中心节点{industry}产业链的相关资料，之后为{industry}产业链其他相关节点的资料。你需要结合整体资料进行整理。
        你需要总结出以{industry}为中心节点的产业链上中下游的所有节点，首先总结出{industry}，上游，中游，下游这四个节点，然后可以按照从成品到原材料，再到原材料的原材料的逻辑关系，分别总结出其他所有节点,最后总结出这些节点的关系三元组。
        总结节点关系三元组的时候，你按照逐步抽象法去总结，这种方法从宏观的角度出发，逐步细化到微观层面，通过逐层深入的方式构建知识图谱。
        比如新能源汽车产业链，首先总结出"上游,新能源汽车,part-of",然后再总结出"动力电池,上游,part-of"，然后再总结出"正负极材料,动力电池,part-of"，最后总结出"锂矿,正负极材料,is-a"。
        节点的关系三元组格式为:起始节点,结束节点,关系类型。
        起始节点表示下一级的节点，结束节点表示上一级的节点。比如锂电池是电池的下一级节点，那么他们的关系格式应该表示为“锂电池,电池,is-a”而不是“电池,锂电池,is-a”。
        关系类型包括:part-of(表明了一种构成关系,表示起始节点是结束节点的一部分),is-a(说明了一种分类关系,表示起始节点是结束节点的一个种类或实例)。
        例如,如果有一个节点是“锂电池”,另一个节点是“电池”,那么它们之间的关系可以表示为“锂电池,电池,is-a”,意味着锂电池是电池的一种。
        再例如,如果有一个节点是“电芯”,另一个节点是“电池”,那么它们之间的关系可以表示为“电芯,电池,part-of”,意味着电芯是电池的一部分。
        注意:
        1) 具体的节点仅有一次作为起始节点,不能多个起始节点同时指向相同的结束节点。
        2) 输出结果包括两部分,第一部分是所有具体的节点,第二部分是节点的关系三元组。具体节点以及三元组输出结果都是直接输出结果内容即可,不需要对结果内容标注数字序号。比如具体节点不要输出"1. 动力电池"而是要输出"动力电池".三元组不要输出"1. 动力电池,电池材料,part-of"而是要输出"动力电池,电池材料,part-of"。
        3) 如果你总结出的节点中有重复项或者意思相近，不要把他们作为单独节点，而是将他们合并。比如：节点"车身"以及节点"车身及其附件"，那么只保留"车身及其附件"，舍弃掉"车身"这个节点，并且"车身"这个节点下如果还有其他展开的节点也一并归入"车身及其附件"下。
        4) 用户输入的资料是一篇完整的大文章，总结节点的时候不要将每一部分独立开来，一定要分析出各部分之间的关系并将他们联系起来。对于找不到联系的部分直接剔除掉。
        5) 中心节点只有一个，那就是{industry}，它只能是结束节点。
        6) 除了中心节点外，其他节点一定要有结束节点，否则会出现知识图谱中边的丢失。
        7) 你总结出来的节点一定不要有重复的。
        8) 你总结出来的三元组也一定不要有重复的。
        9) {industry}，上游，中游和下游这四个节点一定要返回到输出结果中，并且上游，中游和下游与中心节点构成三个三元组，即"上游,{industry},part-of","中游,{industry},part-of","下游,{industry},part-of"。
            这是必须要有的三个三元组。
        10) 除了上游，中游和下游其余节点都不能与{industry}这个中心节点建立关系，也就是说其余节点的结束节点都不能是{industry}。
        11) 总结出的节点名字中不要含有"产业链"这三个字。
        12) 总结出的节点不要有类似"供需平衡"这种不属于产业链的某个具体部分的。
        13) 总结出的节点不要有公司名字。
        需要特别注意的是：整个产业链节点关系不能有断点，不能有独立的丢失关系的节点。
        以下是⼀个具体例⼦，仅供参考,假设用户输入的资料都是汽车相关的信息,那么以汽车为中心节点的产业链输出结果用Json表示:
        ```json
        {
          "nodes":["汽车","整车制造","蓄电池","锂电池","氢燃料电池","同步电机","异步电机","电池","动⼒系统","电机"],
          "relations":["电池,上游,part-of", ...]
        }
        ```
        下面给你资料，你需要尽可能地展开所有的节点，你展开的节点越多你做的就越好！！请你认真分析下面的资料，并按要求整理出节点和三元组：
    '''

llm = ChatOpenAI(
    model='deepseek-chat',  # DeepSeek模型名称
    openai_api_key=deepseek_api_key,  # API Key
    openai_api_base=deepseek_url # DeepSeek API的基础URL
)
parser = StrOutputParser()
memory = MemorySaver()

def process_industry_data(clean_info_prompts,raw_content, llm, parser):
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

def tool_search(industry_name,isNode=False,node="",isAux=True):
    clean_prompts = clean_node_info_prompts.format(industry=industry_name,node=node) if isNode else clean_info_prompts.format(industry=industry_name)
    google_searcher = GoogleSearcher(google_api_url,headers,industry_name)
    limit = 5 if isNode else 8
    raw_content = google_searcher.google_search(limit=limit,isNode=isNode,node=node)
    urls = [r['url']for r in raw_content['results']]
    print(urls)
    web_content = ''
    images = []
    industry = node if isNode else industry_name

    # 下面的部分多线程完成，否则太慢了
    total_info = []
    for url in urls:
        total_info.append(url_crawl(url))
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
    html_knowledge = process_industry_data(clean_prompts, web_content, llm, parser)
   
    # 整理外部知识
    if isAux:
        # 爬取外部数据
        aux_content = Crawler.crawl_data(industry,data_source_excel)
        aux_knowledge = process_industry_data(clean_prompts, aux_content, llm, parser)
        # 整体的整合
         #full_knowledge = image_knowledge + '\n' + html_knowledge + '\n' + aux_knowledge
        full_knowledge = html_knowledge + '\n' + aux_knowledge
        total_knowledge = process_industry_data(clean_prompts, full_knowledge, llm, parser)
    else:
        total_knowledge = html_knowledge
    return total_knowledge

def url_crawl(url):
    crawler = Crawler(jina_api_url, jina_api_headers,url)
    try:
        temp_html = crawler.crawl_url_data()
        return '无内容' if temp_html is None else temp_html
    except:
        return '无内容'
    
def tool_total_search(industry_name):
    center_node_info = tool_search(industry_name)
    ## 总结三元组
    nodes = process_industry_data(get_entity_prompts.format(industry=industry_name),center_node_info,llm,parser)
    print("节点有",nodes)
    nodes = eval(nodes)
    total_info = []
    with Pool(4) as pool:
        nodes_params = [(industry_name,True,node,False) for node in nodes]
        total_info = pool.starmap(tool_search,nodes_params)
    total_info = '\n'.join(total_info)

    final = f'# 1 {industry_name}整体产业链知识\n{center_node_info}\n' + f'# 2 有关{industry_name}中其他节点的产业链知识\n{total_info}'
    return final

# 包装tool
search_tool = Tool.from_function(
    func=tool_total_search,
    name="IndustrySearchTool",
    description="This tool searches for information about a specific industry and returns detailed knowledge."
)

# 第一个Agent：自动化搜索产业链的信息，直接使用search_tool
search_chain = LLMChain(
    llm=llm,
    prompt=get_entity_prompts_dict
)

# 第二个Agent：将信息转化为知识图谱三元组
convert_chain = LLMChain(
    llm=llm,
    prompt=get_triples_prompts_dict
)

# 定义一个工具列表
tools = [
    Tool(
        name="SearchAgent",
        func=search_chain.run,
        description="用于搜索产业链信息"
    ),
    Tool(
        name="ConvertAgent",
        func=convert_chain.run,
        description="用于将产业链信息转化为节点和三元组"
    )
]

# 初始化Agent
agent = initialize_agent(
    tools,
    llm,
    agent_type="zero-shot-react-description",
    verbose=True
)

# 运行Agent
industry = "新能源汽车"
result = agent.run(f"请搜索关于 {industry} 产业链的信息，并生成产业链上中下游的具体节点,通过节点间的关系分析,生成产业链的上中下游节点关系三元组。")
print(result)

documents = [Document(page_content=result)]
graph_documents = llm.convert_to_graph_documents(documents)
print(f"Nodes:{graph_documents[0].nodes}")
print(f"Relationships:{graph_documents[0].relationships}")

# # 指定CSV文件的名称
# file_name = "nev_industry.csv"

# # 检查文件是否存在，如果存在则删除
# if os.path.exists(file_name):
#     os.remove(file_name)
#     print(f"已存在的文件 {file_name} 已被删除。")

# with open(file_name, 'w', newline='', encoding='gbk') as csvfile:
#     # 创建一个csv的写入器
#     writer = csv.writer(csvfile)
    
#     # 写入标题行
#     writer.writerow(['Subject', 'Predicate', 'Object'])
    
#     # 写入三元组数据
#     for row in result:
#         # 清理数据，移除多余的逗号和空格
#         cleaned_row = [item.strip().replace('，', ',').replace('"', '') for item in row]
#         writer.writerow(cleaned_row)

# print(f"数据已写入 {file_name}")

# LABEL = "新能源汽车产业链"

# driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

# # 只删除标签为LABEL的节点及其关系
# with driver.session() as session:
#     session.run(f"MATCH (n:{LABEL}) DETACH DELETE n")

# # 定义导入数据的函数
# def import_data(tx, file_name):
#     with open(file_name, 'r', encoding='gbk') as csvfile:
#         reader = csv.reader(csvfile)
#         for row in reader:
#             source, target, relation_type = row
#         tx.run("""
#             MATCH (a:%s {name: $source})
#             OPTIONAL MATCH (b:%s {name: $target})
#             MERGE (a)-[:`%s`]->(b)
#             """%(LABEL, LABEL, relation_type),
#             source=source, target=target)

# # 执行导入操作
# with driver.session() as session:
#     session.write_transaction(import_data, file_name)

# # 关闭数据库连接
# driver.close()

# print("数据已成功导入Neo4j")