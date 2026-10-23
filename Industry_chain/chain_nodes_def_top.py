"""
第三步，主要是
这个脚本的主要功能是使用大模型为产业链节点自动生成定义。                                                                                               
                                                                                                                                                       
  核心流程：                                                                                                                                             
   
  1. 查询数据（第 94 行）                                                                                                                                
    - 从 chain_needcomp0421 表中查询 chain_name = '氢能产业' 的所有节点                                                                                
  2. 调用大模型生成定义（第 33-66 行）                                                                                                                   
    - 使用 DeepSeek API（deepseek-v4-pro）
    - 输入：产业链名称 + 节点名称                                                                                                                        
    - 输出：JSON 格式的节点定义                                                                                                                          
  3. 更新数据库（第 69-84 行）                                                                                                                           
    - 将生成的 nodes_definition 写回数据库对应记录                                                                                                       
                                                                                                                                                         
  Prompt 示例：                                                                                                                                          
  产业链名称：氢能产业，节点名称：燃料电池                                                                                                               
  模型返回：                                                                                                                                             
  {                                                                                                                                                      
      "产业链名称": "氢能产业",                                                                                                                          
      "节点名称": "燃料电池",                                                                                                                            
      "节点定义": "燃料电池是一种将氢气与氧气反应产生电能的电化学装置..."                                                                                
  }                                                                                                                                                      
                                                                                                                                                         
  作用： 为"氢能产业"的 137 个节点自动补全 nodes_definition 字段，不用人工一个个写。

"""
import os

import json
import pandas as pd
import pymysql
from openai import OpenAI

# 数据库连接配置
host = "8.141.5.67"
user = "root"
password = os.getenv("DB_PASSWORD")
database = "business_data"
port = 3306

# 系统提示
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
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
        )

        response = client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=[
                {'role': 'system', 'content': f'{system_prompt}'},
                {'role': 'user', 'content': f'{words}'}
            ],
            temperature=0.6,
            response_format={"type": "json_object"}
        )            

        #     model="deepseek-chat",
        #     messages=[
        #         {'role': 'system', 'content': f'{system_prompt}'},
        #         {'role': 'user', 'content': f'{words}'}
        #     ],
        #     temperature=1.0,
        #     response_format={"type": "json_object"}
        # )

        try:
            return response.choices[0].message.content
        except:
            return None


def update_nodes_definition(chain_name, nodes, nodes_definition):
    # 连接数据库
    connection = pymysql.connect(host=host, user=user, password=password, database=database, port=port)
    cursor = connection.cursor()
    
    try:
        # 构造SQL语句更新节点定义
        sql = "UPDATE chain_needcomp0421 SET nodes_definition = %s WHERE chain_name = %s AND nodes = %s"
        cursor.execute(sql, (nodes_definition, chain_name, nodes))
        connection.commit()
        print(f"更新成功：{chain_name} - {nodes}")
    except Exception as e:
        print(f"更新失败：{e}")
    finally:
        cursor.close()
        connection.close()


if __name__ == '__main__':
    # 连接数据库
    connection = pymysql.connect(host=host, user=user, password=password, database=database, port=port)
    cursor = connection.cursor()
    
    try:
        # 查询chain_needcomp0608表中的数据
        sql = "SELECT chain_name, nodes FROM chain_needcomp0421 where chain_name = '氢能产业'"
        cursor.execute(sql)
        rows = cursor.fetchall()
        
        for row in rows:
            chain_name, nodes = row
            # 构建提示词
            words = f"产业链名称：{chain_name}，节点名称：{nodes}"
            print(words)
            
            # 获取大模型的摘要
            abstract = get_abstract(words, system_prompt)
            print(abstract)
            if abstract:
                # 解析JSON格式的摘要
                try:
                    result_json = json.loads(abstract)
                    nodes_definition = result_json['节点定义']
                    # 更新节点定义到数据库
                    update_nodes_definition(chain_name, nodes, nodes_definition)
                except json.JSONDecodeError:
                    print("JSON解析错误")
    except Exception as e:
        print(f"查询失败：{e}")
    finally:
        cursor.close()
        connection.close()
