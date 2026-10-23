# -*- coding: utf-8 -*-
import sys, time, logging
logging.basicConfig(level=logging.INFO)
sys.path.insert(0, '/root/mix_project')
from steps.step6_top_company_match import _deepseek_search_list_companies

t0 = time.time()
comps = _deepseek_search_list_companies('生命健康')
print(f"DeepSeek榜单兜底返回 {len(comps)} 家, 耗时 {time.time()-t0:.0f}s")
for c in comps[:30]:
    print("  ", c)