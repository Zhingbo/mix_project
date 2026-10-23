# -*- coding: utf-8 -*-
import os
# 工业软件定向优化: 
#   1) 研发设计类软件 母节点 score=1 删除(593242)
#   2) 应用领域 + 8细分方向 score=1 删除(56764)
#   保留细分方向(含EDA)不动; 应用领域保留 score>=2
# 先备份到 bak_gyrj_* , 再删 finallist/list_output/mapping/merge_temp
import pymysql
from datetime import datetime
def log(m): print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

DB = dict(host='127.0.0.1', port=3306, user='root', password=os.getenv('DB_PASSWORD'),
          database='business_data', charset='utf8mb4', connect_timeout=30,
          read_timeout=3600, write_timeout=3600)
conn = pymysql.connect(**DB)
cur = conn.cursor()

IND = '工业软件'
COND = """industry_name=%s AND (
    (nodes='研发设计类软件' AND node_level=2 AND score='1')
    OR (nodes IN ('应用领域','其他应用领域','安防电子','工业通信','机械设备','汽车制造','能源电子','航空航天','轨道交通') AND score='1')
)"""

# 1. 备份要删的 finallist 行
cur.execute(f"DROP TABLE IF EXISTS bak_gyrj_del_fin")
cur.execute(f"CREATE TABLE bak_gyrj_del_fin AS SELECT * FROM company_nodes_finallist WHERE {COND}", (IND,))
cur.execute("SELECT COUNT(*) FROM bak_gyrj_del_fin")
log(f"备份 finallist 待删行: {cur.fetchone()[0]}")

# 2. 备份要删的 list_output 行 (按 company_name + 层级3=节点 匹配)
cur.execute(f"DROP TABLE IF EXISTS bak_gyrj_del_list")
cur.execute(f"""CREATE TABLE bak_gyrj_del_list AS
  SELECT l.* FROM company_list_output l
  JOIN bak_gyrj_del_fin b
    ON l.供应商 COLLATE utf8mb4_0900_ai_ci = b.company_name COLLATE utf8mb4_0900_ai_ci
   AND l.层级3 COLLATE utf8mb4_0900_ai_ci = b.nodes COLLATE utf8mb4_0900_ai_ci
  WHERE l.industry_name=%s""", (IND,))
cur.execute("SELECT COUNT(*) FROM bak_gyrj_del_list")
log(f"备份 list_output 待删行: {cur.fetchone()[0]}")

# 3. 删 finallist
cur.execute(f"DELETE FROM company_nodes_finallist WHERE {COND}", (IND,))
log(f"已删 finallist: {cur.rowcount} 行")
conn.commit()

# 4. 删 list_output
cur.execute(f"""DELETE l FROM company_list_output l
  JOIN bak_gyrj_del_fin b
    ON l.供应商 COLLATE utf8mb4_0900_ai_ci = b.company_name COLLATE utf8mb4_0900_ai_ci
   AND l.层级3 COLLATE utf8mb4_0900_ai_ci = b.nodes COLLATE utf8mb4_0900_ai_ci
  WHERE l.industry_name=%s""", (IND,))
log(f"已删 list_output: {cur.rowcount} 行")
conn.commit()

# 5. 删 mapping / merge_temp (防复现)
for tbl in ['company_nodes_mapping', 'company_nodes_merge_temp']:
    try:
        cur.execute(f"""DELETE x FROM {tbl} x
          JOIN bak_gyrj_del_fin b
            ON x.company_name COLLATE utf8mb4_0900_ai_ci = b.company_name COLLATE utf8mb4_0900_ai_ci
           AND x.nodes COLLATE utf8mb4_0900_ai_ci = b.nodes COLLATE utf8mb4_0900_ai_ci
          WHERE x.industry_name=%s""", (IND,))
        log(f"已删 {tbl}: {cur.rowcount} 行")
        conn.commit()
    except Exception as e:
        log(f"  {tbl} 跳过: {e}")

# 6. 校验
cur.execute("SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name=%s", (IND,))
log(f"校验 finallist 总量: {cur.fetchone()[0]}")
cur.execute("SELECT COUNT(*) FROM company_list_output WHERE industry_name=%s", (IND,))
log(f"校验 list_output 总量: {cur.fetchone()[0]}")
cur.execute(f"SELECT nodes, score, COUNT(*) FROM company_nodes_finallist WHERE industry_name=%s AND nodes IN ('研发设计类软件','应用领域','其他应用领域','安防电子','工业通信','机械设备','汽车制造','能源电子','航空航天','轨道交通') GROUP BY nodes, score ORDER BY nodes, score", (IND,))
log("校验后目标节点分布:")
for r in cur.fetchall():
    log(f"   {r[0]} | score={r[1]} | {r[2]}")

cur.close(); conn.close()
log("===== 工业软件优化完成 =====")