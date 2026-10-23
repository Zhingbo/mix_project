import os
import json
from openai import OpenAI
from sympy import false
import pandas as pd
from pathos.multiprocessing import Pool
from multiprocessing import set_start_method
import time

industry_name='汽车'
file_path = 'company_info_nev_repaired.xlsx'
nodes_file_path = f'new_nodes_{industry_name}.txt'
relation_file_path = f'new_relations_{industry_name}.txt'
output_file_path = f'matched_nodes_{industry_name}.xlsx'

with open(nodes_file_path, 'r', encoding='utf-8') as file:
    nodes = file.read().splitlines()
file.close()
print(nodes)


system_prompt = f'''你是一个擅于归纳总结的专家。
以下是一些与{industry_name}产业相关公司网站的抓取内容(crawl_content)，请你总结概括出这家公司主要是做什么的，主要概括和{industry_name}有关的部分，之后，输出一段公司简介，并以JSON的格式返回到结果中，例如：
{{
    "crawl_content":"广东顺德和壹设计咨询有限公司主要属于工业设计行业，专注于产品设计、工业设计等领域。"
}}
要严格用json的方式返回，key的名称必须是"crawl_content"。下面开始：
'''

system_prompt_new = f'''你是一个产业链分析专家,也是一个构建产业链知识图谱的专家。

以下是{industry_name}公司名称(company_name)，公司简介(company_intro)，公司网站(website)和公司主营产品(major_product)。我会以Json形式给出：
{{
    "company_name":"",
    "company_intro":"",
    "website":"",
    "major_product":""
}}。
你的任务是根据公司简介(company_intro)和公司主营产品(major_product)在已有的产业链节点中:["动力系统集成","销售与服务","零部件制造"]找到至少1个最匹配的节点并给出你的匹配原因，然后结合产业链对每个节点进行定义说明，多个节点的定义用"|"分隔开。
具体的匹配规则是：比如说，我们现在搞的是新能源汽车产业链。
- 首先，你先去主营产品中找与新能源汽车相关的产品描述，再去已有的产业链节点中找是否有能匹配上的节点，匹配规则是产品描述和已有的产业链节点之间可能是包含关系，组成关系或者关联关系。以下的内容都只是举例，不是真实数据，只是告诉你应该怎样做：
-- 比如：公司主营产品中包括新能源汽车用空压机FRA系列，你分析出这直接关联到新能源汽车的动力系统,你应该去已有的产业链节点中找与动力系统意思最为接近的节点，于是你匹配到的节点为"动力系统集成"。
-- 再比如：公司主营产品中提到新能源汽车测试方案，你分析出这直接关联到新能源汽车产业链的下游销售与服务环节，你应该去已有的产业链节点中找与销售服务环节意思最为接近的节点，于是你匹配到的节点为"销售与服务"。
-- 再比如：公司主营产品中包括新能源汽车电附件，汽车零部件及配件制造，你分析出这些都是零部件制造的重要组成部分，你应该去已有的产业链节点中找与零部件制造意思最为接近的节点，于是你匹配到的节点为"零部件制造"。

- 如果你发现主营产品中与新能源汽车相关的产品描述太过于宽泛不具体，比如主营产品就只有新能源汽车，那么你需要去公司简介(company_intro)中找到这家公司是做什么的，根据这家公司是做什么的，公司的业务，产品描述，再去已有的产业链节点中找是否有能匹配上的节点，匹配规则是公司简介描述的内容和已有的产业链节点之间可能是包含关系，组成关系或者关联关系。以下的内容都只是举例，不是真实数据，只是告诉你应该怎样做：
-- 比如：公司的主营产品包括新能源汽车，你不好判断出他具体的业务产品是什么，于是你去公司简介中找到这家公司是提供新能源汽车技术培训和人才培养的，于是你分析出这属于新能源汽车产业链的下游销售与服务环节，根据关联性，你应该去已有的产业链节点中找与销售服务环节意思最为接近的节点，于是你匹配到的节点为"销售与服务"。
-- 再比如：公司的主营产品包括新能源汽车产品，你不好判断出他具体的产品指的是什么，于是你去公司简介中找到这家公司多年来专注于为新能源汽车零件提供同步开发工艺优化验证制造等多元一体化的制造服务，于是你分析出这些涉及到新能源汽车上游的零部件制造以及下游的销售服务环节，你应该去已有的产业链节点中找与零部件制造以及销售服务环节意思最为接近的节点，于是你匹配到的节点为"零部件制造"和"销售与服务"。

下面给你举例子。假设我们给出的信息是：
{{
    "company_name:"盛大集团",
    "company_intro":"广州宇曦电子科技有限公司是国内一家专业定制化电源及测试系统的高新技术企业，公司集研发、生产、销售、服务于一体。"，
    "website":"http://www.ytechate.com/",
    "major_product":"锂电池充电器"

}}
我们来一步步分析：
- 首先，你从主营产品中找到和新能源汽相关的产品描述，你发现这个公司的主营产品(major_product)是"锂电池充电器",你要从{nodes}中找与"锂电池充电器"关系最紧密的，你找到了"充电设施"。好的，这就匹配上一个节点。
- 之后，你又从公司简介中（company_intro）发现，"公司集研发、生产、销售、服务于一体"。这时，你在{nodes}中寻找和销售服务最接近的，发现正好有一个节点是"销售服务"。这又完成了一次匹配。
- 此时，你从公司简介的"公司集研发"，你觉得这里也有可能匹配上一些节点，你又在{nodes}中找，发现没有这个节点，那就不需要增加了；
- 现在你可以给出结果，用json返回如下：
{{
    "企业名称": "广州宇曦电子科技有限公司",
    "主营产品": "锂电池充电器",
    "企业网站": "http://www.ytechate.com/",
    "公司简介": "广州宇曦电子科技有限公司是国内一家专业定制化电源及测试系统的高新技术企业，公司集研发、生产、销售、服务于一体。",
    "匹配节点": ["充电设施","销售与服务"],
    "节点定义": "充电设施包括车企主导的充电设施服务和公共充电服务商为主导的充电设施服务.|销售与服务包括整车销售、售后服务、维修保养等.",
    "匹配原因": "从主营产品中可以看到锂电池充电器是充电设施中的一个重要组成部分，而且在给出的节点中存在"充电设施",所以匹配节点为充电设施；结合公司简介来看，公司集研发、生产、销售、服务于一体，而且节点中也存在“销售与服务”，所以匹配节点为销售与服务。"
}}
特别注意：
1.结果中的"匹配节点"只返回我提供的产业链节点中存在的节点{nodes}，不要出现主营产品中提到的但是我提供的产业链节点中{nodes}不存在的，也不要出现公司简介中提到的但是我提供的产业链节点{nodes}中不存在的。
2.结果中的"匹配节点"必须要有{industry_name}这个节点。
3.结果中的"匹配节点"不能只有{industry_name}这个节点，按照上边的具体匹配逻辑一定能在我提供的产业链节点中找到除了{industry_name}以外的匹配节点。
4.你在结合公司简介和主营产品匹配我提供的产业链节点的时候，要尽可能的全面。也就是说如果主营产品或者公司简介涉及到我提供的产业链中的某个节点，那么不仅要匹配出这个大的节点，还要进一步细化，找出这个节点下与主营产品以及公司简介相关的子节点。
比如：主营产品包括"精密连接器, 精密注塑模具, 精密冲压模具, 精密注塑件, 精密冲压件"，已有产业链的节点包括"连接器,零部件制造"，你首先分析出主营产品包括的这些都属于新能源汽车零部件制造的一部分，所以匹配出节点为"零部件制造"，接下来你要继续对主营产品中的每部分进行匹配，你发现精密连接器可以匹配上"连接器"这个节点，因此匹配到的节点应该有两个，分别是"零部件制造"和"连接器"。
5.你要严格遵循我提供的产业链节点去匹配，不要自行总结或推断新的节点，也不要关注公司简介与主营产品中与{industry_name}无关的信息，导致匹配节点出现不在我提供的产业链节点中的节点{nodes}。
需要再次强调的是，绝对不能出现匹配节点{nodes}以外的新节点！！！！下面开始：
'''

client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com/beta",
    )



def summarize_crawl_content(row):
    words_json = {
        'crawl_content': row[12]  # 'crawl_content' 是第13列
    }
    if words_json is not None:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {'role': 'system', 'content':system_prompt},
                {'role': 'user', 'content': json.dumps(words_json, ensure_ascii=False)}
                ],
                temperature=0.3,
                response_format={"type": "json_object"}
        )
        try:
            return response.choices[0].message.content
        except:
            return None
    else:
        print("爬取内容列不存在。")
        return None

def process_row_new(row):
    abstract = summarize_crawl_content(row)
    print(abstract)
    if abstract:
        try:
            result_json = json.loads(abstract)
            words_json = {
                'company_name': row[2],  # 'company_name' 是第3列
                'company_intro': result_json['crawl_content'],
                'website': row[1],  # 'website' 是第2列
                'major_product': row[6]  # 'major_product' 是第7列
            }
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {'role': 'system', 'content': system_prompt_new},
                    {'role': 'user', 'content': json.dumps(words_json, ensure_ascii=False)}
                ],
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            response = response.choices[0].message.content
            return response

        except:
            return None



if __name__ == '__main__':
    set_start_method('spawn')
    start_time = time.time()
    # 读取Excel文件   
    df = pd.read_excel(file_path, sheet_name=0,nrows=100) 

    df.columns = df.columns.str.strip().str.replace('\n', '').str.replace('\r', '') 
    print("清理后的列名：", df.columns)   

    with Pool(50) as pool:  # 使用pathos的Pool
        results = pool.map(process_row_new, df.itertuples(index=False, name=None))  # 返回普通元组
    print(results)

    results = []
    for row in df.itertuples(index=False, name=None):
        results.append(process_row_new(row))

    new_df = pd.DataFrame(results)
    print(new_df)

    # 将JSON字符串解析为字典
    # data = [json.loads(json_str) for json_str in results if json_str is not None ]
    data = []
    for json_str in results:
        try:
            data.append(json.load(json_str))
        except:
            continue


    # 创建一个DataFrame
    df = pd.DataFrame(data)
    print(df)

    # 保存到Excel文件
    df.to_excel(output_file_path, index=False)
    print(f"数据已保存到 {output_file_path}")

    end_time = time.time()
    print(f"代码运行总时间：{end_time - start_time}")



