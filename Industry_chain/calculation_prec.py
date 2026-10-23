import json

node_evaluation='''{'动力电池': '中游', '锂电池': '中游', '氢燃料电池': '中游', '电机': '中游', '电控系统': '中游', '电池材料': '上游', '正极材料': '上游', '负极材料': '上游', '电解液': '上游', '隔膜': '上游', '电池管理系统（BMS）': '中游', '驱动电机': '中游', '永磁体': '上游', '硅钢': '上游', '绕组': '上游', '电驱动总成': '中游', '整车制造': '下游', '纯电动汽车': '下游', '油电混合动力汽车': '下游', '燃料电池汽车': '下游', '充电桩': '下游', '电池回收业务': '下游', '销售渠道': '下游', '大型商超': '下游', '品牌专卖店': '下游', '售后服务': '下游', '充换电服务': '下游', '汽车销售': '下游', '车身及其附件': '下游', '底盘': '下游', '车用电子器件': '上游', '内饰件': '下游', '电子元器件': '上游', '传感器': '上游', '处理器': '上游', '软件算法': '上游', '通信模块': '上游', '显示屏': '上游', 'ABS': '中游', 'ESP': '中游', '电子真空泵': '中游', '电芯': '中游', '电池PACK': '中游', '金属结构件': '上游', '电驱动零组件': '中游', '高压储氢瓶': '中游', '储氢系统': '中游', '膜电极': '中游', '双极板': '中游', '电堆': '中游', '燃料电池电堆': '中游', '燃料电池动力系统总成': '中游'}
'''
refer_content = """
{"code":200,"message":"操作成功","data":[{"value":1,"label":"产业链上游","children":[{"value":2,"label":"核心部件","children":[{"value":3,"label":"动力电池","children":null},{"value":4,"label":"驱动电机","children":null},{"value":5,"label":"电机控制器","children":null}]},{"value":6,"label":"核心原材料与元器件","children":[{"value":7,"label":"电池核心原材料","children":null},{"value":8,"label":"核心元器件","children":null}]},{"value":9,"label":"传统零部件","children":[{"value":10,"label":"车身和内外饰系统","children":null},{"value":11,"label":"底盘系统","children":null},{"value":12,"label":"电子电气系统","children":null}]}]},{"value":13,"label":"产业链中游","children":[{"value":14,"label":"汽车设计服务","children":null},{"value":15,"label":"新能源汽车整车制造","children":null}]},{"value":16,"label":"产业链下游","children":[{"value":17,"label":"新能源汽车服务","children":[{"value":18,"label":"充换电服务","children":null},{"value":19,"label":"出行服务","children":null},{"value":20,"label":"汽车行业服务","children":null},{"value":21,"label":"燃料电池汽车加氢站","children":null},{"value":22,"label":"数据服务","children":null},{"value":23,"label":"维修保养","children":null}]}]}]}
"""

# 将单引号替换为双引号，以符合JSON格式
node_evaluation = node_evaluation.replace("'", '"')
print(node_evaluation)

# 解析node_evaluation字符串为Python字典
node_evaluation_dict = json.loads(node_evaluation)
print(node_evaluation_dict)

# 解析refer_content中的最细一级标签及其对应的第一级标签
refer_json = json.loads(refer_content)
print(refer_json)

# 直接访问一级的label值
industry_label = refer_json['data'][0]['label']
print(industry_label)

# 构建一个映射，将最细一级的label映射到其第一级label
label_mapping = {}
def build_label_mapping(data, parent_label=None):
    for item in data:
        if 'children' in item and item['children'] is not None:
            # 如果存在子节点，将父级label作为映射的key，产业链X作为value
            label_mapping[item['label']] = parent_label
            build_label_mapping(item['children'], item['label'])
        else:
            # 如果没有子节点，将该节点label映射到其对应的第一级label
            label_mapping[item['label']] = parent_label

# 从refer_json中提取最细一级标签及其对应的第一级标签
build_label_mapping(refer_json['data'][0]['label'])

# 找出共有的节点
matching_nodes = [node for node in node_evaluation_dict if node in label_mapping]
print(matching_nodes)

# 检查node_evaluation中的每个节点对应的值是否与refer_content中相同内容的label对应的第一级label一致
correct_matches = 0
total_matches = len(matching_nodes)

for node in matching_nodes:
    expected_value = label_mapping[node]  # 从映射中获取第一级label
    actual_value = node_evaluation_dict[node]  # node_evaluation中的值
    if actual_value == expected_value:
        correct_matches += 1

# 计算正确率
accuracy = (correct_matches / total_matches) * 100 if total_matches > 0 else 0

# 输出结果
print(f"匹配的节点数：{total_matches}")
print(f"正确的匹配数：{correct_matches}")
print(f"正确率：{accuracy:.2f}%")