# -*- coding: utf-8 -*-
# step3 修复: 前沿节点找不到精确行业时返回"无匹配", 不落宽类
p = "step3_match_industryry.py"
s = open(p, encoding="utf-8").read()

# 1) prompt: 加"无匹配"规则(第一个注意块)
old1 = "- **重要：你只能在行业名称库{names}中选择行业名称，严禁创造或使用不在库中的行业名称。**"
new1 = (old1 + "\n"
        "        - **如果某个节点在行业名称库中找不到精确、直接相关的行业（只能找到\"其他XX\"、\"其他专用设备/其他批发业/其他未列明\"这类过于宽泛、无法区分该节点的兜底类别），请在该节点的\"行业名称\"字段返回\"无匹配\"，不要强行匹配宽泛类别。**")
assert old1 in s, "old1 未找到"
s = s.replace(old1, new1, 1)

# 2) prompt: "必须返回匹配" -> "可返回无匹配"
old2 = "2. 必须为每个给定的节点都返回匹配结果，不要遗漏"
new2 = "2. 对每个给定的节点都返回结果，但\"行业名称\"可以是\"无匹配\"（表示找不到精确相关的行业，不要强行匹配宽泛类别）"
assert old2 in s, "old2 未找到"
s = s.replace(old2, new2, 1)

# 3) _validate_match_item: 加兜底宽类校验
old3 = """    if industry_name not in name_info:
        logger.warning(f"AI返回的行业名称 '{industry_name}' 不在行业名称库中，节点：{node_name}")
        return None
"""
new3 = old3 + """
    # 跳过兜底宽类(一级是"其他" 或 三级是"其他..."): 前沿节点找不到精确行业时避免落宽类导致下游爆炸
    _lv, _fn = name_info.get(industry_name, (None, None))
    if _fn:
        _fn = str(_fn)
        _segs = _fn.split('|')
        if _fn.startswith('其他|') or (len(_segs) >= 3 and _segs[-1].startswith('其他')):
            logger.info(f"节点 {node_name} 映射到兜底宽类 '{_fn}'，跳过(视为无精确匹配)")
            return None
"""
assert old3 in s, "old3 未找到"
s = s.replace(old3, new3, 1)

open(p, "w", encoding="utf-8").write(s)
print("step3 已修复")