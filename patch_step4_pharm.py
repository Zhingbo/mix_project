# -*- coding: utf-8 -*-
p = "steps/step4_company_match_nodes.py"
s = open(p, encoding="utf-8").read()

old = '    all_matched = deduped\n    print(f"\\n匹配完成，去重后共 {len(all_matched)} 条记录")'
new = ('    all_matched = deduped\n'
       '    print(f"\\n匹配完成，去重后共 {len(all_matched)} 条记录")\n\n'
       '    # 6.0 生命健康专用: 药房/药铺企业强制挂到下游"线下药店"\n'
       "    if industry_name == '生命健康' and all_matched:\n"
       "        _xd = df_b[df_b['nodes'] == '线下药店']\n"
       "        _xd_full = str(_xd.iloc[0]['full_name']) if not _xd.empty else '医疗流通|医药零售|线下药店'\n"
       "        _xd_name = str(_xd.iloc[0]['name']) if not _xd.empty else '线下药店'\n"
       "        _xd_cnt = 0\n"
       "        for _m in all_matched:\n"
       "            _cn = _m.get('company_name') or ''\n"
       "            if ('药房' in _cn) or ('药铺' in _cn):\n"
       "                _m['nodes'] = '线下药店'\n"
       "                _m['name'] = _xd_name\n"
       "                _m['level'] = '3'\n"
       "                _m['full_name'] = _xd_full\n"
       "                _m['reason'] = '生命健康下游:药房/药铺'\n"
       "                _xd_cnt += 1\n"
       "        print(f'药房/药铺强制挂下游: {_xd_cnt} 条')")

assert old in s, "dedup 未找到"
s = s.replace(old, new, 1)
open(p, "w", encoding="utf-8").write(s)
print("step4 pharm patch applied")
