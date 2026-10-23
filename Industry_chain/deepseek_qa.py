import os
import json
from openai import OpenAI
from sympy import false

industry_name = '新能源汽车'

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com/beta",
)



system_prompt = '''
你是一个产业链分析专家,也是一个构建产业链知识图谱的专家。
下面这些内容是{industry_name}产业链知识图谱中的所有节点关系三元组，请你分析出每一条的关系是正确还是不正确，如果判断为不正确请给出原因。
最后计算出三元组总数量，正确数量，不正确数量，正确占比和不正确占比。

节点的关系三元组格式为:起始节点,结束节点,关系类型。
关系类型包括:part-of(表明了一种构成关系,表示起始节点是结束节点的一部分),is-a(说明了一种分类关系,表示起始节点是结束节点的一个种类或实例)。
例如,如果有一个节点是“锂电池”,另一个节点是“电池”,那么它们之间的关系可以表示为“锂电池,电池,is-a”,意味着锂电池是电池的一种。
再例如,如果有一个节点是“电芯”,另一个节点是“电池”,那么它们之间的关系可以表示为“电芯,电池,part-of”,意味着电芯是电池的一部分。


输出结果格式如下边例子所示：
"
关系判断结果：
动力电池,上游,part-of:正确
电机及电控系统,下游,part-of:不正确，因为电机及电控系统是产业链的上游部分

计算结果：
总数量:2
正确数量:1
不正确数量:1
正确占比:50%
不正确占比:50%
"

'''

user_prompt = '''
上游,新能源汽车,part-of
中游,新能源汽车,part-of
下游,新能源汽车,part-of
动力电池,上游,part-of
氢燃料电池,上游,part-of
电机,上游,part-of
电控系统,上游,part-of
传统汽车零部件,上游,part-of
电池材料,动力电池,part-of
正极材料,电池材料,part-of
负极材料,电池材料,part-of
隔膜,电池材料,part-of
电解液,电池材料,part-of
驱动电机,电机,is-a
电动汽车用电机,电机,is-a
永磁同步电机,电动汽车用电机,is-a
IGBT,电控系统,part-of
整车制造,中游,part-of
纯电动汽车,整车制造,is-a
油电混合动力汽车,整车制造,is-a
燃料电池汽车,整车制造,is-a
充电服务,下游,part-of
电池回收利用,下游,part-of
后市场服务,下游,part-of
车身及其附件,整车制造,part-of
车用电子器件,整车制造,part-of
内饰件,整车制造,part-of
底盘,整车制造,part-of
'''

messages = [{"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt, "prefix": True}]

response = client.chat.completions.create(
    model="deepseek-chat",
    messages=messages,
    temperature=1.0,
    max_tokens=8000
)

print(response.choices[0].message.content)