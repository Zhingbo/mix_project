# -*- coding: utf-8 -*-
import os
# 对导入链统一剔除注销企业(两种口径双保险: ①带*号 ②nonactive_ids名单)
import pymysql
from datetime import datetime
def log(m): print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

DB = dict(host='8.141.5.67', port=3306, user='root', password=os.getenv('DB_PASSWORD'),
          database='business_data', charset='utf8mb4', connect_timeout=30, local_infile=True)
CHAINS = ['人工智能', '工业元宇宙', '储能', '光伏产业', '3D打印', '5G', '人形机器人', '仪器仪表', '可控核聚变', '工业软件', '机器人']

conn = pymysql.connect(**DB)
cur = conn.cursor()

# 1) 重建 nonactive 名单(entity_id -> status)
log("重建 nonactive 名单 ...")
cur.execute("DROP TABLE IF EXISTS tmp_nonactive_ids")
cur.execute("CREATE TABLE tmp_nonactive_ids (entity_id VARCHAR(64) COLLATE utf8mb4_0900_ai_ci PRIMARY KEY, status VARCHAR(32)) ENGINE=InnoDB")
conn.commit()
cur.execute("""LOAD DATA INFILE '/var/lib/mysql-files/nonactive_ids.tsv'
  INTO TABLE tmp_nonactive_ids FIELDS TERMINATED BY '\t' LINES TERMINATED BY '\n' (entity_id, status)""")
conn.commit()
cur.execute("SELECT COUNT(*) FROM tmp_nonactive_ids")
log(f"  非活跃entity数: {cur.fetchone()[0]}")

# 2) 映射 entity_id -> company_name
log("映射 entity_id -> company_name ...")
cur.execute("DROP TABLE IF EXISTS tmp_nonactive_companies")
cur.execute("CREATE TABLE tmp_nonactive_companies (company_name VARCHAR(500) COLLATE utf8mb4_0900_ai_ci PRIMARY KEY) ENGINE=InnoDB")
conn.commit()
cur.execute("""INSERT IGNORE INTO tmp_nonactive_companies (company_name)
  SELECT DISTINCT b.company_name FROM ent_industry_class_chain_scope_20260928_converted b
  JOIN tmp_nonactive_ids t ON t.entity_id = b.entity_id""")
conn.commit()
cur.execute("SELECT COUNT(*) FROM tmp_nonactive_companies")
log(f"  非活跃公司名数: {cur.fetchone()[0]}")

# 3) 对每条链双口径剔除
for ch in CHAINS:
    # 口径A: 带*号(标准注销标记)
    cur.execute("DELETE FROM company_nodes_finallist WHERE industry_name=%s AND company_name LIKE '*%'", (ch,))
    a_fin = cur.rowcount
    cur.execute("DELETE FROM company_list_output WHERE industry_name=%s AND 供应商 LIKE '*%'", (ch,))
    a_lst = cur.rowcount
    # 口径B: nonactive_ids名单
    cur.execute("""DELETE f FROM company_nodes_finallist f
      JOIN tmp_nonactive_companies n ON n.company_name = f.company_name COLLATE utf8mb4_0900_ai_ci
      WHERE f.industry_name=%s""", (ch,))
    b_fin = cur.rowcount
    cur.execute("""DELETE l FROM company_list_output l
      JOIN tmp_nonactive_companies n ON n.company_name = l.供应商
      WHERE l.industry_name=%s""", (ch,))
    b_lst = cur.rowcount
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name=%s", (ch,))
    fin = cur.fetchone()[0]
    log(f"  {ch}: *号删 fin={a_fin}/list={a_lst}, 名单删 fin={b_fin}/list={b_lst}, 剩余finallist={fin}")

cur.execute("DROP TABLE IF EXISTS tmp_nonactive_ids")
cur.execute("DROP TABLE IF EXISTS tmp_nonactive_companies")
conn.commit()
cur.close(); conn.close()
log("===== 注销企业剔除完成 =====")