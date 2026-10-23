# -*- coding: utf-8 -*-
import os
# 回补"养生"误伤的医药/大健康/生物/食品企业(5235行), 然后删除备份表
import pymysql

RESTORE_REG = "养生(堂|药业|制药|医药|生物|保健|食品)"
cfg = dict(host="8.141.5.67", port=3306, user="root", password=os.getenv("DB_PASSWORD"),
           database="business_data", charset="utf8mb4")
T = "ent_industry_class_chain_scope_20260928_converted"
BK = "_backup_categories_20261010"

conn = pymysql.connect(**cfg)
cur = conn.cursor()

cur.execute(f"SELECT COUNT(*) FROM {BK} WHERE company_name REGEXP %s", (RESTORE_REG,))
bk_cnt = cur.fetchone()[0]
print(f"备份中待回补行数 = {bk_cnt}")

cols = ("company_name, company_name_full, credit_code, entity_id, website, "
        "is_official_website, product, business, industry, industry_class_first, "
        "industry_class_second, industry_class_third, `explain`, certainty, version, update_time")
sql = (f"INSERT INTO {T} ({cols}) SELECT {cols} FROM {BK} "
       f"WHERE company_name REGEXP %s")
cur.execute(sql, (RESTORE_REG,))
conn.commit()
print(f"回补行数 = {cur.rowcount}")

cur.execute(f"SELECT COUNT(*) FROM {T}")
print(f"回补后底表总行数 = {cur.fetchone()[0]}")

cur.execute(f"DROP TABLE IF EXISTS {BK}")
conn.commit()
print("备份表已删除")
cur.close(); conn.close()
print("完成")
