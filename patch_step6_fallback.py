# -*- coding: utf-8 -*-
# step6 搜索兜底: 百度被封时用 DeepSeek 按榜单口径直搜
import sys
P = "/root/mix_project/steps/step6_top_company_match.py"
s = open(P, encoding="utf-8").read()

# 1. 在 _search_one_position 之后插入榜单兜底函数
anchor = '''def _batch_lookup_company_info(company_names: List[str]) -> Dict[str, dict]:'''
newfunc = '''def _deepseek_search_list_companies(industry_name: str) -> List[str]:
    """DeepSeek 凭模型知识直搜榜单类企业(兜底, 不依赖百度反爬)"""
    angles = [
        f"列出中国{industry_name}行业(细分赛道)的100强、200强、500强企业",
        f"列出中国{industry_name}领域的隐形冠军、专精特新小巨人、瞪羚企业名单",
        f"列出中国{industry_name}领域的独角兽、隐形独角兽、高成长/高创新企业名单",
        f"列出{industry_name}行业科技真榜上榜企业、龙头企业",
    ]
    comps = []
    for a in angles:
        try:
            comps.extend(_deepseek_search_companies(industry_name, '全产业链', a))
        except Exception as e:
            logging.warning(f"DeepSeek榜单兜底搜索失败: {e}")
    seen = set()
    out = []
    for c in comps:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _batch_lookup_company_info(company_names: List[str]) -> Dict[str, dict]:'''
if anchor not in s:
    print("[FAIL] 未找到插入锚点"); sys.exit(1)
s = s.replace(anchor, newfunc, 1)
print("[ok] 已插入 DeepSeek 榜单兜底函数")

# 2. 搜索调用处加兜底
old_r = '''    searched_companies = _baidu_search_head_companies(industry_name)'''
new_r = '''    searched_companies = _baidu_search_head_companies(industry_name)
    if not searched_companies:
        logging.info("百度搜索无结果(可能被反爬), 改用 DeepSeek 榜单兜底直搜")
        searched_companies = _deepseek_search_list_companies(industry_name)'''
if old_r not in s:
    print("[FAIL] 未找到搜索调用行"); sys.exit(1)
s = s.replace(old_r, new_r, 1)
print("[ok] 已加搜索兜底")

open(P, "w", encoding="utf-8").write(s)
print("[done]")