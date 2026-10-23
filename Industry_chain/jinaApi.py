'''
    基于https://jina.ai/reader/的爬虫

    api具体说明文档：

    https://s.jina.ai/docs   这个是搜索用额

    https://r.jina.ai/docs#tag/Crawler/paths/~1crawl/post 这个是爬虫



'''
import requests
import os
import re
from PIL import Image
from io import BytesIO
from paddleocr import PaddleOCR
import numpy as np
from openai import OpenAI


# os.environ["http_proxy"] = "http://localhost:0"
# os.environ["https_proxy"] = "http://localhost:0"
api_key = os.getenv('JINA_API_KEY_C')
ocr = PaddleOCR(use_angle_cls=True, lang='ch')  # 使用英文识别，可以根据需要选择其他语言

deepseek_api_key = os.getenv('DEEPSEEK_API_KEY')


import requests

def get_web_content(given_url):
    url = 'https://r.jina.ai/'
    headers = {
        "Authorization": f"Bearer {api_key}"
    }
    data = {
        'url': given_url,
        'withImagesSummary':False,
        'keepImgDataUrl':False,
        'removeSelector':['a'],
        'targetSelector':['p']

    }
    response = requests.post(url, headers=headers,json=data)
    return response.text

def extract_image_urls(text):
    # 正则表达式匹配图片链接
    image_urls = re.findall(r'(https?://[^\s]+(?:\.(?:jpg|jpeg|png|gif|bmp)))', text)
    return image_urls

if __name__ == "__main__":
    url = 'https://s.jina.ai/'
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json"
    }
    payload = {
        'q':'新能源产业链',
        'count':5
    }

    response = requests.post(url, headers=headers,json=payload)
    data = response.json()['data']
    urls = [d['url'] for d in data]
    print('共找到资料',len(urls))

    text = ''

    for url in urls:
        print(url)
        text = text + '\n' + get_web_content(url)
    


    # ## 从text中找到image，然后得到image的文字
    image_urls = extract_image_urls(text)

    # image_urls = ['https://img3.qianzhan.com/news/202012/15/20201215-5e1a56fbb0d8293b.jpg', 'https://img3.qianzhan.com/news/202012/15/20201215-1854c80d7f068f63.jpg', 'https://img3.qianzhan.com/news/202012/15/20201215-70b572df69716f5f.jpg', 'https://img3.qianzhan.com/news/202012/15/20201215-6816958b28f7776e.jpg', 'https://img1.qianzhan.com/2017bg/images/qzjjxr_wx.jpg', 'https://img1.qianzhan.com/2017/images/yjywx2.jpg', 'http://mp.ofweek.com/data/images/qianzhan/2022-07-18/43c17aa87d35771fc8bdbe2df3ab0387.jpg', 'http://mp.ofweek.com/data/images/qianzhan/2022-07-18/6ead4beb249688230e419bf29dfc61a7.jpg', 'http://mp.ofweek.com/data/images/qianzhan/2022-07-18/51e5fe687d4c64d71761dd4b810d0c29.jpg', 'http://mp.ofweek.com/data/images/qianzhan/2022-07-18/c89cfd3972345058a7d5d07e929e7bf9.jpg', 'http://mp.ofweek.com/data/images/qianzhan/2022-07-18/764cd0bad48f2736ad5be0931cd6be54.jpg', 'http://mp.ofweek.com/data/images/qianzhan/2022-07-18/24681005cec40aa2e71da4919fe49a17.jpg', 'http://mp.ofweek.com/data/images/qianzhan/2022-07-18/7eda8e76034c15d89d50e85fcac07410.jpg', 'http://mp.ofweek.com/data/images/qianzhan/2022-07-18/67d8d54281afc2dae41e70de5fc2631b.jpg', 'http://mp.ofweek.com/data/images/qianzhan/2022-07-18/01ad30dd00dcfe6c7ba4ae17625d8e26.jpg', 'http://mp.ofweek.com/data/images/qianzhan/2022-07-18/31ccd110544e9e9934e5ef669685d7aa.jpg', 'http://mp.ofweek.com/data/images/qianzhan/2022-07-18/28d9b7af9eb3b0fd7e842e02d5e615a8.jpg']
    # print(image_urls)
    client = OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com/beta",
    )
    pic_info = []
    for image_url in image_urls:
        response = requests.get(image_url)
        img = Image.open(BytesIO(response.content))
        img = np.array(img)
        result = ocr.ocr(img, cls=True)
        prompts = '''
            给你一组paddleocr的识别结果，前4个元素是该文字出现位置的坐标，最后一个元素为具体文字。请你通过这些信息，将识别结果转成产业链结构。下面开始：
        '''
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {'role': 'system', 'content': prompts},
                {'role': 'user', 'content': str(result)}
            ],
            temperature=1.0
        )
        pic_info.append(response.choices[0].message.content)
    
    pic_info_text = '\n'.join(pic_info)
    text = text + '\n' + pic_info_text

    with open("infomation.md","w",encoding='utf-8') as f:
        f.write(text)
    


    



