# -*- coding: utf-8 -*-
# 快速测试 step6 联网搜索(榜单口径)
import sys, time, logging
logging.basicConfig(level=logging.INFO)
sys.path.insert(0, '/root/mix_project')
from steps.step6_top_company_match import _baidu_search_head_companies

t0 = time.time()
for ind in ['生命健康', '人工智能']:
    try:
        comps = _baidu_search_head_companies(ind)
        print(f"[{ind}] 搜索到 {len(comps)} 家: {comps[:15]}")
    except Exception as e:
        print(f"[{ind}] 搜索异常: {e}")
print(f"总耗时 {time.time()-t0:.0f}s")