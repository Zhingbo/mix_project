# -*- coding: utf-8 -*-
# 测试优化后的 step6 搜索(榜单直搜) + 企业画像, 三个链
import sys, time, logging, json
logging.basicConfig(level=logging.WARNING)
sys.path.insert(0, '/root/mix_project')
from steps.step6_top_company_match import _deepseek_search_list_companies, _llm_enrich_company_info

CHAINS = ['人工智能', '生物医药', '集成电路']
OUT = '/root/mix_project/test_3chains_result.json'

result = {}
for ind in CHAINS:
    t0 = time.time()
    print(f"===== {ind} 搜索榜单企业 ...", flush=True)
    comps = _deepseek_search_list_companies(ind)
    print(f"[{ind}] 搜索到 {len(comps)} 家, 耗时 {time.time()-t0:.0f}s", flush=True)
    sample = comps[:15]
    info = {}
    if sample:
        print(f"[{ind}] 补画像({len(sample)}家) ...", flush=True)
        info = _llm_enrich_company_info(sample, ind)
    result[ind] = {
        'count': len(comps),
        'all_companies': comps,
        'sample_enriched': [{'name': n, **(info.get(n) or {})} for n in sample],
    }
    for n in sample:
        d = info.get(n) or {}
        print(f"  - {n} | {d.get('industry','')} | {d.get('product','')}", flush=True)

with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print("done, 结果写入 " + OUT, flush=True)