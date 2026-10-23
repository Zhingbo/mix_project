import requests
import json
import pymysql
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from openai import OpenAI
import openpyxl
import asyncio
from PIL import Image
from io import BytesIO
from paddleocr import PaddleOCR
from pyppeteer import launch
from bs4 import BeautifulSoup
import re
import time
import requests
import pdfplumber
from docx2txt import process
import random
import os
from oletools.olevba import VBA_Parser
import pandas as pd
import numpy as np
from zhipuai import ZhipuAI

def get_base_url(url):
    if "?" in url:
        return url.split("?")[0]
    return url


def get_domain(url):
    parts = url.split("//")
    if len(parts) > 1:
        domain_parts = parts[1].split("/")
        return f"{parts[0]}//{domain_parts[0]}"
    return None


def adjust_content_length(content):
    content = re.sub(r'\s+', '', content)
    if len(content) > 100000:
        content = content[:100000]
    return content


# 提取 PDF 文本内容
async def extract_pdf_text(pdf_url):
    try:
        response = requests.get(pdf_url)
        # 生成时间戳和随机数组成的文件名
        timestamp = str(int(time.time()))
        random_part = random.randint(0, 1000)
        filename = f'{timestamp}_{random_part}.pdf'
        temp_file_path = filename
        with open(temp_file_path, 'wb') as file:
            file.write(response.content)
        with pdfplumber.open(temp_file_path) as pdf:
            text_content = ""
            for page in pdf.pages:
                text_content += page.extract_text()

        return adjust_content_length(text_content)
    except Exception as e:
        log_to_file(f"读取 PDF 文件 {pdf_url} 失败：{e}")
        return None
    finally:
        os.remove(temp_file_path)  # 删除临时文件


# 提取DOCX文本内容
async def extract_docx_text(doc_url):
    try:
        response = requests.get(doc_url)
        # 生成时间戳和随机数组成的文件名
        timestamp = str(int(time.time()))
        random_part = random.randint(0, 1000)
        filename = f'{timestamp}_{random_part}.docx'
        temp_file_path = filename
        response = requests.get(doc_url)
        with open(temp_file_path, 'wb') as file:
            file.write(response.content)

        text = process(temp_file_path)
        return adjust_content_length(text)
    except Exception as e:
        log_to_file(f"提取docx {doc_url} 失败：{e}")
        return None
    finally:
        os.remove(temp_file_path)  # 删除临时文件


# 提取excel文本内容
async def extract_excel_text(excel_url):
    try:
        response = requests.get(excel_url)
        # 生成时间戳和随机数组成的文件名
        timestamp = str(int(time.time()))
        random_part = random.randint(0, 1000)
        if excel_url.lower().endswith('.xlsx'):
            filename = f'{timestamp}_{random_part}.xlsx'
        else:
            filename = f'{timestamp}_{random_part}.xls'
        temp_file_path = filename
        with open(temp_file_path, 'wb') as file:
            file.write(response.content)

        df = pd.read_excel(temp_file_path)
        all_columns_data = df.to_dict(orient='list')
        all_columns_data_str = json.dumps(all_columns_data, ensure_ascii=False)
        return adjust_content_length(all_columns_data_str)
    except Exception as e:
        log_to_file(f"提取excel {excel_url} 失败：{e}")
        return None
    finally:
        os.remove(temp_file_path)  # 删除临时文件


# 输出日志
def log_to_file(message):
    # 当前时间
    current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    with open('log.txt', 'a') as file:
        file.write(f"{current_time} :{message}\n")


# 抓取官网
async def scrape_webpage_with_timeout(browser, url):
    # 判断url的后缀，如果是pdf,doc,docx,xlsx就提取文本
    if url.lower().endswith('.pdf'):
        text = await extract_pdf_text(url)
        if len(text) == 0:
            return None
        return {
            "markdown": text,
        }

    if url.lower().endswith('.docx'):
        text = await extract_docx_text(url)
        if len(text) == 0:
            return None
        return {
            "markdown": text,
        }

    if url.lower().endswith('.xlsx') or url.lower().endswith('.xls'):
        text = await extract_excel_text(url)
        if len(text) == 0:
            return None
        return {
            "markdown": text,
        }

    start_time = time.time()
    page = await browser.newPage()
    await page.setUserAgent(
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
    await page.setExtraHTTPHeaders({'Accept-Language': 'en-US,en;q=0.9'})
    try:
        try:
            await page.goto(url, timeout=20000)
        except Exception as e:
            log_to_file(f"Requests 抓取 {url} 失败")
            return None

        title = await page.title()
        meta_tags = await page.evaluate('''() => {
            const title = document.title;
            const keywords = document.querySelector('meta[name="keywords"]')?.getAttribute('content') || '';
            const description = document.querySelector('meta[name="description"]')?.getAttribute('content') || '';
            return { title, keywords, description };
        }''')
        content = await page.content()
        soup = BeautifulSoup(content, 'html.parser')
        text = soup.get_text(separator=' ', strip=True)

        # 如果text为空，返回
        if not text:
            log_to_file(f"页面 {url} 没有文本内容，跳过抓取。")
            return None

        if "404 Not Found" in text or "页面不存在" in text or "HTTP Error 404" in text:
            log_to_file(f"页面 {url} 疑似 404 页面，跳过抓取。")
            return None

        return text
    except Exception as e:
        log_to_file(f"{url}程序执行出现错误: {e}")
    finally:
        await page.close()


async def scrape_and_update_batch(url):
    # 创建一个浏览器实例，在整个批次处理中复用
    browser = await launch(args=['--no-sandbox', '--disable-setuid-sandbox'])
    res = None
    try:
        try:
            # 调用 scrape_webpage_with_timeout 函数
            text = await scrape_webpage_with_timeout(browser, url)
            print('网页内容', text[:300])

            if text:
                res = text
            else:
                log_to_file(f"无法获取 {url} 的文本内容。")
        except Exception as e:
            log_to_file(f"{url}程序执行出现错误: {e}")
        # 批次处理完成后关闭浏览器
        await browser.close()
    except Exception as e:
        if browser:
            await browser.close()
        log_to_file(f"抓取和更新过程中出现错误: {e}")
    return res

def fetch_chat_completion(content, industry_name):
    client = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com/beta")

    prompts = """
        你是一个产业链分析专家,也是一个构建产业链知识图谱的专家。请从这些搜索结果中找出与%s产业链相关的信息，并做如下处理：
        识别重复或相似的内容，并决定哪些内容应该合并。资料中的内容可能在格式或内容上略有不同，但基本上指的是同一件事。
        使用你的分析技能来确定重复或者相似的内容并将他们整合为一种表达方式。
        另外，资料中的内容可能含有与构建%s产业链知识图谱无关的内容，你应该将这些内容剔除掉。

        举例说明，假如文章中提到："眼镜行业的产业链上游主要包括原材料的生产和供应，如玻璃、树脂、塑料橡胶、金属材料和包装材料。",
        文章中还提到："眼镜行业的产业链上游包括原材料生产：包括镜片材料（如树脂、玻璃、水晶石、塑料等）和镜架材料（如板材、塑料、TR、纯钛、钛合金、其他金属架、其他合金架、硅胶、玳瑁壳、贵金属镜架等）。"。
        我们可以看到，以上内容中说的都是原材料生产这个事，并且有重复信息，所以我们需要将他们的内容合并在一起。

        再举例说明，假如文章中提到："湿法隔膜的均价为1.35元/平方米，干法隔膜的均价为0.95元/平方米"。
        我们可以看到此内容与构建产业链知识图谱无关，那么我们需要将这部分信息剔除掉。

        最后，请返回按照上述要求处理后的结果。
        """
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": prompts % (industry_name,industry_name)},
            {"role": "user", "content": content},
        ],
        stream=False,
        max_tokens=8000
    )

    return response.choices[0].message.content

def google_search(industry_name):
    url = "https://google-search74.p.rapidapi.com/"
    headers = {
        "x-rapidapi-key": os.getenv("RAPIDAPI_KEY_B"),
        "x-rapidapi-host": "google-search74.p.rapidapi.com"
    }
    querystring = {"query": industry_name + "的产业链相关信息", "limit": "5", "related_keywords": "true"}
    try:
        response = requests.get(url, headers=headers, params=querystring)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error during requests to {url}: {e}")
        return None

def crawl_data(industry_name):
    result = []

    file_path = 'materials/产业链数据源.xlsx'
    workbook = openpyxl.load_workbook(file_path)
    worksheet_name = f'materials/{industry_name}资料'

    # 检查工作表是否存在
    if worksheet_name in workbook.sheetnames:
        worksheet = workbook[worksheet_name]
        # 获取工作表的最大行数
        nrows = worksheet.max_row
        print(nrows)

        for idx in range(2, nrows + 1):
            url_link = worksheet.cell(idx, 2).value
            if url_link is not None:
                print(f"抓取网页: {url_link}")
                text = asyncio.run(scrape_and_update_batch(url_link))
                if not text:
                    text = "无内容"
                webinfo_list = fetch_chat_completion(text, industry_name)
                print(webinfo_list)
                if webinfo_list:  # 确保webinfo_list不为空
                    result.append(webinfo_list) 
                    print(result)   
        return result                
    
    return []

def crawl_data_org(industry_name):
    result = []

    deepseek_info = str(google_search(industry_name))
    print(deepseek_info)
    if deepseek_info != 'None':
        webinfo_list_2 = []
        for idx, info in enumerate(eval(deepseek_info)['results']):    # 网页所有文本提取的结果
            url = info['url']
            print('抓取第%s个网页' % idx, url)
            text = asyncio.run(scrape_and_update_batch(url))
            if not text:
                text = str(info)
            webinfo_list_2=(fetch_chat_completion(text, industry_name))
            print(webinfo_list_2)
            if webinfo_list_2:  # 确保webinfo_list_2不为空
                result.append(webinfo_list_2)  
                print(result)               
            return webinfo_list_2
    return []       
