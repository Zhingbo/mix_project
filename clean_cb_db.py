# -*- coding: utf-8 -*-
import os
# 船舶海工清理: ①结果表删标黄 ②底表删垃圾 ③建黑名单(确保不挂载)
import pymysql
from datetime import datetime
def log(m): print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

DB = dict(host='127.0.0.1', port=3306, user='root', password=os.getenv('DB_PASSWORD'),
          database='business_data', charset='utf8mb4', connect_timeout=30,
          read_timeout=3600, write_timeout=3600)
conn = pymysql.connect(**DB)
cur = conn.cursor()
IND = '船舶海工'

# 载入标黄名 + 垃圾名
def load_tmp(name, col):
    cur.execute(f"DROP TABLE IF EXISTS {name}")
    cur.execute(f"CREATE TABLE {name} (company_name VARCHAR(500) COLLATE utf8mb4_0900_ai_ci PRIMARY KEY) ENGINE=InnoDB")
    conn.commit()
    cur.execute(f"LOAD DATA INFILE '/var/lib/mysql-files/{col}' IGNORE INTO TABLE {name} LINES TERMINATED BY '\n' (company_name)")
    conn.commit()
    cur.execute(f"SELECT COUNT(*) FROM {name}")
    log(f"  载入 {name}: {cur.fetchone()[0]}")

load_tmp('tmp_biaohuang', 'biaohuang_names.txt')
load_tmp('tmp_garbage', 'garbage_names.txt')

# ① 结果表删标黄
log("① 结果表删除标黄(船舶海工)...")
cur.execute("""DELETE f FROM company_nodes_finallist f
  JOIN tmp_biaohuang b ON b.company_name = f.company_name COLLATE utf8mb4_0900_ai_ci
  WHERE f.industry_name=%s""", (IND,))
log(f"  finallist 删 {cur.rowcount} 行")
conn.commit()
cur.execute("""DELETE l FROM company_list_output l
  JOIN tmp_biaohuang b ON b.company_name = l.供应商
  WHERE l.industry_name=%s""", (IND,))
log(f"  list_output 删 {cur.rowcount} 行")
conn.commit()
cur.execute("SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name=%s", (IND,))
log(f"  删后 finallist 剩 {cur.fetchone()[0]} 行")
cur.execute("SELECT COUNT(*) FROM company_list_output WHERE industry_name=%s", (IND,))
log(f"  删后 list_output 剩 {cur.fetchone()[0]} 行")

# ② 底表删垃圾(全局)
log("② 底表删除垃圾企业(全局, 首字符非中文/名称异常)...")
for tbl in ['ent_industry_class_chain_scope_20260928_converted',
            'ent_industry_class_chain_scope_20260928_converted_nonactive_bak']:
    cur.execute(f"""DELETE a FROM {tbl} a
      JOIN tmp_garbage g ON g.company_name = a.company_name COLLATE utf8mb4_0900_ai_ci""")
    log(f"  {tbl} 删 {cur.rowcount} 行")
    conn.commit()

# ③ 建黑名单
log("③ 建黑名单 chain_exclude_company ...")
cur.execute("""CREATE TABLE IF NOT EXISTS chain_exclude_company (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  industry_name VARCHAR(100) NOT NULL,
  company_name VARCHAR(255) NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_chain_company (industry_name, company_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='产业链排除企业黑名单'""")
conn.commit()
cur.execute("""INSERT IGNORE INTO chain_exclude_company (industry_name, company_name)
  SELECT %s, company_name FROM tmp_biaohuang""", (IND,))
log(f"  写入黑名单 {cur.rowcount} 家")
conn.commit()

cur.execute("DROP TABLE IF EXISTS tmp_biaohuang")
cur.execute("DROP TABLE IF EXISTS tmp_garbage")
conn.commit()
cur.close(); conn.close()
log("===== 船舶海工清理完成 =====")