# -*- coding: utf-8 -*-
# step4: 去掉"节点名->公司名"的通用过滤(欠匹配根因), 只保留 手动关键词 + 主题词 两类主动过滤
import sys
P = "/root/mix_project/steps/step4_company_match_nodes.py"
s = open(P, encoding="utf-8").read()

old = '''    if node_kws is None:
            # 泛化环节(含维修/检修等泛词) -> 用产业链主题关键词收窄
            if any(w in node_name for w in GENERIC_NODE_WORDS):
                node_kws = CHAIN_THEME_KEYWORDS.get(industry_name, [])
            if not node_kws:
                _nkw = str(row_b['nodes'])
                for _w in ['汽车', '整车', '车辆', '制造', '系统', '技术', '零部件', '服务', '车', '产业', '核心']:
                    _nkw = _nkw.replace(_w, '')
                node_kws = [_nkw.strip('，,、- ')] if len(_nkw.strip('，,、- ')) >= 2 else []'''

new = '''    if node_kws is None:
            # 泛化环节(含维修/检修等泛词) -> 用产业链主题关键词收窄
            if any(w in node_name for w in GENERIC_NODE_WORDS):
                node_kws = CHAIN_THEME_KEYWORDS.get(industry_name, [])
            # 其余节点: 不再用节点名过滤公司名(节点名≠公司名, 避免欠匹配),
            # 完全信任 step3 的行业映射 + 手动覆盖字典'''

if old not in s:
    print("[FAIL] 未找到目标块"); sys.exit(1)
s = s.replace(old, new, 1)
open(P, "w", encoding="utf-8").write(s)
print("[done] 已去掉节点名通用过滤")