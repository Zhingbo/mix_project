# -*- coding: utf-8 -*-
# 给 step4 增加老底表 ent_industry_class_old 作为第二匹配源, 老底表优先
p = "steps/step4_company_match_nodes.py"
s = open(p, encoding="utf-8").read()

# 1) 在 source_table 后面加老底表变量
old1 = """    source_table = tables['ent_industry_class_old']
    nodes_mapping_table = tables.get('nodes_industry_mapping', 'nodes_industry_mapping')"""
new1 = """    source_table = tables['ent_industry_class_old']
    old_source_table = 'ent_industry_class_old'  # 老底表(26.9万, 匹配时优先)
    nodes_mapping_table = tables.get('nodes_industry_mapping', 'nodes_industry_mapping')"""
assert old1 in s, "source_table 定位失败"
s = s.replace(old1, new1, 1)

# 2) 替换 _match_one_node 里的查询块为"先老后新"
old2 = '''        sql = f"""
        SELECT COALESCE(a.company_name_full, a.company_name) AS company_name,
               a.credit_code, a.certainty, a.industry_class_third
        FROM {source_table} a
        WHERE a.industry_class_third LIKE '%{full_name_escaped}%'
          AND (a.industry_class_third LIKE '%强%' OR a.industry_class_third LIKE '%中%')
          {domain_filter}
        """
        results = []
        c = pymysql.connect(host=host, user=user, password=password, database=database, port=port)
        try:
            cur = c.cursor()
            try:
                cur.execute(sql)
                rows = cur.fetchall()
            except Exception as e:
                print(f"查询节点 {full_name} 失败: {e}")
                return []
            finally:
                cur.close()
        finally:
            c.close()'''

new2 = '''        def _query_node(table):
            _sql = f"""
            SELECT COALESCE(a.company_name_full, a.company_name) AS company_name,
                   a.credit_code, a.certainty, a.industry_class_third
            FROM {table} a
            WHERE a.industry_class_third LIKE '%{full_name_escaped}%'
              AND (a.industry_class_third LIKE '%强%' OR a.industry_class_third LIKE '%中%')
              {domain_filter}
            """
            _c = pymysql.connect(host=host, user=user, password=password, database=database, port=port)
            try:
                _cur = _c.cursor()
                try:
                    _cur.execute(_sql)
                    return _cur.fetchall()
                except Exception as e:
                    print(f"查询节点 {full_name} 失败: {e}")
                    return []
                finally:
                    _cur.close()
            finally:
                _c.close()

        results = []
        # 老底表优先: 先查老底表, 再查新底表(跳过老底表已命中的公司), 实现"老底表为主"
        _old_rows = _query_node(old_source_table)
        _old_companies = set(r[0] for r in _old_rows)
        _new_rows = [r for r in _query_node(source_table) if r[0] not in _old_companies]
        rows = _old_rows + _new_rows'''
assert old2 in s, "查询块定位失败"
s = s.replace(old2, new2, 1)

open(p, "w", encoding="utf-8").write(s)
print("patch applied")
