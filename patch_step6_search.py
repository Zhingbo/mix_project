# -*- coding: utf-8 -*-
# 优化 step6 联网搜索: 榜单类口径全覆盖 + 重新启用
import sys
P = "/root/mix_project/steps/step6_top_company_match.py"
s = open(P, encoding="utf-8").read()

# 1. 扩展搜索词
old_q = '''    queries = [
        f"{year}中国{industry_name}企业排行榜",
        f"{year}{industry_name}头部企业排名",
        f"{year}{industry_name}百强企业榜",
    ]'''
new_q = '''    # 榜单类搜索口径: 覆盖行业百强/200强/500强/隐形冠军/创新TOP/独角兽/隐形独角兽/科技真榜等
    queries = [
        f"{year}中国{industry_name}企业100强",
        f"{year}中国{industry_name}企业200强名单",
        f"{year}中国{industry_name}企业500强",
        f"{year}{industry_name}龙头企业排行榜",
        f"{year}{industry_name}百强企业",
        f"{year}{industry_name}隐形冠军企业名单",
        f"{year}{industry_name}创新企业TOP100",
        f"{year}{industry_name}独角兽企业名单",
        f"{year}{industry_name}隐形独角兽企业名单",
        f"{year}{industry_name}科技真榜",
        f"{year}{industry_name}专精特新小巨人企业名单",
        f"{year}{industry_name}瞪羚企业名单",
    ]'''
if old_q not in s:
    print("[FAIL] 未找到 queries 块"); sys.exit(1)
s = s.replace(old_q, new_q, 1)
print("[ok] 搜索词已扩展")

# 2. 提高抽取上限
old_p = '''              f'{{"companies":["企业名1","企业名2",...]}}。最多80家，按重要性降序，'
              f'企业名去掉股票代码和括号说明。\\n搜索结果：\\n{corpus[:6000]}')'''
new_p = '''              f'{{"companies":["企业名1","企业名2",...]}}。最多120家，按重要性降序，'
              f'企业名去掉股票代码和括号说明。\\n搜索结果：\\n{corpus[:15000]}')'''
if old_p not in s:
    print("[FAIL] 未找到 prompt 块"); sys.exit(1)
s = s.replace(old_p, new_p, 1)
print("[ok] 抽取上限已提高")

# 3. 重新启用搜索
old_r = '''    searched_companies = []  # 已停用联网搜索'''
new_r = '''    searched_companies = _baidu_search_head_companies(industry_name)'''
if old_r not in s:
    print("[FAIL] 未找到 searched_companies 停用行"); sys.exit(1)
s = s.replace(old_r, new_r, 1)
print("[ok] 联网搜索已重新启用")

open(P, "w", encoding="utf-8").write(s)
print("[done] step6 搜索逻辑优化完成")