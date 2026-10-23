# -*- coding: utf-8 -*-
# 修正: 老底表 industry_class_first 是字典字符串(非普通), 不能用 domain_filter 等值过滤; 老表查询跳过 domain_filter
p = "steps/step4_company_match_nodes.py"
s = open(p, encoding="utf-8").read()

old = '''        def _query_node(table):
            _sql = f"""
            SELECT COALESCE(a.company_name_full, a.company_name) AS company_name,
                   a.credit_code, a.certainty, a.industry_class_third
            FROM {table} a
            WHERE a.industry_class_third LIKE '%{full_name_escaped}%'
              AND (a.industry_class_third LIKE '%强%' OR a.industry_class_third LIKE '%中%')
              {domain_filter}
            """'''
new = '''        def _query_node(table, use_domain=True):
            _df = domain_filter if use_domain else ""
            _sql = f"""
            SELECT COALESCE(a.company_name_full, a.company_name) AS company_name,
                   a.credit_code, a.certainty, a.industry_class_third
            FROM {table} a
            WHERE a.industry_class_third LIKE '%{full_name_escaped}%'
              AND (a.industry_class_third LIKE '%强%' OR a.industry_class_third LIKE '%中%')
              {_df}
            }"""'''

assert old in s, "query_node 定义未找到"
s = s.replace(old, new, 1)

old2 = '''        _old_rows = _query_node(old_source_table)'''
new2 = '''        _old_rows = _query_node(old_source_table, use_domain=False)'''
assert old2 in s, "old_rows 调用未找到"
s = s.replace(old2, new2, 1)

open(p, "w", encoding="utf-8").write(s)
print("domain patch applied")
