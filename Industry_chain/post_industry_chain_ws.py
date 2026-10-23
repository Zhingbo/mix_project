from fastapi import FastAPI, WebSocket
import uvicorn
import asyncio
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
from GoogleSearcherNew import GoogleSearcher
from CrawlerNew import Crawler
from langchain_openai import ChatOpenAI
from functions import *
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import HumanMessage, SystemMessage
from langchain.agents import initialize_agent
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from zhipuai import ZhipuAI
from openai import OpenAI


app = FastAPI()

# 定义日志记录函数
async def log_message(websocket: WebSocket, user_id, message, log_type="INFO"):
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

    # 如果是关键日志，发送到客户端
    if log_type in ["INFO", "ERROR"]:
        await websocket.send_text(log_content.strip())

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


async def process_industry_data(clean_info_prompts, raw_content, user_id, websocket, max_attempts=5, timeout=10):
    max_input_length = 65536  # 最大允许长度
    if len(raw_content) > max_input_length:
        raw_content = raw_content[:max_input_length]
        await log_message(websocket, user_id, f"输入数据过长，已截断至最大长度 {max_input_length}", log_type="WARNING")

    attempts = 0
    while attempts < max_attempts:
        try:
            # 构造消息
            messages = [
                {"role": "system", "content": clean_info_prompts},
                {"role": "user", "content": raw_content}
            ]
            # 调用火山引擎模型
            response = await asyncio.wait_for(client.chat.completions.create(
                model="ep-20250217153421-8lrxj",
                messages=messages,
                temperature=0.6,
                response_format={"type": "json_object"}
            ), timeout=timeout)
            # 获取模型的输出内容和思维链内容
            reasoning_content = response.choices[0].message.reasoning_content
            content = response.choices[0].message.content

            # 记录思维链内容到日志
            await log_message(websocket, user_id, f"Reasoning Content: {reasoning_content}", log_type="DEBUG")
            return content
        except asyncio.TimeoutError:
            await log_message(websocket, user_id, "请求超时，正在重试...", log_type="WARNING")
        except Exception as e:
            await log_message(websocket, user_id, f"Error in process_industry_data: {e}", log_type="ERROR")
        attempts += 1
        await asyncio.sleep(2)  # 等待2秒后重试
    return None


async def tool_search(industry_name, isNode=False, node="", isAux=True, user_id=None, websocket=None):
    try:
        clean_prompts = clean_node_info_prompts.format(industry=industry_name, node=node) if isNode else clean_info_prompts.format(industry=industry_name)
        google_searcher = GoogleSearcher(google_api_url, headers, industry_name)
        limit = 2 if isNode else 3
        try:
            raw_content = await asyncio.wait_for(google_searcher.google_search(limit=limit, isNode=isNode, node=node, websocket=websocket, user_id=user_id), timeout=10)
        except asyncio.TimeoutError:
            await log_message(websocket, user_id, "Google搜索超时，跳过...", log_type="WARNING")
            return '无内容'
        except Exception as e:
            await log_message(websocket, user_id, f"Error in google_search: {e}", log_type="ERROR")
            return '无内容'

        urls = []
        querys = ""
        if raw_content is not None:
            urls = [r['url'] for r in raw_content['results']]
            querys = raw_content['search_term']
            await log_message(websocket, user_id, f"Search query: {querys}")
            await log_message(websocket, user_id, f"URLs: {urls}")

        url_file_path = f"materials/url_list_{industry_name}.txt"
        with open(url_file_path, 'a') as file:
            file.write(querys + '\n')
            for url in urls:
                file.write(url + '\n')
            file.write('\n')
        await log_message(websocket, user_id, "数据源链接url已存入txt文件")

        total_info = []
        for url in urls:
            try:
                result = await asyncio.wait_for(Crawler.crawl_url_data(url, websocket, user_id), timeout=10)
            except asyncio.TimeoutError:
                await log_message(websocket, user_id, f"抓取 {url} 超时，跳过...", log_type="WARNING")
                continue
            if result is not None and result != '无内容':
                total_info.append(str(result))
        if not total_info:
            return '无内容'
        web_content = '\n'.join(total_info)
        html_knowledge = await process_industry_data(clean_prompts, web_content, user_id, websocket)

        if isAux:
            try:
                aux_content = await asyncio.wait_for(Crawler.crawl_data(industry_name, data_source_excel, websocket, user_id), timeout=10)
                aux_knowledge = await process_industry_data(clean_prompts, aux_content, user_id, websocket)
                full_knowledge = (html_knowledge or "") + '\n' + (aux_knowledge or "")
                total_knowledge = await process_industry_data(clean_prompts, full_knowledge, user_id, websocket)
            except asyncio.TimeoutError:
                await log_message(websocket, user_id, "辅助数据处理超时，跳过...", log_type="WARNING")
                return '无内容'
            except Exception as e:
                await log_message(websocket, user_id, f"Error in auxiliary data processing: {e}", log_type="ERROR")
                return '无内容'
        else:
            total_knowledge = html_knowledge
        return total_knowledge
    except BrokenPipeError:
        await log_message(websocket, user_id, "BrokenPipeError occurred in tool_search", log_type="ERROR")
        return '无内容'


async def tool_total_search(industry_name, user_id, websocket):
    try:
        await log_message(websocket, user_id, f"开始抓取中心节点信息：{industry_name}")
        center_node_info = await tool_search(industry_name, user_id=user_id, websocket=websocket)
        if center_node_info in ['无内容', '']:
            await log_message(websocket, user_id, f"中心节点信息为空，尝试重新抓取：{industry_name}")
            center_node_info = await tool_search(industry_name, isNode=False, user_id=user_id, websocket=websocket)

        await log_message(websocket, user_id, f"中心节点信息抓取完成：{industry_name}")

        nodes = await process_industry_data(get_entity_prompts.format(industry=industry_name), center_node_info, user_id, websocket)
        if nodes is None:
            await log_message(websocket, user_id, "未能获取有效的节点信息", log_type="ERROR")
            return None
        await log_message(websocket, user_id, f"节点信息提取完成：{nodes}")

        try:
            nodes = json.loads(nodes.replace("```", "").replace("json", ""))
        except Exception as e:
            await log_message(websocket, user_id, f"JSON解析失败: {e}", log_type="ERROR")
            return None

        tasks = [tool_search(industry_name, isNode=True, node=node, isAux=False, user_id=user_id, websocket=websocket) for node in nodes]
        results = await asyncio.gather(*tasks)
        total_info = [result for result in results if result is not None]
        total_info = '\n'.join(total_info)

        final = f'# 1 {industry_name}整体产业链知识\n{center_node_info}\n' + f'# 2 有关{industry_name}中其他节点的产业链知识\n{total_info}'
        return final, nodes
    except Exception as e:
        await log_message(websocket, user_id, f"tool_total_search 函数中发生错误：{e}", log_type="ERROR")
        return None


async def clean_and_parse(triples_raw, user_id, websocket):
    try:
        if triples_raw is None:
            return None
        cleaned_triples_raw = triples_raw.replace("```", "").replace("json", "")
        await log_message(websocket, user_id, f"清理后的字符串: {cleaned_triples_raw}")
        return json.loads(cleaned_triples_raw)
    except json.JSONDecodeError as e:
        await log_message(websocket, user_id, f"Error in clean_and_parse: {e}", log_type="ERROR")
        return None


async def process_industry(industry_name, user_id, websocket):
    # 获取当前进程的PID
    pid = os.getpid()
    user_folder = f"user_{user_id}_pid_{pid}"
    os.makedirs(f"resultTxt/{user_folder}", exist_ok=True)
    os.makedirs(f"resultImg/{user_folder}", exist_ok=True)

    # 调用异步函数 tool_total_search
    final_info, nodes = await tool_total_search(industry_name, user_id, websocket)

    with open(f"resultTxt/{user_folder}/{industry_name}_total_info.txt", "w", encoding='utf-8') as f:
        f.write(final_info)

    with open(f"resultTxt/{user_folder}/{industry_name}_total_info.txt", "r", encoding='utf-8') as f:
        final_info = f.read()

    # 初始化 white_list 为一个空集合
    white_list = set()

    # 尝试读取白名单文件
    try:
        with open(f'materials/white_list_{industry_name}.txt', 'r', encoding='utf-8') as file:
            white_list = set(line.strip() for line in file.readlines())
    except FileNotFoundError:
        pass

    max_attempts = 5
    attempts = 0

    while attempts < max_attempts:
        # 调用异步函数 process_industry_data
        triples_raw = await process_industry_data(get_triples_prompts.format(industry=industry_name) + "。需要特别注意：不要无限循环输出，不要有重复。", final_info + "。需要特别注意：不要无限循环输出，不要有重复。", user_id, websocket)
        triples_raw_dict = await clean_and_parse(triples_raw, user_id, websocket)
        if triples_raw_dict is None:
            attempts += 1
            if attempts >= max_attempts:
                break
            continue

        relations = triples_raw_dict['relations']
        nodes = triples_raw_dict['nodes']

        nodes_set = set(nodes)
        try:
            nodes_set.update(white_list)
        except Exception as e:
            await log_message(websocket, user_id, f"更新节点时出错: {e}", log_type="ERROR")
            continue

        nodes = list(nodes_set)

        relations_str = '\n'.join(relations)
        nodes_str = '\n'.join(nodes)

        with open(f'resultTxt/{user_folder}/nodes_{industry_name}.txt', 'w', encoding='utf-8') as f:
            f.write(nodes_str)

        with open(f'resultTxt/{user_folder}/relations_{industry_name}.txt', 'w', encoding='utf-8') as f:
            f.write(relations_str)

        break

@app.websocket('/generate_industry_chain')
async def generate_industry_chain(websocket: WebSocket):
    await websocket.accept()
    await log_message(websocket, "system", "WebSocket连接已建立")

    try:
        # 等待客户端发送数据
        data = await websocket.receive_text()
        request_data = json.loads(data)
        user_id = request_data.get("user_id")
        industry_names = request_data.get("industry_names", [])

        if not user_id or not industry_names:
            await log_message(websocket, "system", "错误：缺少必要的参数（user_id或industry_names）", log_type="ERROR")
            await websocket.close()
            return

        await log_message(websocket, user_id, f"接收到请求：{request_data}")

        for industry_name in industry_names:
            await log_message(websocket, user_id, f"开始处理行业：{industry_name}")
            try:
                await asyncio.wait_for(tool_total_search(industry_name, user_id, websocket), timeout=60)  # 设置超时时间为60秒
            except asyncio.TimeoutError:
                await log_message(websocket, user_id, f"处理行业 {industry_name} 超时，跳过...", log_type="WARNING")
            else:
                await log_message(websocket, user_id, f"行业处理完成：{industry_name}")

        await log_message(websocket, user_id, "所有行业处理完成")
    except json.JSONDecodeError:
        await log_message(websocket, "system", "错误：无法解析客户端发送的数据", log_type="ERROR")
    except Exception as e:
        await log_message(websocket, "system", f"发生未知错误：{e}", log_type="ERROR")
    finally:
        await websocket.close()  # 确保 WebSocket 连接在最后关闭

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)