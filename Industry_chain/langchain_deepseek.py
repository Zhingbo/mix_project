from langchain_community.chat_models import ChatOpenAI
from langchain.llms.base import LLM
from langchain.chains.base import Chain
from langchain import LLMChain
from langchain.prompts import PromptTemplate
from langchain.chains import SequentialChain
from langchain.agents import AgentExecutor
from langchain.agents import initialize_agent, Tool
from neo4j import GraphDatabase
from typing import List, Tuple
import csv
import os
from langchain_core.documents import Document
from langchain_experimental.graph_transformers import LLMGraphTransformer



# 设置DeepSeek API Key
deepseek_api_key = os.getenv('DEEPSEEK_API_KEY')

# 配置Neo4j连接
neo4j_uri = "bolt://8.141.19.136:7801"
neo4j_user = "neo4j"
neo4j_password = os.getenv("NEO4J_PASSWORD")


# 创建ChatOpenAI实例
llm = ChatOpenAI(
    model='deepseek-chat',  # DeepSeek模型名称
    openai_api_key=deepseek_api_key,  # API Key
    openai_api_base='https://api.deepseek.com/beta'  # DeepSeek API的基础URL
)


# 第一个Agent：搜索人工智能产业链的信息
search_prompt = PromptTemplate(
    input_variables=["industry"],
    template="请在知乎上搜索关于 {industry} 产业链的信息。"
)

search_chain = LLMChain(
    llm=llm,
    prompt=search_prompt
)

# 第二个Agent：将信息转化为知识图谱三元组
convert_prompt = PromptTemplate(
    input_variables=["information"],
    template='''你是一个产业链分析专家,根据查找到的资料信息生成产业链中所有的具体节点,通过节点间的关系分析,生成产业链的上下游节点关系三元组。
    关系格式为:起始节点,结束节点,关系类型。
    关系类型包括:part-of(表明了一种构成关系,表示起始节点是结束节点的一部分),is-a(说明了一种分类关系,表示起始节点是结束节点的一个种类或实例)。
    例如,如果有一个节点是“锂电池”,另一个节点是“电池”,那么它们之间的关系可以表示为“锂电池,电池,is-a”,意味着锂电池是电池的一种。
    再例如,如果有一个节点是“电芯”,另一个节点是“电池”,那么它们之间的关系可以表示为“电芯,电池,part-of”,意味着电芯是电池的一部分。
    注意:
    1) 具体的节点仅有一次作为起始节点,不能多个起始节点同时指向相同的结束节点。
    2) 直接输出结果内容即可,不需要对结果内容标注数字序号。
    3) 确定并使用最合适的节点作为产业链的中心,并且该节点也是具体节点之一。
    4) 不要将“上游”、“中游”、“下游”作为节点。
    5) 可以对节点再进一步展开。
    6) 输出结果包括两部分,第一部分是所有具体的节点,第二部分是节点关系三元组。

    以下是⼀个具体例⼦:
    "
    假设industry为汽车,总结出的节点有:
    蓄电池
    锂电池
    氢燃料电池
    同步电机
    异步电机
    电池
    动⼒系统
    电机

    构建出的产业链关系为:
    蓄电池,电池,is-a
    锂电池,电池,is-a
    氢燃料电池,电池,is-a
    同步电机,电机,is-a
    异步电机,电机,is-a
    电池,动⼒系统,part-of
    电机,动⼒系统,part-of
    "

    输出结果格式为:起始节点,结束节点,关系类型 :{information}
    
    '''
)

convert_chain = LLMChain(
    llm=llm,
    prompt=convert_prompt
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
        description="用于将信息转化为产业链节点关系三元组"
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
result = agent.run(f"请搜索关于 {industry} 产业链的信息，并生成产业链中所有的具体节点,通过节点间的关系分析,生成产业链的上下游节点关系三元组。输出结果包括两部分,第一部分是所有具体的节点,第二部分是节点关系三元组,节点关系三元组输出结果格式为:起始节点,结束节点,关系类型。输出结果中不要包含数字序号。注意:1) 具体的节点仅有一次作为起始节点,不能多个起始节点同时指向相同的结束节点。2) 确定并使用最合适的节点作为产业链的中心,并且该节点也是具体节点之一。3) 不要将“上游”、“中游”、“下游”作为节点。4)可以对节点再进一步展开。5)两个节点间只能有一种关系，要么是is-a，要么是part-of，不可以既是part-of又是is-a。")
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