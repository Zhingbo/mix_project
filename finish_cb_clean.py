# -*- coding: utf-8 -*-
import os
# 补完船舶海工清理: 删未分类 -> 只留未标黄; 补非活跃底表垃圾删除; 建黑名单(标黄+未分类)
import pymysql
from datetime import datetime
def log(m): print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

DB = dict(host='127.0.0.1', port=3306, user='root', password=os.getenv('DB_PASSWORD'),
          database='business_data', charset='utf8mb4', connect_timeout=30,
          read_timeout=3600, write_timeout=3600)
conn = pymysql.connect(**DB)
cur = conn.cursor()
IND = '船舶海工'

# 载入未标黄(白名单)
cur.execute("DROP TABLE IF EXISTS tmp_weibiao")
cur.execute("CREATE TABLE tmp_weibiao (company_name VARCHAR(500) COLLATE utf8mb4_0900_ai_ci PRIMARY KEY) ENGINE=InnoDB")
conn.commit()
cur.execute("LOAD DATA INFILE '/var/lib/mysql-files/weibiao_names.txt' IGNORE INTO TABLE tmp_weibiao LINES TERMINATED BY '\n' (company_name)")
conn.commit()
cur.execute("SELECT COUNT(*) FROM tmp_weibiao")
log(f"未标黄白名单 {cur.fetchone()[0]} 家")

# 建黑名单表
cur.execute("""CREATE TABLE IF NOT EXISTS chain_exclude_company (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  industry_name VARCHAR(100) NOT NULL,
  company_name VARCHAR(255) NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_chain_company (industry_name, company_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='产业链排除企业黑名单'""")
conn.commit()

# 黑名单: 标黄
cur.execute("INSERT IGNORE INTO chain_exclude_company (industry_name, company_name) SELECT %s, company_name FROM tmp_biaohuang", (IND,))
log(f"黑名单写入标黄 {cur.rowcount} 家")
conn.commit()

# 黑名单: 未分类(当前finallist里 NOT IN 白名单的)
cur.execute(f"""INSERT IGNORE INTO chain_exclude_company (industry_name, company_name)
  SELECT %s, f.company_name FROM company_nodes_finallist f
  LEFT JOIN tmp_weibiao w ON w.company_name = f.company_name COLLATE utf8mb4_0900_ai_ci
  WHERE f.industry_name=%s AND w.company_name IS NULL""", (IND, IND))
log(f"黑名单写入未分类 {cur.rowcount} 家")
conn.commit()

# 删 finallist 未分类(NOT IN 白名单)
cur.execute(f"""DELETE f FROM company_nodes_finallist f
  LEFT JOIN tmp_weibiao w ON w.company_name = f.company_name COLLATE utf8mb4_0900_ai_ci
  WHERE f.industry_name=%s AND w.company_name IS NULL""", (IND,))
log(f"finallist 删未分类 {cur.rowcount} 行")
conn.commit()

# 删 list_output 未分类
cur.execute(f"""DELETE l FROM company_list_output l
  LEFT JOIN tmp_weibiao w ON w.company_name = l.供应商
  WHERE l.industry_name=%s AND w.company_name IS NULL""", (IND,))
log(f"list_output 删未分类 {cur.rowcount} 行")
conn.commit()

# 非活跃底表垃圾删除
cur.execute("""DELETE a FROM ent_industry_class_chain_scope_20260928_converted_nonactive_bak a
  JOIN tmp_garbage g ON g.company_name = a.company_name COLLATE utf8mb4_0900_ai_ci""")
log(f"非活跃底表删垃圾 {cur.rowcount} 行")
conn.commit()

# 校验
cur.execute("SELECT COUNT(*), COUNT(DISTINCT company_name) FROM company_nodes_finallist WHERE industry_name=%s", (IND,))
r = cur.fetchone()
log(f"校验 finallist: {r[0]} 行 / {r[1]} 家")
cur.execute("SELECT COUNT(*) FROM company_list_output WHERE industry_name=%s", (IND,))
log(f"校验 list_output: {cur.fetchone()[0]} 行")
cur.execute("SELECT COUNT(DISTINCT company_name) FROM chain_exclude_company WHERE industry_name=%s", (IND,))
log(f"校验 黑名单: {cur.fetchone()[0]} 家")

cur.execute("DROP TABLE IF EXISTS tmp_weibiao")
cur.execute("DROP TABLE IF EXISTS tmp_biaohuang")
cur.execute("DROP TABLE IF EXISTS tmp_garbage")
conn.commit()
cur.close(); conn.close()
log("===== 补完完成 =====")