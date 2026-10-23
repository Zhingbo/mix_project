# -*- coding: utf-8 -*-
# step4 加"产业链主题关键词"机制: 泛环节(维修/检修等)用主题词收窄, 避免脱离主题过匹配
import sys
P = "/root/mix_project/steps/step4_company_match_nodes.py"
s = open(P, encoding="utf-8").read()

# 1. 在 NODE_KW_OVERRIDES 之后插入 CHAIN_THEME_KEYWORDS + GENERIC_NODE_WORDS
anchor = '''    "生物信息学分析平台": ["生物信息", "生信", "基因", "基因组", "组学", "测序",
                   "转录组", "蛋白组", "代谢组", "分子诊断", "分子生物", "生物芯片",
                   "生命科学", "高通量", "基因检测", "基因科技"],
}'''

insert = '''
# 产业链主题关键词(泛环节收窄用: 环节名含泛词时, 用主题词过滤企业名, 避免脱离主题过匹配)
CHAIN_THEME_KEYWORDS = {
    '大飞机': ['航空', '飞机', '机场', '航天', '民航', '机务', '飞行', '无人机', '直升机', '航空器', '航材', '客机'],
}

# 泛化环节词(含这些词的环节, 若未配置节点关键词, 则用产业链主题关键词收窄)
GENERIC_NODE_WORDS = ['维修', '检修', '修理', '维护']'''

if anchor not in s:
    print("[FAIL] 未找到 NODE_KW_OVERRIDES 结尾"); sys.exit(1)
s = s.replace(anchor, anchor + insert, 1)
print("[ok] 已插入主题关键词配置")

# 2. 修改 node_kws 计算: 泛环节用主题词
old = '''        node_name = str(row_b['nodes'])
        node_kws = NODE_KW_OVERRIDES.get(node_name)
        if node_kws is None:
            _nkw = str(row_b['nodes'])
            for _w in ['汽车', '整车', '车辆', '制造', '系统', '技术', '零部件', '服务', '车', '产业', '核心']:
                _nkw = _nkw.replace(_w, '')
            node_kws = [_nkw.strip('，,、- ')] if len(_nkw.strip('，,、- ')) >= 2 else []'''
new = '''        node_name = str(row_b['nodes'])
        node_kws = NODE_KW_OVERRIDES.get(node_name)
        if node_kws is None:
            # 泛化环节(含维修/检修等泛词) -> 用产业链主题关键词收窄
            if any(w in node_name for w in GENERIC_NODE_WORDS):
                node_kws = CHAIN_THEME_KEYWORDS.get(industry_name, [])
            if not node_kws:
                _nkw = str(row_b['nodes'])
                for _w in ['汽车', '整车', '车辆', '制造', '系统', '技术', '零部件', '服务', '车', '产业', '核心']:
                    _nkw = _nkw.replace(_w, '')
                node_kws = [_nkw.strip('，,、- ')] if len(_nkw.strip('，,、- ')) >= 2 else []'''
if old not in s:
    print("[FAIL] 未找到 node_kws 计算块"); sys.exit(1)
s = s.replace(old, new, 1)
print("[ok] 已改 node_kws 计算")

open(P, "w", encoding="utf-8").write(s)
print("[done]")