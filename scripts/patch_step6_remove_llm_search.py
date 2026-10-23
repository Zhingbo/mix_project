# -*- coding: utf-8 -*-
# 移除 step6 的 DeepSeek 搜索头部企业段, 头部企业来源仅限白名单
import io
import datetime

FN = '/root/mix_project/steps/step6_top_company_match.py'
src = io.open(FN, 'r', encoding='utf-8').read()

bkp = FN + '.bak_nosearch_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
io.open(bkp, 'w', encoding='utf-8').write(src)
print('backup ->', bkp)

start_anchor = '    # ==================== 2. DeepSeek 并行搜索三个环节 ===================='
end_anchor = '        logging.info(f"{position}去重后新增: {len(unique)} 家")'

i = src.index(start_anchor)
j = src.index(end_anchor) + len(end_anchor)

new_text = '''    # ==================== 2. 头部企业来源仅限白名单(已禁用 LLM 搜索) ====================
    # 按需求: 企业来源只有两个 —— 两个底表(step4 关键词匹配) + 白名单(step5)
    # 不再让 LLM 凭空搜索/生成头部企业, all_companies 只保留上面加载的白名单企业
    logging.info("已禁用 DeepSeek 搜索头部企业, 头部企业来源仅限白名单")'''

src = src[:i] + new_text + src[j:]

io.open(FN, 'w', encoding='utf-8').write(src)
print('patched OK, removed block length =', j - i)