import openai

client = openai.OpenAI(api_key="your_api_key", base_url="https://api.deepseek.com/beta")

# 定义你的prompts和industry_name
prompts = "给你一组图片转文字的识别结果，请你通过这些信息，将识别结果转成%s产业链相关信息。"
industry_name = "新能源汽车"

# 你的base_info文本
base_info = "这里是你的长文本..."

# DeepSeek的最大上下文长度限制
max_context_length = 128000  # 以字符数计算

# 计算每个请求的最大tokens数，考虑到prompts也会占用一定的长度
prompt_length = len(prompts % industry_name)
max_tokens_per_request = 8192  # DeepSeek Beta版API的max_tokens限制

# 计算每个请求可以包含的base_info的最大字符数
max_base_info_length = max_context_length - prompt_length

# 重叠分段的大小
overlap = 100  # 可以根据需要调整重叠的大小

# 将base_info分割成多个部分，考虑重叠
base_info_parts = []
start = 0
while start < len(base_info):
    end = start + max_base_info_length - overlap if start + max_base_info_length - overlap < len(base_info) else len(base_info)
    base_info_parts.append(base_info[start:end])
    start += max_base_info_length - overlap

# 初始化结果列表
all_responses = []

# 对每个部分分别发送请求
for part in base_info_parts:
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": prompts % industry_name},
            {"role": "user", "content": part},
        ],
        stream=False,
        max_tokens=8192
    )
    # 将每个请求的结果追加到结果列表中
    all_responses.append(response.choices[0].message.content)

# 将所有结果合并成一个字符串
final_response = "\n".join(all_responses)

# 返回最终结果
print(final_response)