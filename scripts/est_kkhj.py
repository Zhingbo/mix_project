# -*- coding: utf-8 -*-
import os
# 可控核聚变 企业表 -> 匹配成立时间 -> 输出 含成立时间 xlsx
import openpyxl, pymysql, pandas as pd

CH = "可控核聚变"
OUT_XLSX = "/root/mix_project/可控核聚变_企业名单_含成立时间.xlsx"

cfg = dict(host="8.141.5.67", port=3306, user="root", password=os.getenv("DB_PASSWORD"),
           database="business_data", charset="utf8mb4")
RDS = dict(host="rm-2zej668f34v6xr91wdo.mysql.rds.aliyuncs.com", port=3306,
           user="root", password=os.getenv("DB_PASSWORD_ZS"), database="zs_digital_staff_db",
           charset="utf8mb4", connect_timeout=60, read_timeout=60)
TABLE = "enterprise_establish_time_chain_scope_20260928"
BATCH = 500

conn = pymysql.connect(**cfg)
cur = conn.cursor()
# 企业表: 层级1/层级2/层级3/供应商
cur.execute("SELECT 层级1, 层级2, 层级3, 供应商 FROM company_list_output WHERE industry_name=%s ORDER BY id", (CH,))
rows = cur.fetchall()
cur.close(); conn.close()
print(f"读到企业表行数: {len(rows)}")

companies = list(dict.fromkeys([r[3] for r in rows if r[3]]))
print(f"去重企业数: {len(companies)}")

rdb = pymysql.connect(**RDS)
rc = rdb.cursor()
m = {}
for i in range(0, len(companies), BATCH):
    b = companies[i:i+BATCH]
    ph = ",".join(["%s"]*len(b))
    rc.execute(f"SELECT company_name, establish_time, establish_year FROM {TABLE} WHERE company_name IN ({ph})", b)
    for n, t, y in rc.fetchall():
        m[n] = (t, y)
rc.close(); rdb.close()
print(f"匹配到: {len(m)} / {len(companies)}")

wb = openpyxl.Workbook()
ws = wb.active
ws.title = "企业表"
ws.append(["层级1", "层级2", "层级3", "供应商", "成立时间", "注册年份", "匹配状态"])
matched = 0
for c1, c2, c3, supplier in rows:
    t, y = m.get(supplier, (None, None))
    st = "已匹配" if (t or y) else "未匹配"
    if t or y:
        matched += 1
    if t is None:
        ts = ""
    elif hasattr(t, "strftime"):
        ts = t.strftime("%Y-%m-%d")
    else:
        ts = str(t).strip()[:10]
    ws.append([c1, c2, c3, supplier, ts, y or "", st])
wb.save(OUT_XLSX)
print(f"输出: {OUT_XLSX}")
print(f"总 {len(rows)}, 匹配 {matched}, 未匹配 {len(rows)-matched}")