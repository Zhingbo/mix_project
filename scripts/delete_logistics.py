# -*- coding: utf-8 -*-
import os
# 从底表删除 物流类企业(除"供应链"): 运输/货运/配送/仓储/搬家/快递/快运/速递/货代/装箱
import pymysql

cfg = dict(host="8.141.5.67", port=3306, user="root", password=os.getenv("DB_PASSWORD"),
           database="business_data", charset="utf8mb4")
T = "ent_industry_class_chain_scope_20260928_converted"
BK = "_backup_logistics_20261010"
REG = "运输|货运|配送|仓储|搬家|快递|快运|速递|货代|装箱"

conn = pymysql.connect(**cfg)
cur = conn.cursor()

cur.execute(f"DROP TABLE IF EXISTS {BK}")
cur.execute(f"CREATE TABLE {BK} AS SELECT * FROM {T} WHERE company_name REGEXP %s", (REG,))
conn.commit()
cur.execute(f"SELECT COUNT(*) FROM {BK}")
print(f"备份行数 = {cur.fetchone()[0]}")

cur.execute(f"DELETE FROM {T} WHERE company_name REGEXP %s", (REG,))
conn.commit()
print(f"删除行数 = {cur.rowcount}")

cur.execute(f"SELECT COUNT(*) FROM {T}")
print(f"删除后底表总行数 = {cur.fetchone()[0]}")

cur.close(); conn.close()
print("完成")