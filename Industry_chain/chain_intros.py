import json
from openai import OpenAI
from sympy import false
import pandas as pd
import glob
import os


system_prompt = '''下边是产业链名称(chain_name)，你需要对这个产业链给出一个简短的定义，并且结合下边的信息对这个产业链给出简短的景气度分析，创新性分析，活跃度分析以及风险性分析。

    -景气度分析：产业链的景气度通常是指行业在一定时期内的经济活力和市场表现。它可以通过行业景气指数来衡量，该指数是综合反映行业各种指标并反映行业变动趋势的综合指数。行业景气度的高低受多种因素影响，包括宏观经济指标波动、经济周期、上下游产业链的供应需求变动等外部因素，以及行业内部的产品需求变动、生产能力变动、技术水平变化及产业政策变化等内部因素。
    -活跃度分析：产业链的活跃度指的是产业链中各环节的交易频率和市场参与度。一个活跃的产业链通常表现为需求旺盛、生产满负荷、买卖活跃。活跃度可以通过产业链中各环节的交易量、资金流动速度、新企业的出现频率等指标来衡量。
    -创新性分析：产业链的创新性涉及到产业链中各环节的技术创新、产品创新、管理创新等。创新性可以通过专利申请数量、研发投入占比、新产品推出的频率等指标来衡量。创新性高的产业链通常具有较强的竞争力和发展潜力。
    -风险性分析：产业链的风险性指的是产业链在运营过程中可能面临的不确定性和潜在损失。风险性可以通过产业链中各环节的波动性、依赖度、以及对外部冲击的敏感度等指标来衡量。例如，产业链中某个关键环节的供应中断或需求突变都可能带来整个产业链的风险。

结果输出：请返回产业链名称，产业链定义，景气度分析，创新性分析，活跃度分析以及风险性分析，请以Json的方式返回答案，示例如下:
{
    "产业链名称":"新能源汽车",
    "产业链定义":"新能源汽车产业链是指与新能源汽车相关的一系列产品和服务的生产、供应、销售等环节所构成的网络。这个产业链涵盖了从原材料的开采和加工，到新能源汽车的设计、制造、销售、使用、维护，直至最终的回收和再利用等各个环节.",
    "景气度分析":"新能源汽车产业链的景气度持续向好，全球新能源汽车销量大幅增长，纯电动汽车占比逐步提升。",
    "创新性分析":"新能源汽车产业链在技术创新方面表现活跃，特别是在固态电池、钠电池、快充和复合集流体等领域。",
    "活跃度分析":"新能源汽车产业链活跃度高，市场需求增长和技术水平的提高推动了产业链的发展。",
    "风险性分析":"新能源汽车产业链面临一些风险因素，例如新能源车产销量增长可能低于预期，产业链盈利可能低于预期。"
}

'''

def get_client():
    return OpenAI(
        api_key=os.getenv("VOLCENGINE_ARK_API_KEY"),
        base_url="https://ark.cn-beijing.volces.com/api/v3"
    )

def get_abstract(words, system_prompt):
    if words is not None:
        client = get_client()

        
        # response = client.chat.completions.create(
        #     model="deepseek-chat",
        #     messages=[
        #         {'role': 'system', 'content': f'{system_prompt}'},
        #         {'role': 'user', 'content': f'{words}'}
        #     ],
        #     temperature=0.6,
        #     response_format={"type": "json_object"}

        response = client.chat.completions.create(
                    model="ep-20250217153205-d7px5",
                    messages=[
                        {'role': 'system', 'content': f'{system_prompt}'},
                        {'role': 'user', 'content': f'{words}'}
                    ],
                    temperature=0.6,
                    response_format={"type": "json_object"}
        )

        try:
            return response.choices[0].message.content
        except:
            return None


if __name__ == '__main__':
    industry_names = [
        # "电气设备", "电子器件", "医疗器械", "消费电子","无人驾驶", 
        # "集成电路", "元宇宙", "新能源汽车", "电子信息", "机械设备与零件",
        # "3D打印", "卫星导航", "无人机", "大飞机", "激光",
        # "汽车", "眼镜", "工业母机", "工业软件", "人工智能",
        # "光伏", "合成生物", "5G", "检验检测", "储能",
        # "芯片", "氢能", "低碳经济","低空经济", "能源环保", 
        # "仪器仪表","装备制造", "通信设备", "半导体", "新材料", 
        # "医疗美容", "大健康", "机器人", "生命健康", "生物医药",
        # "风电","轨道交通装备",
        # "智能家居","物联网","云计算","服装","绿色建筑",
        # "可再生能源","环保技术","生物科技","数字媒体","电子商务",
        # "食品科技","海洋经济","航空航天","数字安全","纳米技术",
        # "量子计算","精细化工","金属加工","超导材料","船舶制造",
        # "生物经济","直播电商","在线教育","AI智能体","家具制造",
        # "家电设备","端侧AI","人形机器人","未来显示","算力",
        # "新能源", "首发经济","未来信息" ,"虚拟现实","碳中和",
        # "远程医疗","智能交通","智能电网","智能金融","智能农业",
        "AI大模型","装配式建筑","跨境电商","银发经济","情绪价值",
        "量子科技","空天信息","电竞","5G-A","固态电池",
        "商业航天","AI眼镜","北斗产业","碳纤维","智能穿戴",
        "智能传感器","预制菜产业","高端装备制造","宠物经济","露营经济",
        "数字创意产业","数字医疗","脑机接口"        
    ]  # 可以更换行业名称


    # 创建一个空的DataFrame来存储筛选后的结果，包含所需的列
    new_df = pd.DataFrame(columns=['chain_name', 'chain_definition','source_url','prosperity_analysis','innovation_analysis','activity_analysis','risk_analysis'])
    print(new_df)

    for industry_name in industry_names:
        print(f"正在处理:{industry_name}")

        output_file_path = 'outputFiles/chain_information_total.xlsx'

        # 构建提示词
        words = f"产业链名称：{industry_name}"
        print(words)
        
        # 获取大模型的摘要
        abstract = get_abstract(words, system_prompt)
        print(abstract)
        if abstract:
            # 解析JSON格式的摘要
            try:
                result_json = json.loads(abstract)
                new_row = {
                    'chain_name': industry_name,
                    'chain_definition': result_json['产业链定义'],
                    'prosperity_analysis': result_json['景气度分析'],
                    'innovation_analysis': result_json['创新性分析'],
                    'activity_analysis': result_json['活跃度分析'],
                    'risk_analysis': result_json['风险性分析']
                }

                # 读取对应的txt文件并提取URL
                file_path = f"materials/url_list_{industry_name}.txt"
                if os.path.exists(file_path):
                    with open(file_path, 'r', encoding='utf-8') as file:
                        lines = file.readlines()
                        start_index = 0
                        for i, line in enumerate(lines):
                            if line.strip() == f"{industry_name}的产业链信息":
                                start_index = i + 1
                                break
                        urls = []
                        for line in lines[start_index:]:
                            url = line.strip()
                            if url.startswith("https") and url.endswith(".html"):
                                urls.append(url)
                                if len(urls) == 3:
                                    break
                        new_row['source_url'] = ';'.join(urls)
                else:
                    new_row['source_url'] = 'No file found'

                new_df = pd.concat([new_df, pd.DataFrame([new_row])], ignore_index=True)
                print(new_df)       
                with pd.ExcelWriter(output_file_path, engine='xlsxwriter') as writer:
                    new_df.to_excel(writer, sheet_name='chain_info', index=False)
                print(f'数据已写入到 {output_file_path}')                           
            except json.JSONDecodeError:
                print("JSON解析错误")

