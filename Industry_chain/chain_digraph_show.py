from graphviz import Digraph
import os


def read_nodes(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        nodes = [line.strip() for line in f.readlines()]
    return nodes

def read_relations(file_path):
    relations = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f.readlines():
            parts = line.strip().split(',')
            if len(parts) == 3:
                relations.append((parts[0], parts[1], parts[2]))
    return relations

def classify_nodes(nodes):
    upstream_nodes = []
    midstream_nodes = []
    downstream_nodes = []
    for node in nodes:
        # 假设节点名称的格式为 "部分:名称"，例如 "上游:Node1"
        parts = node.split(':')
        if len(parts) == 2:  # 确保分割后有两个部分
            part_type, node_name = parts
            if part_type == '上游':
                upstream_nodes.append(node_name)
            elif part_type == '中游':
                midstream_nodes.append(node_name)
            elif part_type == '下游':
                downstream_nodes.append(node_name)
    return upstream_nodes, midstream_nodes, downstream_nodes

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
        # "AI大模型","装配式建筑","跨境电商","银发经济","情绪价值",
        # "量子科技","空天信息","电竞","5G-A","固态电池",
        # "商业航天","AI眼镜","北斗产业","碳纤维","智能穿戴",
        # "智能传感器","预制菜产业","高端装备制造","宠物经济","露营经济",
        # "数字创意产业","数字医疗","脑机接口","deepseek","超导"

        # "AI制药","冰雪经济","AI基础设施","特斯拉","供应链服务",
        # "地方特色食品","特钢材料","疗愈经济","本地化运营","智能算力",
        # "风电装备","铝镁精深加工"   
        "供应链服务"
]

# 遍历行业名称列表
for industry_name in industry_names:
    # 构造目标文件名
    nodes_filename = f"nodes_{industry_name}.txt"
    relations_filename = f"relations_{industry_name}.txt"

    # 遍历 resultTxt 文件夹中所有以 user 开头的文件夹
    base_dir = "resultTxt"
    user_folders = [name for name in os.listdir(base_dir) if name.startswith("user")]

    # 初始化文件路径变量
    nodes_file_path = None
    relations_file_path = None

    # 遍历每个 user 文件夹，查找目标文件
    for folder in user_folders:
        folder_path = os.path.join(base_dir, folder)
        if os.path.isdir(folder_path):  # 确保是文件夹
            nodes_path = os.path.join(folder_path, nodes_filename)
            relations_path = os.path.join(folder_path, relations_filename)
            if os.path.exists(nodes_path) and os.path.exists(relations_path):
                nodes_file_path = nodes_path
                relations_file_path = relations_path
                break  # 找到文件后退出循环

    # 检查是否找到文件
    if nodes_file_path and relations_file_path:
        # 读取文件
        nodes = read_nodes(nodes_file_path)
        relations = read_relations(relations_file_path)
        print(f"成功读取文件：\n{nodes_file_path}\n{relations_file_path}")
    else:
        print(f"未找到文件：\n{nodes_filename}\n{relations_filename}\n请检查文件夹和文件名是否正确！")

    # 分类节点
    upstream_nodes, midstream_nodes, downstream_nodes = classify_nodes(nodes)

    # 创建一个有向图
    dot = Digraph(comment=f'产业链结构图 - {industry_name}')

    # 设置图的属性，包括方向为自左而右
    dot.graph_attr['rankdir'] = 'LR'

    # 添加节点，并设置rank属性
    for node in upstream_nodes:
        dot.node(node, rank='source')
    for node in midstream_nodes:
        dot.node(node, rank='middle')
    for node in downstream_nodes:
        dot.node(node, rank='sink')

    # 添加边，但是不显示关系标签
    for relation in relations:
        dot.edge(relation[1], relation[0])

    # 输出DOT源码
    print(dot.source)

    # 保存和渲染图形，输出为PDF文件
    dot.render(f'outputFiles/{industry_name}产业链', format='pdf', cleanup=True)