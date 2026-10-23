import json
from openai import OpenAI
from sympy import false
import pandas as pd
from multiprocessing import Pool
from multiprocessing import set_start_method
from concurrent.futures import ProcessPoolExecutor
import time
import mysql.connector
import os

industry_names = [
    "电气设备", "电子器件", "医疗器械", "消费电子","无人驾驶", 
    "集成电路", "元宇宙", "新能源汽车", "电子信息", "机械设备与零件",
    "3D打印", "卫星导航", "无人机", "大飞机", "激光",
    "汽车", "眼镜", "工业母机", "工业软件", "人工智能",
    "光伏", "合成生物", "5G", "检验检测", "储能",
    "芯片", "氢能", "低碳经济","低空经济", "能源环保", 
    "仪器仪表","装备制造", "通信设备", "半导体", "新材料", 
    "医疗美容", "大健康", "机器人", "生命健康", "生物医药",
    "风电","轨道交通装备"
    ]  # 可以更换行业名称

zlc_api_key = os.getenv('DEEPSEEK_API_KEY_LC')
sandro_api_key = os.getenv('DEEPSEEK_API_KEY')
mh_api_key = os.getenv('DEEPSEEK_API_KEY_MH')
gy_api_key = os.getenv('DEEPSEEK_API_KEY_GY')

def get_rules(industry_name):
    rules_file_path = f'materials/rules_list_{industry_name}.txt'
    if os.path.exists(rules_file_path):
        with open(rules_file_path, 'r', encoding='utf-8') as file:
            return file.read().splitlines()
    return None

def get_nodes(industry_name):
    nodes_file_path_2 = f'resultTxt/nodes2_{industry_name}.txt'
    nodes_file_path = f'resultTxt/nodes_{industry_name}.txt'
    
    if os.path.exists(nodes_file_path_2):
        with open(nodes_file_path_2, 'r', encoding='utf-8') as file:
            return file.read().splitlines()
    elif os.path.exists(nodes_file_path):
        with open(nodes_file_path, 'r', encoding='utf-8') as file:
            return file.read().splitlines()
    else:
        print(f"节点文件不存在：{nodes_file_path_2} 或 {nodes_file_path}")
        return []


system_prompt = '''你是一个擅于归纳总结的专家。
以下是一些公司网站的抓取内容(crawl_content)，请你总结概括出每一家公司主要是做什么的，输出一段公司简介，并以JSON的格式返回到结果中，输出示例如下：
{
    "crawl_content":"广东顺德和壹设计咨询有限公司主要属于工业设计行业，专注于产品设计、工业设计等领域。"
}

注意：返回结果中键的名字一定是"crawl_content"，不可以是别的！！

'''

system_prompt_filter = '''你是一个产业链分析专家。以下是公司名称(company_name)，公司简介(company_intro)，和公司主营产品(major_product)，我会以Json形式给出：
    {
        "company_name":"",
        "company_intro":"",
        "major_product":""
    }

以下是一些产业链的定义:
    -电气设备：涉及发电、输电、配电、用电等环节的设备制造和相关服务，包括变压器、开关设备、电缆等。
    -电子器件：包括电子元器件的设计、制造、封装、测试等环节，如电阻、电容、电感、二极管、晶体管等。
    -医疗器械：涵盖医疗设备的研发、生产、销售、服务等，包括诊断设备、治疗设备、手术工具、医疗耗材等。
    -消费电子：涉及个人使用的电子产品，如智能手机、电脑、电视、音响设备等的研发、制造、销售。
    -无人驾驶：包括无人驾驶汽车的研发、制造、测试、服务等，涉及传感器、控制系统、地图服务等多个环节。
    -集成电路：包括集成电路的设计、制造、封装、测试等环节，是现代电子设备的核心。
    -元宇宙：涉及虚拟现实、增强现实、3D建模、数字孪生等技术，构建虚拟世界和体验。
    -新能源汽车：包括电动汽车、插电式混合动力汽车等的研发、制造、销售、服务等。
    -电子信息：涉及信息的获取、处理、传输、存储等环节，包括通信设备、计算机、网络设备等。
    -机械设备与零件：包括各种机械设备及其零部件的设计、制造、销售和维修服务。
    -3D打印：涉及3D打印技术的研发、打印设备制造、打印材料供应、打印服务等。
    -卫星导航：包括卫星制造、发射、地面设备制造、导航服务等环节。
    -无人机：涉及无人机的研发、制造、销售、服务，包括军用和民用无人机。
    -大飞机：包括大型飞机的研发、制造、销售、服务等，涉及航空材料、发动机、航电系统等。
    -激光：包括激光器的研发、制造、应用等，广泛应用于工业加工、医疗、科研等领域。
    -汽车：涉及汽车的研发、制造、销售、服务，包括整车制造和零部件供应。
    -眼镜：包括眼镜架、镜片的生产、设计、销售，以及验光、配镜服务。
    -工业母机：指用于制造其他机械设备的机床，包括数控机床、加工中心等。
    -工业软件：包括用于工业自动化、设计、管理等方面的软件的开发、销售、服务。
    -人工智能：涉及AI技术的研发、应用，包括机器学习、自然语言处理、计算机视觉等。
    -光伏：包括太阳能电池板的研发、制造、安装、维护等。
    -合成生物：涉及生物合成技术，包括基因编辑、合成生物学产品的研发和应用。
    -5G：包括5G网络的基础设施建设、终端设备制造、服务提供等。
    -检验检测：提供产品质量、安全、性能等方面的检测和认证服务。
    -储能：涉及电能存储技术的研发、制造、应用，如电池、储能系统等。
    -芯片：与集成电路类似，更侧重于芯片的设计和制造。
    -氢能：涉及氢气的生产、储存、运输、应用等，包括氢燃料电池。
    -低碳经济：涉及减少温室气体排放的技术和产业，如清洁能源、节能技术等。
    -低空经济：涉及低空领域的经济活动，如无人机物流、低空旅游等。
    -能源环保：包括能源的生产、使用过程中的环保技术和服务。
    -仪器仪表：涉及各种测量、控制、分析仪器的研发、制造、销售。
    -装备制造：包括各种工业装备的研发、制造、销售，如工程机械、农业机械等。
    -通信设备：涉及通信网络的建设和维护，包括基站、交换机、路由器等。
    -半导体：与集成电路类似，更侧重于半导体材料和器件。
    -新材料：涉及新型材料的研发、制造、应用，如纳米材料、复合材料等。
    -医疗美容：包括医疗美容服务、美容产品、医疗器械等。
    -大健康：涉及健康相关的产品和服务，如健康管理、医疗保健、健康食品等。
    -机器人：包括工业机器人、服务机器人的研发、制造、销售。
    -生命健康：涉及生命科学领域的产品和服务，如生物技术、基因检测等。
    -生物医药：包括生物药品的研发、生产、销售，涉及基因工程、细胞治疗等。
    -风电：涉及风力发电技术的研发、制造、安装、维护等。
    -轨道交通装备：包括地铁、高铁等轨道交通车辆及其相关设备的研发、制造、销售。


请你结合这些产业链定义，公司简介以及公司主营产品，匹配出该公司可能涉及到的产业链，并以JSON的格式返回结果，例如：
{
    "公司名称":"广州宇曦电子科技有限公司"
    "产业链列表":["电气设备","电子器件","新能源汽车","电子信息","机械设备与零件"]
}

注意："产业链列表"结果只能从我上边列举的这些产业链里进行匹配，不要构造出其他的产业链。

'''


client = OpenAI(
            api_key=sandro_api_key,
            base_url="https://api.deepseek.com/beta",
    )


def validate_matching_nodes(matching_nodes, nodes):
    # 校验匹配节点是否都在nodes列表中，不在则移除
    valid_nodes = [node for node in matching_nodes if node in nodes]
    return valid_nodes

def get_data_from_mysql(query):
    # 数据库连接配置
    cnx = mysql.connector.connect(
        user='remote_user',
        password=os.getenv('DB_PASSWORD_REMOTE'),
        host='8.141.23.4',
        database='business_data'
    )
    cursor = cnx.cursor()
    try:
        cursor.execute(query)
        df = pd.DataFrame(cursor.fetchall())
        cursor.close()
        cnx.close()
        return df
    except mysql.connector.Error as err:
        print("Something went wrong: {}".format(err))
        cursor.close()
        cnx.close()
        return None

def summarize_crawl_content(crawl_content):
    if crawl_content:  
        words_json = {
            'crawl_content': crawl_content
        }
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': json.dumps(words_json, ensure_ascii=False)}
            ],
            temperature=1.0,
            response_format={"type": "json_object"}
        )
        try:
            return response.choices[0].message.content
        except:
            return None
    else:
        print("crawl_content列不存在或为空。")
        return None

def chain_filter(row):
    abstract = summarize_crawl_content(row[4]) ## row是以tuple形式传递的，需要用index而不是列名
    print(abstract)
    if abstract is not None:
        try:
            result_json = json.loads(abstract)
        except json.JSONDecodeError as e:
            print(f"JSON解析错误：{e}")
            return None  # 返回 None 表示解析失败

        words_json = {
            'company_name': row[0],
            'company_intro': result_json['crawl_content'],
            'major_product': row[3]
        }
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {'role': 'system', 'content': system_prompt_filter},
                {'role': 'user', 'content': json.dumps(words_json, ensure_ascii=False)}
            ],
            temperature=1.0,
            response_format={"type": "json_object"}
        )
        try:
            print(response.choices[0].message.content)
            return response.choices[0].message.content
        except:
            print("process_row_new出错")
            return None
    else:
        return None
    
def process_row_new(row, nodes,rules,system_prompt_new):        
    abstract = summarize_crawl_content(row[4]) ## row是以tuple形式传递的，需要用index而不是列名
    if abstract is not None:
        try:
            result_json = json.loads(abstract)
        except json.JSONDecodeError as e:
            print(f"JSON解析错误：{e}")
            return None  # 返回 None 表示解析失败

        words_json = {
            'nodes': nodes,
            'company_name': row[0],
            'company_intro': result_json['crawl_content'],
            'website': row[1],
            'major_product': row[3],
            'rules': rules,
            'certainty': str(row[5]),
        }
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {'role': 'system', 'content': system_prompt_new},
                {'role': 'user', 'content': json.dumps(words_json, ensure_ascii=False)}
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        try:
            print(response.choices[0].message.content)
            return response.choices[0].message.content
        except:
            print("process_row_new出错")
            return None
    else:
        return None

def get_data_from_mysql_in_batches(query):
    return get_data_from_mysql(query)
    # results = []
    # offset = 0
    # has_more = True
    # while has_more:
    #     batch_query = f"{query} LIMIT {batch_size} OFFSET {offset}"
    #     print(batch_query)
    #     batch_df = get_data_from_mysql(batch_query)
    #     if batch_df is not None and not batch_df.empty:
    #         results.append(batch_df)
    #         offset += batch_size
    #         print(f"Processed {len(batch_df)} rows")
    #     else:
    #         has_more = False
    # return pd.concat(results, ignore_index=True)

    
if __name__ == '__main__':
    set_start_method('spawn')
    start_time = time.time()

    query = """
    SELECT distinct company_name,
        website,
        other_website,
        major_product,
        crawl_content,
        certainty
    FROM company_info_gf1204
    limit 2000
    """

    df = get_data_from_mysql_in_batches(query)
    print(df.head())

    if df.empty:
        print("No data found. Exiting.")
        exit()  # 如果没有数据，退出程序

    df.columns = ['company_name', 'website', 'other_website', 'major_product', 'crawl_content', 'certainty']
    print(df.columns)

    company_industry_list = []  # 存储公司及其产业链列表

    for row in df.itertuples(index=False, name=None):
        chain_filter_output = chain_filter(row)
        if chain_filter_output:  # 确保chain_filter_output不为空
            try:
                chain_filter_output_dict = json.loads(chain_filter_output)
                company_industry_list.append({
                    '公司名称': chain_filter_output_dict.get('公司名称', []),
                    '产业链列表': chain_filter_output_dict.get('产业链列表', [])
                })
            except json.JSONDecodeError as e:
                print(f"JSON解析错误：{e}")

    print(company_industry_list)

    # 使用Pool来并行处理数据
    with ProcessPoolExecutor(max_workers=50) as executor:
        results = {}
        for company_info in company_industry_list:
            company_name = company_info['公司名称']
            industry_list = company_info['产业链列表']
            # 根据公司名称从df中获取对应的行数据
            row = df[df['company_name'] == company_name].iloc[0]  
            for industry_name in industry_list:
                # 读取规则和节点
                rules = get_rules(industry_name)
                nodes = get_nodes(industry_name)

                system_prompt_new = f'''你是一个产业链分析专家,也是一个构建产业链知识图谱的专家。

                以下是公司名称(company_name)，公司简介(company_intro)，公司网站(website)，公司主营产品(major_product)和置信度(certainty)，我会以Json形式给出：
                {{
                    "company_name":"",
                    "company_intro":"",
                    "website":"",
                    "major_product":"",
                    "certainty":""
                }}

                你的任务是根据公司简介(company_intro)和公司主营产品(major_product)在已有的产业链节点{nodes}中找到至少1个最匹配的节点并给出你的匹配原因，然后概括总结出{industry_name}产业链的定义，并结合{industry_name}产业链对每个节点进行定义说明，多个节点的定义用"|"分隔开。
                具体匹配逻辑为：
                    - 首先，你先去主营产品中找与{industry_name}相关的产品描述，再去已有的产业链节点{nodes}中找是否有能匹配上的节点，匹配规则是产品描述和已有的产业链节点{nodes}之间可能是包含关系，组成关系或者关联关系。
                    比如：公司主营产品中包括新能源汽车用空压机FRA系列，你分析出这直接关联到新能源汽车的动力系统,你应该去已有的产业链节点{nodes}中找与动力系统意思最为接近的节点，于是你匹配到的节点为"动力系统集成"。
                    再比如：公司主营产品中提到新能源汽车测试方案，你分析出这直接关联到新能源汽车产业链的下游销售与服务环节，你应该去已有的产业链节点{nodes}中找与销售服务环节意思最为接近的节点，于是你匹配到的节点为"销售与服务"。
                    再比如：公司主营产品中包括新能源汽车电附件，汽车零部件及配件制造，你分析出这些都是零部件制造的重要组成部分，你应该去已有的产业链节点{nodes}中找与零部件制造意思最为接近的节点，于是你匹配到的节点为"零部件制造"。

                    - 如果你发现主营产品中与{industry_name}相关的产品描述太过于宽泛不具体，比如主营产品就只有{industry_name}，那么你需要去公司简介(company_intro)中找到这家公司是做什么的，根据这家公司是做什么的，公司的业务，产品描述，再去已有的产业链节点{nodes}中找是否有能匹配上的节点，匹配规则是公司简介描述的内容和已有的产业链节点{nodes}之间可能是包含关系，组成关系或者关联关系。
                    比如：公司的主营产品包括新能源汽车，你不好判断出他具体的业务产品是什么，于是你去公司简介中找到这家公司是提供新能源汽车技术培训和人才培养的，于是你分析出这属于新能源汽车产业链的下游销售与服务环节，根据关联性，你应该去已有的产业链节点{nodes}中找与销售服务环节意思最为接近的节点，于是你匹配到的节点为"销售与服务"。
                    再比如：公司的主营产品包括新能源汽车产品，你不好判断出他具体的产品指的是什么，于是你去公司简介中找到这家公司多年来专注于为新能源汽车零件提供同步开发工艺优化验证制造等多元一体化的制造服务，于是你分析出这些涉及到新能源汽车上游的零部件制造以及下游的销售服务环节，你应该去已有的产业链节点{nodes}中找与零部件制造以及销售服务环节意思最为接近的节点，于是你匹配到的节点为"零部件制造"和"销售与服务"。

                    - 如果公司简介(company_intro)和公司主营产品(major_product)中都没有内容，那么你需要根据公司名称(company_name)和你的分析技能去已有的产业链节点{nodes}中找是否有能匹配上的节点。

                    - 请你严格遵守我提供的硬规则{rules}中的内容。

                请你以JSON格式返回结果，例如：

                {{
                    "企业名称": "广州宇曦电子科技有限公司",
                    "主营产品": "锂电池充电器",
                    "企业网站": "http://www.ytechate.com/",
                    "公司简介": "广州宇曦电子科技有限公司是国内一家专业定制化电源及测试系统的高新技术企业，公司集研发、生产、销售、服务于一体。",
                    "匹配节点": ["充电设施","销售与服务"],
                    "产业链定义": "新能源汽车产业链是指与新能源汽车相关的一系列产品和服务的生产、供应、销售等环节所构成的网络。这个产业链涵盖了从原材料的开采和加工，到新能源汽车的设计、制造、销售、使用、维护，直至最终的回收和再利用等各个环节.",
                    "节点定义": "充电设施包括车企主导的充电设施服务和公共充电服务商为主导的充电设施服务.|销售与服务包括整车销售、售后服务、维修保养等.",
                    "匹配原因": "从主营产品中可以看到锂电池充电器是充电设施中的一个重要组成部分，所以匹配节点为充电设施；结合公司简介来看，公司集研发、生产、销售、服务于一体，所以匹配节点为销售与服务。",
                    "certainty": "1"
                }}

                特别注意：
                1.结果中的"匹配节点"只返回我提供的产业链节点中存在的节点{nodes}，不要出现主营产品中提到的但是我提供的产业链节点中{nodes}不存在的，也不要出现公司简介中提到的但是我提供的产业链节点{nodes}中不存在的。
                2.你在结合公司简介和主营产品匹配我提供的产业链节点的时候，要尽可能的全面。也就是说如果主营产品或者公司简介涉及到我提供的产业链{nodes}中的某个节点，那么不仅要匹配出这个大的节点，还要进一步细化，在{nodes}中找出这个节点下与主营产品以及公司简介相关的子节点。
                比如：主营产品包括"精密连接器, 精密注塑模具, 精密冲压模具, 精密注塑件, 精密冲压件"，已有产业链的节点包括"连接器,零部件制造"，你首先分析出主营产品包括的这些都属于新能源汽车零部件制造的一部分，所以匹配出节点为"零部件制造"，接下来你要继续对主营产品中的每部分进行匹配，你发现精密连接器可以匹配上"连接器"这个节点，因此匹配到的节点应该有两个，分别是"零部件制造"和"连接器"。
                3.你要严格遵循我提供的产业链节点{nodes}去匹配，不要自行总结或推断新的节点，导致匹配节点不在我提供的产业链节点{nodes}中。
                4.如果公司简介或者主营产品与{industry_name}无关或者没有在{nodes}中找到合适的匹配节点，那么结果中的"匹配节点"以及"节点定义"都返回"无"不要返回"其他"，并且在结果中的"匹配原因"中说明原因.
                5.结果中的"certainty"是我上边给你提供的置信度(certainty)这个字段的值，不是你自己判断出来的置信度。

                需要再次强调的是，绝对不能出现匹配节点{nodes}以外的节点！下面开始：
                '''

                args = (row, nodes, rules, system_prompt_new)
                if industry_name not in results:
                    results[industry_name] = []
                results[industry_name].append(executor.submit(process_row_new, *args))

    # 等待所有任务完成并收集结果
    industry_data = {}
    for industry_name, futures in results.items():
        industry_results = []
        for future in futures:
            result = future.result()
            if result is not None:
                try:
                    result_json = json.loads(result.replace("```", "").replace("json", ""))
                    industry_results.append(result_json)
                except Exception as e:
                    print("result_json格式有问题", result, e)
        if industry_results:
            industry_data[industry_name] = industry_results

    # 为每个产业链创建一个Excel文件
    for industry_name, data in industry_data.items():
        output_file_path = f'outputFiles/company_nodesV3_{industry_name}.xlsx'
        industry_df = pd.DataFrame(data)
        with pd.ExcelWriter(output_file_path, engine='xlsxwriter') as writer:
            industry_df.to_excel(writer, sheet_name=f'company_with_nodes_{industry_name}', index=False)
        print(f"数据已写入文件: company_nodesV3_{industry_name}.xlsx")

        # # 校验匹配节点并将结果保存到Excel文件中
        # validated_results = []
        # for result in results:
        #     if result is not None:
        #         try:
        #             result_json = json.loads(result.replace("```", "").replace("json", ""))
        #             if '匹配节点' in result_json:
        #                 result_json['匹配节点'] = validate_matching_nodes(result_json['匹配节点'], nodes)
        #             validated_results.append(result_json)
        #         except:
        #             print("result_json格式有问题", result)

 


    end_time = time.time()
    print(f"代码运行总时间：{end_time - start_time}")
