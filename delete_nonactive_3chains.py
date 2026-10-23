# -*- coding: utf-8 -*-
import os
# 导入后: 重建非活跃名单 -> 从导入的3条链 finallist/list_output 中剔除非活跃企业
import pymysql, sys
from datetime import datetime

def log(m): print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

DB = dict(host='127.0.0.1', port=3306, user='root', password=os.getenv('DB_PASSWORD'),
          database='business_data', charset='utf8mb4', local_infile=True)
CHAINS = ['AI智能算力', '人工智能', '工业元宇宙']

conn = pymysql.connect(**DB)
cur = conn.cursor()

# 1) 重建 tmp_nonactive_ids
log("重建 tmp_nonactive_ids ...")
cur.execute("DROP TABLE IF EXISTS tmp_nonactive_ids")
cur.execute("CREATE TABLE tmp_nonactive_ids (entity_id VARCHAR(64) COLLATE utf8mb4_0900_ai_ci PRIMARY KEY, status VARCHAR(32)) ENGINE=InnoDB")
conn.commit()
cur.execute("""LOAD DATA INFILE '/var/lib/mysql-files/nonactive_ids.tsv'
  INTO TABLE tmp_nonactive_ids FIELDS TERMINATED BY '\t' LINES TERMINATED BY '\n' (entity_id, status)""")
conn.commit()
cur.execute("SELECT COUNT(*) FROM tmp_nonactive_ids")
log(f"  tmp_nonactive_ids 行数: {cur.fetchone()[0]}")

# 2) 映射 entity_id -> company_name
log("映射 entity_id -> company_name (hash join) ...")
cur.execute("DROP TABLE IF EXISTS tmp_nonactive_companies")
cur.execute("""CREATE TABLE tmp_nonactive_companies (
  company_name VARCHAR(255) COLLATE utf8mb4_0900_ai_ci PRIMARY KEY
) ENGINE=InnoDB""")
conn.commit()
cur.execute("""INSERT IGNORE INTO tmp_nonactive_companies (company_name)
  SELECT DISTINCT b.company_name
  FROM ent_industry_class_chain_scope_20260928_converted b
  JOIN tmp_nonactive_ids t ON t.entity_id = b.entity_id""")
conn.commit()
cur.execute("SELECT COUNT(*) FROM tmp_nonactive_companies")
log(f"  tmp_nonactive_companies 行数: {cur.fetchone()[0]}")

# 3) 从导入的3条链剔除
for ch in CHAINS:
    cur.execute("SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name=%s", (ch,))
    n1 = cur.fetchone()[0]
    # 剔除非活跃(finallist 的 company_name 是 unicode_ci, cast 成 0900_ai_ci 匹配)
    cur.execute("""DELETE f FROM company_nodes_finallist f
      JOIN tmp_nonactive_companies n ON n.company_name = f.company_name COLLATE utf8mb4_0900_ai_ci
      WHERE f.industry_name=%s""", (ch,))
    delfin = cur.rowcount
    cur.execute("""DELETE l FROM company_list_output l
      JOIN tmp_nonactive_companies n ON n.company_name = l.供应商
      WHERE l.industry_name=%s""", (ch,))
    dellist = cur.rowcount
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name=%s", (ch,))
    fin = cur.fetchone()[0]
    log(f"  {ch}: 导入总 {n1} 行, 剔除非活跃 finallist={delfin} list_output={dellist}, 剩余 finallist={fin}")

# 清理临时表
cur.execute("DROP TABLE IF EXISTS tmp_nonactive_ids")
cur.execute("DROP TABLE IF EXISTS tmp_nonactive_companies")
conn.commit()
cur.close(); conn.close()
log("===== 剔除非活跃完成 =====")