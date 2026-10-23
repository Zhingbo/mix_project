# -*- coding: utf-8 -*-
# step3 加强: 前沿修饰词 + 通用制造宽类 -> 判无匹配跳过
p = "step3_match_industryry.py"
s = open(p, encoding="utf-8").read()

# 1) 在 _validate_match_item 函数前插入辅助函数与常量
anchor = "def _validate_match_item(item, name_info):\n"
helper = '''FRONTIER_MARKS = ["超导", "核聚变", "托卡马克", "等离子体", "量子", "脑机", "数字孪生", "元宇宙", "合成生物", "光量子", "粒子", "智能算力", "大模型", "AI芯片"]
BROAD_MANUF = ["输配电", "电机制造", "通信设备", "钢铁", "金属冶炼", "通用设备", "专用设备", "泵、阀门", "铸造", "模具", "轴承", "齿轮", "通用机械", "金属压延"]


def _is_frontier_broad(node_name, full_name):
    """前沿概念节点被配到通用制造宽类 -> 视为无精确匹配"""
    if any(m in (node_name or "") for m in FRONTIER_MARKS):
        if any(b in (full_name or "") for b in BROAD_MANUF):
            return True
    return False


def _validate_match_item(item, name_info):
'''
assert anchor in s and "_is_frontier_broad" not in s, "锚点问题"
s = s.replace(anchor, helper, 1)

# 2) 在兜底宽类校验之后, 加前沿+通用制造宽类校验
old = '''    if _fn:
        _fn = str(_fn)
        _segs = _fn.split('|')
        if _fn.startswith('其他|') or (len(_segs) >= 3 and _segs[-1].startswith('其他')):
            logger.info(f"节点 {node_name} 映射到兜底宽类 '{_fn}'，跳过(视为无精确匹配)")
            return None
'''
new = old + '''
    if _fn and _is_frontier_broad(node_name, str(_fn)):
        logger.info(f"节点 {node_name} 是前沿概念但配到通用制造宽类 '{_fn}'，跳过(视为无精确匹配)")
        return None
'''
assert old in s, "宽类校验锚点未找到"
s = s.replace(old, new, 1)

open(p, "w", encoding="utf-8").write(s)
print("step3 加强修复完成")