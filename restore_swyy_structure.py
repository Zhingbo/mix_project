# -*- coding: utf-8 -*-
import os
# 从 backup_20260508 恢复 生物医药 结构到 industrial_chain.industrial_chain_structure (重映射 parent_id)
import pymysql
from datetime import datetime
def log(m): print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

conn = pymysql.connect(host='127.0.0.1', port=3306, user='root', password=os.getenv('DB_PASSWORD'),
                       database='industrial_chain', charset='utf8mb4', connect_timeout=30)
cur = conn.cursor()
CHAIN = '生物医药'

# 1. 读备份节点
cur.execute("""SELECT id, chain_name, nodes, parent_node, parent_id, node_level, chain_id, status
               FROM industrial_chain_structure_backup_20260508
               WHERE chain_name=%s ORDER BY node_level, id""", (CHAIN,))
rows = cur.fetchall()
log(f"备份节点 {len(rows)} 个")
for r in rows[:5]:
    log(f"  样例: id={r[0]} nodes={r[2]} parent={r[3]} parent_id={r[4]} level={r[5]} chain_id={r[6]} status={r[7]}")

# 2. 清空目标里可能的生物医药残留, 再插入(重映射 id)
cur.execute("DELETE FROM industrial_chain_structure WHERE chain_name=%s", (CHAIN,))
old_to_new = {}
for r in rows:
    old_id, cn, nodes, parent_node, parent_id, lvl, chain_id, status = r
    # 先插 parent_id=NULL, 后面统一更新
    cur.execute("""INSERT INTO industrial_chain_structure
      (chain_name, nodes, parent_node, parent_id, node_level, chain_id, status)
      VALUES (%s,%s,%s,%s,%s,%s,%s)""",
      (cn, nodes, parent_node, None, lvl, chain_id if chain_id else 939, 1 if status is None else status))
    new_id = cur.lastrowid
    old_to_new[old_id] = new_id
conn.commit()
log(f"已插入 {len(old_to_new)} 个节点")

# 3. 重映射 parent_id
for r in rows:
    old_id, cn, nodes, parent_node, parent_id, lvl, chain_id, status = r
    if parent_id and parent_id in old_to_new:
        cur.execute("UPDATE industrial_chain_structure SET parent_id=%s WHERE id=%s",
                    (old_to_new[parent_id], old_to_new[old_id]))
conn.commit()
log("parent_id 已重映射")

# 4. 校验
cur.execute("SELECT COUNT(*) FROM industrial_chain_structure WHERE chain_name=%s", (CHAIN,))
log(f"恢复后 industrial_chain_structure 生物医药节点: {cur.fetchone()[0]}")

cur.close(); conn.close()
log("===== 生物医药结构恢复完成 =====")