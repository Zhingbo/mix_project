# -*- coding: utf-8 -*-
import os
# step4 加产业链黑名单过滤: 加载 chain_exclude_company, 匹配结果剔除黑名单企业
import sys
P = "/root/mix_project/steps/step4_company_match_nodes.py"
s = open(P, encoding="utf-8").read()

# 1. 插入 _load_chain_blacklist 函数
anchor = '''def step4_company_match_nodes(industry_name, tables, whitelist_data=None, progress_callback=None, change_context=None):'''
func = '''def _load_chain_blacklist(industry_name: str) -> set:
    """加载产业链排除黑名单(人工清洗标记的无关企业), 返回企业名集合"""
    try:
        conn = pymysql.connect(host='8.141.5.67', user='root', password=os.getenv('DB_PASSWORD'),
                               database='business_data', charset='utf8mb4')
        cur = conn.cursor()
        cur.execute("SELECT company_name FROM chain_exclude_company WHERE industry_name=%s", (industry_name,))
        s = set(r[0] for r in cur.fetchall())
        cur.close(); conn.close()
        return s
    except Exception as e:
        print(f"加载产业链黑名单失败(忽略): {e}")
        return set()


''' + anchor
if anchor not in s:
    print("[FAIL] 未找到 step4 函数锚点"); sys.exit(1)
s = s.replace(anchor, func, 1)
print("[ok] 已插入 _load_chain_blacklist")

# 2. 在 _match_one_node 定义前加载黑名单
anchor2 = '''    def _match_one_node(row_b):
        """单个节点的匹配，返回 matched 列表（供线程池并发）"""'''
new2 = '''    blacklist_set = _load_chain_blacklist(industry_name)
    if blacklist_set:
        print(f"产业链 {industry_name} 黑名单 {len(blacklist_set)} 家, 匹配时将剔除")

    def _match_one_node(row_b):
        """单个节点的匹配，返回 matched 列表（供线程池并发）"""'''
if anchor2 not in s:
    print("[FAIL] 未找到 _match_one_node 锚点"); sys.exit(1)
s = s.replace(anchor2, new2, 1)
print("[ok] 已加载黑名单")

# 3. 在 return results 前加黑名单过滤
anchor3 = '''            if _kw_hit:
                results = _kw_hit
        return results'''
new3 = '''            if _kw_hit:
                results = _kw_hit
        # 产业链黑名单过滤(确保无关企业不再挂载)
        if blacklist_set:
            results = [r for r in results if (r.get('company_name') or '') not in blacklist_set]
        return results'''
if anchor3 not in s:
    print("[FAIL] 未找到 return results 锚点"); sys.exit(1)
s = s.replace(anchor3, new3, 1)
print("[ok] 已加黑名单过滤")

open(P, "w", encoding="utf-8").write(s)
print("[done]")