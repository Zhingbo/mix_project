import json

# 定义两个文件的内容
nodes_content = """
新能源汽车
动力电池
锂电池
氢燃料电池
电机
电控系统
电池材料
正极材料
负极材料
电解液
隔膜
电池管理系统（BMS）
驱动电机
永磁体
硅钢
绕组
电驱动总成
整车制造
纯电动汽车
油电混合动力汽车
燃料电池汽车
充电桩
电池回收业务
销售渠道
大型商超
品牌专卖店
售后服务
充换电服务
汽车销售
车身及其附件
底盘
车用电子器件
内饰件
电子元器件
传感器
处理器
软件算法
通信模块
显示屏
ABS
ESP
电子真空泵
电芯
电池PACK
金属结构件
电驱动零组件
高压储氢瓶
储氢系统
膜电极
双极板
电堆
燃料电池电堆
燃料电池动力系统总成
""".strip()

refer_content = """
{"code":200,"message":"操作成功","data":[{"value":1,"label":"产业链上游","children":[{"value":2,"label":"核心部件","children":[{"value":3,"label":"动力电池","children":null},{"value":4,"label":"驱动电机","children":null},{"value":5,"label":"电机控制器","children":null}]},{"value":6,"label":"核心原材料与元器件","children":[{"value":7,"label":"电池核心原材料","children":null},{"value":8,"label":"核心元器件","children":null}]},{"value":9,"label":"传统零部件","children":[{"value":10,"label":"车身和内外饰系统","children":null},{"value":11,"label":"底盘系统","children":null},{"value":12,"label":"电子电气系统","children":null}]}]},{"value":13,"label":"产业链中游","children":[{"value":14,"label":"汽车设计服务","children":null},{"value":15,"label":"新能源汽车整车制造","children":null}]},{"value":16,"label":"产业链下游","children":[{"value":17,"label":"新能源汽车服务","children":[{"value":18,"label":"充换电服务","children":null},{"value":19,"label":"出行服务","children":null},{"value":20,"label":"汽车行业服务","children":null},{"value":21,"label":"燃料电池汽车加氢站","children":null},{"value":22,"label":"数据服务","children":null},{"value":23,"label":"维修保养","children":null}]}]}]}
""".strip()

# 将字符串分割成列表
nodes = [line for line in nodes_content.split('\n') if line]

# 解析refer_content中的最细一级标签
refer_labels = set()
refer_json = json.loads(refer_content)

def extract_labels(data):
    for item in data:
        if 'children' in item and item['children'] is not None:
            for category in item['children']:
                if 'children' in category and category['children'] is None:
                    refer_labels.add(category['label'])
                else:
                    extract_labels(category['children'])
        else:
            refer_labels.add(item['label'])

extract_labels(refer_json['data'])

# 计算覆盖率
matching_nodes = sum(1 for node in nodes if node in refer_labels)
total_refer_labels = len(refer_labels)
coverage_rate = (matching_nodes / total_refer_labels) * 100 if total_refer_labels > 0 else 0

# 输出结果
print(f"覆盖的节点数：{matching_nodes}")
print(f"最细一级label总数：{total_refer_labels}")
print(f"覆盖率：{coverage_rate:.2f}%")

# 计算匹配的节点
matching_nodes = [node for node in nodes if node in refer_labels]

# 输出覆盖的节点名字
print("覆盖的节点名字：")
for node in matching_nodes:
    print(node)