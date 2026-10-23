import asyncio
import aiohttp
import re
import io
import os
import pdfplumber
from datetime import datetime
from bs4 import BeautifulSoup  # 需要安装 BeautifulSoup 库

from utils.logger import get_logger

logger = get_logger(__name__)

# 日志记录函数
def log_message(user_id, message, log_type="INFO"):
    # 格式化日志内容
    log_content = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][{log_type}] {message}\n"
    # 仅打印到控制台
    print(log_content.strip())

# Crawler 类
class Crawler:
    def __init__(self, url, headers, given_url):
        self.url = url
        self.headers = headers
        self.given_url = given_url
        self.content = ''
        self.title = ''
        self.summary = ''

    async def get_web_content(self, user_id: str, send_message):
        url = f'{self.url}{self.given_url}'
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers) as response:
                    response.raise_for_status()
                    self.content = await response.read()  # 读取二进制内容
                    log_message(user_id, f"成功获取网页内容: {url}", log_type="INFO")
                    # 提取标题和摘要
                    self.extract_title_and_summary()
                    # 发送标题和摘要信息
                    await send_message(f"成功获取网页内容: {url}", "2")
                    await send_message(f"文章标题: {self.title}", "5")
                    await send_message(f"文章摘要: {self.summary}", "5")
                    return {
                        "status": "success",
                        "message": f"成功获取网页内容: {url}",
                        "title": self.title,
                        "summary": self.summary
                        # "content": self.content  # 返回网页内容
                    }
        except aiohttp.ClientError as e:
            log_message(user_id, f"获取网页内容失败: {url}, 错误: {e}", log_type="ERROR")
            # self.content = ''
            # await send_message(f"获取网页内容失败: {url}, 错误: {e}", "Error")
            return {
                "status": "error",
                "message": f"获取网页内容失败: {url}, 错误: {e}",
                "title": None,
                "summary": None
            }

    def extract_title_and_summary(self):
        if self.content == "":
            print("请先运行get_web_content函数，或者抓取出错")
            return
        try:
            soup = BeautifulSoup(self.content, 'html.parser')
            # 提取标题
            title_tag = soup.find('title')
            self.title = title_tag.get_text() if title_tag else "未知标题"
            # 提取摘要
            meta_description = soup.find('meta', attrs={'name': 'description'})
            self.summary = meta_description.get('content') if meta_description else "无摘要信息"
        except Exception as e:
            print(f"提取标题和摘要时出错: {e}")

    def extract_image_urls(self):
        if self.content == "":
            print("请先运行get_web_content函数，或者抓取出错")
            return []
        else:
            image_urls = re.findall(r'(https?://[^\s]+(?:\.(?:jpg|jpeg|png|gif|bmp)))', self.content)
            print(image_urls)
            return image_urls

    @staticmethod
    async def crawl_url_data(url: str, user_id: str, send_message):
        try:
            result = await Crawler.scrape_and_update_batch(url, user_id, send_message)
            return result
        except Exception as e:
            log_message(user_id, f"抓取网页数据时出错: {url}, 错误: {e}", log_type="ERROR")
            return {"status": "error", "message": f"抓取网页数据时出错: {url}, 错误: {e}"}

    @staticmethod
    async def scrape_and_update_batch(url: str, user_id: str, send_message):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    response.raise_for_status()
                    content = await response.read()  # 读取二进制内容
                    log_message(user_id, f"成功抓取网页内容: {url}", log_type="INFO")
                    
                    if url.endswith('.pdf'):
                        text = await Crawler.extract_text_from_pdf(content, user_id)
                        # 对于 PDF 文件，发送默认的标题和摘要
                        #await send_message(f"文章标题: PDF 文件,url:{url}", "5")
                        #await send_message("文章摘要: PDF 文件内容", "5")
                        return {
                            "status": "success",
                            "content": text,
                            "title": "PDF 文件",
                            "summary": "PDF 文件内容"
                        }
                    else:
                        # 解码为文本并提取标题和摘要
                        html_content = content.decode('utf-8')
                        soup = BeautifulSoup(html_content, 'html.parser')
                        title_tag = soup.find('title')
                        title = title_tag.get_text() if title_tag else "未知标题"
                        meta_description = soup.find('meta', attrs={'name': 'description'})
                        summary = meta_description.get('content') if meta_description else "无摘要信息"
                        
                        # 发送标题和摘要到用户端
                        #await send_message(f"文章标题: {title},url:{url}", "5")
                        #await send_message(f"文章摘要: {summary}", "5")
                        
                        return {
                            "status": "success",
                            "content": html_content,
                            "title": title,
                            "summary": summary
                        }
        except aiohttp.ClientError as e:
            log_message(user_id, f"抓取网页时出错: {url}, 错误: {e}", log_type="ERROR")
            # await send_message(f"抓取网页时出错: {url}, 错误: {e}", "Error")
            return {"status": "error", "message": f"抓取网页时出错: {url}, 错误: {e}"}

    @staticmethod
    async def extract_text_from_pdf(pdf_content, user_id):
        try:
            with io.BytesIO(pdf_content) as pdf_file:
                with pdfplumber.open(pdf_file) as pdf:
                    text = []
                    for page in pdf.pages:
                        text.append(page.extract_text())
                    return '\n'.join(text)
        except Exception as e:
            log_message(user_id, f"解析PDF文件时出错: {e}", log_type="ERROR")
            return f"解析PDF文件时出错: {e}"