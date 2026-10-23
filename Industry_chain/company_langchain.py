from langchain.agents import initialize_agent, AgentType
from langchain_openai import ChatOpenAI
import yaml
import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
import ast
from multiprocessing import Pool
from langchain.tools import Tool
from langchain.tools.render import render_text_description
import json
from langchain.agents import AgentExecutor,create_openai_tools_agent
from langchain import hub
from langchain.agents.format_scratchpad import format_log_to_str
from langchain.agents.output_parsers import ReActSingleInputOutputParser
from typing import List
from pathos.multiprocessing import Pool

with open("settings.yaml", "r") as file:
    settings = yaml.load(file, Loader=yaml.FullLoader)



deepseek_api_key = settings['system_settings']['deepseek_api_key']
deepseek_url = settings['system_settings']['deepseek_url']
industry_name = '汽车'
parser = StrOutputParser()

llm = ChatOpenAI(
    model='deepseek-chat',  # DeepSeek模型名称
    openai_api_key=deepseek_api_key,  # API Key
    openai_api_base=deepseek_url,
    temperature = 0.3 # DeepSeek API的基础URL
) 
nodes_file_path = f'new_nodes_{industry_name}.txt'

output_file_path = f'company_match_zlc_{industry_name}.xlsx'

with open(nodes_file_path, 'r', encoding='utf-8') as file:
    nodes = file.read().splitlines()

summary_prompt = f'''你是一个擅于归纳总结的专家。
    以下是一些与{industry_name}产业相关公司网站的抓取内容(crawl_content)，请你总结概括出这家公司主要是做什么的，主要概括和{industry_name}有关的部分，之后，输出一段公司简介，并以JSON的格式返回到结果中，例如：
    {{
        "crawl_content":"广东顺德和壹设计咨询有限公司主要属于工业设计行业，专注于产品设计、工业设计等领域。"
    }}
    要严格用json的方式返回，key的名称必须是"crawl_content"。下面开始：
    '''
match_nodes_prompt = f'''
    你是{industry_name}产业链专家，现在需要你根据我给出的一家公司的材料，然后把这家公司挂到{industry_name}产业链节点上去。我会以Json的方式给你有公司的材料，例如：
    {{
        "company_name":"",
        "company_intro":"",
        "major_product":""
    }}
    其中company_name是公司名称，company_intro是公司简介，major_product是公司主要产品。你需要通过公司主要产品（major_product)以及公司简介(company_info)，从下列节点中
    ```json
    {{
        "nodes" : {nodes}
    }}```
    找到至少2个最匹配的节点。
    需要你特别注意的是：
    1. 匹配节点中必须要有{industry_name}这个节点；
    2. 结果中的"匹配节点"不能只有{industry_name}这个节点，按照上边的具体匹配逻辑一定能在我提供的产业链节点中找到除了{industry_name}以外的匹配节点。
    3. 你在结合公司简介和主营产品匹配我提供的产业链节点的时候，要尽可能的全面。也就是说如果主营产品或者公司简介涉及到我提供的产业链中的某个节点，那么不仅要匹配出这个大的节点，还要进一步细化，找出这个节点下与主营产品以及公司简介相关的子节点。
    4. 不得出现其他新的节点，只能在我上面给出的节点中找。
    完成之后，请你以Json的方式返回结果，例如：
    ```json
    {{
        "company_name":"",
        "matched_nodes":[]
    }}
    ```
    其中，company_name是公司名称，matched_nodes为匹配到的节点。
    下面开始：
'''



def check_nodes(input_nodes:json)->bool:
    '''
        判断输入的节点中是否在框架范围内
    '''
    input_nodes = json.loads(input_nodes.replace("```","").replace("json",""))
    input_nodes = input_nodes['nodes']
    error_nodes = []
    for node in input_nodes:
        if not node in nodes:
            error_nodes.append(node)
    return True if len(error_nodes)==0 else False,error_nodes 
def summarise_crawl_data(raw_data:str)->str:
    '''
        输入网页爬虫的markdown内容，然后返回整理好的文字
    '''
    system_message = SystemMessage(content=summary_prompt)
    human_message = HumanMessage(content=raw_data)    
    # 构造消息列表
    messages = [system_message, human_message]      
    # 获取 LLM 输出（假设 llm.invoke 已经封装）
    html_knowledge = llm.invoke(messages)
    # 解析输出的 HTML
    parsed_knowledge = parser.invoke(html_knowledge)
    return parsed_knowledge

def match_nodes(company_info:json)->str:
    '''
        输入company_info的json数据，返回匹配节点
    '''
    system_message = SystemMessage(content=match_nodes_prompt)
    human_message = HumanMessage(content=company_info)    
    # 构造消息列表
    messages = [system_message, human_message]      
    # 获取 LLM 输出（假设 llm.invoke 已经封装）
    output = llm.invoke(messages)
    # 解析输出的 HTML
    output = parser.invoke(output)
    return output


'''
    开始写tool
'''

summary_tool = Tool(
    name="summary_tool",
    func=summarise_crawl_data,
    description='''
        该工具用于总结网页信息，把网页信息中和目标产业相关的内容总结出来。
        输入：
            - raw_data（str）: 网页爬取的数据
        输出：
            - str：归纳总结好的网页信息
    '''
)

check_nodes_tool = Tool(
    name="check_nodes_tool",
    func=check_nodes,
    description='''
        该工具用于检查匹配出来的节点是否在框架范围内。返回值为布尔类型，True表示匹配出来的节点在框架范围内，否表示不在。
        输入：
            - nodes(json): 匹配出来的节点列表，数组，格式为：
            {{
                "nodes":[]
            }}
        输出：
            - tuple
                - bool: True表示匹配的节点都在框架内，False表示不在框架内
                - list of str: 不符合要求的节点名称。如果为空，则都符合要求。
    '''
)

match_nodes_tool = Tool(
    name="match_nodes_tool",
    func=match_nodes,
    description='''
        该工具用于将企业匹配到节点上。
        输入：
            - companye_info(json):公司信息json，格式如下：
            {
                "company_name":"",
                "company_intro":"",
                "major_product":""
            }
        输出：
            - json：匹配结果json，格式如下：
            {
                "company_name":"",
                "matched_nodes":[]
            }
    '''
)
tools = [summary_tool,check_nodes_tool,match_nodes_tool]
mission = '''
    你是产业链专家，你需要帮我把我给你的这家公司匹配到{industry_name}产业链中。我先告诉必备的参数：
    "company_name":{company_name},
    "major_products":{major_product},
    "raw_data":{raw_data}
    我给了你summary_tool、check_nodes_tool、match_nodes_tool这三个工具，供你在需要的时候调用。工作流程如下：
    1. 你需要把公司的网页数据(raw_data)给到summary_tool，它会帮你总结这个企业的简介信息（company_intro);
    2. 然后你把公司名称（company_name)和公司简介(company_intro)以及公司主要生产的产品(major_product)以Json的形式给到match_nodes_tool，它会帮你进行产业链节点匹配；
    3. 匹配完成之后，你要把匹配结果(matched_nodes)给到check_nodes_tool，它会帮你检查这些匹配的节点是否在我们要求的范围内。这个工具返回两个值：
    - 第一个是节点是否符合要求：如果返回True则合格，工作完成；如果返回False则说明有不正确的节点，需要你重新进行2、3的步骤，直到最后所有的节点都在我们要求的范围内才可以。
    - 第二个是不符合的节点列表，供你参考使用。
    4. 必须确保所有的节点都在指定节点内，否则不能结束！如果实在不行，就去掉不符合要求的节点！
    如果没有问题了，直接以Json形式返回结果：
    {{
        "company_name":"",
        "company_intro":"",
        "matched_nodes":[]
    }}
    下面开始：
'''
prompt = hub.pull("hwchase17/react")

prompt = prompt.partial(
    tools = render_text_description(tools),
    tool_names = ",".join([t.name for t in tools]),
)
llm_with_stop = llm.bind(stop=["\nObservation"])

agent = (
    {
        "input":lambda x:x["input"],
        "agent_scratchpad":lambda x:format_log_to_str(x["intermediate_steps"]),
    }
    | prompt
    | llm_with_stop
    | ReActSingleInputOutputParser()
    )

def process_row(row):
    try:
        company_name=row[2],  # 'company_name' 是第3列
        major_product=row[6]  # 'major_product' 是第7列
        raw_data = row[12]
        agent_executor = AgentExecutor(agent=agent,tools=tools,verbose=True)
        print(company_name)
        response = agent_executor.invoke({"input":mission.format(industry_name=industry_name,company_name=company_name,raw_data=raw_data,major_product=major_product)})
        result_json = response['output'].replace("```","").replace("json","")
        return result_json
    except:
        return None
    

if __name__ =='__main__':

    file_path = 'company_info_nev_repaired.xlsx'
    df = pd.read_excel(file_path, sheet_name=0,nrows=100) 
    df.columns = df.columns.str.strip().str.replace('\n', '').str.replace('\r', '') 
    print("清理后的列名：", df.columns)   
    # results = []
    # for row in df.itertuples(index=False, name=None):
    #     results.append(process_row(row))
    with Pool(5) as pool:  # 使用pathos的Pool
        results = pool.map(process_row, df.itertuples(index=False, name=None))  # 返回普通元组
    
    data = [json.loads(json_str) for json_str in results if json_str is not None ]
    df = pd.DataFrame(data)
    print(df)

    # 保存到Excel文件
    df.to_excel(output_file_path, index=False)
    print(f"数据已保存到 {output_file_path}")

        

