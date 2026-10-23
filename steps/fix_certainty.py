# -*- coding: utf-8 -*-
# 修复: confidence None -> 1 (代码层根因)
import sys

def fix(path, old, new):
    s = open(path, encoding="utf-8").read()
    c = s.count(old)
    print(f"{path}: 命中 {c} 处")
    if c == 0:
        print("  未找到,跳过")
        return
    s = s.replace(old, new)
    open(path, "w", encoding="utf-8").write(s)
    print("  已替换")

# step9: str(row['score']) -> None/空/'None'/'nan' 默认 "1"
fix(
    "step9_export_finallist.py",
    "str(row['score'])",
    "('1' if row['score'] is None or str(row['score']).strip() in ('', 'None', 'nan') else str(row['score']))",
)

# step4 (两个文件): certainty 为 None 时默认 "1"
for p in ("step4_company_match_nodes.py", "step4_company_match_nodes_v2.py"):
    fix(p, "'certainty': certainty,", "'certainty': (certainty if certainty else '1'),")