import os
import json
from openai import OpenAI
import pandas as pd
import time

DASHSCOPE_API_KEY = os.getenv('DASHSCOPE_API_KEY')

industry_names = [
    "新能源汽车", "激光"
]  # 可以更换行业名称

def process_row_new(nodes, industry_name, api_key):
    # 确保nodes是字符串
    nodes_str = str(nodes)

    try:
        client = OpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
        )

        response = client.chat.completions.create(
            model="deepseek-v4.1-flash",
            messages=[
                {'role': 'system', 'content': f'''你是一个产业链分析专家,也是一个构建产业链知识图谱的专家。
                以下是{industry_name}产业链的所有结点：{nodes}，你的任务是识别重复或相似的节点，并且只保留一个节点，比如"销售","分销","零售"这三个节点指向的都是同一个事情，因此你应该将它们合并成一个节点"销售"。
                另外，有些节点能归纳为一大类节点，那么你要创造出这个新的大类节点，比如"行星减速器"和"谐波减速器"，他们都是减速器的具体分类，因此你需要总结出新的大类节点"减速器"，然后将"行星减速器"和"谐波减速器"作为"减速器"的下一级节点。
                然后，根据你处理后的节点，生成节点关系三元组。
                三元组格式为:起始节点,结束节点,关系类型。
                起始节点表示下一级的节点，结束节点表示上一级的节点。比如锂电池是电池的下一级节点，那么他们的关系格式应该表示为“锂电池,电池,is-a”而不是“电池,锂电池,is-a”。
                关系类型包括:part-of(表明了一种构成关系,表示起始节点是结束节点的一部分),is-a(说明了一种分类关系,表示起始节点是结束节点的一个种类或实例)。
                例如,如果有一个节点是“锂电池”,另一个节点是“电池”,那么它们之间的关系可以表示为“锂电池,电池,is-a”,意味着锂电池是电池的一种。
                再例如,如果有一个节点是“电芯”,另一个节点是“电池”,那么它们之间的关系可以表示为“电芯,电池,part-of”,意味着电芯是电池的一部分。

                注意:
                1) 具体的节点仅有一次作为起始节点,不能多个起始节点同时指向相同的结束节点。
                2) 输出结果包括两部分,第一部分是所有节点,第二部分是三元组。节点以及三元组都是直接输出结果内容即可,不需要对结果内容标注数字序号。比如节点不要输出"1. 动力电池"而是要输出"动力电池".三元组不要输出"1. 动力电池,电池材料,part-of"而是要输出"动力电池,电池材料,part-of"。
                3) 中心节点只有一个，那就是{industry_name}，它只能是结束节点。
                4) 除了中心节点外，其他节点一定要有结束节点，否则会出现知识图谱中边的丢失。
                5) 你总结出来的节点一定不要有重复的，如果有相似意思的节点一定要合并，比如"原材料"和"原材料生产"，再比如"销售"和"零售"。
                6) 你总结出来的三元组也一定不要有重复的。
                7) {industry_name}，上游，中游和下游这四个节点一定要返回到输出结果中，并且上游，中游和下游与中心节点构成三个三元组，即"上游,{industry_name},part-of","中游,{industry_name},part-of","下游,{industry_name},part-of"。
                    这是必须要有的三个三元组。
                8) 你在展开上游，中游，下游节点的时候要遵循以下规则：
                    - 上游节点包括原材料，零部件，基础加工设备相关的节点；
                    - 中游节点指原材料转化为中间产品或最终产品的生产和加工环节包括制造，组装，封装，测试，深加工相关的节点；
                    - 下游节点主要涉及产品的销售、分销、零售以及售后服务包括品牌营销、物流配送、应用、培训相关的节点。
                9) 总结出的节点不要是产品。    
                10) 除了上游，中游和下游其余节点都不能与{industry_name}这个中心节点建立关系，也就是说其余节点的结束节点都不能是{industry_name}。
                11) 总结出的节点名字中不要含有"产业链"这三个字。
                12) 总结出的节点不要有类似"供需平衡","重要性","意义","定义","政策","标准制定","决策层","合作","挑战","协同","趋势","应用","优化","动态","发展","改进"等这种非具体的不属于产业链的某个具体部分的内容。
                13) 总结出的节点不要是公司名字，不要是供应商/提供商的名字，不要是制造商名字，不要是品牌名字(中英文品牌都不要).
                14) 总结出的节点名字中不要含有"产业链上游"这五个字.
                15) 总结出的节点名字中不要含有"产业链中游"这五个字.
                16) 总结出的节点名字中不要含有"产业链下游"这五个字.
                17) 总结出的节点不要超过80个。
                18) 总结出的节点必须是实际的产业链节点。类似政策信息、未来趋势、重要性、发展战略、市场环境，企业等务虚的内容，都不要总结到节点中.
                19) 总结出的节点名字中不要含有"产业上游"这四个字.
                20) 总结出的节点名字中不要含有"产业中游"这四个字.
                21) 总结出的节点名字中不要含有"产业下游"这四个字.


                以下是⼀个具体例⼦，仅供参考,假设我给你提供的资料都是汽车相关的信息,那么以汽车为中心节点的产业链输出结果用Json表示为:
                ```json
                {{
                    "nodes":["汽车",""整车制造","蓄电池","锂电池","氢燃料电池","同步电机","异步电机","电池","动⼒系统","电机"],
                    "relations":["电池,上游,part-of",
                        "电机,上游,part-of",
                        "动⼒系统,上游,part-of",
                        "整车制造,中游,part-of",
                        "上游,汽车,part-of",
                        "中游,汽车,part-of",
                        "下游,汽车,part-of",
                        "蓄电池,电池,is-a",
                        "锂电池,电池,is-a",
                        "氢燃料电池,电池,is-a",
                        "同步电机,电机,is-a",
                        "异步电机,电机,is-a",
                        "电池,动⼒系统,part-of",
                        "电机,动⼒系统,part-of"]
                }}
                ```
                需要特别注意的是：
                1. 上面给出的仅仅是个例子，具体输出什么要以具体资料为准。
                2. 中心节点必须是{industry_name}。
                3. 三元组中的起始节点和结束节点都必须要在你首先总结出来的节点中，即不能在三元组中出现你总结出来的节点中没有的；
                4. 你必须要注意三元组不能出现断点。也就是说，每个三元组中的第二个元素必须要出现在之前三元组中的第一个元素上，只有{industry_name}这个节点除外，因为这些三元组都是围绕着这个节点的。
                5. 中心节点{industry_name}只能与三个节点建立三元组关系，那就是"上游","中游","下游"。
                6. 如果你总结出的节点与中心节点{industry_name}建立了"is-a"的关系，那么请剔除这个节点并且重新总结三元组。
                7. 你要特别注意一定要正确返回JSON格式，不要出现缺少引号等等的异常情况。
                8. 一定要严格遵守上边提到的展开上游，中游，下游节点的规则，中游展开的节点不要包括原材料，零部件等等上游相关的节点。
                9. 如果你发现你总结出来的节点和三元组存在上面的问题，就必须重新总结。      

                下面给你{industry_name}产业链的所有节点，并按要求总结出节点和三元组。只返回json即可，不需要其他内容。
                '''},
                {'role': 'user', 'content': nodes_str}  # 确保nodes是字符串
            ],
            temperature=0.6,
            response_format={"type": "json_object"}
        )
        # 确保响应内容是JSON格式
        response_content = response.choices[0].message.content
        return response_content
    except Exception as e:
        print(f"process_row_new出错: {e}")
        return None

def clean_and_parse(triples_raw):
    try:
        # 尝试清理字符串并解析为JSON
        cleaned_triples_raw = triples_raw.replace("```", "").replace("json", "")
        print("清理后的字符串：", cleaned_triples_raw)  # 打印清理后的字符串以供调试

        # 检查并补全缺失的引号
        if not cleaned_triples_raw.endswith('"') and cleaned_triples_raw.count('"') % 2 != 0:
            cleaned_triples_raw += '"'
        if not cleaned_triples_raw.endswith("'") and cleaned_triples_raw.count("'") % 2 != 0:
            cleaned_triples_raw += "'"

        print("补全后的字符串：", cleaned_triples_raw)  # 打印补全后的字符串以供调试

        # 使用 json.loads 而不是 ast.literal_eval
        return json.loads(cleaned_triples_raw)
    except json.JSONDecodeError as e:
        print(f"解析 triples_raw 时出错：{e}")
        return None


if __name__ == '__main__':
    start_time = time.time()

    for industry_name in industry_names:
        print(f"Processing {industry_name}")

        nodes_file_path = f'resultTxt/nodes_{industry_name}.txt'
        new_nodes_file_path = f'resultTxt/update_nodes_{industry_name}.txt'
        relations_file_path = f'resultTxt/relations_{industry_name}.txt'
        new_relations_file_path = f'resultTxt/update_relations_{industry_name}.txt'

        # 读取产业链节点
        with open(nodes_file_path, 'r', encoding='utf-8') as file:
            nodes = file.read().splitlines()

        results = process_row_new(nodes, industry_name, DASHSCOPE_API_KEY)
        triples_raw_dict = clean_and_parse(results) 

        if triples_raw_dict:
            relations = triples_raw_dict['relations']
            nodes = triples_raw_dict['nodes']
            
            relations_str = '\n'.join(relations)
            nodes_str = '\n'.join(nodes)

            # 写入 nodes 文件
            with open(new_nodes_file_path, 'w', encoding='utf-8') as f:
                f.write(nodes_str)
                print(f"Nodes written to {new_nodes_file_path}")    

            # 写入 relations 文件
            with open(new_relations_file_path, 'w', encoding='utf-8') as f:
                f.write(relations_str)          
                print(f"Relations written to {new_relations_file_path}")     

    end_time = time.time()
    print(f"代码运行总时间：{end_time - start_time}")
    print("done")
    