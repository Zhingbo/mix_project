# -*- coding: utf-8 -*-
import sys, logging
logging.basicConfig(level=logging.INFO)
sys.path.insert(0, '/root/mix_project')
from steps.step6_top_company_match import _llm_enrich_company_info

names = ['海湃泰克（北京）科技有限公司', '北京泛生子基因科技有限公司', '北京吉因加生物医学工程有限公司', '北京炎明生物科技有限公司']
info = _llm_enrich_company_info(names, '生命健康')
for n in names:
    d = info.get(n)
    print(f"{n} -> {d}")
print("enrich返回", len(info), "家")