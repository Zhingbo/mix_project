# nodes = '''树脂
# 玻璃
# 塑料
# 五金配件
# 板材
# TR
# 纯钛
# 钛合金
# 其他金属架
# 其他合金架
# 硅胶
# 玳瑁壳
# 贵金属镜架
# 辅料
# 生产设备
# 镜片
# 镜架
# 镜片材料
# 镜架材料
# 镜片加工
# 眼镜装配
# 眼镜零售商
# 医院配镜中心
# 大型商超
# 品牌专卖店
# 医院
# 视力矫正中心
# 电商平台
# 销售渠道'''

nodes = '''树脂
玻璃
塑料
聚碳酸酯PC
聚甲基丙烯酸甲酯PMMA
铜合金
镍合金
贵金属
钛合金
硅胶
玳瑁
特殊木材
动物头角
鼻托
螺丝
铰链
切割机
打磨机
焊接机
抛光机
涂膜机
中国石化
中国石油
茂化实华
沈阳化工
蔡司
依视路
明月镜片
康耐特光学
凯米
金属镜架
塑料镜架
木材镜架
混合材料镜架
眼镜组装
连锁眼镜零售商
眼镜零售门店
电商平台
民营眼科医院
综合医院附属配镜中心
品牌专卖店
京东
天猫
验光服务
配镜服务
装配服务
试戴服务
销售服务
配送服务
维修服务'''

info = [node for node in nodes.split("\n")]

import json

from typing import *
 
import os
import json
 
from openai import OpenAI
from openai.types.chat.chat_completion import Choice



class Agent:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = self._init_client()

    def _init_client(self):
        # 初始化 OpenAI 客户端
        return OpenAI(
            base_url="https://api.moonshot.cn/v1", 
            api_key=self.api_key
        )

    def search_impl(self, arguments: Dict[str, Any]) -> Any:
        # search 工具的具体实现，这里我们只需要返回参数即可
        return arguments

    def search(self, query: str) -> str:
        # 搜索方法，接收一个查询字符串，返回搜索结果
        messages = [
            {"role": "system", "content": "你是一个眼镜产业链专家，而且特别擅长从各种网页上查询资料来获取某个行业的产业链。"},
            {"role": "user", "content": f"请搜索和眼镜产业链相关的{query}产业链，要搜索出{query}的上下游产业分别都有哪些，注意这些上下游的产业也必须和眼镜有关，不要跳出眼镜的大框架。"}
        ]
        finish_reason = None
        while finish_reason is None or finish_reason == "tool_calls":
            choice = self._chat(messages)
            finish_reason = choice.finish_reason
            if finish_reason == "tool_calls":
                messages.append(choice.message)
                for tool_call in choice.message.tool_calls:
                    tool_call_name = tool_call.function.name
                    tool_call_arguments = json.loads(tool_call.function.arguments)
                    if tool_call_name == "$web_search":
                        tool_result = self.search_impl(tool_call_arguments)
                    else:
                        tool_result = f"Error: unable to find tool by name '{tool_call_name}'"

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call_name,
                        "content": json.dumps(tool_result),
                    })
        return choice.message.content

    def _chat(self, messages) -> Choice:
        # 聊天方法，用于与 OpenAI 客户端进行交互
        completion = self.client.chat.completions.create(
            model="moonshot-v1-128k",
            messages=messages,
            temperature=0.3,
            tools=[
                {
                    "type": "builtin_function",
                    "function": {
                        "name": "$web_search",
                    },
                }
            ]
        )
        return completion.choices[0]



if __name__ == '__main__':
    # 使用示例
    api_key = os.getenv('MOONSHOT_API_KEY')
    agent = Agent(api_key)
    result = []
    for word in info:
        search_result = agent.search(word)
        result.append(search_result)
        print(f'{word}已搜索完成')
    s = '\n'.join(result)
    with open('result_iter_2.txt','w',encoding='utf-8') as f:
        f.write(s)
    

    