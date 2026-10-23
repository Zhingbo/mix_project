# -*- coding: utf-8 -*-
import os
# 补齐工业软件一次清理中未完成的 list_output / mapping / merge_temp 删除(用已有的 bak_gyrj_del_fin 备份)
import pymysql
from datetime import datetime
def log(m): print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

DB = dict(host='127.0.0.1', port=3306, user='root', password=os.getenv('DB_PASSWORD'),
          database='business_data', charset='utf8mb4', connect_timeout=30,
          read_timeout=3600, write_timeout=3600)
conn = pymysql.connect(**DB)
cur = conn.cursor()
IND = '工业软件'

cur.execute("SELECT COUNT(*) FROM bak_gyrj_del_fin")
log(f"bak_gyrj_del_fin 现有 {cur.fetchone()[0]} 行")

# 删 list_output(按 company_name + 层级3=节点 精确匹配)
log("删除 list_output ...")
cur.execute("""DELETE l FROM company_list_output l
  JOIN bak_gyrj_del_fin b
    ON l.供应商 COLLATE utf8mb4_0900_ai_ci = b.company_name COLLATE utf8mb4_0900_ai_ci
   AND l.层级3 COLLATE utf8mb4_0900_ai_ci = b.nodes COLLATE utf8mb4_0900_ai_ci
  WHERE l.industry_name=%s""", (IND,))
log(f"  list_output 删 {cur.rowcount} 行")
conn.commit()

# 删 mapping / merge_temp
for tbl in ['company_nodes_mapping', 'company_nodes_merge_temp']:
    try:
        log(f"删除 {tbl} ...")
        cur.execute(f"""DELETE x FROM {tbl} x
          JOIN bak_gyrj_del_fin b
            ON x.company_name COLLATE utf8mb4_0900_ai_ci = b.company_name COLLATE utf8mb4_0900_ai_ci
           AND x.nodes COLLATE utf8mb4_0900_ai_ci = b.nodes COLLATE utf8mb4_0900_ai_ci
          WHERE x.industry_name=%s""", (IND,))
        log(f"  {tbl} 删 {cur.rowcount} 行")
        conn.commit()
    except Exception as e:
        log(f"  {tbl} 跳过: {e}")

# 校验
cur.execute("SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name=%s", (IND,))
log(f"校验 finallist={cur.fetchone()[0]}")
cur.execute("SELECT COUNT(*) FROM company_list_output WHERE industry_name=%s", (IND,))
log(f"校验 list_output={cur.fetchone()[0]}")

cur.close(); conn.close()
log("===== 补齐完成 =====")