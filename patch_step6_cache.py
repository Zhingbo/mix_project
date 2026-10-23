# -*- coding: utf-8 -*-
# step6 复用白名单缓存: 已回填 matched_nodes 的头部企业直接复用, 只对新/空企业跑 LLM
p = "steps/step6_top_company_match.py"
s = open(p, encoding="utf-8").read()

# Part 1: 在"搜索阶段完成"后加载缓存 + 拆分 all_companies
old1 = '    logging.info(f"搜索阶段完成，共 {len(all_companies)} 家企业待匹配")'
new1 = '''    logging.info(f"搜索阶段完成，共 {len(all_companies)} 家企业待匹配")

    # ==================== 2.5 白名单缓存复用(已匹配过的直接取, 不再跑 LLM) ====================
    def _norm(x):
        x = (x or '').strip()
        if len(x) >= 2 and x[0] == '"' and x[-1] == '"':
            try:
                return str(json.loads(x))
            except Exception:
                return x
        return x
    _wl_cache = {}
    _cc = get_db_connection()
    _c = _cc.cursor()
    _c.execute(
        "SELECT company_name, matched_nodes, match_reason, match_score, certainty "
        "FROM whitelist_company WHERE industry_name=%s "
        "AND matched_nodes IS NOT NULL AND LENGTH(matched_nodes)>0", (industry_name,))
    for _cn, _mn, _mr, _ms, _ce in _c.fetchall():
        _wl_cache[_cn] = (_norm(_mn), _norm(_mr), _norm(_ms), _norm(_ce))
    _c.close(); _cc.close()

    _cached_companies = []
    _to_match_companies = []
    for _item in all_companies:
        if _item[0] in _wl_cache:
            _cached_companies.append(_item)
        else:
            _to_match_companies.append(_item)
    all_companies = _to_match_companies
    logging.info(f"白名单缓存命中 {len(_cached_companies)} 家, 需新匹配 {len(all_companies)} 家")'''
assert old1 in s, "搜索阶段完成 未找到"
s = s.replace(old1, new1, 1)

# Part 2: 在 results=[] 后加入缓存结果
old2 = '''    client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
    results = []
    total_companies = len(all_companies)'''
new2 = '''    client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
    results = []
    # 复用白名单缓存(已匹配节点的企业直接加入, 跳过 LLM)
    for _cn, _pos in _cached_companies:
        _mn, _mr, _ms, _ce = _wl_cache[_cn]
        results.append({
            '原始公司名': _cn,
            '企业名称': _cn,
            '主营产品': '',
            '公司简介': f'{_cn}是{industry_name}环节的头部企业。',
            '匹配节点': _mn,
            '匹配原因': _mr,
            '置信度': _ce,
            '分数': _ms,
        })
    total_companies = len(all_companies)'''
assert old2 in s, "results=[] 未找到"
s = s.replace(old2, new2, 1)

open(p, "w", encoding="utf-8").write(s)
print("step6 cache patch applied")
