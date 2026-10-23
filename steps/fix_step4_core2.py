# -*- coding: utf-8 -*-
# 修正 step4 核心词过滤的三处问题: 未转义引号 / nodes_rows 提前用 / SQL 锚点漏 AND
def fix(p):
    s = open(p, encoding="utf-8").read()
    n0 = s
    # 1) "2. 不要给"制造/设备..." -> 「...」(修未转义引号)
    s = s.replace('不要给"制造/设备/科技/工程/系统/材料/能源"这类', '不要给「制造/设备/科技/工程/系统/材料/能源」这类')
    # 2) core_names 用 df_b 而非 nodes_rows(后者在本行之后才定义)
    s = s.replace("for _, r in nodes_rows]))", "for _, r in df_b.iterrows()]))")
    # 3) SQL 加 core_filter(带 AND 的锚点)
    old = "          AND (a.industry_class_third LIKE '%强%' OR a.industry_class_third LIKE '%中%')\n          {domain_filter}\n"
    new = "          AND (a.industry_class_third LIKE '%强%' OR a.industry_class_third LIKE '%中%')\n          {domain_filter}\n          {core_filter}\n"
    if old in s:
        s = s.replace(old, new, 1)
    else:
        print(p, "!! SQL锚点仍未匹配")
    if s != n0:
        open(p, "w", encoding="utf-8").write(s)
        print(p, "已修正")
    else:
        print(p, "无变化")

for p in ("step4_company_match_nodes.py", "step4_company_match_nodes_v2.py"):
    fix(p)
print("done")