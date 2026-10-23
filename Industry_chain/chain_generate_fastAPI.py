from fastapi import FastAPI, Request, HTTPException, StreamingResponse
from fastapi.responses import JSONResponse
import os
import time
from datetime import datetime
import json
import yaml
from pydantic import BaseModel
from typing import Optional, List, Dict, Generator
import GoogleSearcherNew
from CrawlerNew import Crawler
from functions import *
from openai import OpenAI
import uuid
import asyncio

# 初始化 FastAPI 应用
app = FastAPI()

tasks = {}  # 存储任务状态

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

async def process_industry_data(clean_info_prompts: str, raw_content: str, user_id: str) -> Optional[str]:
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

async def tool_search(industry_name: str, isNode: bool = False, node: str = "", isAux: bool = True, user_id: Optional[str] = None) -> str:
    try:
        clean_prompts = clean_node_info_prompts.format(industry=industry_name, node=node) if isNode else clean_info_prompts.format(industry=industry_name)
        google_searcher = GoogleSearcherNew.GoogleSearcher(google_api_url, headers, industry_name)
        limit = 2 if isNode else 3
        try:
            raw_content = await google_searcher.google_search(limit=limit, isNode=isNode, node=node)
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
            # 使用 await 调用异步方法
            result = await Crawler.crawl_url_data(url)
            if result is not None and result != '无内容':
                total_info.append(str(result))
        if not total_info:
            return '无内容'
        web_content = '\n'.join(total_info)
        html_knowledge = await process_industry_data(clean_prompts, web_content, user_id)

        if isAux:
            try:
                aux_content = await Crawler.crawl_data(industry_name, data_source_excel)
                aux_knowledge = await process_industry_data(clean_prompts, aux_content, user_id)
                full_knowledge = (html_knowledge or "") + '\n' + (aux_knowledge or "")
                total_knowledge = await process_industry_data(clean_prompts, full_knowledge, user_id)
            except Exception as e:
                log_message(user_id, f"Error in auxiliary data processing: {e}", log_type="ERROR")
                return '无内容'
        else:
            total_knowledge = html_knowledge
        return total_knowledge
    except BrokenPipeError:
        log_message(user_id, "BrokenPipeError occurred in tool_search", log_type="ERROR")
        return '无内容'

async def tool_total_search(industry_name: str, user_id: Optional[str] = None) -> tuple:
    center_node_info = await tool_search(industry_name, user_id=user_id)
    log_message(user_id, f"搜索结果为: {center_node_info}")
    if center_node_info in ['无内容', '']:
        log_message(user_id, "未获取到有效内容，调用普通搜索逻辑")
        center_node_info = await tool_search(industry_name, isNode=False, user_id=user_id)

    nodes = await process_industry_data(get_entity_prompts.format(industry=industry_name), center_node_info, user_id)
    log_message(user_id, f"节点有: {nodes}")
    while True:
        if nodes is None:
            log_message(user_id, "nodes is None, retrying...", log_type="ERROR")
            nodes = await process_industry_data(get_entity_prompts.format(industry=industry_name), center_node_info, user_id)
        else:
            try:
                nodes = json.loads(nodes.replace("```", "").replace("json", ""))
            except Exception as e:
                log_message(user_id, f"nodes解析失败，重新尝试: {e}", log_type="ERROR")
                nodes = await process_industry_data(get_entity_prompts.format(industry=industry_name), center_node_info, user_id)
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
    for node in nodes:
        result = await tool_search(industry_name, True, node, False, user_id)
        if result is not None:
            total_info.append(result)
    total_info = '\n'.join(total_info)

    final = f'# 1 {industry_name}整体产业链知识\n{center_node_info}\n' + f'# 2 有关{industry_name}中其他节点的产业链知识\n{total_info}'
    return final, nodes

async def clean_and_parse(triples_raw: str, user_id: Optional[str] = None) -> Optional[Dict]:
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

async def process_industry(industry_name: str, user_id: str, log_queue: asyncio.Queue):
    # 获取当前进程的PID
    pid = os.getpid()
    user_folder = f"user_{user_id}_pid_{pid}"
    os.makedirs(f"resultTxt/{user_folder}", exist_ok=True)
    os.makedirs(f"resultImg/{user_folder}", exist_ok=True)

    final_info, nodes = await tool_total_search(industry_name, user_id=user_id)

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
        triples_raw = await process_industry_data(
            get_triples_prompts.format(industry=industry_name) + "。需要特别注意：不要无限循环输出，不要有重复。",
            final_info + "。需要特别注意：不要无限循环输出，不要有重复。", user_id)
        triples_raw_dict = await clean_and_parse(triples_raw, user_id)
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

    log_queue.put_nowait("Task completed successfully.")

async def log_generator(log_queue: asyncio.Queue):
    while True:
        log = await log_queue.get()
        if log is None:
            break
        yield f"data: {log}\n\n"

@app.post('/generate_industry_chain')
async def generate_industry_chain(request: Request):
    try:
        data = await request.json()
        user_id = data.get('user_id')
        industry_name = data.get('industry_name')

        if not user_id or not industry_name:
            return JSONResponse(content={"error": "Missing user_id or industry_name"}, status_code=400)

        log_message(user_id, f"Received request for {industry_name}")

        log_queue = asyncio.Queue()

        asyncio.create_task(process_industry(industry_name, user_id, log_queue))  # 使用 asyncio.create_task 启动后台任务

        return StreamingResponse(log_generator(log_queue), media_type="text/event-stream")
    except Exception as e:
        log_message(user_id, f"Error in generate_industry_chain: {e}", log_type="ERROR")
        return JSONResponse(content={"error": "Internal Server Error"}, status_code=500)

@app.get('/task_status/{task_id}')
async def task_status(task_id: str):
    """查询任务状态"""
    task = tasks.get(task_id)
    if not task:
        return JSONResponse(content={"error": "Task not found"}, status_code=404)

    return JSONResponse(content={"task_id": task_id, "status": task["status"]}, status_code=200)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)