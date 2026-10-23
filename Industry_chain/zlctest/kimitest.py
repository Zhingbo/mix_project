from typing import *
import os
import json
from openai import OpenAI
from openai.types.chat.chat_completion import Choice

api_key = os.getenv('MOONSHOT_API_KEY')
 
client = OpenAI(
    base_url="https://api.moonshot.cn/v1",
    api_key=api_key
)
 
 
# search 工具的具体实现，这里我们只需要返回参数即可
def search_impl(arguments: Dict[str, Any]) -> Any:
    """
    在使用 Moonshot AI 提供的 search 工具的场合，只需要原封不动返回 arguments 即可，
    不需要额外的处理逻辑。
 
    但如果你想使用其他模型，并保留联网搜索的功能，那你只需要修改这里的实现（例如调用搜索
    和获取网页内容等），函数签名不变，依然是 work 的。
 
    这最大程度保证了兼容性，允许你在不同的模型间切换，并且不需要对代码有破坏性的修改。
    """
    return arguments
 
 
def chat(messages) -> Choice:
    completion = client.chat.completions.create(
        model="moonshot-v1-128k",
        messages=messages,
        temperature=0.3,
        tools=[
            {
                "type": "builtin_function",  # <-- 使用 builtin_function 声明 $web_search 函数，请在每次请求都完整地带上 tools 声明
                "function": {
                    "name": "$web_search",
                },
            }
        ]
    )
    return completion.choices[0]
 
 
def entity_find():
    messages = [
        {"role": "system", "content": "你是一个产业链分析专家，并且特别擅长从各种网页上搜集查询产业链相关资料。"},
    ]
    
    # 查找实体
    messages.append({
        "role": "user",
        "content": '''请搜索眼镜产业链相关信息，搜索的时候要采用广度优先的策略进行，即先从产业链的整体出发，按照产品类别（如镜架和镜片）进行一级分类，
                      然后进一步分解到原材料级别（如镜架原材料和镜片原材料），最后细化到具体的材料元素（如水晶、树脂），直到最后不能再细分下去才停止搜索。
                      相关资料搜索的越多越详细越好，然后从这些搜索结果中找出与产业链相关的实体，实体越多越好。输出格式示例如下：
                      "眼镜\n镜架\n镜片\n鼻托\n螺丝\n..."
                      注意：
                      1.输出结果严格按照上述格式返回，除了这些实体不要返回任何其他内容，比如："以下是眼镜产业链的相关信息","这些信息涵盖了眼镜产业链"等等，这些总结或者阐述方面的内容都不要返回到结果中。
                      2.输出结果不要返回任何标点符号，比如："-","(",")"等等。
                   '''
    })
 
    finish_reason = None
    while finish_reason is None or finish_reason == "tool_calls":
        choice = chat(messages)
        finish_reason = choice.finish_reason
        if finish_reason == "tool_calls":  
            messages.append(choice.message)  
            for tool_call in choice.message.tool_calls:  
                tool_call_name = tool_call.function.name
                tool_call_arguments = json.loads(tool_call.function.arguments)  
                if tool_call_name == "$web_search":
                    tool_result = search_impl(tool_call_arguments)
                else:
                    tool_result = f"Error: unable to find tool by name '{tool_call_name}'"
  
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call_name,
                    "content": json.dumps(tool_result),  
                })
 
    result1 = choice.message.content
    print(result1)
    with open('chain/entity_info.txt','w',encoding='utf-8') as f:
        f.write(result1)


def entity_search(query):
    messages = [
        {"role": "system", "content": "你是一个产业链分析专家，并且特别擅长从各种网页上搜集查询产业链相关资料。"},
    ]
    
    # 搜索实体相关资料
    messages.append({
        "role": "user",
        "content": f"请搜索和眼镜相关的{query}产业链相关资料，搜索的时候要采用广度优先的策略进行，即先从产业链的整体出发，按照产品类别（如镜架和镜片）进行一级分类，然后进一步分解到原材料级别（如镜架原材料和镜片原材料），最后细化到具体的材料元素（如水晶、树脂），直到最后不能再细分下去才停止搜索。相关资料搜索的越多越详细越好，然后根据这些资料请你把他们整合成一篇大文章包含所有的信息。"
    })
 
    finish_reason = None
    while finish_reason is None or finish_reason == "tool_calls":
        choice = chat(messages)
        finish_reason = choice.finish_reason
        if finish_reason == "tool_calls":  
            messages.append(choice.message)  
            for tool_call in choice.message.tool_calls:  
                tool_call_name = tool_call.function.name
                tool_call_arguments = json.loads(tool_call.function.arguments)  
                if tool_call_name == "$web_search":
                    tool_result = search_impl(tool_call_arguments)
                else:
                    tool_result = f"Error: unable to find tool by name '{tool_call_name}'"
  
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call_name,
                    "content": json.dumps(tool_result),  
                })
 
    result2 = choice.message.content
 
if __name__ == '__main__':
    
    entity_find()
    with open('chain/entity_info.txt', 'r', encoding='utf-8') as file:
        content = file.read()

    entities = [node for node in content.split("\n")] 
    print(entities)  
    all_search_results = []

    for entity in entities:
        search_result = entity_search(entity)
        if search_result is not None:  # 确保搜索结果不是None
            all_search_results.append(search_result)
            print(f'{entity}已搜索完成')

    filtered_results = [result for result in all_search_results if result.strip()]  # 过滤掉空白字符串
    s = '\n'.join(filtered_results)
    with open('chain/industry_info.txt', 'w', encoding='utf-8') as f:
        f.write(s)
 
