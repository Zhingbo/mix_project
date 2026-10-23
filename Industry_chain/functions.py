import requests 
from bs4 import BeautifulSoup
from PIL import Image
from io import BytesIO
from paddleocr import PaddleOCR as ocr
import numpy as np


# ocr = PaddleOCR(use_angle_cls=True, lang='ch')  # 使用英文识别，可以根据需要选择其他语言
   

def get_html_content(url):
    # 发送HTTP请求获取网页内容
    try:
        response = requests.get(url)
        response.encoding = 'utf-8'  # 根据网页的编码设置编码，这里假设为utf-8

        # 使用BeautifulSoup解析HTML
        soup = BeautifulSoup(response.text, 'html.parser')

        # 查找所有的<p>标签
        paragraphs = soup.find_all('p')
        images = soup.find_all('img')
        return paragraphs,images
    except:
        return None

def get_image_content(imageUrl):
    try:
        response = requests.get(imageUrl)
        img = Image.open(BytesIO(response.content))
        img = np.array(img)
        height, width, channels = img.shape
        if(height>=200 and width>=600):
            result = ocr.ocr(img, cls=True)
            return result
        else:
            print("图片太小，不抽取文字")
            return None

    except:
        return None
