# -*- coding: utf-8 -*-
# 给 step4 的 NODE_KW_OVERRIDES 加"生物信息学分析平台"关键词过滤(合成生物)
import sys
P = "/root/mix_project/steps/step4_company_match_nodes.py"
s = open(P, encoding="utf-8").read()

anchor = '''    "具身智能": ["机器人", "具身智能"],
}'''

new = '''    "具身智能": ["机器人", "具身智能"],
    # ==== 合成生物 ====
    "生物信息学分析平台": ["生物信息", "生信", "基因", "基因组", "组学", "测序",
                   "转录组", "蛋白组", "代谢组", "分子诊断", "分子生物", "生物芯片",
                   "生命科学", "高通量", "基因检测", "基因科技"],
}'''

if anchor not in s:
    print("[FAIL] 未找到 NODE_KW_OVERRIDES 结尾锚点"); sys.exit(1)
s = s.replace(anchor, new, 1)
open(P, "w", encoding="utf-8").write(s)
print("[done] 已加 生物信息学分析平台 关键词过滤")