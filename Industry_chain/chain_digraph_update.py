from graphviz import Digraph

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
    "电气设备", "电子器件", "医疗器械", "消费电子", 
    "集成电路", "元宇宙", "新能源汽车", "电子信息", "机械设备与零件",
    "3D打印", "卫星导航", "无人机", "大飞机", "激光",
    "汽车", "眼镜", "工业母机", "工业软件", "人工智能",
    "光伏", "合成生物", "5G", "检验检测", "储能",
    "芯片", "氢能", "低碳经济","低空经济", "能源环保", 
    "仪器仪表","装备制造", "通信设备", "半导体", "新材料", 
    "医疗美容", "大健康", "机器人", "生命健康", "生物医药",
    "无人驾驶","风电","轨道交通装备"
]

# 遍历行业名称列表
for industry_name in industry_names:
    print(industry_name)
    # 读取节点和关系数据
    try:
        nodes = read_nodes(f'resultTxt/nodes_{industry_name}.txt')
        relations = read_relations(f'resultTxt/relations_{industry_name}.txt')
    except:
        print("没有找到节点和关系文件",industry_name)    

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

    # # 输出DOT源码
    # print(dot.source)

    # 保存和渲染图形，输出为PDF文件
    dot.render(f'outputFiles/{industry_name}产业链update', view=True)