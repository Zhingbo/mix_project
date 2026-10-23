import os
from paddleocr import PaddleOCR
from openai import OpenAI

# 创建一个 OpenAI 客户端实例
client = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com/beta")

def fetch_chat_completion(content, industry_name):
    prompts = """
        给你一组%s产业链相关图片转文字的识别结果，请你通过这些信息，将识别结果进行概括总结，并去掉重复的内容。
        """
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": prompts % industry_name},
            {"role": "user", "content": content}
        ],
        stream=False,
        max_tokens=8000
    )
    return response.choices[0].message.content

def process_images(industry_name):
    image_folder = f'/data/ASRProject/Industry_chain/pics_{industry_name}'
    ocr = PaddleOCR(use_angle_cls=True)
    pic_info = []
    all_results = []

    if not os.path.exists(image_folder):
        print(f"文件夹 {image_folder} 不存在。")
        return pic_info

    for image_name in os.listdir(image_folder):
        image_path = os.path.join(image_folder, image_name)
        print(image_name)
        result = ocr.ocr(image_path, cls=True)
        # 假设result是一个列表，我们需要将其转换为字符串以便比较
        result_str = str(result)
        if result_str not in all_results:
            all_results.append(result_str)

    # 将all_results转换为一个字符串，以便传递给fetch_chat_completion函数
    pic_info = fetch_chat_completion('\n'.join(all_results), industry_name)
    return pic_info
