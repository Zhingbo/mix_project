# -*- coding: utf-8 -*-
import os
# 统计数据库结果表中 排除标黄(未标黄) 后的数量
import pymysql
from datetime import datetime
def log(m): print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

DB = dict(host='127.0.0.1', port=3306, user='root', password=os.getenv('DB_PASSWORD'),
          database='business_data', charset='utf8mb4', connect_timeout=30,
          read_timeout=3600, write_timeout=3600)
conn = pymysql.connect(**DB)
cur = conn.cursor()
IND = '船舶海工'

cur.execute("DROP TABLE IF EXISTS tmp_weibiao")
cur.execute("CREATE TABLE tmp_weibiao (company_name VARCHAR(500) COLLATE utf8mb4_0900_ai_ci PRIMARY KEY) ENGINE=InnoDB")
conn.commit()
cur.execute("LOAD DATA INFILE '/var/lib/mysql-files/weibiao_names.txt' IGNORE INTO TABLE tmp_weibiao LINES TERMINATED BY '\n' (company_name)")
conn.commit()
cur.execute("SELECT COUNT(*) FROM tmp_weibiao")
log(f"未标黄企业名(装了 {cur.fetchone()[0]} 个)")

# finallist
cur.execute("SELECT COUNT(*), COUNT(DISTINCT f.company_name) FROM company_nodes_finallist f JOIN tmp_weibiao w ON w.company_name = f.company_name COLLATE utf8mb4_0900_ai_ci WHERE f.industry_name=%s", (IND,))
fr, fu = cur.fetchone()
cur.execute("SELECT COUNT(*), COUNT(DISTINCT company_name) FROM company_nodes_finallist WHERE industry_name=%s", (IND,))
ftr, ftu = cur.fetchone()
log(f"finallist: 总 {ftr}行/{ftu}家 | 未标黄 {fr}行/{fu}家 | 剔除 {ftr-fr}行/{ftu-fu}家")

# list_output
cur.execute("SELECT COUNT(*), COUNT(DISTINCT l.供应商) FROM company_list_output l JOIN tmp_weibiao w ON w.company_name = l.供应商 WHERE l.industry_name=%s", (IND,))
lr, lu = cur.fetchone()
cur.execute("SELECT COUNT(*), COUNT(DISTINCT 供应商) FROM company_list_output WHERE industry_name=%s", (IND,))
ltr, ltu = cur.fetchone()
log(f"list_output: 总 {ltr}行/{ltu}家 | 未标黄 {lr}行/{lu}家 | 剔除 {ltr-lr}行/{ltu-lu}家")

cur.execute("DROP TABLE IF EXISTS tmp_weibiao")
conn.commit()
cur.close(); conn.close()
log("===== 统计完成 =====")