# -*- coding: utf-8 -*-
import os
# 清理 11 条链的输出数据(不动生命健康、不动其它链、不动图谱)
import pymysql

CHAINS = ("储能","光伏产业","人工智能","大飞机","合成生物","氢能产业",
          "工业软件","AI智能算力","可控核聚变","工业元宇宙","生物医药")

cfg = dict(host="8.141.5.67", port=3306, user="root", password=os.getenv("DB_PASSWORD"),
           database="business_data", charset="utf8mb4")

OUT = [  # (表, 链名字段)
    ("nodes_industry_mapping", "industry_name"),
    ("company_nodes_mapping", "industry_name"),
    ("company_nodes_top", "industry_chain"),
    ("company_nodes_info_result", "industry_name"),
    ("company_nodes_info_split", "industry_name"),
    ("company_nodes_final", "industry_name"),
    ("company_nodes_finallist", "industry_name"),
    ("company_list_output", "industry_name"),
]

conn = pymysql.connect(**cfg)
cur = conn.cursor()
ph = ",".join(["%s"] * len(CHAINS))

total = 0
for t, col in OUT:
    cur.execute(f"DELETE FROM {t} WHERE {col} IN ({ph})", CHAINS)
    conn.commit()
    print(f"{t}.{col} 删除 = {cur.rowcount}")
    total += cur.rowcount

print(f"\n共删除 = {total}")

# 校验: 11 链各输出表现应为0
print("\n=== 清理后核对(应为0) ===")
for t, col in OUT:
    cur.execute(f"SELECT COUNT(*) FROM {t} WHERE {col} IN ({ph})", CHAINS)
    c = cur.fetchone()[0]
    print(f"  {t}: 剩余 {c}")

cur.close(); conn.close()
print("完成")