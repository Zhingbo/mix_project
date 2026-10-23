import os
import json
from openai import OpenAI
from sympy import false
import pandas as pd
import glob
import pymysql

system_prompt = '''下边是产业链名称(chain_name)和该产业链中的节点名称(nodes)，你需要结合产业链对每个节点给出一个简短的定义,然后你还需要利用你的分析技能，分析该产业链中每个节点是否存在瓶颈环节，颈环节指的是在产业链中那些限制或阻碍整个产业链顺畅运作和效率的环节。
如果有瓶颈环节，那么请提供出瓶颈环节的简短定义，国产化现状以及改善建议措施。此外，你还需要利用你的分析技能分析该产业链中每个节点是否存在机会环节，机会环节指的是在产业链中，各个节点存在的潜在商业机会或者增值点。如果存在机会环节，那么请提供出机会环节的简短定义以及潜在机会分析。

结果输出：请返回产业链名称，节点名称，节点定义，瓶颈环节定义，瓶颈环节国产化现状，瓶颈环节建议措施，机会环节定义，机会分析。请以Json的方式返回答案，示例如下:
{
    "产业链名称":"新能源汽车",
    "节点名称":"内饰",
    "节点定义":"内饰包括汽车内部装饰材料和部件，如座椅、仪表盘、门板等。",
    "瓶颈环节定义":"内饰环节的瓶颈可能包括技术限制、材料供应、环保要求、成本控制等方面。这些因素可能限制内饰件的生产效率和质量，影响整车的舒适性、美观性和功能性。",
    "瓶颈环节国产化现状":"目前，国内企业在汽车内饰技术上已达到甚至超越国际水平，特别是在饰面材料如真皮、纺织布、PVC/TPU等高分子复合材料、TPO材料等方面，生产技术相对成熟。然而，新能源汽车对内饰的需求与传统汽车有所不同，更加注重轻量化、环保性和智能化等特点。",
    "瓶颈环节建议措施":"加强新材料、新工艺的研发，以满足新能源汽车轻量化和环保性的需求。",
    "机会环节定义":"内饰环节的机会主要来自于新能源汽车市场的快速增长以及消费者对内饰个性化和定制化需求的增加。",
    "机会分析":"内饰逐渐向“智能座舱”方向演变，液晶仪表盘、大尺寸触摸屏、语音控制、车载联网等智能化功能成为标配，为内饰件行业带来新的增长点。"
}

注意：返回结果中的键一定是"产业链名称"，"节点名称"，"节点定义"，"瓶颈环节定义"，"瓶颈环节国产化现状"，"瓶颈环节建议措施"，"机会环节定义"，"机会分析"，不可以是别的！

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

# 连接数据库
def connect_db():
    return pymysql.connect(host='8.141.23.4', user='remote_user', password=os.getenv('DB_PASSWORD_REMOTE'), db='business_data', charset='utf8mb4')

# 从数据库中读取数据
def read_from_db(chain_name=None):
    conn = connect_db()
    try:
        if chain_name:
            query = 'SELECT * FROM chain_nodes_info_all WHERE chain_name = %s'
            df = pd.read_sql(query, conn, params=(chain_name,))
        else:
            # excluded_chain_names = "('新能源汽车','机器人','半导体')"
            query = f'SELECT DISTINCT chain_name FROM chain_nodes_info_all WHERE bottleneck_definition is null'
            df = pd.read_sql(query, conn)
            return df['chain_name'].tolist()
        return df
    finally:
        conn.close()

# 更新数据库
def update_db(new_df):
    conn = connect_db()
    try:
        for index, row in new_df.iterrows():
            update_sql = """
                UPDATE chain_nodes_info_all
                SET nodes_definition = %s, bottleneck_definition = %s, bottleneck_status = %s,
                    bottleneck_recommend = %s, opportunity_definition = %s, opportunity_analysis = %s
                WHERE chain_name = %s AND nodes = %s
            """
            conn.cursor().execute(update_sql, (
                row['nodes_definition'], row['bottleneck_definition'], row['bottleneck_status'],
                row['bottleneck_recommend'], row['opportunity_definition'], row['opportunity_analysis'],
                row['chain_name'], row['nodes']
            ))
        conn.commit()
    except Exception as e:
        print(f"更新数据库时发生错误: {e}")
    finally:
        conn.close()

if __name__ == '__main__':
    chain_names = read_from_db()

    # 为当前文件创建一个空的DataFrame来存储筛选后的结果
    new_df = pd.DataFrame(columns=['chain_name', 'nodes', 'parent_node', 'nodes_definition','bottleneck_definition','bottleneck_status','bottleneck_recommend','opportunity_definition','opportunity_analysis'])

    for chain_name in chain_names:
        df = read_from_db(chain_name)  # 读取当前产业链的所有节点信息
        temp_df = pd.DataFrame()  # 用于存储当前产业链的结果，每次处理新的产业链时重置
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
                    temp_row = {
                        'chain_name': row['chain_name'],
                        'nodes': row['nodes'],
                        'parent_node': row['parent_node'],
                        'nodes_definition': result_json['节点定义'],
                        'bottleneck_definition': result_json['瓶颈环节定义'],
                        'bottleneck_status': result_json['瓶颈环节国产化现状'],
                        'bottleneck_recommend': result_json['瓶颈环节建议措施'],
                        'opportunity_definition': result_json['机会环节定义'],
                        'opportunity_analysis': result_json['机会分析']
                    }
                    temp_df = pd.concat([temp_df, pd.DataFrame([temp_row])], ignore_index=True)
                except json.JSONDecodeError:
                    print("JSON解析错误")

        # 更新数据库
        update_db(temp_df)
        print(f"处理完产业链：{chain_name}，已更新到数据库")

    print('done')