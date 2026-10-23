# -*- coding: utf-8 -*-
# 修复 step6: 生命健康"药房/药铺"硬规则
# 1) 药房/药铺不读白名单缓存, 强制走 LLM 重匹配
# 2) 结果兜底: 药房/药铺若匹配到非下游节点, 强制改为下游"线下药店"
import io
import datetime

FN = '/root/mix_project/steps/step6_top_company_match.py'
src = io.open(FN, 'r', encoding='utf-8').read()

bkp = FN + '.bak_pharm_fix_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
io.open(bkp, 'w', encoding='utf-8').write(src)
print('backup ->', bkp)

# ---- Edit 1: 缓存拆分时, 生命健康药房/药铺强制重匹配 ----
old1 = '''    _cached_companies = []
    _to_match_companies = []
    for _item in all_companies:
        if _item[0] in _wl_cache:
            _cached_companies.append(_item)
        else:
            _to_match_companies.append(_item)
    all_companies = _to_match_companies
    logging.info(f"白名单缓存命中 {len(_cached_companies)} 家, 需新匹配 {len(all_companies)} 家")'''

new1 = '''    _cached_companies = []
    _to_match_companies = []
    for _item in all_companies:
        _cn = _item[0]
        # 生命健康硬规则: 药房/药铺必须走LLM重匹配, 旧缓存可能绕过"挂下游"规则
        _force_rematch = (industry_name == '生命健康' and ('药房' in str(_cn) or '药铺' in str(_cn)))
        if _cn in _wl_cache and not _force_rematch:
            _cached_companies.append(_item)
        else:
            _to_match_companies.append(_item)
    all_companies = _to_match_companies
    logging.info(f"白名单缓存命中 {len(_cached_companies)} 家, 需新匹配 {len(all_companies)} 家")'''

# ---- Edit 2: 结果兜底(保存前) ----
old2 = '''    # ==================== 5. 保存到数据库 ====================
    if results:
        save_conn = get_db_connection()'''

new2 = '''    # ==================== 4.5 生命健康硬规则兜底(保存前) ====================
    # 药房/药铺企业无论来自缓存还是LLM, 只要匹配到非下游节点, 一律改为下游"线下药店"
    if industry_name == '生命健康':
        try:
            _ds_conn = get_db_connection()
            _ds_cur = _ds_conn.cursor()
            _ds_cur.execute(
                "SELECT nodes FROM industrial_chain.industrial_chain_structure "
                "WHERE chain_name=%s AND parent_node=%s", (industry_name, '产业链下游'))
            _ds_nodes = set()
            _lvl2 = [r[0] for r in _ds_cur.fetchall()]
            for _n2 in _lvl2:
                if _n2:
                    _ds_nodes.add(_n2)
                _ds_cur.execute(
                    "SELECT nodes FROM industrial_chain.industrial_chain_structure "
                    "WHERE chain_name=%s AND parent_node=%s", (industry_name, _n2))
                for (_g,) in _ds_cur.fetchall():
                    if _g:
                        _ds_nodes.add(_g)
            _ds_cur.close(); _ds_conn.close()
            _forced_cnt = 0
            for _r in results:
                _cname = str(_r.get('原始公司名', '') or _r.get('企业名称', ''))
                if ('药房' in _cname) or ('药铺' in _cname):
                    _mn = str(_r.get('匹配节点', '') or '')
                    _nlist = [x.strip() for x in _mn.split(';') if x.strip()]
                    _bad = [n for n in _nlist if n not in _ds_nodes]
                    if _bad or not _nlist:
                        _r['匹配节点'] = '线下药店'
                        _r['匹配原因'] = '生命健康下游:药房/药铺'
                        _r['置信度'] = '2'
                        _r['分数'] = '60'
                        _forced_cnt += 1
            if _forced_cnt:
                logging.info(f"生命健康药房/药铺兜底纠正: {_forced_cnt} 家 -> 线下药店")
        except Exception as _e:
            logging.warning(f"生命健康药房/药铺兜底检查失败(忽略): {_e}")

    # ==================== 5. 保存到数据库 ====================
    if results:
        save_conn = get_db_connection()'''

if old1 not in src:
    raise SystemExit('ERROR: old1 未找到(step6 可能已改过)')
src = src.replace(old1, new1, 1)

if old2 not in src:
    raise SystemExit('ERROR: old2 未找到(保存段锚点不匹配)')
src = src.replace(old2, new2, 1)

io.open(FN, 'w', encoding='utf-8').write(src)
print('patched OK')