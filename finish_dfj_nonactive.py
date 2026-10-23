# -*- coding: utf-8 -*-
import os
# tmp_nonactive_names 已加载(8.3M), 直接删大飞机的注销企业(finallist + list_output)
import pymysql
from datetime import datetime
def log(m): print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

DB = dict(host='127.0.0.1', port=3306, user='root', password=os.getenv('DB_PASSWORD'),
          database='business_data', charset='utf8mb4', connect_timeout=30,
          read_timeout=3600, write_timeout=3600)
conn = pymysql.connect(**DB)
cur = conn.cursor()
IND = '大飞机'

cur.execute("SELECT COUNT(*) FROM tmp_nonactive_names")
log(f"tmp_nonactive_names = {cur.fetchone()[0]}")

cur.execute("""DELETE f FROM company_nodes_finallist f
  JOIN tmp_nonactive_names n ON n.company_name = f.company_name COLLATE utf8mb4_0900_ai_ci
  WHERE f.industry_name=%s""", (IND,))
log(f"finallist 删 {cur.rowcount} 行")
conn.commit()

cur.execute("""DELETE l FROM company_list_output l
  JOIN tmp_nonactive_names n ON n.company_name = l.供应商
  WHERE l.industry_name=%s""", (IND,))
log(f"list_output 删 {cur.rowcount} 行")
conn.commit()

cur.execute("SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name=%s", (IND,))
log(f"剔除后 finallist={cur.fetchone()[0]}")
cur.execute("SELECT COUNT(*) FROM company_list_output WHERE industry_name=%s", (IND,))
log(f"剔除后 list_output={cur.fetchone()[0]}")

cur.close(); conn.close()
log("完成")