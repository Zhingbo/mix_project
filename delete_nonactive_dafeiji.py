# -*- coding: utf-8 -*-
import os
# 针对"大飞机"重跑后的新结果, 重新剔除注销企业(只清 finallist + list_output, 避免大表 JOIN 锁)
import pymysql
from datetime import datetime
def log(m): print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

DB = dict(host='127.0.0.1', port=3306, user='root', password=os.getenv('DB_PASSWORD'),
          database='business_data', charset='utf8mb4', connect_timeout=30,
          read_timeout=3600, write_timeout=3600)
conn = pymysql.connect(**DB)
cur = conn.cursor()
IND = '大飞机'

log("建 tmp_nonactive_names 并 LOAD DATA ...")
cur.execute("DROP TABLE IF EXISTS tmp_nonactive_names")
cur.execute("CREATE TABLE tmp_nonactive_names (company_name VARCHAR(500) COLLATE utf8mb4_0900_ai_ci PRIMARY KEY) ENGINE=InnoDB")
conn.commit()
cur.execute("LOAD DATA INFILE '/var/lib/mysql-files/nonactive_names.txt' IGNORE INTO TABLE tmp_nonactive_names LINES TERMINATED BY '\n' (company_name)")
conn.commit()
cur.execute("SELECT COUNT(*) FROM tmp_nonactive_names")
log(f"  非活跃企业名数: {cur.fetchone()[0]}")

# 统计/删除 finallist
cur.execute("""SELECT COUNT(*) FROM company_nodes_finallist f
  JOIN tmp_nonactive_names n ON n.company_name = f.company_name COLLATE utf8mb4_0900_ai_ci
  WHERE f.industry_name=%s""", (IND,))
log(f"  大飞机 finallist 命中注销: {cur.fetchone()[0]}")

cur.execute("""DELETE f FROM company_nodes_finallist f
  JOIN tmp_nonactive_names n ON n.company_name = f.company_name COLLATE utf8mb4_0900_ai_ci
  WHERE f.industry_name=%s""", (IND,))
log(f"  finallist 删除 {cur.rowcount} 行")
conn.commit()

# 统计/删除 list_output
cur.execute("""SELECT COUNT(*) FROM company_list_output l
  JOIN tmp_nonactive_names n ON n.company_name = l.供应商
  WHERE l.industry_name=%s""", (IND,))
log(f"  大飞机 list_output 命中注销: {cur.fetchone()[0]}")

cur.execute("""DELETE l FROM company_list_output l
  JOIN tmp_nonactive_names n ON n.company_name = l.供应商
  WHERE l.industry_name=%s""", (IND,))
log(f"  list_output 删除 {cur.rowcount} 行")
conn.commit()

cur.execute("DROP TABLE IF EXISTS tmp_nonactive_names")
conn.commit()

cur.execute("SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name=%s", (IND,))
log(f"剔除后 finallist={cur.fetchone()[0]}")
cur.execute("SELECT COUNT(*) FROM company_list_output WHERE industry_name=%s", (IND,))
log(f"剔除后 list_output={cur.fetchone()[0]}")

cur.close(); conn.close()
log("===== 大飞机注销清理完成 =====")