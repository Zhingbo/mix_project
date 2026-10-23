# -*- coding: utf-8 -*-
import os
# 用 nonactive_company_names_20261021.txt (837万注销企业名) 从结果表全链删除
import pymysql
from datetime import datetime
def log(m): print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

DB = dict(host='8.141.5.67', port=3306, user='root', password=os.getenv('DB_PASSWORD'),
          database='business_data', charset='utf8mb4', connect_timeout=30, read_timeout=3600, write_timeout=3600)
conn = pymysql.connect(**DB)
cur = conn.cursor()

log("建 tmp_nonactive_names 并 LOAD DATA ...")
cur.execute("DROP TABLE IF EXISTS tmp_nonactive_names")
cur.execute("CREATE TABLE tmp_nonactive_names (company_name VARCHAR(500) COLLATE utf8mb4_0900_ai_ci PRIMARY KEY) ENGINE=InnoDB")
conn.commit()
cur.execute("LOAD DATA INFILE '/var/lib/mysql-files/nonactive_names.txt' IGNORE INTO TABLE tmp_nonactive_names LINES TERMINATED BY '\n' (company_name)")
conn.commit()
cur.execute("SELECT COUNT(*) FROM tmp_nonactive_names")
log(f"  非活跃企业名数: {cur.fetchone()[0]}")

# 删除 finallist (全链)
log("删除 finallist 中的非活跃企业(全链)...")
cur.execute("""DELETE f FROM company_nodes_finallist f
  JOIN tmp_nonactive_names n ON n.company_name = f.company_name COLLATE utf8mb4_0900_ai_ci""")
log(f"  finallist 删除 {cur.rowcount} 行")
conn.commit()

# 删除 list_output (全链)
log("删除 list_output 中的非活跃企业(全链)...")
cur.execute("""DELETE l FROM company_list_output l
  JOIN tmp_nonactive_names n ON n.company_name = l.供应商""")
log(f"  list_output 删除 {cur.rowcount} 行")
conn.commit()

# 也同步删 mapping/final/merge_temp(避免重跑又冒出来)
for tbl, col in [('company_nodes_mapping','company_name'), ('company_nodes_final','company_name'), ('company_nodes_merge_temp','company_name')]:
    try:
        cur.execute(f"""DELETE x FROM {tbl} x JOIN tmp_nonactive_names n ON n.company_name = x.{col} COLLATE utf8mb4_0900_ai_ci""")
        log(f"  {tbl} 删除 {cur.rowcount} 行")
        conn.commit()
    except Exception as e:
        log(f"  {tbl} 跳过: {e}")

cur.execute("DROP TABLE IF EXISTS tmp_nonactive_names")
conn.commit()
cur.close(); conn.close()
log("===== 全链剔除注销企业完成 =====")