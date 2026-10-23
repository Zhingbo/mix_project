from fastapi import FastAPI, Request
from sse_starlette.sse import EventSourceResponse
import asyncio
import uvicorn
import os
import time
from datetime import datetime
import json
import yaml
from multiprocessing import Pool
from openai import OpenAI
import aiohttp
import re
import openpyxl
import pdfplumber
import io

# 初始化 FastAPI 应用
app = FastAPI()

# 日志记录函数
def log_message(user_id, message, log_type="INFO"):
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
with open("settings_show.yaml", "r") as file:
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

# Crawler 类
class Crawler:
    def __init__(self, url, headers, given_url):
        self.url = url
        self.headers = headers
        self.given_url = given_url
        self.content = ''

    async def get_web_content(self, user_id: str, send_message):
        url = f'{self.url}{self.given_url}'
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers) as response:
                    response.raise_for_status()
                    self.content = await response.read()  # 读取二进制内容
                    log_message(user_id, f"成功获取网页内容: {url}", log_type="INFO")
                    await send_message(f"成功获取网页内容: {url}", "Searching")
                    return f"成功获取网页内容: {url}"
        except aiohttp.ClientError as e:
            log_message(user_id, f"获取网页内容失败: {url}, 错误: {e}", log_type="ERROR")
            self.content = ''
            await send_message(f"获取网页内容失败: {url}, 错误: {e}", "Error")
            return f"获取网页内容失败: {url}, 错误: {e}"

    def extract_image_urls(self):
        if self.content == "":
            print("请先运行get_web_content函数，或者抓取出错")
            return []
        else:
            image_urls = re.findall(r'(https?://[^\s]+(?:\.(?:jpg|jpeg|png|gif|bmp)))', self.content)
            print(image_urls)
            return image_urls

    @staticmethod
    async def crawl_data(industry_name: str, file_path: str, user_id: str, send_message):
        try:
            workbook = openpyxl.load_workbook(file_path)
            worksheet_name = f'materials/{industry_name}资料'
            total_text = ''
            if worksheet_name in workbook.sheetnames:
                worksheet = workbook[worksheet_name]
                nrows = worksheet.max_row
                for idx in range(2, nrows + 1):
                    url_link = worksheet.cell(idx, 2).value
                    if url_link is not None:
                        log_message(user_id, f"开始抓取网页: {url_link}", log_type="INFO")
                        await send_message(f"开始抓取网页: {url_link}", "Searching")
                        try:
                            text = await Crawler.crawl_url_data(url_link, user_id, send_message)
                            if not text:
                                text = "无内容"
                            total_text = total_text + '\n' + text
                        except Exception as e:
                            log_message(user_id, f"抓取网页时出错: {url_link}, 错误: {e}", log_type="ERROR")
                            await send_message(f"抓取网页时出错: {url_link}, 错误: {e}", "Error")
            log_message(user_id, "辅助数据源抓取完成", log_type="INFO")
            await send_message("辅助数据源抓取完成", "Searching")
            return total_text
        except Exception as e:
            log_message(user_id, f"读取Excel文件时出错: {e}", log_type="ERROR")
            await send_message(f"读取Excel文件时出错: {e}", "Error")
            return f"读取Excel文件时出错: {e}"

    @staticmethod
    async def crawl_url_data(url: str, user_id: str, send_message):
        try:
            text = await Crawler.scrape_and_update_batch(url, user_id, send_message)
            return text
        except Exception as e:
            log_message(user_id, f"抓取网页数据时出错: {url}, 错误: {e}", log_type="ERROR")
            await send_message(f"抓取网页数据时出错: {url}, 错误: {e}", "Error")
            return f"抓取网页数据时出错: {url}, 错误: {e}"

    @staticmethod
    async def scrape_and_update_batch(url: str, user_id: str, send_message):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    response.raise_for_status()
                    content = await response.read()  # 读取二进制内容
                    log_message(user_id, f"成功抓取网页内容: {url}", log_type="INFO")
                    await send_message(f"成功抓取网页内容: {url}", "Searching")
                    if url.endswith('.pdf'):
                        return await Crawler.extract_text_from_pdf(content, user_id)
                    else:
                        return content.decode('utf-8')  # 尝试解码为文本
        except aiohttp.ClientError as e:
            log_message(user_id, f"抓取网页时出错: {url}, 错误: {e}", log_type="ERROR")
            await send_message(f"抓取网页时出错: {url}, 错误: {e}", "Error")
            return f"抓取网页时出错: {url}, 错误: {e}"

    @staticmethod
    async def extract_text_from_pdf(pdf_content, user_id):
        try:
            with io.BytesIO(pdf_content) as pdf_file:
                # 使用 pdfplumber 解析PDF
                with pdfplumber.open(pdf_file) as pdf:
                    text = []
                    for page in pdf.pages:
                        text.append(page.extract_text())
                    return '\n'.join(text)
        except Exception as e:
            log_message(user_id, f"解析PDF文件时出错: {e}", log_type="ERROR")
            return f"解析PDF文件时出错: {e}"

# GoogleSearcher 类
class GoogleSearcher:
    def __init__(self, url, headers, industry_name):
        self.url = url
        self.headers = headers
        self.industry_name = industry_name

    async def google_search(self, limit=5, isNode=False, node="", user_id=None, send_message=None, custom_urls=None):
        # 如果客户输入的url不为空
        if custom_urls:
            # 先优先搜索客户给的url链接
            custom_query_part = " OR ".join([f"site:{url}" for url in custom_urls])
            query = f"{self.industry_name}相关的{node}产业链信息 {custom_query_part}" if isNode else f"{self.industry_name}的产业链信息 {custom_query_part}"
            if send_message:
                await send_message(f"正在搜索：{query}", "Searching")
            response = await self._make_request({"query": query, "limit": limit, "related_keywords": "false"}, user_id, send_message)
            if response is not None:
                links = response.get("links", [])
                if len(links) >= 3:
                    parsed_data = await self._parse_links(links, send_message)
                    if parsed_data:
                        return parsed_data
                # 如果链接数量不满足3个则再优先用site:qianzhan.com OR site:zhihu.com OR site:askci.com这三个随机补齐
                else:
                    default_sites = ["qianzhan.com", "zhihu.com", "askci.com"]
                    remaining_sites = [site for site in default_sites if site not in custom_urls]
                    if remaining_sites:
                        additional_query_part = " OR ".join([f"site:{site}" for site in remaining_sites])
                        query += f" OR {additional_query_part}"
                        if send_message:
                            await send_message(f"正在搜索：{query}", "Searching")
                        response = await self._make_request({"query": query, "limit": limit, "related_keywords": "false"}, user_id, send_message)
                        if response is not None:
                            links = response.get("links", [])
                            parsed_data = await self._parse_links(links, send_message)
                            if parsed_data:
                                return parsed_data
        # 如果客户没给任何url则优先用site:qianzhan.com OR site:zhihu.com OR site:askci.com这三个
        else:
            default_sites = ["qianzhan.com", "zhihu.com", "askci.com"]
            query = f"{self.industry_name}相关的{node}产业链信息 site:{' OR site:'.join(default_sites)}" if isNode else f"{self.industry_name}的产业链信息 site:{' OR site:'.join(default_sites)}"
            if send_message:
                await send_message(f"正在搜索：{query}", "Searching")
            response = await self._make_request({"query": query, "limit": limit, "related_keywords": "false"}, user_id, send_message)
            if response is not None:
                links = response.get("links", [])
                parsed_data = await self._parse_links(links, send_message)
                if parsed_data:
                    return parsed_data
        # 如果搜索不到再进行普通搜索就是不带site限制的
        if send_message:
            await send_message("特定网站未搜索到相关内容，尝试普通搜索", "Searching")
        if isNode:
            general_query = {"query": f"{self.industry_name}相关的{node}产业链信息", "limit": limit, "related_keywords": "false"}
            if send_message:
                await send_message(f"正在搜索：{general_query['query']}", "Searching")
        else:
            general_query = {"query": f"{self.industry_name}的产业链信息", "limit": limit, "related_keywords": "false"}
            if send_message:
                await send_message(f"正在搜索：{general_query['query']}", "Searching")
        return await self._make_request(general_query, user_id, send_message)

    async def _make_request(self, querystring, user_id, send_message=None, retries=3, delay=2):
        for attempt in range(retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(self.url, headers=self.headers, params=querystring, timeout=10) as response:
                        response.raise_for_status()
                        data = await response.json()
                        if data.get("error"):
                            if send_message:
                                await send_message(f"Error in response: {data['error']}", "Error")
                            return None
                        return data
            except aiohttp.ClientResponseError as e:
                if e.status == 403:
                    error_message = (
                        f"尝试访问 {self.url} 时遇到 403 Forbidden 错误。这可能是由于以下原因之一：\n"
                        "1. API 密钥无效或权限不足。\n"
                        "2. 链接格式问题，某些自定义 URL 可能包含特殊字符。\n"
                        "3. 网络问题，导致请求无法正常到达服务器。\n"
                        "请检查您的 API 密钥和自定义 URL 的合法性，适当重试。如果不需要这些链接的内容，可以继续其他操作。"
                    )
                    if send_message:
                        await send_message(error_message, "Error")
                    log_message(user_id, error_message, log_type="ERROR")
                elif e.status == 429:
                    error_message = (
                        f"尝试访问 {self.url} 时遇到 429 Too Many Requests 错误。这表示您达到了 API 提供商设定的请求频率限制。\n"
                        "请适当减少请求频率，稍后再试。"
                    )
                    if send_message:
                        await send_message(error_message, "Error")
                    log_message(user_id, error_message, log_type="ERROR")
                    await asyncio.sleep(10)  # 增加延迟，等待10秒后再试
                else:
                    if send_message:
                        await send_message(f"Attempt {attempt + 1}/{retries} failed with status {e.status}: {e}", "Error")
            except aiohttp.ClientError as e:
                if send_message:
                    await send_message(f"Attempt {attempt + 1}/{retries} failed: {e}", "Error")
            await asyncio.sleep(delay)
        if send_message:
            await send_message("All attempts failed.", "Error")
        return None

    async def _parse_links(self, links, send_message=None):
        parsed_data = []
        async with aiohttp.ClientSession() as session:  
            for link in links:
                try:
                    if send_message:
                        await send_message(f"尝试解析链接：{link}", "Searching")
                    async with session.get(link) as response:
                        response.raise_for_status()
                        content = await response.text()  
                        parsed_data.append(f"解析成功：{link} - {content[:50]}...")  
                except Exception as e:
                    if send_message:
                        await send_message(f"解析链接 {link} 时失败：{e}", "Error")
        if parsed_data:
            return parsed_data
        return None

# 处理行业数据
async def process_industry_data(clean_info_prompts, raw_content, user_id, send_message):
    try:
        # 如果输入内容过长，进行截断
        max_length = 65536
        if len(raw_content) > max_length:
            raw_content = raw_content[:max_length]
            log_message(user_id, "输入内容过长，已截断", log_type="WARNING")

        # 构造消息
        messages = [
            {"role": "system", "content": clean_info_prompts},
            {"role": "user", "content": raw_content}
        ]
        # 异步调用火山引擎模型
        response = client.chat.completions.create(
            model="ep-20250217153421-8lrxj",
            messages=messages,
            temperature=0.6,
            response_format={"type": "json_object"}
        )
        # 获取模型的输出内容和思维链内容
        reasoning_content = response.choices[0].message.reasoning_content
        content = response.choices[0].message.content

        # 记录思维链内容到日志
        log_message(user_id, f"Reasoning Content: {reasoning_content}", log_type="DEBUG")
        # 将日志信息发送给用户
        await send_message(f"Reasoning Content: {reasoning_content}", "Reasoning")
        return content
    except Exception as e:
        log_message(user_id, f"Error in process_industry_data: {e}", log_type="ERROR")
        # 将错误信息发送给用户
        await send_message(f"Error in process_industry_data: {e}", "Error")
        return None

# 工具函数：搜索行业信息
async def tool_search(industry_name, custom_urls=None, isNode=False, node="", isAux=True, user_id=None, send_message=None):
    await send_message(f"用户 {user_id} 开始搜索产业链 {industry_name}", "Searching")
    try:
        clean_prompts = clean_node_info_prompts.format(industry=industry_name, node=node) if isNode else clean_info_prompts.format(industry=industry_name)
        google_searcher = GoogleSearcher(google_api_url, headers, industry_name)
        limit = 2 if isNode else 3
        try:
            raw_content = await google_searcher.google_search(limit=limit, isNode=isNode, node=node, custom_urls=custom_urls, user_id=user_id, send_message=send_message)
        except Exception as e:
            log_message(user_id, f"Error in google_search: {e}", log_type="ERROR")
            return '无内容'
        urls = []
        querys = ""
        if raw_content is not None:
            urls = [r['url'] for r in raw_content['results']]
            querys = raw_content['search_term']
            log_message(user_id, f"Search query: {querys}")
            if send_message:
                await send_message(f"Search query: {querys}", "Searching")                
            log_message(user_id, f"URLs: {urls}")
            if send_message:
                await send_message(f"URLs: {urls}", "Searching")                 

        url_file_path = f"materials/url_list_{industry_name}.txt"
        with open(url_file_path, 'a') as file:
            file.write(querys + '\n')
            for url in urls:
                file.write(url + '\n')
            file.write('\n')
        log_message(user_id, "数据源链接url已存入txt文件")

        total_info = []
        for url in urls:
            result = await Crawler.crawl_url_data(url, user_id, send_message)
            if result is not None and result != '无内容':
                total_info.append(str(result))
        if not total_info:
            return '无内容'
        web_content = '\n'.join(total_info)
        html_knowledge = await process_industry_data(clean_prompts, web_content, user_id, send_message)

        if isAux:
            try:
                aux_content = await Crawler.crawl_data(industry_name, data_source_excel, user_id, send_message)
                aux_knowledge =await process_industry_data(clean_prompts, aux_content, user_id, send_message)
                full_knowledge = (html_knowledge or "") + '\n' + (aux_knowledge or "")
                total_knowledge =await process_industry_data(clean_prompts, full_knowledge, user_id, send_message)
            except Exception as e:
                log_message(user_id, f"Error in auxiliary data processing: {e}", log_type="ERROR")
                return '无内容'
        else:
            total_knowledge = html_knowledge
        # 发送完成消息
        await send_message(f"用户 {user_id} 搜索产业链 {industry_name} 完成", "Searching")   
        return total_knowledge
        
    except BrokenPipeError:
        log_message(user_id, "BrokenPipeError occurred in tool_search", log_type="ERROR")
        await send_message(f"用户 {user_id} 搜索产业链 {industry_name} 时发生 BrokenPipeError", "Error")        
        return '无内容'

# 工具函数：总搜索
async def tool_total_search(industry_name, custom_urls=None, user_id=None, send_message=None):
    center_node_info = await tool_search(industry_name, custom_urls=custom_urls,user_id=user_id, send_message=send_message)
    log_message(user_id, f"搜索结果为: {center_node_info}")
    if center_node_info in ['无内容', '']:
        log_message(user_id, "未获取到有效内容，调用普通搜索逻辑")
        center_node_info = await tool_search(industry_name,custom_urls=custom_urls, isNode=False, user_id=user_id, send_message=send_message)

    nodes = await process_industry_data(get_entity_prompts.format(industry=industry_name), center_node_info, user_id, send_message)
    log_message(user_id, f"节点有: {nodes}")
    if send_message:
        await send_message(f"节点有: {nodes}", "Result")      
    while True:
        try:
            nodes = json.loads(nodes.replace("```", "").replace("json", ""))
        except Exception as e:
            log_message(user_id, f"nodes解析失败，重新尝试: {e}", log_type="ERROR")
            nodes = await process_industry_data(get_entity_prompts.format(industry=industry_name), center_node_info, user_id, send_message)
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
        result = await tool_search(industry_name,custom_urls=custom_urls, isNode=True, node=node, isAux=False, user_id=user_id, send_message=send_message)
        if result is not None and result != '无内容':
            total_info.append(result)

    total_info = '\n'.join(total_info)

    final = f'# 1 {industry_name}整体产业链知识\n{center_node_info}\n' + f'# 2 有关{industry_name}中其他节点的产业链知识\n{total_info}'
    return final, nodes

# 清理和解析三元组
async def clean_and_parse(triples_raw, user_id=None, send_message=None):
    try:
        if triples_raw is None:
            log_message(user_id, "Error: triples_raw is None", log_type="ERROR")
            if send_message:
                await send_message("Error: triples_raw is None", "Error")
            return None
        cleaned_triples_raw = triples_raw.replace("```", "").replace("json", "")
        log_message(user_id, f"清理后的字符串: {cleaned_triples_raw}")
        if send_message:
            await send_message(f"清理后的字符串: {cleaned_triples_raw}", "Result")
        return json.loads(cleaned_triples_raw)
    except json.JSONDecodeError as e:
        log_message(user_id, f"解析 triples_raw 时出错: {e}", log_type="ERROR")
        if send_message:
            await send_message(f"解析 triples_raw 时出错: {e}", "Error")
        return None

# 处理行业逻辑
async def process_industry(industry_name, custom_urls=None, user_id=None, send_message=None):
    try:
        await send_message(f"用户 {user_id} 开始处理产业链 {industry_name}", "Start")
        # 获取当前进程的PID
        pid = os.getpid()
        user_folder = f"user_{user_id}_pid_{pid}"
        os.makedirs(f"resultTxt/{user_folder}", exist_ok=True)
        os.makedirs(f"resultImg/{user_folder}", exist_ok=True)

        final_info, nodes = await tool_total_search(industry_name, custom_urls=custom_urls, user_id=user_id, send_message=send_message)

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
            try:
                # 确保等待异步函数的结果
                triples_raw = await process_industry_data(
                    get_triples_prompts.format(industry=industry_name) + "。需要特别注意：不要无限循环输出，不要有重复。",
                    final_info + "。需要特别注意：不要无限循环输出，不要有重复。",
                    user_id,
                    send_message
                )
                if triples_raw is None:
                    raise ValueError("process_industry_data 返回了 None")
                # 清理字符串并尝试解析
                triples_raw_dict = await clean_and_parse(triples_raw, user_id, send_message)
                if triples_raw_dict is None:
                    raise ValueError("clean_and_parse 返回了 None")

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
                
                break  # 如果一切顺利，退出循环
                
            except Exception as e:
                attempts += 1
                log_message(user_id, f"解析失败，第 {attempts} 次尝试: {e}", log_type="ERROR")
                if attempts >= max_attempts:
                    log_message(user_id, "达到最大尝试次数，退出循环。", log_type="ERROR")
                    break

    except Exception as e:
        log_message(user_id, f"处理产业链过程中发生错误: {e}", log_type="ERROR")
        await send_message(f"用户 {user_id} 处理产业链 {industry_name} 时发生错误: {e}", "Error")
        return
    finally:
        # 确保在所有情况下都发送结束消息
        await send_message(f"用户 {user_id} 的产业链处理结束", "End")

# FastAPI 接口
@app.post("/process_industry")
async def process_industry_api(request: Request):
    data = await request.json()
    user_id = data.get("user_id")
    industry_name = data.get("industry_name")
    custom_urls = data.get("custom_urls")  # 获取自定义URL
    if not user_id or not industry_name:
        return {"error": "Missing user_id or industry_name"}

    async def event_generator():
        queue = asyncio.Queue()

        async def send_message(message, message_type):
            await queue.put(json.dumps({"type": message_type, "content": message}))

        async def worker():
            try:
                await process_industry(industry_name, custom_urls=custom_urls, user_id=user_id, send_message=send_message)
            finally:
                await queue.put(json.dumps({"type": "End", "content": f"用户 {user_id} 的产业链处理结束"}))  # 添加结束标识

        asyncio.create_task(worker())

        while True:
            message = await queue.get()
            if message is None:
                break
            # 解析 JSON 格式的消息
            message_data = json.loads(message)
            message_type = message_data["type"]
            message_content = message_data["content"]
            # 生成符合 SSE 格式的响应
            yield f"type: {message_type}\ndata: {message_content}\n\n"

    return EventSourceResponse(event_generator())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)