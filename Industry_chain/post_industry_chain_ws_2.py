from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import asyncio
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

# 初始化 FastAPI 应用
app = FastAPI()

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

async def process_industry_data(
    clean_info_prompts: str,
    raw_content: str,
    user_id: str,
    websocket: WebSocket = None
) -> Optional[str]:
    try:
        max_length = 65536
        chunks = [raw_content[i:i + max_length] for i in range(0, len(raw_content), max_length)]

        results = []
        for chunk_index, chunk in enumerate(chunks, 1):
            messages = [
                {"role": "system", "content": clean_info_prompts},
                {"role": "user", "content": chunk}
            ]

            response = client.chat.completions.create(
                model="ep-20250217153421-8lrxj",
                messages=messages,
                temperature=0.6,
                response_format={"type": "json_object"}
            )

            reasoning_content = response.choices[0].message.reasoning_content
            content = response.choices[0].message.content

            log_message(user_id, f"Reasoning Content: {reasoning_content}", log_type="DEBUG")

            if websocket:
                await websocket.send_text(f"Reasoning Content (Chunk {chunk_index}): {reasoning_content}")

            results.append(content)

        final_result = "\n".join(results)

        if websocket:
            await websocket.send_text("数据处理完成，所有 reasoning content 已发送。")

        return final_result

    except WebSocketDisconnect as e:
        log_message(user_id, f"WebSocket disconnected by client: {e}", log_type="WARNING")
    except Exception as e:
        log_message(user_id, f"Error in process_industry_data: {e}", log_type="ERROR")
        if websocket:
            await websocket.send_text(f"数据处理出错: {str(e)}")
        return None

async def tool_search(industry_name: str, isNode: bool = False, node: str = "", isAux: bool = True, user_id: Optional[str] = None, websocket: WebSocket = None) -> str:
    heartbeat_task = asyncio.create_task(send_heartbeat(websocket))
    try:
        clean_prompts = clean_node_info_prompts.format(industry=industry_name, node=node) if isNode else clean_info_prompts.format(industry=industry_name)
        google_searcher = GoogleSearcherNew.GoogleSearcher(google_api_url, headers, industry_name)
        limit = 2 if isNode else 3
        try:
            raw_content = await google_searcher.google_search(limit=limit, isNode=isNode, node=node, websocket=websocket, user_id=user_id)
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
            result = await Crawler.crawl_url_data(url, websocket, user_id)
            if result is not None and result != '无内容':
                total_info.append(str(result))
        if not total_info:
            return '无内容'
        web_content = '\n'.join(total_info)
        html_knowledge = await process_industry_data(clean_prompts, web_content, user_id)

        if isAux:
            try:
                aux_content = await Crawler.crawl_data(industry_name, data_source_excel, websocket, user_id)
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

async def tool_total_search(industry_name: str, user_id: Optional[str] = None, websocket: WebSocket = None) -> tuple:
    heartbeat_task = asyncio.create_task(send_heartbeat(websocket))
    # 开始搜索中心节点信息，并逐步发送状态信息
    log_message(user_id, f"开始处理 {industry_name} 的产业链数据")
    if websocket:
        await websocket.send_text(f"开始处理 {industry_name} 的产业链数据")

    center_node_info = await tool_search(industry_name, user_id=user_id, websocket=websocket)
    log_message(user_id, f"搜索结果为: {center_node_info}")
    if websocket:
        await websocket.send_text(f"搜索到中心节点信息：{center_node_info}")

    # 如果未获取到有效内容，调用普通搜索逻辑
    if center_node_info in ['无内容', '']:
        log_message(user_id, "未获取到有效内容，调用普通搜索逻辑")
        if websocket:
            await websocket.send_text("未获取到有效内容，调用普通搜索逻辑")
        center_node_info = await tool_search(industry_name, isNode=False, user_id=user_id, websocket=websocket)
        log_message(user_id, f"普通搜索结果为: {center_node_info}")
        if websocket:
            await websocket.send_text(f"普通搜索结果为：{center_node_info}")

    # 开始处理节点信息，并逐步发送状态信息
    log_message(user_id, f"开始处理 {industry_name} 的节点信息")
    if websocket:
        await websocket.send_text(f"开始处理 {industry_name} 的节点信息")

    nodes = await process_industry_data(get_entity_prompts.format(industry=industry_name), center_node_info, user_id)
    log_message(user_id, f"初步获取到的节点有: {nodes}")
    if websocket:
        await websocket.send_text(f"初步获取到的节点有：{nodes}")

    while True:
        if nodes is None:
            log_message(user_id, "nodes is None, retrying...", log_type="ERROR")
            if websocket:
                await websocket.send_text("未获取到节点信息，正在重试...")
            nodes = await process_industry_data(get_entity_prompts.format(industry=industry_name), center_node_info, user_id)
        else:
            try:
                nodes = json.loads(nodes.replace("```", "").replace("json", ""))
            except Exception as e:
                log_message(user_id, f"nodes解析失败，重新尝试: {e}", log_type="ERROR")
                if websocket:
                    await websocket.send_text(f"节点信息解析失败，错误信息：{e}，正在重试...")
                nodes = await process_industry_data(get_entity_prompts.format(industry=industry_name), center_node_info, user_id)
            else:
                break

    # 加入白名单节点，并逐步发送状态信息
    try:
        with open(f'materials/white_list_{industry_name}.txt', 'r', encoding='utf-8') as file:
            white_list = file.read().splitlines()
            for item in white_list:
                if item not in nodes:
                    nodes.append(item)
            log_message(user_id, f"加入白名单后的节点有: {nodes}")
            if websocket:
                await websocket.send_text(f"加入白名单后的节点有：{nodes}")
    except FileNotFoundError:
        log_message(user_id, f"文件 materials/white_list_{industry_name}.txt 不存在。", log_type="WARNING")
        if websocket:
            await websocket.send_text(f"白名单文件 materials/white_list_{industry_name}.txt 不存在。")

    # 开始处理每个节点的产业链知识，并逐步发送状态信息
    log_message(user_id, f"开始处理每个节点的产业链知识")
    if websocket:
        await websocket.send_text(f"开始处理每个节点的产业链知识")

    total_info = []
    for node in nodes:
        log_message(user_id, f"正在处理节点：{node}")
        if websocket:
            await websocket.send_text(f"正在处理节点：{node}")
        result = await tool_search(industry_name, True, node, False, user_id, websocket)
        if result is not None:
            total_info.append(result)
            log_message(user_id, f"节点 {node} 的产业链知识处理完成")
            if websocket:
                await websocket.send_text(f"节点 {node} 的产业链知识处理完成")

    total_info = '\n'.join(total_info)

    final = f'# 1 {industry_name}整体产业链知识\n{center_node_info}\n' + f'# 2 有关{industry_name}中其他节点的产业链知识\n{total_info}'
    log_message(user_id, f"产业链知识处理完成，最终结果为：{final}")
    if websocket:
        await websocket.send_text(f"产业链知识处理完成，最终结果为：{final}")

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

async def process_industry(industry_name: str, user_id: str, websocket: WebSocket):
    heartbeat_task = asyncio.create_task(send_heartbeat(websocket))
    # 获取当前进程的PID
    pid = os.getpid()
    user_folder = f"user_{user_id}_pid_{pid}"
    os.makedirs(f"resultTxt/{user_folder}", exist_ok=True)
    os.makedirs(f"resultImg/{user_folder}", exist_ok=True)

    # 逐步处理任务并发送日志信息
    async def send_log(message: str):
        await websocket.send_text(message)
        await asyncio.sleep(0.5)  # 模拟处理延迟

    try:
        log_message(user_id, f"开始处理 {industry_name} 的产业链数据")
        if websocket:
            await websocket.send_text(f"开始处理 {industry_name} 的产业链数据")

        # final_info, nodes = await tool_total_search(industry_name, user_id=user_id, websocket=websocket)
        # if websocket:
        #     await websocket.send_text(f"完成产业链数据的初步处理，获取到中心节点信息和相关节点")

        # with open(f"resultTxt/{user_folder}/{industry_name}_total_info.txt", "w", encoding='utf-8') as f:
        #     f.write(final_info)

        # with open(f"resultTxt/{user_folder}/{industry_name}_total_info.txt", "r", encoding='utf-8') as f:
        #     final_info = f.read()

        # # 初始化 white_list 为一个空集合
        # white_list = set()

        # 尝试读取白名单文件
        try:
            with open(f'materials/white_list_{industry_name}.txt', 'r', encoding='utf-8') as f:
                white_list = set(line.strip() for line in f.readlines())
        except FileNotFoundError:
            log_message(user_id, f"文件 materials/white_list_{industry_name}.txt 不存在。", log_type="WARNING")
            await send_log(f"警告：未找到白名单文件 materials/white_list_{industry_name}.txt")

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
                await send_log(f"错误：解析失败，正在尝试第 {attempts} 次...")
                if attempts >= max_attempts:
                    log_message(user_id, "达到最大尝试次数，退出循环。", log_type="ERROR")
                    await send_log("错误：达到最大尝试次数，退出循环。")
                    break
                continue

            relations = triples_raw_dict['relations']
            nodes = triples_raw_dict['nodes']

            nodes_set = set(nodes)
            try:
                nodes_set.update(white_list)
            except Exception as e:
                log_message(user_id, f"更新节点时出错: {e}", log_type="ERROR")
                await send_log(f"错误：更新节点时出错: {e}")
                continue

            nodes = list(nodes_set)

            relations_str = '\n'.join(relations)
            nodes_str = '\n'.join(nodes)

            with open(f'resultTxt/{user_folder}/nodes_{industry_name}.txt', 'w', encoding='utf-8') as f:
                f.write(nodes_str)

            with open(f'resultTxt/{user_folder}/relations_{industry_name}.txt', 'w', encoding='utf-8') as f:
                f.write(relations_str)

            await send_log("任务完成，产业链知识已生成。")
            break

    except Exception as e:
        log_message(user_id, f"处理 {industry_name} 时出错: {e}", log_type="ERROR")
        if websocket: 
            await websocket.send_text(f"错误：处理 {industry_name} 时出错: {e}")
    # finally:
    #     if not websocket.closed:  # 再次检查 WebSocket 是否已关闭
    #         await websocket.close()  # 确保 WebSocket 在最后关闭

@app.websocket('/generate_industry_chain')
async def generate_industry_chain(websocket: WebSocket):
    #try:
    await websocket.accept()

    # 启动心跳任务
    heartbeat_task = asyncio.create_task(send_heartbeat(websocket))
    data = await websocket.receive_json()
    user_id = data.get('user_id')
    industry_name = data.get('industry_name')

    if not user_id or not industry_name:
        await websocket.send_text("Error: Missing user_id or industry_name")
        return

    log_message(user_id, f"收到请求，开始处理 {industry_name}")
    await process_industry(industry_name, user_id, websocket)
    heartbeat_task.cancel()

    # except WebSocketDisconnect:
    #     log_message(user_id, f"WebSocket disconnected by client", log_type="WARNING")
    # except Exception as e:
    #     log_message(user_id, f"Error in generate_industry_chain: {e}", log_type="ERROR")
    #     await websocket.send_text(f"Error: {e}")
    # finally:
    #     # 确保心跳任务停止
    #     heartbeat_task.cancel()
    #     try:
    #         await heartbeat_task
    #     except asyncio.CancelledError:
    #         pass  # 捕获取消任务的错误，防止异常打印

# 这个是新增的代码，定时发送一个心跳，确保websocket一直有信息在传递着
async def send_heartbeat(websocket: WebSocket):
    """定期发送心跳包，防止 WebSocket 断开""" 
    # try:
    while True:
        await websocket.send_text("heartbeat")
        await asyncio.sleep(5)  # 每 10 秒发送一次
    # except WebSocketDisconnect:
    #     print("WebSocket 断开")
    # except Exception as e:
    #     print(f"心跳任务错误: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=40000, ws_max_size=1024 * 1024 * 10, ws_ping_interval=10, ws_ping_timeout=300)
