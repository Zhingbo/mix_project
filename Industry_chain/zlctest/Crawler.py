'''
    定义一个爬虫类
'''

import requests 
import re
from crawling_new import * 

class Crawler:
    def __init__(self, url, headers,given_url):
        self.url = url
        self.headers = headers
        self.given_url = given_url
        self.content = ''
    def get_web_content(self):
        url = self.url
        headers = self.headers

        url = f'https://r.jina.ai/{self.given_url}'
        # data = {
        #     'url': self.given_url,
        #     'withImagesSummary':False,
        #     'keepImgDataUrl':True
        # }
        try:
            response = requests.get(url, headers=headers)
            self.content = response.text
            print(self.content)
            return self.content
        except:
            self.content = ''
            return self.content
    def extract_image_urls(self):
        if self.content=="":
            print("请先运行get_web_content函数，或者抓取出错")
            return []
        else:
            image_urls = re.findall(r'(https?://[^\s]+(?:\.(?:jpg|jpeg|png|gif|bmp)))', self.content)
            print(image_urls)
            return image_urls
    
    @staticmethod  # 表示下面这个是静态方法
    def crawl_data(industry_name,file_path):
        workbook = openpyxl.load_workbook(file_path)
        worksheet_name = f'materials/{industry_name}资料'
        total_text = ''
        if worksheet_name in workbook.sheetnames:
            worksheet = workbook[worksheet_name]
            # 获取工作表的最大行数
            nrows = worksheet.max_row
            for idx in range(2, nrows + 1):
                url_link = worksheet.cell(idx, 2).value
                if url_link is not None:
                    print(f"抓取网页: {url_link}")
                    text = asyncio.run(scrape_and_update_batch(url_link))
                    if not text:
                        text = "无内容"
                    total_text = total_text + '\n' + text
        print("辅助数据源",total_text)
        return total_text

    @staticmethod 
    def crawl_url_data(url):
        text = asyncio.run(scrape_and_update_batch(url))
        return text