# -*- coding: utf-8 -*-
import os
import pymysql
KW = ["快递", "货运", "仓储", "搬家", "配送", "供应链", "运输", "速递", "快运", "物流园", "货代", "装箱"]
cfg = dict(host="8.141.5.67", port=3306, user="root", password=os.getenv("DB_PASSWORD"),
           database="business_data", charset="utf8mb4")
T = "ent_industry_class_chain_scope_20260928_converted"
conn = pymysql.connect(**cfg)
cur = conn.cursor()
parts = [f"SUM(company_name LIKE '%{k}%') AS `{k}`" for k in KW]
sql = "SELECT " + ", ".join(parts) + f" FROM {T}"
cur.execute(sql)
row = cur.fetchone()
cols = [d[0] for d in cur.description]
for c, v in sorted(zip(cols, row), key=lambda x: -x[1]):
    print(f"  {c}: {v}")
cur.close(); conn.close()
print("完成")