import requests
from openai import OpenAI
import os
import csv
import logging
from neo4j import GraphDatabase
import time


industry_name = '大健康'

def google_search(industry_name):
    url = "https://google-search74.p.rapidapi.com/"
    headers = {
        "x-rapidapi-key": os.getenv("RAPIDAPI_KEY_B"),
        "x-rapidapi-host": "google-search74.p.rapidapi.com"
    }
    
    querystring = {"query": industry_name + "的产业链相关信息", "limit": "3", "related_keywords": "true"}
    try:
        response = requests.get(url, headers=headers, params=querystring)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error during requests to {url}: {e}")
        return None

def google_nodes_search(industry_name,node):
    url = "https://google-search74.p.rapidapi.com/"
    headers = {
        "x-rapidapi-key": os.getenv("RAPIDAPI_KEY_B"),
        "x-rapidapi-host": "google-search74.p.rapidapi.com"
    }
    
    querystring = {"query": industry_name + "相关的%s产业链信息" % node, "limit": "2", "related_keywords": "true"}
    try:
        response = requests.get(url, headers=headers, params=querystring)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error during requests to {url}: {e}")
        return None

def fetch_entity_completion(content, industry_name):
    client = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com/beta")
    prompts = """
        请从这些搜索结果中找出与%s产业链相关的实体，实体越多越好。输出格式示例如下：
        "眼镜\n镜架\n镜片\n鼻托\n螺丝\n..."
        注意：
            1.输出结果严格按照上述格式返回，除了这些实体不要返回任何其他内容，比如："以下是眼镜产业链的相关信息","这些信息涵盖了眼镜产业链"等等，这些总结或者阐述方面的内容都不要返回到结果中。
            2.输出结果不要返回任何标点符号，比如："-","(",")"等等。
        """
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": prompts % (industry_name)},
            {"role": "user", "content": content},
        ],
        stream=False,
        max_tokens=8000
    )

    return response.choices[0].message.content

def fetch_nodes_completion(nodescontent, industry_name,node):
    client = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com/beta")
    prompts = """
        你是一个产业链分析专家,也是一个构建产业链知识图谱的专家。请从这些搜索结果中找出与%s相关的%s信息，并做如下处理：
        识别重复或相似的内容，并决定哪些内容应该合并。资料中的内容可能在格式或内容上略有不同，但基本上指的是同一件事。
        使用你的分析技能来确定重复或者相似的内容并将他们整合为一种表达方式。
        另外，资料中的内容可能含有与构建%s产业链知识图谱无关的内容，你应该将这些内容剔除掉。

        举例说明，假如文章中提到："眼镜行业的产业链上游主要包括原材料的生产和供应，如玻璃、树脂、塑料橡胶、金属材料和包装材料。",
        文章中还提到："眼镜行业的产业链上游包括原材料生产：包括镜片材料（如树脂、玻璃、水晶石、塑料等）和镜架材料（如板材、塑料、TR、纯钛、钛合金、其他金属架、其他合金架、硅胶、玳瑁壳、贵金属镜架等）。"。
        我们可以看到，以上内容中说的都是原材料生产这个事，并且有重复信息，所以我们需要将他们的内容合并在一起。

        再举例说明，假如文章中提到："湿法隔膜的均价为1.35元/平方米，干法隔膜的均价为0.95元/平方米"。
        我们可以看到此内容与构建产业链知识图谱无关，那么我们需要将这部分信息剔除掉。

        最后，请返回按照上述要求处理后的结果。
        """
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": prompts % (industry_name,node,industry_name)},
            {"role": "user", "content": nodescontent},
        ],
        stream=False,
        max_tokens=8000
    )

    return response.choices[0].message.content

def fetch_center_node(content, industry_name):
    client = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com/beta")
    prompts = """
        你是一个产业链分析专家,也是一个构建产业链知识图谱的专家。请从这些搜索结果中找出与%s产业链相关的信息，并做如下处理：
        识别重复或相似的内容，并决定哪些内容应该合并。资料中的内容可能在格式或内容上略有不同，但基本上指的是同一件事。
        使用你的分析技能来确定重复或者相似的内容并将他们整合为一种表达方式。
        另外，资料中的内容可能含有与构建%s产业链知识图谱无关的内容，你应该将这些内容剔除掉。

        举例说明，假如文章中提到："眼镜行业的产业链上游主要包括原材料的生产和供应，如玻璃、树脂、塑料橡胶、金属材料和包装材料。",
        文章中还提到："眼镜行业的产业链上游包括原材料生产：包括镜片材料（如树脂、玻璃、水晶石、塑料等）和镜架材料（如板材、塑料、TR、纯钛、钛合金、其他金属架、其他合金架、硅胶、玳瑁壳、贵金属镜架等）。"。
        我们可以看到，以上内容中说的都是原材料生产这个事，并且有重复信息，所以我们需要将他们的内容合并在一起。

        再举例说明，假如文章中提到："湿法隔膜的均价为1.35元/平方米，干法隔膜的均价为0.95元/平方米"。
        我们可以看到此内容与构建产业链知识图谱无关，那么我们需要将这部分信息剔除掉。

        最后，请返回按照上述要求处理后的结果。
        """
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": prompts % (industry_name,industry_name)},
            {"role": "user", "content": content},
        ],
        stream=False,
        max_tokens=8000
    )

    return response.choices[0].message.content

def process_entity_info(industry_name):
    deepseek_info = str(google_search(industry_name))
    print(deepseek_info)
    if deepseek_info != 'None':
        webinfo = fetch_entity_completion(deepseek_info, industry_name)   # 网页摘要提取的结果
        print(webinfo)
        return webinfo
    return []

def process_nodes_info(industry_name,node):
    deepseek_info = str(google_nodes_search(industry_name,node))
    print(deepseek_info)
    if deepseek_info != 'None':
        webinfo = fetch_nodes_completion(deepseek_info, industry_name,node)   # 网页摘要提取的结果
        print(webinfo)
        return webinfo
    return []

def process_center_node(industry_name):
    deepseek_info = str(google_search(industry_name))
    print(deepseek_info)
    if deepseek_info != 'None':
        webinfo = fetch_center_node(deepseek_info, industry_name)   # 网页摘要提取的结果
        print(webinfo)
        return webinfo
    return []

def fetch_relations_completion(base_info, industry_name):
    client = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com/beta")
    prompts = """
                你是一个产业链分析专家,也是一个构建产业链知识图谱的专家。用户输入的资料中，最开始为中心节点%s产业链的相关资料，之后为%s产业链其他相关节点的资料。
                你需要总结出以%s为中心节点的产业链上中下游的所有节点，首先总结出%s，上游，中游，下游这四个节点，然后可以按照从成品到原材料，再到原材料的原材料的逻辑关系，分别总结出其他所有节点,最后总结出这些节点的关系三元组。
                总结节点关系三元组的时候，你按照逐步抽象法去总结，这种方法从宏观的角度出发，逐步细化到微观层面，通过逐层深入的方式构建知识图谱。
                比如新能源汽车产业链，首先总结出"上游,新能源汽车,part-of",然后再总结出"动力电池,上游,part-of"，然后再总结出"正负极材料,动力电池,part-of"，最后总结出"锂矿,正负极材料,is-a"。
                节点的关系三元组格式为:起始节点,结束节点,关系类型。
                起始节点表示下一级的节点，结束节点表示上一级的节点。比如锂电池是电池的下一级节点，那么他们的关系格式应该表示为“锂电池,电池,is-a”而不是“电池,锂电池,is-a”。
                关系类型包括:part-of(表明了一种构成关系,表示起始节点是结束节点的一部分),is-a(说明了一种分类关系,表示起始节点是结束节点的一个种类或实例)。
                例如,如果有一个节点是“锂电池”,另一个节点是“电池”,那么它们之间的关系可以表示为“锂电池,电池,is-a”,意味着锂电池是电池的一种。
                再例如,如果有一个节点是“电芯”,另一个节点是“电池”,那么它们之间的关系可以表示为“电芯,电池,part-of”,意味着电芯是电池的一部分。
                
                注意:
                1) 具体的节点仅有一次作为起始节点,不能多个起始节点同时指向相同的结束节点。
                2) 输出结果包括两部分,第一部分是所有具体的节点,第二部分是节点的关系三元组。
                   具体节点以及三元组输出结果都是直接输出结果内容即可,不需要对结果内容标注数字序号。比如具体节点不要输出"1. 动力电池"而是要输出"动力电池".三元组不要输出"1. 动力电池,电池材料,part-of"而是要输出"动力电池,电池材料,part-of"。
                3) 如果你总结出的节点中有重复项或者意思相近，不要把他们作为单独节点，而是将他们合并。比如：节点"车身"以及节点"车身及其附件"，那么只保留"车身及其附件"，舍弃掉"车身"这个节点，并且"车身"这个节点下如果还有其他展开的节点也一并归入"车身及其附件"下。
                4) 用户输入的资料是一篇完整的大文章，总结节点的时候不要将每一部分独立开来，一定要分析出各部分之间的关系并将他们联系起来。对于找不到联系的部分直接剔除掉。
                5) 中心节点只有一个，那就是%s，它只能是结束节点。
                6) 除了中心节点外，其他节点一定要有结束节点，否则会出现知识图谱中边的丢失。
                7) 你总结出来的节点一定不要有重复的。
                8) 你总结出来的三元组也一定不要有重复的。
                9) %s，上游，中游和下游这四个节点一定要返回到输出结果中，并且上游，中游和下游与中心节点构成三个三元组，即"上游,%s,part-of","中游,%s,part-of","下游,%s,part-of"。
                    这是必须要有的三个三元组。
                10) 除了上游，中游和下游其余节点都不能与%s这个中心节点建立关系，也就是说其余节点的结束节点都不能是%s。
                11) 总结出的节点名字中不要含有"产业链"这三个字。
                12) 总结出的节点不要有类似"供需平衡"这种不属于产业链的某个具体部分的。
                13) 总结出的节点不要有公司名字。


                需要特别注意的是：整个产业链节点关系不能有断点，不能有独立的丢失关系的节点。

                以下是⼀个具体例⼦，仅供参考:
                "
                假设用户输入的资料都是汽车相关的信息,那么以汽车为中心节点的产业链输出结果为:
                具体节点
                汽车
                上游
                中游
                下游
                整车制造
                蓄电池
                锂电池
                氢燃料电池
                同步电机
                异步电机
                电池
                动⼒系统
                电机

                节点关系三元组:
                电池,上游,part-of
                电机,上游,part-of
                动⼒系统,上游,part-of
                整车制造,中游,part-of
                上游,汽车,part-of
                中游,汽车,part-of
                下游,汽车,part-of
                蓄电池,电池,is-a
                锂电池,电池,is-a
                氢燃料电池,电池,is-a
                同步电机,电机,is-a
                异步电机,电机,is-a
                电池,动⼒系统,part-of
                电机,动⼒系统,part-of
                "
        """
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": prompts % (industry_name,industry_name,industry_name,industry_name,industry_name,industry_name,industry_name,industry_name,industry_name,industry_name,industry_name)},
            {"role": "user", "content": base_info},
        ],
        stream=False,
        max_tokens=8000
    )

    return response.choices[0].message.content

def create_nodes(tx, nodes):
    for node in nodes:
        tx.run("MERGE (n:`%s` {name: $name})"%(industry_name), name=node)

def create_relationships(tx, relationships):
    for rel in relationships:
        source, target, relation_type = rel
        tx.run("""
            MATCH (a:`%s` {name: $source})
            OPTIONAL MATCH (b:`%s` {name: $target})
            MERGE (a)-[:`%s`]->(b)
            """%(industry_name, industry_name, relation_type),
            source=source, target=target)  

if __name__ == "__main__":
    start_time = time.time()
    industry_nodes = process_entity_info(industry_name)
    info = [node for node in industry_nodes.split("\n")]
    result = process_center_node(industry_name)

    # 确保result是一个列表，如果不是，则将其转换为列表
    if not isinstance(result, list):
        result = [result]    

    for node in info:
        search_result = process_nodes_info(industry_name, node)
        if search_result not in result:
            result.append(search_result)
        print(f'{node}已搜索完成')

    # 调用crawling_new.py中的crawl_data函数，并获取结果
    from crawling_new import crawl_data
    crawl_result = crawl_data(industry_name) 
    if crawl_result not in result:
        result.append(crawl_result)

    # # 调用crawling_new.
    # from crawling_new import crawl_data_org
    # crawl_result2 = crawl_data_org(industry_name) 
    # if crawl_result2 not in result:
    #     result.append(crawl_result2)  

    # 调用getdata_with_image.py中的process_images函数，并获取结果
    from getdata_with_image import process_images
    crawl_result3 = process_images(industry_name)
    if crawl_result3 not in result:
        result.append(crawl_result3)  

    str_result = [str(item) for item in result]
    s = '\n'.join(str_result)

    with open('resultTxt/base_info.txt','w',encoding='utf-8') as f:
        f.write(s)

    with open('resultTxt/base_info.txt', 'r', encoding='utf-8') as f:
        org_input = f.read()
    print(org_input)        

    org_output=fetch_relations_completion(org_input,industry_name)
    print(org_output)

    # 提取"### 具体节点"后"### 节点关系三元组"前的内容
    nodes_content = []
    relation_content = []

    # 标识符，用于确定当前正在提取哪个部分的内容
    is_nodes_section = False
    is_relation_section = False

    for line in org_output.split('\n'):
        if '具体节点' in line:
            is_nodes_section = True
            is_relation_section = False
        elif '节点关系三元组' in line:
            is_nodes_section = False
            is_relation_section = True
        elif is_nodes_section and line.strip():  # 忽略空行
            nodes_content.append(line)
        elif is_relation_section and line.strip():  # 忽略空行
            relation_content.append(line)

    # 移除nodes_content和relation_content列表中每个字符串的尾部空格
    nodes_content = [line.rstrip() for line in nodes_content]
    relation_content = [line.rstrip() for line in relation_content]

    # 将提取的内容写入nodes.txt和relations.txt文件
    with open(f'resultTxt/nodes_{industry_name}.txt', 'w', encoding='utf-8') as f_nodes:
        f_nodes.write('\n'.join(nodes_content).rstrip()) 

    with open(f'resultTxt/relations_{industry_name}.txt', 'w', encoding='utf-8') as f_relations:
        f_relations.write('\n'.join(relation_content).rstrip())  

    # 设置日志级别为 ERROR，忽略 WARNING 和 INFO 级别的日志
    logging.basicConfig(level=logging.ERROR)

    # 连接到 Neo4j 数据库
    uri = "bolt://8.141.19.136:7801"
    user = "neo4j"
    password = os.getenv("NEO4J_PASSWORD")

    driver = GraphDatabase.driver(uri, auth=(user, password))        

    # 只删除标签为industry_name的节点及其关系
    with driver.session() as session:
        session.run(f"MATCH (n:`{industry_name}`) DETACH DELETE n")

    # 读取节点文件
    with open(f'resultTxt/nodes_{industry_name}.txt', newline='', encoding='utf-8') as csvfile:
        reader = csv.reader(csvfile)
        nodes = [row[0] for row in reader]

    # 读取关系文件
    with open(f'resultTxt/relations_{industry_name}.txt', newline='', encoding='utf-8') as csvfile:
        reader = csv.reader(csvfile)
        relationships = [row for row in reader]

    with driver.session() as session:
        # 创建节点
        session.write_transaction(create_nodes, nodes)
        # 创建关系
        session.write_transaction(create_relationships, relationships)

    end_time = time.time()
    print(f"代码运行总时间：{end_time - start_time}")    
      