'''
    这里一共有3个关键接口：
    1. 后端先请求这个接口：'/generate_industry_chain'  触发生成产业链操作，此时会得到任务的唯一id，missionId
    2. 前端如果想查询一个任务的实时状态，需要轮询请求这个接口：'/get_mission_status' ，参数是missionId，这样就能获取一个任务的实时状态，running 为 正在运行, finished 为执行完毕， failed为执行失败
    3. 前端需要轮询请求：'/get_mision_result' 来获得一个任务每个步骤的实时结果，参数也是 missionId


    注意： 
    1. mission_result这个表我只是示范了一种结构，可以根据前端的实际需求进行修改，但是必须要有missionId 这个主键
    2. 目前这个逻辑暂时不支持重跑、停止等功能；
    3. 目前单进程跑产业链，可以尝试用multiprocessing，还是多进程跑产业链，原则上应该可以，但是考虑到并发，多进程也不能太多，否则就崩掉了。还是单进程求稳吧。

'''


from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import os
import time
from datetime import datetime
import json
import yaml
from pydantic import BaseModel
from typing import Optional, List, Dict, Generator
import GoogleSearcher
from CrawlerNew import Crawler
from functions import *
from openai import OpenAI
import uuid
import mysql

server = '8.141.23.4'
username = 'remote_user'
password = os.getenv('DB_PASSWORD_REMOTE')
database = 'business_data'



# 初始化 FastAPI 应用
app = FastAPI()

tasks = {}  # 存储任务状态

# step_info = {}  # 记录每个步骤的结果，这个地方未来最好落地入库，要不然这个后端只要一关闭，这里面的信息都丢失了
# 这个东西的数据是这样的：
'''
    {'taskId':{'step1':'result1','step2':'result2',... },'taskId2':{'step1':'',..}}

    这地方其实也应该建1个表 ： mission_result 
    create table mission_result(
        missionId varchar(100),
        stepId int,
        stepName varchar(100),
        result varchar(100)
    )
'''
# 定义日志记录函数
def log_message(user_id: str, message: str, log_type: str = "INFO"):
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

def process_industry_data(clean_info_prompts: str, raw_content: str, user_id: str) -> Optional[str]:
    try:
        messages = [
            {"role": "system", "content": clean_info_prompts},
            {"role": "user", "content": raw_content}
        ]
        # 调用火山引擎模型
        response = client.chat.completions.create(
            model="ep-20250217153421-8lrxj",
            messages=messages,
            temperature=0.6,
            response_format={"type": "json_object"}
        )
        reasoning_content = response.choices[0].message.reasoning_content
        content = response.choices[0].message.content
        log_message(user_id, f"Reasoning Content: {reasoning_content}", log_type="DEBUG")
        return content
    except Exception as e:
        log_message(user_id, f"Error in process_industry_data: {e}", log_type="ERROR")
        return None
def tool_search(industry_name: str, isNode: bool = False, node: str = "", isAux: bool = True, user_id: Optional[str] = None) -> str:
    try:
        clean_prompts = clean_node_info_prompts.format(industry=industry_name, node=node) if isNode else clean_info_prompts.format(industry=industry_name)
        google_searcher = GoogleSearcher.GoogleSearcher(google_api_url, headers, industry_name)
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

def tool_total_search(industry_name: str, user_id: str, uuid_str:str) -> tuple:
    center_node_info = tool_search(industry_name, user_id=user_id)
    


    log_message(user_id, f"搜索结果为: {center_node_info}")
    if center_node_info in ['无内容', '']:
        log_message(user_id, "未获取到有效内容，调用普通搜索逻辑")
        center_node_info = tool_search(industry_name, isNode=False, user_id=user_id)
    
    conn = mysql.MySQLConnection(server,username,password,database)
    conn.execute(f'''insert into  mission_result values ('{uuid_str}','1','搜索节点信息','{center_node_info.replace("'",'"')}') ''')
    

    nodes = process_industry_data(get_entity_prompts.format(industry=industry_name), center_node_info, user_id)

    log_message(user_id, f"节点有: {nodes}")
    while True:
        if nodes is None:
            log_message(user_id, "nodes is None, retrying...", log_type="ERROR")
            nodes = process_industry_data(get_entity_prompts.format(industry=industry_name), center_node_info, user_id)
        else:
            try:
                nodes = json.loads(nodes.replace("```", "").replace("json", ""))
            except Exception as e:
                log_message(user_id, f"nodes解析失败，重新尝试: {e}", log_type="ERROR")
                nodes = process_industry_data(get_entity_prompts.format(industry=industry_name), center_node_info, user_id)
            else:
                break

    conn.execute(f'''insert into  mission_result values ('{uuid_str}','2','得到节点信息','{str(nodes).replace("'",'"')}')''')
    

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
    for node in nodes:
        result = tool_search(industry_name, True, node, False, user_id)
        if result is not None:
            total_info.append(result)
    total_info = '\n'.join(total_info)

    final = f'# 1 {industry_name}整体产业链知识\n{center_node_info}\n' + f'# 2 有关{industry_name}中其他节点的产业链知识\n{total_info}'
    conn.execute(f'''insert into  mission_result values ('{uuid_str}','3','产业链整体知识','{final.replace("'",'"')}') ''')
    conn.close

    return final, nodes

def clean_and_parse(triples_raw: str, user_id: Optional[str] = None) -> Optional[Dict]:
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

def process_industry(industry_name: str, user_id: str,uuid_str:str):
    # 获取当前进程的PID
    try:
        pid = os.getpid()
        user_folder = f"user_{user_id}_pid_{pid}"
        os.makedirs(f"resultTxt/{user_folder}", exist_ok=True)
        os.makedirs(f"resultImg/{user_folder}", exist_ok=True)


        final_info, nodes = tool_total_search(industry_name, user_id,uuid_str)    # 这个是第1-3步

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
        relations_str = ''
        nodes_str = ''

        while attempts < max_attempts:
            triples_raw = process_industry_data(
                get_triples_prompts.format(industry=industry_name) + "。需要特别注意：不要无限循环输出，不要有重复。",
                final_info + "。需要特别注意：不要无限循环输出，不要有重复。", user_id)
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
        
        conn = mysql.MySQLConnection(server,username,password,database)
        conn.execute(f'''insert into  mission_result values ('{uuid_str}','4','节点关系结果','{relations_str.replace("'",'"')}'))''')
        conn.execute(f'''insert into  mission_result values ('{uuid_str}','5','节点结果','{nodes_str.replace("'",'"')}'))''')
        '''
            这个地方也要更新 任务表 update mission_info set mission_status = 'finished' where uuid = xxxxxx
        '''
        conn.execute(f'''update mission_info set missionStatus = 'finished' where missionId = '{uuid_str}')''')
        conn.close()


    except:
        print('出错了') # 或者增加其他逻辑
        '''
            也要更新任务表   update mission_info set mission_status = 'failed' where uuid = xxxxxx 
        '''
        conn = mysql.MySQLConnection(server,username,password,database)
        print('')
        conn.execute(f'''update mission_info set missionStatus = 'failed' where missionId = '{uuid_str}' ''')
        conn.close()



class industryModel(BaseModel):
    user_id:str
    industry_name:str

class missionItem(BaseModel):
    missionId:str 


@app.post('/generate_industry_chain')
async def generate_industry_chain(item:industryModel):
    import multiprocessing
    import uuid
    uuid_str = str(uuid.uuid4()) 
    data = item.model_dump()
    user_id = data['user_id']
    industry_name = data['industry_name']

    if not user_id or not industry_name:
        return JSONResponse(content={"error": "Missing user_id or industry_name"}, status_code=400)
    # await process_industry(industry_name,user_id)
    process = multiprocessing.Process(target=process_industry,args=(industry_name,user_id,uuid_str,))
    process.start()
    tasks[f'{user_id}_{industry_name}'] = process
    '''
        这个地方需要你建一张表（mission_info），表的字段有：uuid（唯一定义一个任务）,user_id, industry_name, mission_status 
        mission_status 就是当前这个任务的状态
        这里需要写一个语句，因为这个时候任务开始跑了，所以 insert into mission_info values(uuid,user_id,industry_name,'running')
    '''
    conn = mysql.MySQLConnection(server,username,password,database)
    conn.execute(f'''insert into mission_info values('{uuid_str}','{user_id}','{industry_name}','running')''')
    conn.close()
    return {'message':'ok','missionId':uuid_str}

@app.post('/get_mission_status')  # 获取任务状态，是running、finished还是failed。这个接口需要轮询请求（循环请求），就可以得到某个任务的实时状态
def get_mission_status(item:missionItem):   # 输入uuid，得到 任务状态
    try:
        data = item.model_dump()
        missionId = data['missionId']
        conn = mysql.MySQLConnection(server,username,password,database)
        rows = conn.query(f''' select * from  mission_info where missionId = {missionId} ''')
        row = rows[0]
        conn.close()
        return {'message':'ok','data':row}
    except:
        return {'message':'failed'}

@app.post('/get_mision_result')  # 这个获取整个过程的结果,需要轮询请求，就可以得到某个任务的实时结果
def get_mission_result(item:missionItem):
    try:
        data = item.model_dump()
        missionId = data['missionId']
        conn = mysql.MySQLConnection(server,username,password,database)
        rows = conn.query(f''' select * from  mission_result where missionId = {missionId} ''')
        conn.close()
        return {'message':'ok','data':rows}
    except:
        return {'message':'failed'}





if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)