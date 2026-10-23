# -*- coding: utf-8 -*-
import os
# 航电系统补挂 改进版: 关键词 + 行业过滤(排除电力/建筑/工程等误命中)
import pymysql
from datetime import datetime
def log(m): print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

DB = dict(host='127.0.0.1', port=3306, user='root', password=os.getenv('DB_PASSWORD'),
          database='business_data', charset='utf8mb4', connect_timeout=30,
          read_timeout=3600, write_timeout=3600)
conn = pymysql.connect(**DB)
cur = conn.cursor()

IND = '大飞机'
NODE = '航电系统'
PARENT = '机载设备'
GRAND = '产业链中游'
NAME_KWS = ['航电系统', '航空电子', '机载电子', '飞控', '飞行控制', '惯导', '惯性导航', '航电']
# 行业域过滤: 只保留电子/航空/软件/信息等真正相关行业
IND_KWS = ['航空', '航天', '电子', '软件', '信息', '通信', '计算机', '集成电路', '无人机', '卫星', '导航', '雷达', '仪器']

# 1. 先删掉上一版(纯关键词, 有误命中)的航电系统数据
log("清理上一版航电系统数据...")
for tbl, col in [('company_nodes_finallist', 'nodes'), ('company_list_output', '层级3')]:
    cur.execute(f"DELETE FROM {tbl} WHERE industry_name=%s AND {col}=%s", (IND, NODE))
    log(f"  {tbl} 删 {cur.rowcount} 行")
cur.execute("DELETE FROM company_nodes_mapping WHERE industry_name=%s AND nodes=%s", (IND, NODE))
log(f"  mapping 删 {cur.rowcount} 行")
conn.commit()

# 2. 查询: 名字关键词 + 行业过滤
name_where = " OR ".join(["COALESCE(company_name_full, company_name) LIKE %s"] * len(NAME_KWS))
ind_where = " OR ".join(["industry_class_third LIKE %s"] * len(IND_KWS))
sql = (f"SELECT COALESCE(company_name_full, company_name) AS cn, credit_code "
       f"FROM ent_industry_class_chain_scope_20260928_converted "
       f"WHERE ({name_where}) AND ({ind_where})")
params = tuple("%" + k + "%" for k in NAME_KWS) + tuple("%" + k + "%" for k in IND_KWS)
log("查询(关键词+行业过滤)...")
cur.execute(sql, params)
rows = cur.fetchall()
log(f"  命中: {len(rows)} 家 (去重前)")

seen = {}
for cn, cc in rows:
    if cn and cn.strip() and cn not in seen:
        seen[cn] = cc
log(f"  去重后: {len(seen)} 家")

# 3. 排除已在大飞机名单的公司
cur.execute("SELECT company_name FROM company_nodes_finallist WHERE industry_name=%s", (IND,))
existing = set(r[0] for r in cur.fetchall())
new = {cn: cc for cn, cc in seen.items() if cn not in existing}
log(f"  排除已在大飞机名单: 新增 {len(new)} 家")

# 4. 插入
FULL = '电子信息|电子设备|电子控制设备'
REASON = '航电系统关键词+行业过滤直配'
inserted = 0
for cn, cc in new.items():
    try:
        cur.execute("""INSERT IGNORE INTO company_nodes_mapping
          (company_name, credit_code, certainty, industry_name, nodes, name, level, full_name, reason)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
          (cn, cc, '4', IND, NODE, NODE, '3', FULL, REASON))
        cur.execute("""INSERT IGNORE INTO company_nodes_finallist
          (company_name, industry_name, nodes, node_level, parent_node, score)
          VALUES (%s,%s,%s,%s,%s,%s)""",
          (cn, IND, NODE, 3, PARENT, '4'))
        cur.execute("""INSERT IGNORE INTO company_list_output
          (层级1, 层级2, 层级3, 供应商, industry_name)
          VALUES (%s,%s,%s,%s,%s)""",
          (GRAND, PARENT, NODE, cn, IND))
        inserted += 1
    except Exception as e:
        log(f"  跳过 {cn}: {e}")
conn.commit()
log(f"  实际插入: {inserted} 家")

cur.execute("SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name=%s AND nodes=%s", (IND, NODE))
log(f"校验 航电系统 finallist: {cur.fetchone()[0]}")
cur.execute("SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name=%s", (IND,))
log(f"校验 大飞机 finallist 总量: {cur.fetchone()[0]}")

cur.close(); conn.close()
log("===== 航电系统补挂(改进版)完成 =====")