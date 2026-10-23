# -*- coding: utf-8 -*-
# 还原: 移除"前沿链跳过 step3"的逻辑, 保留 无匹配 + 前沿词/宽类 两轮过滤
p = "step3_match_industryry.py"
s = open(p, encoding="utf-8").read()

# 1) 移除 FRONTIER_CHAINS 常量块
old1 = '''# 前沿链(国标/联东A没有精确门类, 底表行业匹配不可靠), 跳过 step3 映射
FRONTIER_CHAINS = {"可控核聚变", "工业元宇宙", "AI智能算力", "人工智能", "工业软件", "合成生物",
                   "量子科技", "脑机接口", "5G", "低空经济", "商业航天", "生物医药"}


def _validate_match_item(item, name_info):
'''
new1 = '''def _validate_match_item(item, name_info):
'''
assert old1 in s, "FRONTIER_CHAINS 常量块未找到"
s = s.replace(old1, new1, 1)

# 2) 移除 step3 函数开头的 skip
old2 = '''def step3_match_industryry(industry_name, tables, whitelist_data=None, progress_callback=None, change_context=None):
    if industry_name in FRONTIER_CHAINS:
        print(f"产业链 '{industry_name}' 是前沿链(国标/联东A无精确门类)，跳过底表行业匹配；企业将主要来自白名单+LLM搜头部(step6)")
        return []
    """步骤3：节点匹配行业（批量优化版）"""'''
new2 = '''def step3_match_industryry(industry_name, tables, whitelist_data=None, progress_callback=None, change_context=None):
    """步骤3：节点匹配行业（批量优化版）"""'''
assert old2 in s, "step3 skip 块未找到"
s = s.replace(old2, new2, 1)

open(p, "w", encoding="utf-8").write(s)
print("已还原: 移除前沿链跳过, 保留两轮过滤")