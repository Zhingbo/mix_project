# -*- coding: utf-8 -*-
p = "steps/step6_top_company_match.py"
s = open(p, encoding="utf-8").read()

# 1) 在 nodes_definitions_str 行后加入 special_rule 定义
old1 = '    nodes_definitions_str = "; ".join([f"{node}: {nodes_definitions[node]}" for node in nodes])'
new1 = old1 + '\n\n    special_rule = ""\n    if industry_name == \'生命健康\':\n        special_rule = \'\\n- 特别规则：企业名称含"药房"或"药铺"的，必须匹配到下游节点（如线下药店、医疗流通），不要匹配到中游的药品研发与生产、化学药、中药、生物药\''
assert old1 in s, "nodes_definitions_str 未找到"
s = s.replace(old1, new1, 1)

# 2) 在"匹配关系"行后注入 {special_rule}
old2 = '- 匹配关系可能是：包含关系、组成关系、关联关系'
new2 = '- 匹配关系可能是：包含关系、组成关系、关联关系{special_rule}'
assert old2 in s, "匹配关系行未找到"
s = s.replace(old2, new2, 1)

open(p, "w", encoding="utf-8").write(s)
print("step6 pharm patch applied")
