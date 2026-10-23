# -*- coding: utf-8 -*-
import os
import re, pymysql
src = open("/root/mix_project/steps/step4_company_match_nodes.py", encoding="utf-8").read()
m = re.search(r"NODE_KW_OVERRIDES = \{(.*?)\n\}", src, re.S)
dict_keys = set(re.findall(r'"([^"]+)": \[', m.group(1)))
c = pymysql.connect(host="127.0.0.1", user="root", password=os.getenv("DB_PASSWORD"),
                    database="business_data", charset="utf8mb4")
cur = c.cursor()
cur.execute("SELECT DISTINCT nodes FROM nodes_industry_mapping WHERE industry_name=%s", ("AI智能算力",))
db_keys = set(r[0] for r in cur.fetchall())
print("dict key 数:", len(dict_keys), "| db 节点数:", len(db_keys))
print("dict 有但 db 无:", sorted(dict_keys - db_keys))
print("db 有但 dict 无(退回通用剥离):", sorted(db_keys - dict_keys))
cur.close(); c.close()