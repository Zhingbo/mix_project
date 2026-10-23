import json
from openai import OpenAI
from sympy import false
import pandas as pd
import glob
import os

system_prompt = '''下边是产业链名称(chain_name)和该产业链中的节点名称(nodes)，你需要结合产业链对每个节点给出一个简短的定义。

结果输出：请返回产业链名称，节点名称以及节点定义，请以Json的方式返回答案，示例如下:
{
    "产业链名称":"新能源汽车",
    "节点名称":"内饰",
    "节点定义":"内饰包括汽车内部装饰材料和部件，如座椅、仪表盘、门板等。"
}

'''

def get_abstract(words, system_prompt):
    if words is not None:

        client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com/beta",
        )

        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {'role': 'system', 'content': f'{system_prompt}'},
                {'role': 'user', 'content': f'{words}'}
            ],
            temperature=1.0,
            response_format={"type": "json_object"}
        )

        try:
            return response.choices[0].message.content
        except:
            return None


if __name__ == '__main__':
    file_paths = glob.glob('chain_info/*.xlsx')

    # 创建一个空的DataFrame来存储筛选后的结果，包含所需的列
    new_df = pd.DataFrame(columns=['chain_name', 'nodes','parent_node','nodes_definition'])
    print(new_df)

    for file_path in file_paths:
        df = pd.read_excel(file_path, sheet_name=0)
        print(f"正在处理:{file_path}")
        
        for index, row in df.iterrows():
            # 构建提示词
            words = f"产业链名称：{row['chain_name']}，节点名称：{row['nodes']}"
            print(words)
            
            # 获取大模型的摘要
            abstract = get_abstract(words, system_prompt)
            print(abstract)
            if abstract:
                # 解析JSON格式的摘要
                try:
                    result_json = json.loads(abstract)
                    new_row = {
                        'chain_name': row['chain_name'],
                        'nodes': row['nodes'],
                        'parent_node': row['parent_node'],
                        'nodes_definition': result_json['节点定义']
                    }
                    new_df = pd.concat([new_df, pd.DataFrame([new_row])], ignore_index=True)
                    print(new_df)
                    with pd.ExcelWriter(file_path, mode='a', engine='openpyxl', if_sheet_exists='replace') as writer:
                        new_df.to_excel(writer, sheet_name=f'new_chain_info', index=False)
                        print(f"筛选后的企业名单已保存到 {file_path} 的 'new_chain_info' sheet")
                except json.JSONDecodeError:
                    print("JSON解析错误")

